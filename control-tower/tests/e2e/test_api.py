"""E2E FastAPI tests with mocked agent plans."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def client(tmp_path: Path, project_root: Path) -> TestClient:
    app = create_app(audit_path=tmp_path / "api_audit.db", project_root=project_root)
    return TestClient(app)


def test_submit_clean_case_allow(client: TestClient) -> None:
    resp = client.post(
        "/cases",
        json={
            "process": "procurement_review",
            "case_id": "api-clean",
            "request": {
                "vendor_id": "V-1001",
                "amount": 2500,
                "item": "Laptop docks x10",
            },
            "mock_agent_plan": {
                "tool_name": "create_purchase_order",
                "tool_args": {
                    "vendor_id": "V-1001",
                    "amount": 2500,
                    "item": "Laptop docks x10",
                },
                "agent_rationale": (
                    "Purchase orders at or below USD 10,000 may be auto-approved when "
                    "the vendor is active on the vendor master list."
                ),
                "context_refs": ["chunk:policy:auto_approve", "chunk:vendor:V-1001"],
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["gateway_decision"]["decision"] == "allow"

    audit = client.get("/cases/api-clean/audit")
    assert audit.status_code == 200
    assert audit.json()["chain_valid"] is True
    types = {e["event_type"] for e in audit.json()["entries"]}
    assert "retrieval" in types
    assert "policy_check" in types


def test_unauthorized_blocks(client: TestClient) -> None:
    resp = client.post(
        "/cases",
        json={
            "case_id": "api-unauth",
            "request": {"vendor_id": "V-1001", "amount": 100, "item": "x"},
            "mock_agent_plan": {
                "tool_name": "send_payment",
                "tool_args": {"vendor_id": "V-1001", "amount": 100},
                "agent_rationale": "Pay now",
                "context_refs": ["chunk:vendor:V-1001"],
            },
        },
    )
    assert resp.status_code == 200
    assert resp.json()["gateway_decision"]["decision"] == "block"
    assert resp.json()["status"] == "blocked"


def test_escalate_then_approve(client: TestClient) -> None:
    resp = client.post(
        "/cases",
        json={
            "case_id": "api-escalate",
            "request": {
                "vendor_id": "V-1001",
                "amount": 50000,
                "item": "Server racks",
            },
            "mock_agent_plan": {
                "tool_name": "create_purchase_order",
                "tool_args": {
                    "vendor_id": "V-1001",
                    "amount": 50000,
                    "item": "Server racks",
                },
                "agent_rationale": (
                    "Purchase orders at or below USD 10,000 may be auto-approved when "
                    "the vendor is active on the vendor master list."
                ),
                "context_refs": ["chunk:policy:auto_approve", "chunk:vendor:V-1001"],
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["gateway_decision"]["decision"] == "escalate"
    assert body["status"] == "pending_approval"
    call_id = body["call_id"]
    assert call_id

    got = client.get("/cases/api-escalate")
    assert got.json()["status"] == "pending_approval"

    approved = client.post(
        f"/approvals/{call_id}",
        json={"action": "approve", "actor": "auditor"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "completed"

    audit = client.get("/cases/api-escalate/audit")
    types = {e["event_type"] for e in audit.json()["entries"]}
    assert "approval" in types
    assert audit.json()["chain_valid"] is True


def test_list_cases_newest_first(client: TestClient) -> None:
    plan = {
        "tool_name": "create_purchase_order",
        "tool_args": {"vendor_id": "V-1001", "amount": 100, "item": "x"},
        "agent_rationale": (
            "Purchase orders at or below USD 10,000 may be auto-approved when "
            "the vendor is active on the vendor master list."
        ),
        "context_refs": ["chunk:policy:auto_approve", "chunk:vendor:V-1001"],
    }
    first = client.post(
        "/cases",
        json={
            "case_id": "list-a",
            "request": {"vendor_id": "V-1001", "amount": 100, "item": "a"},
            "mock_agent_plan": plan,
        },
    )
    assert first.status_code == 200
    second = client.post(
        "/cases",
        json={
            "case_id": "list-b",
            "request": {"vendor_id": "V-1001", "amount": 100, "item": "b"},
            "mock_agent_plan": plan,
        },
    )
    assert second.status_code == 200

    listed = client.get("/cases")
    assert listed.status_code == 200
    cases = listed.json()["cases"]
    ids = [c["case_id"] for c in cases]
    assert "list-a" in ids and "list-b" in ids
    assert all("created_at" in c for c in cases)
    # Newest first: list-b should appear before list-a
    assert ids.index("list-b") < ids.index("list-a")
