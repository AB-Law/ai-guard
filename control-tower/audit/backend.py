"""Pick the audit store backend from DATABASE_URL — additive, doesn't change
the SQLite default. AuditLogStore (audit/log_store.py) stays the default
implementation used by every existing test; PostgresAuditLogStore only comes
into play when DATABASE_URL is a postgres:// / postgresql:// URL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from audit.log_store import AppendInput, AuditLogStore
from contracts.schemas import AuditLogEntry

_POSTGRES_PREFIXES = ("postgres://", "postgresql://")


class AuditStore(Protocol):
    """The subset of AuditLogStore's interface every backend must provide."""

    def append(self, entry: AppendInput) -> AuditLogEntry: ...
    def verify_chain(self) -> bool: ...
    def query(
        self, *, process: str | None = None, event_type: str | None = None
    ) -> list[AuditLogEntry]: ...
    def clear(self) -> None: ...
    def close(self) -> None: ...


def is_postgres_url(database_url: str | None) -> bool:
    return bool(database_url) and database_url.startswith(_POSTGRES_PREFIXES)


def build_audit_store(database_url: str | None, *, sqlite_path: Path) -> AuditStore:
    """SQLite file by default; Postgres when DATABASE_URL is a postgres:// URL."""
    if is_postgres_url(database_url):
        from audit.postgres_store import PostgresAuditLogStore

        return PostgresAuditLogStore(database_url)  # type: ignore[arg-type]
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return AuditLogStore(sqlite_path)
