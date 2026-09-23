"""LangGraph checkpointer factory — MemorySaver by default (today's behavior,
single-process only), SqliteSaver/PostgresSaver when DATABASE_URL is set.

This is what actually makes /approvals resume work across workers/replicas:
MemorySaver's HITL interrupt state lives only in the process that created it,
so a resume routed to a different worker fails. A persisted checkpointer
shares that state the same way the audit log and case store now do.

Usage: checkpointer, close_fn = build_checkpointer(...); call close_fn() on
shutdown (it's a no-op for MemorySaver).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from audit.backend import is_postgres_url


def build_checkpointer(
    database_url: str | None, *, sqlite_path: Path
) -> tuple[BaseCheckpointSaver, Callable[[], None]]:
    if is_postgres_url(database_url):
        from langgraph.checkpoint.postgres import PostgresSaver

        cm = PostgresSaver.from_conn_string(database_url)  # type: ignore[arg-type]
        saver = cm.__enter__()
        saver.setup()
        return saver, lambda: cm.__exit__(None, None, None)

    if database_url == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver

        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        cm = SqliteSaver.from_conn_string(str(sqlite_path))
        saver = cm.__enter__()
        saver.setup()
        return saver, lambda: cm.__exit__(None, None, None)

    return MemorySaver(), lambda: None
