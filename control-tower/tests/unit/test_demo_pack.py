"""Unit tests for demo_pack fixture → API body mapping."""

from __future__ import annotations

from scripts.demo_pack import (
    REHEARSAL_IDS,
    fixture_to_submit_body,
    load_rehearsal_bodies,
)
from scripts.scenario_lib import list_fixtures, load_fixture


def test_fixture_to_submit_body_omits_resume() -> None:
    path = next(p for p in list_fixtures() if p.stem == "high_amount_escalate")
    fixture = load_fixture(path)
    assert "resume" in fixture
    body = fixture_to_submit_body(fixture)
    assert "resume" not in body
    assert body["case_id"] == "high_amount_escalate"
    assert body["mock_agent_plan"]["tool_name"] == "create_purchase_order"
    assert body["request"]["amount"] == 50000


def test_load_rehearsal_bodies_order() -> None:
    bodies = load_rehearsal_bodies()
    assert [b["case_id"] for b in bodies] == list(REHEARSAL_IDS)
    injection = next(b for b in bodies if b["case_id"] == "injection_planted")
    assert injection["force_chunk_ids"] == ["chunk:injected:quote"]
