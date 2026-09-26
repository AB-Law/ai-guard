"""Unit tests for GuardClient — mocks httpx.Client so these run with no server."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import aiguard
import pytest
from aiguard.client import GuardClient
from aiguard.config import GuardConfig, get_config


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _patch_http_client() -> MagicMock:
    mock_http = MagicMock()
    return mock_http


@pytest.fixture(autouse=True)
def _reset_config() -> None:
    # Ensure timeout default assertions aren't polluted by prior configure().
    cfg = get_config()
    cfg.api_url = "http://127.0.0.1:8000"
    cfg.process = "procurement_review"
    cfg.timeout = GuardConfig.timeout
    cfg.source_app = None
    cfg.api_key = None


def test_default_timeout_is_sixty_seconds() -> None:
    assert GuardConfig().timeout == 60.0
    with patch("aiguard.client.httpx.Client") as mock_cls:
        mock_cls.return_value = MagicMock()
        GuardClient()
    mock_cls.assert_called_once()
    assert mock_cls.call_args.kwargs.get("timeout") == 60.0


def test_evaluate_posts_to_guard_evaluate_with_expected_payload() -> None:
    aiguard.configure(api_url="http://example.test:9000", process="procurement_review")
    mock_http = MagicMock()
    mock_http.post.return_value = _mock_response(
        {"call_id": "abc", "decision": "allow", "reason": "ok", "policy_refs": []}
    )
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient()
        result = client.evaluate(tool_name="create_purchase_order", tool_args={"amount": 100})

    assert result["decision"] == "allow"
    args, kwargs = mock_http.post.call_args
    assert args[0] == "http://example.test:9000/guard/evaluate"
    body = kwargs["json"]
    assert body["tool_name"] == "create_purchase_order"
    assert body["tool_args"] == {"amount": 100}
    assert body["process"] == "procurement_review"
    assert "call_id" not in body  # not supplied -> omitted, not sent as null


def test_client_reuses_same_http_transport_across_calls() -> None:
    mock_http = MagicMock()
    mock_http.post.return_value = _mock_response({"call_id": "1", "decision": "allow"})
    with patch("aiguard.client.httpx.Client", return_value=mock_http) as mock_cls:
        client = GuardClient(api_url="http://example.test:9000")
        client.evaluate(tool_name="a")
        client.evaluate(tool_name="b")
    assert mock_cls.call_count == 1
    assert mock_http.post.call_count == 2


def test_evaluate_includes_call_id_when_supplied() -> None:
    mock_http = MagicMock()
    mock_http.post.return_value = _mock_response(
        {"call_id": "xyz", "decision": "block", "reason": "no"}
    )
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient(api_url="http://example.test:9000")
        client.evaluate(tool_name="t", call_id="my-call-id")

    body = mock_http.post.call_args.kwargs["json"]
    assert body["call_id"] == "my-call-id"


def test_evaluate_includes_source_app_from_configure() -> None:
    aiguard.configure(
        api_url="http://example.test:9000",
        process="finance",
        source_app="finance_app",
    )
    mock_http = MagicMock()
    mock_http.post.return_value = _mock_response({"call_id": "1", "decision": "allow"})
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        GuardClient().evaluate(tool_name="submit_expense_report", tool_args={"amount": 10})

    assert mock_http.post.call_args.kwargs["json"]["source_app"] == "finance_app"


def test_per_call_process_overrides_global_config() -> None:
    aiguard.configure(process="procurement_review")
    mock_http = MagicMock()
    mock_http.post.return_value = _mock_response({"call_id": "1", "decision": "allow"})
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        GuardClient(api_url="http://example.test:9000").evaluate(
            tool_name="verify_identity", process="onboarding_kyc"
        )

    assert mock_http.post.call_args.kwargs["json"]["process"] == "onboarding_kyc"


def test_get_approval_gets_the_guard_approvals_endpoint() -> None:
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response(
        {"call_id": "c1", "status": "pending_approval", "decision": {"decision": "escalate"}}
    )
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient(api_url="http://example.test:9000", api_key="sk_test_abc")
        result = client.get_approval("c1")

    assert result["status"] == "pending_approval"
    args, kwargs = mock_http.get.call_args
    assert args[0] == "http://example.test:9000/guard/approvals/c1"
    assert kwargs["headers"]["Authorization"] == "Bearer sk_test_abc"


def test_get_approval_omits_auth_header_when_no_api_key() -> None:
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response({"call_id": "c1", "status": "completed"})
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        GuardClient(api_url="http://example.test:9000").get_approval("c1")

    headers = mock_http.get.call_args.kwargs["headers"]
    assert "Authorization" not in headers


def test_resolve_approval_posts_action_and_actor() -> None:
    mock_http = MagicMock()
    mock_http.post.return_value = _mock_response(
        {"call_id": "c1", "status": "completed", "decision": {"decision": "allow"}}
    )
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient(api_url="http://example.test:9000")
        result = client.resolve_approval("c1", action="approve", actor="alice")

    assert result["status"] == "completed"
    args, kwargs = mock_http.post.call_args
    assert args[0] == "http://example.test:9000/guard/approvals/c1"
    assert kwargs["json"] == {"action": "approve", "actor": "alice"}


def test_wait_for_decision_returns_immediately_when_already_resolved() -> None:
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response(
        {"call_id": "c1", "status": "completed", "decision": {"decision": "allow"}}
    )
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient(api_url="http://example.test:9000")
        result = client.wait_for_decision("c1", poll_interval=0.01, timeout=1.0)

    assert result["status"] == "completed"
    assert mock_http.get.call_count == 1


def test_wait_for_decision_polls_until_resolved() -> None:
    responses = [
        _mock_response({"call_id": "c1", "status": "pending_approval"}),
        _mock_response({"call_id": "c1", "status": "pending_approval"}),
        _mock_response({"call_id": "c1", "status": "completed", "decision": {"decision": "allow"}}),
    ]
    mock_http = MagicMock()
    mock_http.get.side_effect = responses
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient(api_url="http://example.test:9000")
        result = client.wait_for_decision("c1", poll_interval=0.001, timeout=5.0)

    assert result["status"] == "completed"
    assert mock_http.get.call_count == 3


def test_wait_for_decision_times_out_while_still_pending() -> None:
    mock_http = MagicMock()
    mock_http.get.return_value = _mock_response({"call_id": "c1", "status": "pending_approval"})
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient(api_url="http://example.test:9000")
        with pytest.raises(TimeoutError):
            client.wait_for_decision("c1", poll_interval=0.01, timeout=0.03)


def test_heartbeat_posts_to_applications_heartbeat() -> None:
    mock_http = MagicMock()
    mock_http.post.return_value = _mock_response(
        {"app_id": "app_1", "last_seen_at": "2026-01-01T00:00:00+00:00", "health": "online"}
    )
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient(api_url="http://example.test:9000", api_key="sk_test_abc")
        result = client.heartbeat()

    assert result["health"] == "online"
    args, kwargs = mock_http.post.call_args
    assert args[0] == "http://example.test:9000/applications/heartbeat"
    assert kwargs["headers"]["Authorization"] == "Bearer sk_test_abc"


def test_update_inventory_patches_applications() -> None:
    mock_http = MagicMock()
    mock_http.request.return_value = _mock_response(
        {"app_id": "app_1", "owner": "alice", "tools": ["create_purchase_order"]}
    )
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient(api_url="http://example.test:9000", api_key="sk_test_abc")
        result = client.update_inventory(
            "app_1", owner="alice", tools=["create_purchase_order"]
        )

    assert result["owner"] == "alice"
    args, kwargs = mock_http.request.call_args
    assert args[0] == "PATCH"
    assert args[1] == "http://example.test:9000/applications/app_1"
    assert kwargs["json"] == {"owner": "alice", "tools": ["create_purchase_order"]}
    assert kwargs["headers"]["Authorization"] == "Bearer sk_test_abc"


def test_headers_inject_w3c_traceparent_when_span_active() -> None:
    pytest.importorskip("opentelemetry")
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    trace.set_tracer_provider(TracerProvider())
    mock_http = MagicMock()
    mock_http.post.return_value = _mock_response({"call_id": "1", "decision": "allow"})
    with patch("aiguard.client.httpx.Client", return_value=mock_http):
        client = GuardClient(api_url="http://example.test:9000", api_key="sk_test")
        with trace.get_tracer("test").start_as_current_span("client"):
            client.evaluate(tool_name="t")
    headers = mock_http.post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk_test"
    assert "traceparent" in headers
    assert headers["traceparent"].startswith("00-")
