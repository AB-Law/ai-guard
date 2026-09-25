"""Pending-approval rows waiting on a human click in THIS app's own UI —
not Aegis's dashboard, which is view-only for these (see the tower's
_authorize_guard_case_resolve). Plain in-memory dict; fine for a demo,
would be a real table in a real deployment.
"""

from __future__ import annotations

from typing import Any

PENDING: dict[str, dict[str, Any]] = {}
RESOLVED: list[dict[str, Any]] = []


def add(call_id: str, record: dict[str, Any]) -> None:
    PENDING[call_id] = record


def list_pending() -> list[dict[str, Any]]:
    return list(PENDING.values())


def pop(call_id: str) -> dict[str, Any] | None:
    return PENDING.pop(call_id, None)


def mark_resolved(record: dict[str, Any]) -> None:
    RESOLVED.append(record)
