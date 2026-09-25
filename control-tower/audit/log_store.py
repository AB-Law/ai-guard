"""Hash-chained SQLite audit log."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audit.redact import redact_payload
from contracts.schemas import AuditLogEntry, GatewayDecision

GENESIS_PREV_HASH = "0" * 64


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_entry_hash(prev_hash: str, payload: dict, timestamp: str) -> str:
    material = prev_hash + canonical_json(payload) + timestamp
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class AppendInput:
    process: str
    step_id: str
    event_type: str
    payload: dict
    scores: GatewayDecision | None = None
    entry_id: str | None = None
    timestamp: str | None = None


class AuditLogStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def close(self) -> None:
        """No persistent connection; provided for explicit cleanup in tests."""
        return

    def clear(self) -> None:
        """Delete all audit rows (keeps schema). Safe while the API process holds the file."""
        with self._connect() as conn:
            conn.execute("DELETE FROM audit_log")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        schema_path = Path(__file__).resolve().parent / "schema.sql"
        sql = schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(sql)

    def _last_entry_hash(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return row["entry_hash"] if row else GENESIS_PREV_HASH

    def append(self, entry: AppendInput) -> AuditLogEntry:
        entries = self.append_many([entry])
        return entries[0]

    def append_many(self, entries: list[AppendInput]) -> list[AuditLogEntry]:
        """Append multiple events in one connection/transaction (hash chain order preserved)."""
        if not entries:
            return []

        results: list[AuditLogEntry] = []
        with self._connect() as conn:
            prev_hash = self._last_entry_hash(conn)
            for entry in entries:
                redacted_payload = redact_payload(entry.payload)
                timestamp = entry.timestamp or datetime.now(UTC).isoformat()
                entry_id = entry.entry_id or str(uuid.uuid4())
                entry_hash = compute_entry_hash(prev_hash, redacted_payload, timestamp)
                scores_json: str | None = None
                if entry.scores is not None:
                    scores_json = entry.scores.model_dump_json()

                conn.execute(
                    """
                    INSERT INTO audit_log (
                        entry_id, process, step_id, event_type,
                        payload_json, scores_json, timestamp, prev_hash, entry_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        entry.process,
                        entry.step_id,
                        entry.event_type,
                        canonical_json(redacted_payload),
                        scores_json,
                        timestamp,
                        prev_hash,
                        entry_hash,
                    ),
                )
                results.append(
                    AuditLogEntry(
                        entry_id=entry_id,
                        process=entry.process,
                        step_id=entry.step_id,
                        event_type=entry.event_type,  # type: ignore[arg-type]
                        payload=redacted_payload,
                        scores=entry.scores,
                        timestamp=timestamp,
                        prev_hash=prev_hash,
                        entry_hash=entry_hash,
                    )
                )
                prev_hash = entry_hash
            conn.commit()
        return results

    def verify_chain(self) -> bool:
        valid, _ = self.verify_chain_detailed()
        return valid

    def verify_chain_detailed(self) -> tuple[bool, str | None]:
        """Like verify_chain(), but also names the first entry whose hash no
        longer matches its payload — powers the tamper-demo banner so it can
        say *which* row broke, not just that something did.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT entry_id, payload_json, timestamp, prev_hash, entry_hash "
                "FROM audit_log ORDER BY rowid ASC"
            ).fetchall()
        expected_prev = GENESIS_PREV_HASH
        for row in rows:
            if row["prev_hash"] != expected_prev:
                return False, row["entry_id"]
            payload = json.loads(row["payload_json"])
            recomputed = compute_entry_hash(row["prev_hash"], payload, row["timestamp"])
            if recomputed != row["entry_hash"]:
                return False, row["entry_id"]
            expected_prev = row["entry_hash"]
        return True, None

    def demo_corrupt_entry(self, entry_id: str | None = None) -> dict[str, str]:
        """Debug/demo only: overwrite one entry's stored hash so verify_chain()
        genuinely fails, for the tamper-detection demo in ARCHITECTURE.md §12.
        Never called from the normal append/query path. Returns the entry_id
        and its original hash so demo_restore_entry() can undo it.
        """
        with self._connect() as conn:
            if entry_id is None:
                row = conn.execute(
                    "SELECT entry_id, entry_hash FROM audit_log ORDER BY rowid DESC LIMIT 1 OFFSET 2"
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        "SELECT entry_id, entry_hash FROM audit_log ORDER BY rowid DESC LIMIT 1"
                    ).fetchone()
                if row is None:
                    raise ValueError("no audit entries to tamper with")
                entry_id = row["entry_id"]
                original_hash = row["entry_hash"]
            else:
                row = conn.execute(
                    "SELECT entry_hash FROM audit_log WHERE entry_id = ?", (entry_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"entry {entry_id!r} not found")
                original_hash = row["entry_hash"]
            conn.execute(
                "UPDATE audit_log SET entry_hash = ? WHERE entry_id = ?",
                ("0" * 64, entry_id),
            )
            conn.commit()
        return {"entry_id": entry_id, "original_hash": original_hash}

    def demo_restore_entry(self, entry_id: str, original_hash: str) -> None:
        """Undo demo_corrupt_entry()."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE audit_log SET entry_hash = ? WHERE entry_id = ?",
                (original_hash, entry_id),
            )
            conn.commit()

    def query(
        self,
        *,
        process: str | None = None,
        event_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str = "asc",
    ) -> list[AuditLogEntry]:
        clauses: list[str] = []
        params: list[Any] = []
        if process is not None:
            clauses.append("process = ?")
            params.append(process)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        direction = "DESC" if order == "desc" else "ASC"
        sql = f"SELECT * FROM audit_log {where} ORDER BY rowid {direction}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        entries: list[AuditLogEntry] = []
        for row in rows:
            scores = None
            if row["scores_json"]:
                scores = GatewayDecision.model_validate_json(row["scores_json"])
            entries.append(
                AuditLogEntry(
                    entry_id=row["entry_id"],
                    process=row["process"],
                    step_id=row["step_id"],
                    event_type=row["event_type"],  # type: ignore[arg-type]
                    payload=json.loads(row["payload_json"]),
                    scores=scores,
                    timestamp=row["timestamp"],
                    prev_hash=row["prev_hash"],
                    entry_hash=row["entry_hash"],
                )
            )
        return entries
