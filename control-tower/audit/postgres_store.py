"""Postgres-backed audit log — same interface and hash-chain guarantee as
AuditLogStore (audit/log_store.py), for when DATABASE_URL points at Postgres
instead of the default SQLite file. See audit/backend.py for the factory that
picks between the two.
"""

from __future__ import annotations

import json
from datetime import UTC
from typing import Any

import psycopg
from psycopg.rows import dict_row

from audit.log_store import (
    GENESIS_PREV_HASH,
    AppendInput,
    canonical_json,
    compute_entry_hash,
    resolve_entry_trace_id,
)
from audit.redact import redact_payload
from contracts.schemas import AuditLogEntry, GatewayDecision
from telemetry.tracing import start_span

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    rowid BIGSERIAL PRIMARY KEY,
    entry_id TEXT UNIQUE NOT NULL,
    process TEXT NOT NULL,
    step_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    scores_json TEXT,
    timestamp TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    trace_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_process ON audit_log(process);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log(event_type);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    process_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_process ON incidents(process_id);
CREATE INDEX IF NOT EXISTS idx_incidents_entry ON incidents(entry_id);
"""


class PostgresAuditLogStore:
    """Drop-in replacement for AuditLogStore backed by Postgres.

    Same public surface (append/verify_chain/query/clear/close) so api/main.py
    and everything downstream (investigation assistant, dashboard) works
    unchanged regardless of which backend audit/backend.py picked.
    """

    def __init__(self, conn_string: str) -> None:
        self.conn_string = conn_string
        self._init_db()

    def close(self) -> None:
        return

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM audit_log")
            conn.commit()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.conn_string, row_factory=dict_row)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_SCHEMA)
            conn.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS trace_id TEXT")
            conn.commit()

    def _last_entry_hash(self, conn: psycopg.Connection) -> str:
        row = conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return row["entry_hash"] if row else GENESIS_PREV_HASH

    def append(self, entry: AppendInput) -> AuditLogEntry:
        entries = self.append_many([entry])
        return entries[0]

    def append_many(self, entries: list[AppendInput]) -> list[AuditLogEntry]:
        """Append multiple events in one connection/transaction (hash chain order preserved).

        Locks the tip row (or takes an advisory lock when empty) so concurrent
        writers cannot fork prev_hash.
        """
        if not entries:
            return []

        import uuid
        from datetime import datetime

        with start_span(
            "aegis.audit.append",
            attributes={"process": entries[0].process},
        ):
            results: list[AuditLogEntry] = []
            with self._connect() as conn:
                # Serialize tip updates across workers.
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (87201401,))
                tip = conn.execute(
                    "SELECT entry_hash FROM audit_log ORDER BY rowid DESC LIMIT 1 FOR UPDATE"
                ).fetchone()
                prev_hash = tip["entry_hash"] if tip else GENESIS_PREV_HASH
                for entry in entries:
                    redacted_payload = redact_payload(entry.payload)
                    timestamp = entry.timestamp or datetime.now(UTC).isoformat()
                    entry_id = entry.entry_id or str(uuid.uuid4())
                    entry_hash = compute_entry_hash(prev_hash, redacted_payload, timestamp)
                    scores_json = (
                        entry.scores.model_dump_json() if entry.scores is not None else None
                    )
                    tid = resolve_entry_trace_id(entry)

                    conn.execute(
                        """
                        INSERT INTO audit_log (
                            entry_id, process, step_id, event_type,
                            payload_json, scores_json, timestamp, prev_hash,
                            entry_hash, trace_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                            tid,
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
                            trace_id=tid,
                        )
                    )
                    prev_hash = entry_hash
                conn.commit()
            return results

    def index_incident(
        self,
        *,
        incident_id: str,
        entry_id: str,
        process_id: str,
        created_at: str | None = None,
    ) -> None:
        from datetime import datetime

        ts = created_at or datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO incidents (incident_id, entry_id, process_id, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (incident_id) DO UPDATE SET
                    entry_id = EXCLUDED.entry_id,
                    process_id = EXCLUDED.process_id,
                    created_at = EXCLUDED.created_at
                """,
                (incident_id, entry_id, process_id, ts),
            )
            conn.commit()

    def verify_chain(self) -> bool:
        valid, _ = self.verify_chain_detailed()
        return valid

    def verify_chain_detailed(self) -> tuple[bool, str | None]:
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
        """Debug/demo only — see AuditLogStore.demo_corrupt_entry()."""
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
                    "SELECT entry_hash FROM audit_log WHERE entry_id = %s", (entry_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"entry {entry_id!r} not found")
                original_hash = row["entry_hash"]
            conn.execute(
                "UPDATE audit_log SET entry_hash = %s WHERE entry_id = %s",
                ("0" * 64, entry_id),
            )
            conn.commit()
        return {"entry_id": entry_id, "original_hash": original_hash}

    def demo_restore_entry(self, entry_id: str, original_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE audit_log SET entry_hash = %s WHERE entry_id = %s",
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
            clauses.append("process = %s")
            params.append(process)
        if event_type is not None:
            clauses.append("event_type = %s")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        direction = "DESC" if order == "desc" else "ASC"
        sql = f"SELECT * FROM audit_log {where} ORDER BY rowid {direction}"
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
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
                    trace_id=row.get("trace_id"),
                )
            )
        return entries
