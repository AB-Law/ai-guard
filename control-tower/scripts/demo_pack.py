"""Shared helpers: map scenario fixtures → API submit bodies for demo seed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.scenario_lib import list_fixtures, load_fixture

# ARCHITECTURE §15 live-run mapping (dashboard leaves escalate pending)
REHEARSAL_IDS: tuple[str, ...] = (
    "clean_po",
    "injection_planted",
    "unauthorized_tool",
    "high_amount_escalate",
)

# Expected gateway decisions when seeded via API (escalate not auto-resumed)
REHEARSAL_EXPECTED_DECISIONS: dict[str, set[str]] = {
    "clean_po": {"allow"},
    "injection_planted": {"block", "escalate"},
    "unauthorized_tool": {"block"},
    "high_amount_escalate": {"escalate"},
}


def fixture_to_submit_body(
    fixture: dict[str, Any],
    *,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Build POST /cases JSON from a fixture. Does not include resume."""
    body: dict[str, Any] = {
        "process": fixture.get("process", "procurement_review"),
        "case_id": case_id or fixture["id"],
        "request": fixture["request"],
    }
    if fixture.get("mock_agent_plan") is not None:
        body["mock_agent_plan"] = fixture["mock_agent_plan"]
    if fixture.get("force_chunk_ids") is not None:
        body["force_chunk_ids"] = fixture["force_chunk_ids"]
    return body


def load_rehearsal_bodies(
    *,
    cases_dir: Path | None = None,
    fixture_ids: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Load submit bodies for the demo rehearsal pack (escalate left pending)."""
    ids = list(fixture_ids) if fixture_ids is not None else list(REHEARSAL_IDS)
    by_stem = {p.stem: p for p in list_fixtures(cases_dir)}
    missing = [fid for fid in ids if fid not in by_stem]
    if missing:
        raise ValueError(f"Unknown fixture id(s): {missing}")
    return [fixture_to_submit_body(load_fixture(by_stem[fid])) for fid in ids]
