"""E2E: POST /demo/seed populates CaseStore for the dashboard."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from scripts.demo_pack import REHEARSAL_EXPECTED_DECISIONS, REHEARSAL_IDS


@pytest.fixture
def client(tmp_path: Path, project_root: Path) -> TestClient:
    app = create_app(audit_path=tmp_path / "demo_api.db", project_root=project_root)
    return TestClient(app)


def test_demo_seed_endpoint_leaves_escalate_pending(client: TestClient) -> None:
    resp = client.post("/demo/seed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["fixture_ids"] == list(REHEARSAL_IDS)
    # injection_planted may block or escalate; high_amount_escalate always pending
    assert body["pending_approval_count"] >= 1

    cases = {c["case_id"]: c for c in body["cases"]}
    assert set(cases) == set(REHEARSAL_IDS)

    for fid, allowed in REHEARSAL_EXPECTED_DECISIONS.items():
        decision = (cases[fid].get("gateway_decision") or {}).get("decision")
        assert decision in allowed, (fid, decision, allowed)

    escalate = cases["high_amount_escalate"]
    assert escalate["status"] == "pending_approval"
    assert escalate["call_id"]
    assert escalate["gateway_decision"]["decision"] == "escalate"

    listed = client.get("/cases")
    assert listed.status_code == 200
    assert len(listed.json()["cases"]) == len(REHEARSAL_IDS)

    call_id = escalate["call_id"]
    approved = client.post(
        f"/approvals/{call_id}",
        json={"action": "approve", "actor": "demo"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"


def test_demo_reset_clears_cases(client: TestClient) -> None:
    client.post("/demo/seed")
    reset = client.post("/demo/reset")
    assert reset.status_code == 200
    listed = client.get("/cases")
    assert listed.json()["cases"] == []
    verify = client.get("/audit/verify")
    assert verify.json()["entry_count"] == 0


def test_demo_seed_idempotent_via_api(client: TestClient) -> None:
    first = client.post("/demo/seed")
    second = client.post("/demo/seed")
    assert first.status_code == 200 and second.status_code == 200
    assert len(second.json()["cases"]) == len(REHEARSAL_IDS)
    assert second.json()["pending_approval_count"] >= 1
    cases = {c["case_id"]: c for c in second.json()["cases"]}
    assert cases["high_amount_escalate"]["status"] == "pending_approval"
