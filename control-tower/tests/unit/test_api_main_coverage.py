"""Additional tests for api/main.py endpoints to increase coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def client(tmp_path: Path, project_root: Path) -> TestClient:
    app = create_app(audit_path=tmp_path / "main_test_audit.db", project_root=project_root)
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    """Test /health endpoint."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_configs_endpoint(client: TestClient) -> None:
    """Test /configs endpoint."""
    resp = client.get("/configs")
    assert resp.status_code == 200
    body = resp.json()
    assert "processes" in body
    assert len(body["processes"]) > 0
    
    # Check structure of first process
    proc = body["processes"][0]
    assert "id" in proc
    assert "title" in proc
    assert "config_path" in proc
    assert "allowed_tools" in proc
    assert "disallowed_tools" in proc
    assert "approval_threshold" in proc
    assert "seed_docs" in proc
    assert "uploaded_docs" in proc


def test_list_audit_entries_default(client: TestClient) -> None:
    """Test /audit/entries with default parameters."""
    # Submit a case to generate audit entries
    client.post(
        "/cases",
        json={
            "case_id": "audit-list-test",
            "request": {"vendor_id": "V-1001", "amount": 100, "item": "Test"},
            "mock_agent_plan": {
                "tool_name": "create_purchase_order",
                "tool_args": {"vendor_id": "V-1001", "amount": 100},
                "agent_rationale": "Test",
                "context_refs": [],
            },
        },
    )
    
    resp = client.get("/audit/entries")
    assert resp.status_code == 200
    body = resp.json()
    assert "entries" in body
    assert "total" in body
    assert "limit" in body
    assert "offset" in body
    assert body["limit"] == 100
    assert body["offset"] == 0


def test_list_audit_entries_with_limit_and_offset(client: TestClient) -> None:
    """Test /audit/entries with pagination."""
    resp = client.get("/audit/entries?limit=5&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 5
    assert body["offset"] == 0


def test_list_audit_entries_invalid_limit(client: TestClient) -> None:
    """Test /audit/entries with invalid limit."""
    resp = client.get("/audit/entries?limit=0")
    assert resp.status_code == 422


def test_list_audit_entries_with_process_filter(client: TestClient) -> None:
    """Test /audit/entries with process filter."""
    resp = client.get("/audit/entries?process=procurement_review")
    assert resp.status_code == 200
    body = resp.json()
    assert "entries" in body


def test_list_audit_entries_with_event_type_filter(client: TestClient) -> None:
    """Test /audit/entries with event_type filter."""
    resp = client.get("/audit/entries?event_type=retrieval")
    assert resp.status_code == 200
    body = resp.json()
    assert "entries" in body


def test_list_audit_entries_with_decision_filter(client: TestClient) -> None:
    """Test /audit/entries with decision filter."""
    resp = client.get("/audit/entries?decision=allow")
    assert resp.status_code == 200
    body = resp.json()
    assert "entries" in body


def test_create_application_endpoint(client: TestClient) -> None:
    """Test POST /applications."""
    resp = client.post(
        "/applications",
        json={
            "name": "Test Application",
            "environment": "staging",
            "process": "procurement_review",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Test Application"
    assert body["environment"] == "staging"
    assert body["process"] == "procurement_review"
    assert "api_key" in body  # Only returned on creation
    assert body["api_key"].startswith("sk_test_")
    assert "app_id" in body
    assert body["status"] == "connected"


def test_create_application_with_custom_source_app(client: TestClient) -> None:
    """Test creating application with custom source_app."""
    resp = client.post(
        "/applications",
        json={
            "name": "Custom App",
            "environment": "production",
            "process": "procurement_review",
            "source_app": "custom_source",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_app"] == "custom_source"
    assert body["api_key"].startswith("sk_live_")


def test_create_application_unknown_process(client: TestClient) -> None:
    """Test creating application with unknown process returns 400."""
    resp = client.post(
        "/applications",
        json={
            "name": "Bad App",
            "process": "unknown_process",
        },
    )
    assert resp.status_code == 400


def test_list_applications_endpoint(client: TestClient) -> None:
    """Test GET /applications."""
    resp = client.get("/applications")
    assert resp.status_code == 200
    body = resp.json()
    assert "applications" in body
    # Should have default seeded applications
    assert len(body["applications"]) > 0


def test_revoke_application_endpoint(client: TestClient) -> None:
    """Test POST /applications/{app_id}/revoke."""
    # Create an application first
    create_resp = client.post(
        "/applications",
        json={
            "name": "To Be Revoked",
            "process": "procurement_review",
        },
    )
    app_id = create_resp.json()["app_id"]
    
    # Revoke it
    revoke_resp = client.post(f"/applications/{app_id}/revoke")
    assert revoke_resp.status_code == 200
    body = revoke_resp.json()
    assert body["status"] == "revoked"
    assert body["revoked_at"] is not None


def test_revoke_nonexistent_application(client: TestClient) -> None:
    """Test revoking non-existent application returns 404."""
    resp = client.post("/applications/nonexistent-app-id/revoke")
    assert resp.status_code == 404


def _assert_no_key_secrets(view: dict) -> None:
    assert "key_hash" not in view
    assert "key_prefix" not in view
    assert "key_last4" not in view
    # Plaintext api_key only on create — callers of this helper should pass
    # list/patch/heartbeat/revoke bodies.
    assert "api_key" not in view


def test_create_application_defaults_inventory_fields(client: TestClient) -> None:
    """Existing clients omitting inventory fields still get safe defaults."""
    resp = client.post(
        "/applications",
        json={"name": "Minimal App", "process": "procurement_review"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["owner"] is None
    assert body["team"] is None
    assert body["description"] is None
    assert body["framework"] is None
    assert body["runtime"] is None
    assert body["tools"] == []
    assert body["capabilities"] == []
    assert body["mcp_servers"] == []
    assert body["last_seen_at"] is None
    assert body["last_seen"] is None
    assert body["health"] == "never_seen"
    assert "api_key" in body
    assert "key_hash" not in body


def test_create_application_with_inventory_metadata(client: TestClient) -> None:
    resp = client.post(
        "/applications",
        json={
            "name": "Inventory App",
            "process": "procurement_review",
            "owner": "alice@example.com",
            "team": "Platform",
            "description": "Demo agent",
            "framework": "langchain",
            "runtime": "python3.12",
            "tools": ["create_purchase_order"],
            "capabilities": ["procure"],
            "mcp_servers": [
                {"name": "docs", "url": "http://127.0.0.1:3100", "tools": ["search"]}
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["owner"] == "alice@example.com"
    assert body["team"] == "Platform"
    assert body["framework"] == "langchain"
    assert body["tools"] == ["create_purchase_order"]
    assert body["mcp_servers"][0]["name"] == "docs"
    list_resp = client.get("/applications")
    listed = next(a for a in list_resp.json()["applications"] if a["app_id"] == body["app_id"])
    _assert_no_key_secrets(listed)
    assert listed["owner"] == "alice@example.com"


def test_patch_application_inventory_when_auth_disabled(client: TestClient) -> None:
    created = client.post(
        "/applications",
        json={"name": "Patch Me", "process": "procurement_review"},
    ).json()
    app_id = created["app_id"]
    resp = client.patch(
        f"/applications/{app_id}",
        json={"owner": "bob@example.com", "tools": ["search_knowledge_base"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["owner"] == "bob@example.com"
    assert body["tools"] == ["search_knowledge_base"]
    _assert_no_key_secrets(body)


def test_list_applications_omits_key_secrets(client: TestClient) -> None:
    resp = client.get("/applications")
    assert resp.status_code == 200
    for app in resp.json()["applications"]:
        _assert_no_key_secrets(app)
        assert "key_display" in app


def test_demo_tamper_enable(client: TestClient) -> None:
    """Test POST /audit/demo-tamper with enable=true."""
    # Submit a case first to have audit entries
    client.post(
        "/cases",
        json={
            "case_id": "tamper-test",
            "request": {"vendor_id": "V-1001", "amount": 100, "item": "Test"},
            "mock_agent_plan": {
                "tool_name": "create_purchase_order",
                "tool_args": {"vendor_id": "V-1001", "amount": 100},
                "agent_rationale": "Test",
                "context_refs": [],
            },
        },
    )
    
    resp = client.post("/audit/demo-tamper", json={"enable": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tampered"] is True
    assert "entry_id" in body


def test_demo_tamper_disable(client: TestClient) -> None:
    """Test POST /audit/demo-tamper with enable=false."""
    # Enable first
    client.post(
        "/cases",
        json={
            "case_id": "tamper-test-2",
            "request": {"vendor_id": "V-1001", "amount": 100, "item": "Test"},
            "mock_agent_plan": {
                "tool_name": "create_purchase_order",
                "tool_args": {"vendor_id": "V-1001", "amount": 100},
                "agent_rationale": "Test",
                "context_refs": [],
            },
        },
    )
    client.post("/audit/demo-tamper", json={"enable": True})
    
    # Now disable
    resp = client.post("/audit/demo-tamper", json={"enable": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tampered"] is False


def test_traffic_recent_with_since_minutes(client: TestClient) -> None:
    """Test /traffic/recent with since_minutes filter."""
    resp = client.get("/traffic/recent?since_minutes=60")
    assert resp.status_code == 200
    body = resp.json()
    assert body["since_minutes"] == 60


def test_traffic_recent_with_source_app_filter(client: TestClient) -> None:
    """Test /traffic/recent with source_app filter."""
    resp = client.get("/traffic/recent?source_app=test_app")
    assert resp.status_code == 200
    body = resp.json()
    assert "cases" in body


def test_traffic_recent_with_decision_filter(client: TestClient) -> None:
    """Test /traffic/recent with decision filter."""
    resp = client.get("/traffic/recent?decision=allow")
    assert resp.status_code == 200
    body = resp.json()
    assert "cases" in body


def test_traffic_recent_invalid_limit(client: TestClient) -> None:
    """Test /traffic/recent with invalid limit."""
    resp = client.get("/traffic/recent?limit=0")
    assert resp.status_code == 422


def test_traffic_recent_invalid_since_minutes(client: TestClient) -> None:
    """Test /traffic/recent with invalid since_minutes."""
    resp = client.get("/traffic/recent?since_minutes=0")
    assert resp.status_code == 422


def test_get_case_not_found(client: TestClient) -> None:
    """Test GET /cases/{case_id} for non-existent case."""
    resp = client.get("/cases/nonexistent-case-id")
    assert resp.status_code == 404


def test_get_case_audit_not_found(client: TestClient) -> None:
    """Test GET /cases/{case_id}/audit for non-existent case."""
    resp = client.get("/cases/nonexistent-case-id/audit")
    assert resp.status_code == 404


def test_list_approvals_empty(client: TestClient) -> None:
    """Test GET /approvals when no approvals pending."""
    resp = client.get("/approvals")
    assert resp.status_code == 200
    body = resp.json()
    assert "approvals" in body
    assert "count" in body


def test_approve_nonexistent_call_id(client: TestClient) -> None:
    """Test POST /approvals/{call_id} with non-existent call_id."""
    resp = client.post(
        "/approvals/nonexistent-call-id",
        json={"action": "approve", "actor": "test-user"},
    )
    assert resp.status_code == 404


def test_upload_document_invalid_extension(client: TestClient) -> None:
    """Test uploading file with invalid extension."""
    resp = client.post(
        "/knowledge/documents",
        files={"file": ("test.exe", b"binary content", "application/octet-stream")},
        data={"process": "procurement_review"},
    )
    assert resp.status_code == 400
    assert "Only" in resp.json()["detail"]


def test_upload_document_empty_file(client: TestClient) -> None:
    """Test uploading empty file."""
    resp = client.post(
        "/knowledge/documents",
        files={"file": ("test.md", b"", "text/markdown")},
        data={"process": "procurement_review"},
    )
    assert resp.status_code == 400
    assert "Empty file" in resp.json()["detail"]


def test_upload_document_unknown_process(client: TestClient) -> None:
    """Test uploading to unknown process."""
    resp = client.post(
        "/knowledge/documents",
        files={"file": ("test.md", b"content", "text/markdown")},
        data={"process": "unknown_process"},
    )
    assert resp.status_code == 400


def test_upload_document_too_large(client: TestClient) -> None:
    """Test uploading file that's too large."""
    large_content = b"x" * (3 * 1024 * 1024)  # 3MB, over the 2MB limit
    resp = client.post(
        "/knowledge/documents",
        files={"file": ("large.txt", large_content, "text/plain")},
        data={"process": "procurement_review"},
    )
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"]


def test_investigate_without_case_id(client: TestClient) -> None:
    """Test POST /investigate without case_id."""
    resp = client.post(
        "/investigate",
        json={
            "question": "What happened?",
            "mock_answer": {
                "answer": "Mock response",
                "cited_entry_ids": [],
                "cited_chunk_ids": [],
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Mock response"


def test_investigate_with_nonexistent_case_id(client: TestClient) -> None:
    """Test POST /investigate with non-existent case_id."""
    resp = client.post(
        "/investigate",
        json={
            "question": "What happened?",
            "case_id": "nonexistent-case",
            "mock_answer": {
                "answer": "No case found, using all entries",
                "cited_entry_ids": [],
                "cited_chunk_ids": [],
            },
        },
    )
    assert resp.status_code == 200


def test_submit_case_without_case_id_generates_one(client: TestClient) -> None:
    """Test submitting case without case_id generates UUID."""
    resp = client.post(
        "/cases",
        json={
            "request": {"vendor_id": "V-1001", "amount": 100, "item": "Test"},
            "mock_agent_plan": {
                "tool_name": "create_purchase_order",
                "tool_args": {"vendor_id": "V-1001", "amount": 100},
                "agent_rationale": "Test",
                "context_refs": [],
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "case_id" in body
    assert body["case_id"]  # Not empty


def test_guard_evaluate_with_custom_step_id(client: TestClient) -> None:
    """Test /guard/evaluate with custom step_id."""
    resp = client.post(
        "/guard/evaluate",
        json={
            "process": "procurement_review",
            "tool_name": "create_purchase_order",
            "tool_args": {"vendor_id": "V-1001", "amount": 100},
            "step_id": "custom-step-id",
        },
    )
    assert resp.status_code == 200


def test_case_request_body_with_extra_fields(client: TestClient) -> None:
    """Test that CaseRequestBody accepts extra fields."""
    resp = client.post(
        "/cases",
        json={
            "case_id": "extra-fields-test",
            "request": {
                "vendor_id": "V-1001",
                "amount": 100,
                "item": "Test",
                "extra_field": "extra_value",
                "another_extra": 123,
            },
            "mock_agent_plan": {
                "tool_name": "create_purchase_order",
                "tool_args": {"vendor_id": "V-1001", "amount": 100},
                "agent_rationale": "Test",
                "context_refs": [],
            },
        },
    )
    assert resp.status_code == 200
