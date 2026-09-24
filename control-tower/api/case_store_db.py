"""DB-backed CaseStore — same shape as the in-memory dict version in
api/main.py (``.cases[case_id]``, ``.call_to_case[call_id]``), so this is a
drop-in swap, not a rewrite of api/main.py's call sites.

This is the actual fix for "can't run a second worker": the in-memory
CaseStore dict is per-process, so a request routed to a different worker (or
a fresh container) never sees cases another worker created. Backing it with
SQLite or Postgres — same DATABASE_URL as the audit log — makes case state
shared and durable instead.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, MutableMapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from audit.backend import is_postgres_url

if TYPE_CHECKING:
    import psycopg


class _SqliteJSONMap(MutableMapping):
    """MutableMapping[str, Any] persisted as JSON blobs in a SQLite table.

    Note: sqlite3.Connection used as a context manager only commits/rolls
    back on exit — it does NOT close the connection. Every method here closes
    explicitly (try/finally), otherwise connections leak and, on Windows,
    block anyone from deleting or replacing the underlying file.
    """

    def __init__(self, db_path: Path, table: str, key_col: str) -> None:
        self.db_path = db_path
        self.table = table
        self.key_col = key_col
        conn = self._connect()
        try:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table} "
                f"({self.key_col} TEXT PRIMARY KEY, value_json TEXT NOT NULL)"
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def __setitem__(self, key: str, value: Any) -> None:
        conn = self._connect()
        try:
            conn.execute(
                f"INSERT INTO {self.table} ({self.key_col}, value_json) VALUES (?, ?) "
                f"ON CONFLICT({self.key_col}) DO UPDATE SET value_json = excluded.value_json",
                (key, json.dumps(value)),
            )
            conn.commit()
        finally:
            conn.close()

    def __getitem__(self, key: str) -> Any:
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT value_json FROM {self.table} WHERE {self.key_col} = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def __delitem__(self, key: str) -> None:
        conn = self._connect()
        try:
            cur = conn.execute(f"DELETE FROM {self.table} WHERE {self.key_col} = ?", (key,))
            conn.commit()
            deleted = cur.rowcount
        finally:
            conn.close()
        if deleted == 0:
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        conn = self._connect()
        try:
            rows = conn.execute(f"SELECT {self.key_col} FROM {self.table}").fetchall()
        finally:
            conn.close()
        return iter(r[0] for r in rows)

    def __len__(self) -> int:
        conn = self._connect()
        try:
            (count,) = conn.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()
        finally:
            conn.close()
        return count

    def clear(self) -> None:
        conn = self._connect()
        try:
            conn.execute(f"DELETE FROM {self.table}")
            conn.commit()
        finally:
            conn.close()


class _PostgresJSONMap(MutableMapping):
    """MutableMapping[str, Any] persisted as JSON blobs in a Postgres table."""

    def __init__(self, conn_string: str, table: str, key_col: str) -> None:
        self.conn_string = conn_string
        self.table = table
        self.key_col = key_col
        with self._connect() as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table} "
                f"({self.key_col} TEXT PRIMARY KEY, value_json TEXT NOT NULL)"
            )
            conn.commit()

    def _connect(self) -> psycopg.Connection:
        import psycopg  # lazy — only needed when the postgres tier is selected

        return psycopg.connect(self.conn_string)

    def __setitem__(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO {self.table} ({self.key_col}, value_json) VALUES (%s, %s) "
                f"ON CONFLICT ({self.key_col}) DO UPDATE SET value_json = EXCLUDED.value_json",
                (key, json.dumps(value)),
            )
            conn.commit()

    def __getitem__(self, key: str) -> Any:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT value_json FROM {self.table} WHERE {self.key_col} = %s", (key,)
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def __delitem__(self, key: str) -> None:
        with self._connect() as conn:
            cur = conn.execute(f"DELETE FROM {self.table} WHERE {self.key_col} = %s", (key,))
            conn.commit()
        if cur.rowcount == 0:
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        with self._connect() as conn:
            rows = conn.execute(f"SELECT {self.key_col} FROM {self.table}").fetchall()
        return iter(r[0] for r in rows)

    def __len__(self) -> int:
        with self._connect() as conn:
            (count,) = conn.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()
        return count

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self.table}")
            conn.commit()


class SqliteCaseStore:
    """Same shape as api.main.CaseStore (.cases / .call_to_case), SQLite-backed."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cases: MutableMapping[str, dict] = _SqliteJSONMap(db_path, "case_records", "case_id")
        self.call_to_case: MutableMapping[str, str] = _SqliteJSONMap(
            db_path, "call_to_case", "call_id"
        )


class PostgresCaseStore:
    """Same shape as api.main.CaseStore (.cases / .call_to_case), Postgres-backed."""

    def __init__(self, conn_string: str) -> None:
        self.cases: MutableMapping[str, dict] = _PostgresJSONMap(
            conn_string, "case_records", "case_id"
        )
        self.call_to_case: MutableMapping[str, str] = _PostgresJSONMap(
            conn_string, "call_to_case", "call_id"
        )


def build_kv_store(
    database_url: str | None,
    *,
    table: str,
    key_col: str,
    sqlite_path: Path,
    memory_factory: Callable[[], Any],
) -> MutableMapping[str, Any]:
    """Generic persisted key -> JSON-blob map, same DATABASE_URL semantics as
    build_case_store: unset -> in-memory, "sqlite" -> SQLite file, postgres(ql)://
    -> Postgres. Used for stores (e.g. applications) that don't need
    build_case_store's specific .cases/.call_to_case shape.
    """
    if is_postgres_url(database_url):
        return _PostgresJSONMap(database_url, table, key_col)  # type: ignore[arg-type]
    if database_url == "sqlite":
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        return _SqliteJSONMap(sqlite_path, table, key_col)
    return memory_factory()


def build_case_store(
    database_url: str | None,
    *,
    sqlite_path: Path,
    memory_factory: Callable[[], Any],
) -> Any:
    """Postgres/SQLite/in-memory, matching audit.backend's DATABASE_URL semantics:

    unset          -> memory_factory() (today's default; single-process only)
    "sqlite"        -> SqliteCaseStore (persisted, still single-process/file)
    postgres(ql)://  -> PostgresCaseStore (persisted, safe for multiple workers)
    """
    if is_postgres_url(database_url):
        return PostgresCaseStore(database_url)  # type: ignore[arg-type]
    if database_url == "sqlite":
        return SqliteCaseStore(sqlite_path)
    return memory_factory()
