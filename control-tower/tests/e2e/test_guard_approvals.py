"""E2E tests for the /guard/approvals/{call_id} pair — resolving a human
approval for a call that came in through POST /guard/evaluate (no LangGraph
thread, unlike /cases). Covers: status polling, approve, reject, re-resolve
rejection, unknown call_id, visibility + resolvability from the existing
dashboard /approvals endpoints, and audit-chain integrity. A separate
@pytest.mark.auth block covers cross-application authorization.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def client(tmp_path: Path, project_root: Path) -> TestClient:
    app = create_app(audit_path=tmp_path / "guard_approvals_audit.db", project_root=project_root)
    return TestClient(app)


# Resolving a guard_evaluate escalation requires an api_key-typed caller
# (see _authorize_guard_case_resolve) — with no Authorization header at all,
# require_dashboard_or_api_key defaults to "dashboard" (blocked, by design).
# Under the default test mode (AEGIS_DISABLE_AUTH=1) the key's actual value
# is never checked, only the "Bearer sk_" prefix used for routing — so a
# fake key is enough here; real ownership enforcement is covered by the
# @pytest.mark.auth block below instead.
_APP_HEADERS = {"Authorization": "Bearer sk_test_fake"}


def _escalate_a_call(client: TestClient) -> str:
    """create_purchase_order at $75,000 exceeds procurement_review's $10,000
    max_auto_amount — gateway.decide()'s over-limit rule escalates it
    deterministically, no live LLM/judge involved."""
    resp = client.post(
        "/guard/evaluate",
        json={
            "process": "procurement_review",
            "tool_name": "create_purchase_order",
            "tool_args": {"vendor_id": "V-1001", "amount": 75000, "item": "Data center hardware"},
            "agent_rationale": "Large capital purchase, needs sign-off.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision"] == "escalate", body
    return body["call_id"]


def test_escalated_call_is_pending_and_approve_resolves_it(client: TestClient) -> None:
    call_id = _escalate_a_call(client)

    pending = client.get(f"/guard/approvals/{call_id}")
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending_approval"
    assert pending.json()["decision"]["decision"] == "escalate"

    resolved = client.post(
        f"/guard/approvals/{call_id}",
        json={"action": "approve", "actor": "reviewer@example.com"},
        headers=_APP_HEADERS,
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "completed"
    assert body["decision"]["decision"] == "allow"

    # The caller's own tool never ran (the tower never executes anything for
    # a /guard/evaluate-originated case) — only the decision flips; a polling
    # SDK client is responsible for running its own function after this.
    after = client.get(f"/guard/approvals/{call_id}")
    assert after.json()["status"] == "completed"
    assert after.json()["decision"]["decision"] == "allow"


def test_reject_resolves_to_block_and_rejected_status(client: TestClient) -> None:
    call_id = _escalate_a_call(client)

    resolved = client.post(
        f"/guard/approvals/{call_id}",
        json={"action": "reject", "actor": "reviewer@example.com"},
        headers=_APP_HEADERS,
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "rejected"
    assert body["decision"]["decision"] == "block"


def test_resolving_an_already_resolved_call_is_a_409(client: TestClient) -> None:
    call_id = _escalate_a_call(client)
    first = client.post(
        f"/guard/approvals/{call_id}", json={"action": "approve", "actor": "a"}, headers=_APP_HEADERS
    )
    assert first.status_code == 200

    second = client.post(
        f"/guard/approvals/{call_id}", json={"action": "approve", "actor": "b"}, headers=_APP_HEADERS
    )
    assert second.status_code == 409


def test_unknown_call_id_is_404_for_get_and_post(client: TestClient) -> None:
    assert client.get("/guard/approvals/does-not-exist").status_code == 404
    resp = client.post(
        "/guard/approvals/does-not-exist", json={"action": "approve", "actor": "a"}
    )
    assert resp.status_code == 404


def test_non_escalated_call_id_is_still_readable_but_not_pending(client: TestClient) -> None:
    """A call that resolved to allow/block outright (never escalated) is
    still a real guard_evaluate case — GET returns it (so a polling client
    gets one consistent status shape for any call_id it holds) but its
    status is never "pending_approval", and resolving it is a 409."""
    resp = client.post(
        "/guard/evaluate",
        json={
            "process": "procurement_review",
            "tool_name": "send_payment",
            "tool_args": {"vendor_id": "V-1001", "amount": 500},
        },
    )
    call_id = resp.json()["call_id"]
    assert resp.json()["decision"] == "block"

    status = client.get(f"/guard/approvals/{call_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["decision"]["decision"] == "block"

    resolve = client.post(
        f"/guard/approvals/{call_id}", json={"action": "approve", "actor": "a"}, headers=_APP_HEADERS
    )
    assert resolve.status_code == 409


def test_escalated_guard_call_is_excluded_from_dashboard_approvals_list(client: TestClient) -> None:
    """The dashboard can't resolve a guard_evaluate escalation (only the
    owning application's own API key can — see _authorize_guard_case_resolve),
    so it must not appear in the Approval queue with Approve/Reject buttons
    that would just 403. It's still fully visible via Logs instead."""
    call_id = _escalate_a_call(client)
    listing = client.get("/approvals")
    assert listing.status_code == 200
    body = listing.json()
    assert all(r["call_id"] != call_id for r in body["approvals"])
    assert body["count"] == 0

    # Confirm it's not silently dropped — it's genuinely pending, just not
    # listed here.
    status = client.get(f"/guard/approvals/{call_id}")
    assert status.json()["status"] == "pending_approval"


def test_dashboard_legacy_approve_endpoint_refuses_guard_evaluate_calls(
    client: TestClient,
) -> None:
    """POST /approvals/{call_id} (the dashboard-only, LangGraph-resume-based
    endpoint) must refuse a /guard/evaluate-originated case rather than
    resolving it — the dashboard is view-only for these; only the owning
    application's own API key may resolve them, via POST
    /guard/approvals/{call_id}."""
    call_id = _escalate_a_call(client)
    resp = client.post(f"/approvals/{call_id}", json={"action": "approve", "actor": "ops"})
    assert resp.status_code == 403, resp.text

    # Confirm it's genuinely untouched, not silently resolved before the 403.
    still_pending = client.get(f"/guard/approvals/{call_id}")
    assert still_pending.json()["status"] == "pending_approval"


def test_approval_is_recorded_in_the_audit_chain(client: TestClient) -> None:
    before = client.get("/audit/verify").json()["entry_count"]
    call_id = _escalate_a_call(client)
    resp = client.post(
        f"/guard/approvals/{call_id}", json={"action": "approve", "actor": "ops"}, headers=_APP_HEADERS
    )
    assert resp.status_code == 200, resp.text
    after = client.get("/audit/verify")
    assert after.json()["entry_count"] > before
    assert after.json()["valid"] is True


@pytest.mark.auth
class TestGuardApprovalAuthorization:
    """A registered application's own API key may resolve its own escalated
    calls, but not another application's — @pytest.mark.auth so api/main.py's
    real auth checks run instead of the test-default AEGIS_DISABLE_AUTH=1."""

    @pytest.fixture
    def auth_client(
        self, tmp_path: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> TestClient:
        monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
        monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
        app = create_app(audit_path=tmp_path / "guard_approvals_auth.db", project_root=project_root)
        return TestClient(app)

    def _dashboard_token(self, client: TestClient) -> str:
        resp = client.post("/auth/login", json={"password": "test-password"})
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]

    def _register_app(self, client: TestClient, dashboard_token: str, source_app: str) -> str:
        resp = client.post(
            "/applications",
            json={"name": source_app, "process": "procurement_review", "source_app": source_app},
            headers={"Authorization": f"Bearer {dashboard_token}"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["api_key"]

    def test_owning_app_can_resolve_its_own_escalated_call(self, auth_client: TestClient) -> None:
        dash = self._dashboard_token(auth_client)
        key = self._register_app(auth_client, dash, "app_a")

        resp = auth_client.post(
            "/guard/evaluate",
            json={
                "process": "procurement_review",
                "tool_name": "create_purchase_order",
                "tool_args": {"vendor_id": "V-1001", "amount": 75000, "item": "Servers"},
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        call_id = resp.json()["call_id"]
        assert resp.json()["decision"] == "escalate"

        resolved = auth_client.post(
            f"/guard/approvals/{call_id}",
            json={"action": "approve", "actor": "app_a_operator"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resolved.status_code == 200, resolved.text

    def test_other_app_cannot_resolve_a_different_apps_escalated_call(
        self, auth_client: TestClient
    ) -> None:
        dash = self._dashboard_token(auth_client)
        key_a = self._register_app(auth_client, dash, "app_a")
        key_b = self._register_app(auth_client, dash, "app_b")

        resp = auth_client.post(
            "/guard/evaluate",
            json={
                "process": "procurement_review",
                "tool_name": "create_purchase_order",
                "tool_args": {"vendor_id": "V-1001", "amount": 75000, "item": "Servers"},
            },
            headers={"Authorization": f"Bearer {key_a}"},
        )
        call_id = resp.json()["call_id"]
        assert resp.json()["decision"] == "escalate"

        blocked = auth_client.post(
            f"/guard/approvals/{call_id}",
            json={"action": "approve", "actor": "app_b_operator"},
            headers={"Authorization": f"Bearer {key_b}"},
        )
        assert blocked.status_code == 403

        blocked_get = auth_client.get(
            f"/guard/approvals/{call_id}", headers={"Authorization": f"Bearer {key_b}"}
        )
        assert blocked_get.status_code == 403

    def test_dashboard_operator_can_view_but_not_resolve_an_escalated_call(
        self, auth_client: TestClient
    ) -> None:
        """The dashboard has full visibility (GET) into every escalation,
        including guard_evaluate ones, but only the owning application's own
        API key may resolve them — approval for these lives inside that
        application, not the tower's dashboard."""
        dash = self._dashboard_token(auth_client)
        key_a = self._register_app(auth_client, dash, "app_a")

        resp = auth_client.post(
            "/guard/evaluate",
            json={
                "process": "procurement_review",
                "tool_name": "create_purchase_order",
                "tool_args": {"vendor_id": "V-1001", "amount": 75000, "item": "Servers"},
            },
            headers={"Authorization": f"Bearer {key_a}"},
        )
        call_id = resp.json()["call_id"]

        viewed = auth_client.get(
            f"/guard/approvals/{call_id}", headers={"Authorization": f"Bearer {dash}"}
        )
        assert viewed.status_code == 200
        assert viewed.json()["status"] == "pending_approval"

        blocked = auth_client.post(
            f"/guard/approvals/{call_id}",
            json={"action": "approve", "actor": "dashboard_ops"},
            headers={"Authorization": f"Bearer {dash}"},
        )
        assert blocked.status_code == 403

        legacy_blocked = auth_client.post(
            f"/approvals/{call_id}",
            json={"action": "approve", "actor": "dashboard_ops"},
            headers={"Authorization": f"Bearer {dash}"},
        )
        assert legacy_blocked.status_code == 403
