"""Cross-process persistence proofs for the DATABASE_URL storage tiers.

The bug this guards against: CaseStore/checkpointer used to live only in one
process's memory, so a case created by "worker 1" was invisible to "worker 2"
and an /approvals resume on a different worker would fail outright. These
tests create two independent create_app() instances (simulating two workers
or a restart) sharing the same backing store and prove state crosses between
them.

The sqlite tier needs nothing extra and runs in the default suite. The
postgres tier is marked @pytest.mark.postgres and skipped unless
AEGIS_TEST_POSTGRES_URL is set (see README "Storage backends" section for how
to stand one up with docker compose) — mirrors the existing @pytest.mark.live
opt-in pattern so CI never needs Docker running.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

_ESCALATE_BODY = {
    "process": "procurement_review",
    "request": {"vendor_id": "V-1001", "amount": 50000, "item": "Server racks"},
    "mock_agent_plan": {
        "tool_name": "create_purchase_order",
        "tool_args": {"vendor_id": "V-1001", "amount": 50000, "item": "Server racks"},
        "agent_rationale": "This larger amount needs human approval.",
        "context_refs": ["chunk:policy:auto_approve", "chunk:policy:escalation"],
    },
}


def _cross_process_round_trip(
    *, database_url: str | None, project_root: Path, audit_path: Path, case_id: str
) -> None:
    """Submit on app #1, then read + resume on a brand new app #2 instance
    that never saw the submit — proving state isn't process-local memory.

    Uses TestClient as a context manager so FastAPI's shutdown lifespan
    actually runs (it's what closes the sqlite/postgres checkpointer
    connection) instead of leaking it past the end of the test.
    """
    app1 = create_app(
        project_root=project_root, audit_path=audit_path, database_url=database_url
    )
    call_id: str
    with TestClient(app1) as client1:
        body = dict(_ESCALATE_BODY, case_id=case_id)
        resp = client1.post("/cases", json=body)
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "pending_approval"
        assert result["gateway_decision"]["decision"] == "escalate"
        call_id = result["call_id"]

    # A fresh instance: its own (empty, if in-memory) CaseStore/checkpointer.
    app2 = create_app(
        project_root=project_root, audit_path=audit_path, database_url=database_url
    )
    with TestClient(app2) as client2:
        seen = client2.get(f"/cases/{case_id}")
        assert seen.status_code == 200
        assert seen.json()["status"] == "pending_approval"

        approved = client2.post(
            f"/approvals/{call_id}", json={"action": "approve", "actor": "tester"}
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"

        verify = client2.get("/audit/verify")
        assert verify.json()["valid"] is True


def test_sqlite_tier_shares_case_and_hitl_state_across_processes(
    tmp_path: Path, project_root: Path
) -> None:
    _cross_process_round_trip(
        database_url="sqlite",
        project_root=project_root,
        audit_path=tmp_path / "audit.db",
        case_id="sqlite-tier-persist",
    )
    # data/cases.db and data/checkpoints.db are created under project_root by
    # design (same directory as data/audit.db) — clean up what this test made.
    for name in ("cases.db", "checkpoints.db"):
        p = project_root / "data" / name
        if p.exists():
            p.unlink()


def test_default_tier_is_in_memory_only_per_process(
    tmp_path: Path, project_root: Path
) -> None:
    """Documents today's default explicitly: unset DATABASE_URL does NOT
    share state across app instances — this is the gap the sqlite/postgres
    tiers fix, and the default should stay this way (fast, zero setup)."""
    audit_path = tmp_path / "audit.db"
    app1 = create_app(project_root=project_root, audit_path=audit_path, database_url=None)
    client1 = TestClient(app1)
    resp = client1.post("/cases", json=dict(_ESCALATE_BODY, case_id="mem-tier"))
    assert resp.status_code == 200

    app2 = create_app(project_root=project_root, audit_path=audit_path, database_url=None)
    client2 = TestClient(app2)
    seen = client2.get("/cases/mem-tier")
    assert seen.status_code == 404


@pytest.mark.postgres
def test_postgres_tier_shares_case_and_hitl_state_across_processes(
    tmp_path: Path, project_root: Path
) -> None:
    pg_url = os.environ.get("AEGIS_TEST_POSTGRES_URL")
    if not pg_url:
        pytest.skip("set AEGIS_TEST_POSTGRES_URL to run the postgres storage tier tests")
    _cross_process_round_trip(
        database_url=pg_url,
        project_root=project_root,
        audit_path=tmp_path / "unused_audit.db",
        case_id="postgres-tier-persist",
    )
