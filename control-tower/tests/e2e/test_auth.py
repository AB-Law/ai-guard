"""E2E tests for the two auth mechanisms: dashboard login (POST /auth/login,
a bearer session token) and agent API keys (POST /applications, a bearer
sk_* key). tests/conftest.py's _test_auth_mode fixture sets
AEGIS_DISABLE_AUTH=1 for every other test — these opt back in with
@pytest.mark.auth so the checks in api/main.py actually run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

pytestmark = pytest.mark.auth


@pytest.fixture
def client(
    tmp_path: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    app = create_app(audit_path=tmp_path / "auth_audit.db", project_root=project_root)
    return TestClient(app)


def _login(client: TestClient, password: str = "test-password") -> str:
    resp = client.post("/auth/login", json={"password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_rejects_wrong_password(client: TestClient) -> None:
    resp = client.post("/auth/login", json={"password": "nope"})
    assert resp.status_code == 401


def test_login_issues_a_bearer_token(client: TestClient) -> None:
    token = _login(client)
    assert token


def test_dashboard_endpoint_requires_token(client: TestClient) -> None:
    resp = client.get("/cases")
    assert resp.status_code == 401


def test_dashboard_endpoint_accepts_valid_token(client: TestClient) -> None:
    token = _login(client)
    resp = client.get("/cases", headers=_auth_headers(token))
    assert resp.status_code == 200


def test_dashboard_endpoint_rejects_garbage_token(client: TestClient) -> None:
    resp = client.get("/cases", headers=_auth_headers("not-a-real-token"))
    assert resp.status_code == 401


def test_guard_evaluate_requires_api_key(client: TestClient) -> None:
    resp = client.post(
        "/guard/evaluate",
        json={"process": "finance", "tool_name": "submit_expense_report"},
    )
    assert resp.status_code == 401


def test_guard_evaluate_rejects_unknown_key(client: TestClient) -> None:
    resp = client.post(
        "/guard/evaluate",
        json={"process": "finance", "tool_name": "submit_expense_report"},
        headers=_auth_headers("sk_test_doesnotexist"),
    )
    assert resp.status_code == 401


def test_guard_evaluate_accepts_registered_key_and_binds_process(
    client: TestClient,
) -> None:
    dashboard_token = _login(client)
    created = client.post(
        "/applications",
        json={"name": "Finance Agent", "process": "finance", "source_app": "finance_app"},
        headers=_auth_headers(dashboard_token),
    )
    assert created.status_code == 200, created.text
    api_key = created.json()["api_key"]

    # Body claims a different process than the app is registered for — the
    # endpoint must bind to the authenticated app's own process, not trust it.
    resp = client.post(
        "/guard/evaluate",
        json={
            "process": "procurement_review",
            "tool_name": "submit_expense_report",
            "tool_args": {"employee_id": "E-1001", "amount": 100, "item": "Office supplies"},
            "agent_rationale": "Receipt attached; under threshold.",
        },
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 200, resp.text

    traffic = client.get("/traffic/recent", headers=_auth_headers(dashboard_token))
    rows = traffic.json()["cases"]
    assert any(r["process"] == "finance" and r["source_app"] == "finance_app" for r in rows)


def test_revoked_key_is_rejected(client: TestClient) -> None:
    dashboard_token = _login(client)
    created = client.post(
        "/applications",
        json={"name": "RAG Bot", "process": "rag_bot"},
        headers=_auth_headers(dashboard_token),
    )
    app_id = created.json()["app_id"]
    api_key = created.json()["api_key"]

    revoke = client.post(
        f"/applications/{app_id}/revoke", headers=_auth_headers(dashboard_token)
    )
    assert revoke.status_code == 200
    assert revoke.json()["health"] is None

    resp = client.post(
        "/guard/evaluate",
        json={"process": "rag_bot", "tool_name": "search_knowledge_base"},
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 401


def test_heartbeat_bound_to_authenticated_application(client: TestClient) -> None:
    dashboard_token = _login(client)
    created = client.post(
        "/applications",
        json={"name": "Heartbeat Agent", "process": "finance", "source_app": "hb_app"},
        headers=_auth_headers(dashboard_token),
    ).json()
    api_key = created["api_key"]
    app_id = created["app_id"]
    assert created["last_seen_at"] is None
    assert "key_hash" not in created

    hb = client.post("/applications/heartbeat", headers=_auth_headers(api_key))
    assert hb.status_code == 200, hb.text
    body = hb.json()
    assert body["app_id"] == app_id
    assert body["last_seen_at"] is not None
    assert body["last_seen"] == body["last_seen_at"]
    assert body["health"] == "online"
    assert "api_key" not in body
    assert "key_hash" not in body
    # No way to spoof another app via body — endpoint accepts no source_app.
    assert client.post(
        "/applications/heartbeat",
        json={"source_app": "someone_else"},
        headers=_auth_headers(api_key),
    ).json()["app_id"] == app_id


def test_authenticated_evaluate_updates_last_seen_at(client: TestClient) -> None:
    dashboard_token = _login(client)
    created = client.post(
        "/applications",
        json={"name": "Seen Agent", "process": "finance", "source_app": "seen_app"},
        headers=_auth_headers(dashboard_token),
    ).json()
    api_key = created["api_key"]
    app_id = created["app_id"]

    resp = client.post(
        "/guard/evaluate",
        json={
            "process": "finance",
            "tool_name": "submit_expense_report",
            "tool_args": {"employee_id": "E-1", "amount": 10, "item": "Pens"},
            "agent_rationale": "Under threshold.",
        },
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 200, resp.text

    listed = client.get("/applications", headers=_auth_headers(dashboard_token)).json()
    row = next(a for a in listed["applications"] if a["app_id"] == app_id)
    assert row["last_seen_at"] is not None
    assert row["health"] == "online"
    assert "key_hash" not in row
    assert "api_key" not in row


def test_patch_inventory_ownership(client: TestClient) -> None:
    dashboard_token = _login(client)
    a = client.post(
        "/applications",
        json={"name": "Owner A", "process": "finance", "source_app": "owner_a"},
        headers=_auth_headers(dashboard_token),
    ).json()
    b = client.post(
        "/applications",
        json={"name": "Owner B", "process": "rag_bot", "source_app": "owner_b"},
        headers=_auth_headers(dashboard_token),
    ).json()

    # Own key may patch own inventory.
    own = client.patch(
        f"/applications/{a['app_id']}",
        json={"owner": "alice", "framework": "langgraph"},
        headers=_auth_headers(a["api_key"]),
    )
    assert own.status_code == 200, own.text
    assert own.json()["owner"] == "alice"
    assert "api_key" not in own.json()
    assert "key_hash" not in own.json()

    # Other app's key cannot patch.
    cross = client.patch(
        f"/applications/{a['app_id']}",
        json={"owner": "eve"},
        headers=_auth_headers(b["api_key"]),
    )
    assert cross.status_code == 403

    # Dashboard may patch any.
    dash = client.patch(
        f"/applications/{b['app_id']}",
        json={"team": "Risk", "tools": ["search_knowledge_base"]},
        headers=_auth_headers(dashboard_token),
    )
    assert dash.status_code == 200, dash.text
    assert dash.json()["team"] == "Risk"
    assert dash.json()["tools"] == ["search_knowledge_base"]
