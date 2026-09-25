"""Learned injection-rule store — SQLite/Postgres with compile-once cache.

Hot path never hits the DB: active literals are compiled into memory and
refreshed when the per-process epoch bumps or a short TTL expires.
Multi-worker: epoch/TTL + POST /configs/reload for immediate consistency.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from re import Pattern
from typing import Any

from audit.backend import is_postgres_url
from contracts.schemas import LearnedRule

MAX_RULE_TEXT_LEN = 80
MAX_PENDING_PER_PROCESS = 20
MAX_ACTIVE_PER_PROCESS = 50
REJECTED_COOLDOWN = timedelta(hours=24)
CACHE_TTL_SECONDS = 15.0

# Characters that would imply open-ended regex if left unescaped. Literals
# are always matched via re.escape, but we reject human edits that look like
# someone tried to smuggle a pattern in.
_META_HINT_RE = re.compile(r"[.*+?^${}|()\[\]\\]")

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS learned_rules (
    rule_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    rule_type TEXT NOT NULL DEFAULT 'literal',
    rule_text TEXT NOT NULL,
    rule_text_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    source_incident_id TEXT NOT NULL,
    approved_by TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    rejected_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_learned_rules_process_status
    ON learned_rules(process_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_learned_rules_dedup_pending_active
    ON learned_rules(process_id, rule_type, rule_text_hash)
    WHERE status IN ('pending', 'active');

CREATE TABLE IF NOT EXISTS learned_rules_epoch (
    process_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 0
);
"""

_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS learned_rules (
    rule_id TEXT PRIMARY KEY,
    process_id TEXT NOT NULL,
    rule_type TEXT NOT NULL DEFAULT 'literal',
    rule_text TEXT NOT NULL,
    rule_text_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    source_incident_id TEXT NOT NULL,
    approved_by TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    rejected_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_learned_rules_process_status
    ON learned_rules(process_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_learned_rules_dedup_pending_active
    ON learned_rules(process_id, rule_type, rule_text_hash)
    WHERE status IN ('pending', 'active');

CREATE TABLE IF NOT EXISTS learned_rules_epoch (
    process_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True)
class CompiledRule:
    rule_id: str
    process_id: str
    rule_text: str
    pattern: Pattern[str]


@dataclass
class _CacheEntry:
    epoch: int
    loaded_at: float
    rules: list[CompiledRule]


def normalize_literal(text: str) -> str:
    """Display form: strip, collapse internal whitespace, cap length."""
    collapsed = " ".join((text or "").split())
    return collapsed[:MAX_RULE_TEXT_LEN]


def rule_text_hash(rule_type: str, rule_text: str) -> str:
    key = f"{rule_type}:{rule_text.casefold()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def validate_literal_rule_text(rule_text: str) -> str:
    """Return normalized literal or raise ValueError."""
    normalized = normalize_literal(rule_text)
    if not normalized:
        raise ValueError("rule_text must be non-empty")
    if len(normalized) > MAX_RULE_TEXT_LEN:
        raise ValueError(f"rule_text exceeds {MAX_RULE_TEXT_LEN} characters")
    # After normalize we still reject strings that look like regex attempts
    # (metacharacters). Matching uses re.escape so these would be literal,
    # but humans editing "advanced" patterns should be blocked in v1.
    if _META_HINT_RE.search(normalized):
        raise ValueError(
            "rule_text must be a plain literal (no regex metacharacters) in v1"
        )
    return normalized


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_rule(row: Any) -> LearnedRule:
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    return LearnedRule(
        rule_id=get("rule_id"),
        process_id=get("process_id"),
        rule_type=get("rule_type"),
        rule_text=get("rule_text"),
        rule_text_hash=get("rule_text_hash"),
        status=get("status"),
        source_incident_id=get("source_incident_id"),
        approved_by=get("approved_by"),
        created_at=get("created_at"),
        activated_at=get("activated_at"),
        rejected_at=get("rejected_at"),
    )


class LearnedRuleStore:
    """Dedicated learned_rules tables — not case JSON blobs."""

    def __init__(self, db_path: str | Path | None = None, *, database_url: str | None = None) -> None:
        self.database_url = database_url or os.environ.get("DATABASE_URL")
        self._pg = is_postgres_url(self.database_url)
        if self._pg:
            self.db_path = None
        else:
            path = Path(db_path) if db_path else Path(__file__).resolve().parents[1] / "data" / "learned_rules.db"
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path = path
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.RLock()
        self._init_db()

    def _connect_sqlite(self) -> sqlite3.Connection:
        assert self.db_path is not None
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _connect_pg(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _init_db(self) -> None:
        if self._pg:
            with self._connect_pg() as conn:
                conn.execute(_SCHEMA_PG)
                conn.commit()
            return
        with self._connect_sqlite() as conn:
            conn.executescript(_SCHEMA_SQLITE)
            conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            if self._pg:
                with self._connect_pg() as conn:
                    conn.execute("DELETE FROM learned_rules")
                    conn.execute("DELETE FROM learned_rules_epoch")
                    conn.commit()
            else:
                with self._connect_sqlite() as conn:
                    conn.execute("DELETE FROM learned_rules")
                    conn.execute("DELETE FROM learned_rules_epoch")
                    conn.commit()

    def clear_cache(self) -> None:
        """Drop in-process compiled cache (this worker only)."""
        with self._lock:
            self._cache.clear()

    def get_epoch(self, process_id: str) -> int:
        if self._pg:
            with self._connect_pg() as conn:
                row = conn.execute(
                    "SELECT version FROM learned_rules_epoch WHERE process_id = %s",
                    (process_id,),
                ).fetchone()
                return int(row["version"]) if row else 0
        with self._connect_sqlite() as conn:
            row = conn.execute(
                "SELECT version FROM learned_rules_epoch WHERE process_id = ?",
                (process_id,),
            ).fetchone()
            return int(row["version"]) if row else 0

    def _bump_epoch(self, conn: Any, process_id: str) -> int:
        if self._pg:
            conn.execute(
                """
                INSERT INTO learned_rules_epoch (process_id, version) VALUES (%s, 1)
                ON CONFLICT (process_id) DO UPDATE SET version = learned_rules_epoch.version + 1
                """,
                (process_id,),
            )
            row = conn.execute(
                "SELECT version FROM learned_rules_epoch WHERE process_id = %s",
                (process_id,),
            ).fetchone()
            return int(row["version"])
        conn.execute(
            """
            INSERT INTO learned_rules_epoch (process_id, version) VALUES (?, 1)
            ON CONFLICT(process_id) DO UPDATE SET version = version + 1
            """,
            (process_id,),
        )
        row = conn.execute(
            "SELECT version FROM learned_rules_epoch WHERE process_id = ?",
            (process_id,),
        ).fetchone()
        return int(row["version"])

    def count_by_status(self, process_id: str, status: str) -> int:
        if self._pg:
            with self._connect_pg() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM learned_rules WHERE process_id = %s AND status = %s",
                    (process_id, status),
                ).fetchone()
                return int(row["c"])
        with self._connect_sqlite() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM learned_rules WHERE process_id = ? AND status = ?",
                (process_id, status),
            ).fetchone()
            return int(row["c"])

    def find_blocking_duplicate(
        self, process_id: str, rule_type: str, text_hash: str
    ) -> LearnedRule | None:
        """Pending, active, or rejected-within-cooldown with same dedup key."""
        cooldown_after = (datetime.now(UTC) - REJECTED_COOLDOWN).isoformat()
        if self._pg:
            with self._connect_pg() as conn:
                row = conn.execute(
                    """
                    SELECT * FROM learned_rules
                    WHERE process_id = %s AND rule_type = %s AND rule_text_hash = %s
                      AND (
                        status IN ('pending', 'active')
                        OR (status = 'rejected' AND rejected_at IS NOT NULL AND rejected_at >= %s)
                      )
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (process_id, rule_type, text_hash, cooldown_after),
                ).fetchone()
                return _row_to_rule(row) if row else None
        with self._connect_sqlite() as conn:
            row = conn.execute(
                """
                SELECT * FROM learned_rules
                WHERE process_id = ? AND rule_type = ? AND rule_text_hash = ?
                  AND (
                    status IN ('pending', 'active')
                    OR (status = 'rejected' AND rejected_at IS NOT NULL AND rejected_at >= ?)
                  )
                ORDER BY created_at DESC LIMIT 1
                """,
                (process_id, rule_type, text_hash, cooldown_after),
            ).fetchone()
            return _row_to_rule(row) if row else None

    def create_pending(
        self,
        *,
        process_id: str,
        rule_text: str,
        source_incident_id: str,
        rule_type: str = "literal",
        rule_id: str | None = None,
    ) -> LearnedRule:
        normalized = validate_literal_rule_text(rule_text)
        text_hash = rule_text_hash(rule_type, normalized)
        dup = self.find_blocking_duplicate(process_id, rule_type, text_hash)
        if dup is not None:
            raise ValueError(f"duplicate rule ({dup.status}): {dup.rule_id}")
        if self.count_by_status(process_id, "pending") >= MAX_PENDING_PER_PROCESS:
            raise ValueError(f"pending rule cap ({MAX_PENDING_PER_PROCESS}) reached for {process_id}")
        if self.count_by_status(process_id, "active") >= MAX_ACTIVE_PER_PROCESS:
            raise ValueError(f"active rule cap ({MAX_ACTIVE_PER_PROCESS}) reached for {process_id}")

        rid = rule_id or str(uuid.uuid4())
        created = _utc_now()
        if self._pg:
            with self._connect_pg() as conn:
                conn.execute(
                    """
                    INSERT INTO learned_rules (
                        rule_id, process_id, rule_type, rule_text, rule_text_hash,
                        status, source_incident_id, approved_by, created_at,
                        activated_at, rejected_at
                    ) VALUES (%s, %s, %s, %s, %s, 'pending', %s, NULL, %s, NULL, NULL)
                    """,
                    (rid, process_id, rule_type, normalized, text_hash, source_incident_id, created),
                )
                conn.commit()
        else:
            with self._connect_sqlite() as conn:
                conn.execute(
                    """
                    INSERT INTO learned_rules (
                        rule_id, process_id, rule_type, rule_text, rule_text_hash,
                        status, source_incident_id, approved_by, created_at,
                        activated_at, rejected_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL, ?, NULL, NULL)
                    """,
                    (rid, process_id, rule_type, normalized, text_hash, source_incident_id, created),
                )
                conn.commit()
        return LearnedRule(
            rule_id=rid,
            process_id=process_id,
            rule_type=rule_type,  # type: ignore[arg-type]
            rule_text=normalized,
            rule_text_hash=text_hash,
            status="pending",
            source_incident_id=source_incident_id,
            approved_by=None,
            created_at=created,
            activated_at=None,
            rejected_at=None,
        )

    def get(self, rule_id: str) -> LearnedRule | None:
        if self._pg:
            with self._connect_pg() as conn:
                row = conn.execute(
                    "SELECT * FROM learned_rules WHERE rule_id = %s", (rule_id,)
                ).fetchone()
                return _row_to_rule(row) if row else None
        with self._connect_sqlite() as conn:
            row = conn.execute(
                "SELECT * FROM learned_rules WHERE rule_id = ?", (rule_id,)
            ).fetchone()
            return _row_to_rule(row) if row else None

    def activate(
        self,
        rule_id: str,
        *,
        approved_by: str,
        rule_text: str | None = None,
    ) -> LearnedRule:
        if not (approved_by or "").strip():
            raise ValueError("approved_by is required")
        rule = self.get(rule_id)
        if rule is None:
            raise ValueError(f"rule {rule_id!r} not found")
        if rule.status != "pending":
            raise ValueError(f"rule {rule_id!r} is not pending (status={rule.status})")

        new_text = validate_literal_rule_text(rule_text if rule_text is not None else rule.rule_text)
        new_hash = rule_text_hash(rule.rule_type, new_text)
        if self.count_by_status(rule.process_id, "active") >= MAX_ACTIVE_PER_PROCESS:
            raise ValueError(
                f"active rule cap ({MAX_ACTIVE_PER_PROCESS}) reached for {rule.process_id}"
            )

        activated = _utc_now()
        if self._pg:
            with self._connect_pg() as conn:
                conn.execute(
                    """
                    UPDATE learned_rules SET
                        rule_text = %s, rule_text_hash = %s, status = 'active',
                        approved_by = %s, activated_at = %s
                    WHERE rule_id = %s
                    """,
                    (new_text, new_hash, approved_by.strip(), activated, rule_id),
                )
                self._bump_epoch(conn, rule.process_id)
                conn.commit()
        else:
            with self._connect_sqlite() as conn:
                conn.execute(
                    """
                    UPDATE learned_rules SET
                        rule_text = ?, rule_text_hash = ?, status = 'active',
                        approved_by = ?, activated_at = ?
                    WHERE rule_id = ?
                    """,
                    (new_text, new_hash, approved_by.strip(), activated, rule_id),
                )
                self._bump_epoch(conn, rule.process_id)
                conn.commit()
        with self._lock:
            self._cache.pop(rule.process_id, None)
        updated = self.get(rule_id)
        assert updated is not None
        return updated

    def reject(self, rule_id: str, *, actor: str) -> LearnedRule:
        rule = self.get(rule_id)
        if rule is None:
            raise ValueError(f"rule {rule_id!r} not found")
        if rule.status != "pending":
            raise ValueError(f"rule {rule_id!r} is not pending (status={rule.status})")
        rejected = _utc_now()
        if self._pg:
            with self._connect_pg() as conn:
                conn.execute(
                    """
                    UPDATE learned_rules SET status = 'rejected', rejected_at = %s, approved_by = %s
                    WHERE rule_id = %s
                    """,
                    (rejected, actor.strip() or None, rule_id),
                )
                conn.commit()
        else:
            with self._connect_sqlite() as conn:
                conn.execute(
                    """
                    UPDATE learned_rules SET status = 'rejected', rejected_at = ?, approved_by = ?
                    WHERE rule_id = ?
                    """,
                    (rejected, actor.strip() or None, rule_id),
                )
                conn.commit()
        updated = self.get(rule_id)
        assert updated is not None
        return updated

    def list_active(self, process_id: str) -> list[LearnedRule]:
        if self._pg:
            with self._connect_pg() as conn:
                rows = conn.execute(
                    "SELECT * FROM learned_rules WHERE process_id = %s AND status = 'active'",
                    (process_id,),
                ).fetchall()
                return [_row_to_rule(r) for r in rows]
        with self._connect_sqlite() as conn:
            rows = conn.execute(
                "SELECT * FROM learned_rules WHERE process_id = ? AND status = 'active'",
                (process_id,),
            ).fetchall()
            return [_row_to_rule(r) for r in rows]

    def compiled_active(self, process_id: str) -> list[CompiledRule]:
        """Cache-backed compiled literals for the evaluate/scan hot path."""
        now = time.monotonic()
        epoch = self.get_epoch(process_id)
        with self._lock:
            cached = self._cache.get(process_id)
            if (
                cached is not None
                and cached.epoch == epoch
                and (now - cached.loaded_at) < CACHE_TTL_SECONDS
            ):
                return cached.rules

        rules: list[CompiledRule] = []
        for r in self.list_active(process_id):
            pattern = re.compile(re.escape(r.rule_text), re.IGNORECASE)
            rules.append(
                CompiledRule(
                    rule_id=r.rule_id,
                    process_id=r.process_id,
                    rule_text=r.rule_text,
                    pattern=pattern,
                )
            )
        with self._lock:
            self._cache[process_id] = _CacheEntry(epoch=epoch, loaded_at=now, rules=rules)
        return rules

    def match_texts(self, process_id: str, texts: list[str]) -> list[tuple[CompiledRule, str]]:
        """Return (rule, matched_span) for the first hit per rule across texts."""
        hits: list[tuple[CompiledRule, str]] = []
        seen: set[str] = set()
        for compiled in self.compiled_active(process_id):
            if compiled.rule_id in seen:
                continue
            for text in texts:
                m = compiled.pattern.search(text or "")
                if m:
                    hits.append((compiled, m.group(0)))
                    seen.add(compiled.rule_id)
                    break
        return hits


_default_store: LearnedRuleStore | None = None
_default_lock = threading.Lock()


def get_rule_store(
    *,
    db_path: str | Path | None = None,
    database_url: str | None = None,
    reset: bool = False,
) -> LearnedRuleStore:
    """Process-wide default store (tests can pass reset=True with a temp path)."""
    global _default_store
    with _default_lock:
        if reset or _default_store is None:
            _default_store = LearnedRuleStore(db_path=db_path, database_url=database_url)
        return _default_store


def clear_rule_caches() -> None:
    store = _default_store
    if store is not None:
        store.clear_cache()
