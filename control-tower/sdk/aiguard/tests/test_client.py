"""Unit tests for GuardClient — mocks httpx.post/get so these run with no server."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import aiguard
import pytest
from aiguard.client import GuardClient


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def test_evaluate_posts_to_guard_evaluate_with_expected_payload() -> None:
    aiguard.configure(api_url="http://example.test:9000", process="procurement_review")
    with patch("aiguard.client.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"call_id": "abc", "decision": "allow", "reason": "ok", "policy_refs": []}
        )
        client = GuardClient()
        result = client.evaluate(tool_name="create_purchase_order", tool_args={"amount": 100})

    assert result["decision"] == "allow"
    args, kwargs = mock_post.call_args
    assert args[0] == "http://example.test:9000/guard/evaluate"
    body = kwargs["json"]
    assert body["tool_name"] == "create_purchase_order"
    assert body["tool_args"] == {"amount": 100}
    assert body["process"] == "procurement_review"
    assert "call_id" not in body  # not supplied -> omitted, not sent as null


def test_evaluate_includes_call_id_when_supplied() -> None:
    with patch("aiguard.client.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"call_id": "xyz", "decision": "block", "reason": "no"}
        )
        client = GuardClient(api_url="http://example.test:9000")
        client.evaluate(tool_name="t", call_id="my-call-id")

    body = mock_post.call_args.kwargs["json"]
    assert body["call_id"] == "my-call-id"


def test_evaluate_includes_source_app_from_configure() -> None:
    aiguard.configure(
        api_url="http://example.test:9000",
        process="finance",
        source_app="finance_app",
    )
    with patch("aiguard.client.httpx.post") as mock_post:
        mock_post.return_value = _mock_response({"call_id": "1", "decision": "allow"})
        GuardClient().evaluate(tool_name="submit_expense_report", tool_args={"amount": 10})

    assert mock_post.call_args.kwargs["json"]["source_app"] == "finance_app"


def test_per_call_process_overrides_global_config() -> None:
    aiguard.configure(process="procurement_review")
    with patch("aiguard.client.httpx.post") as mock_post:
        mock_post.return_value = _mock_response({"call_id": "1", "decision": "allow"})
        GuardClient(api_url="http://example.test:9000").evaluate(
            tool_name="verify_identity", process="onboarding_kyc"
        )

    assert mock_post.call_args.kwargs["json"]["process"] == "onboarding_kyc"


def test_get_approval_gets_the_guard_approvals_endpoint() -> None:
    with patch("aiguard.client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(
            {"call_id": "c1", "status": "pending_approval", "decision": {"decision": "escalate"}}
        )
        client = GuardClient(api_url="http://example.test:9000", api_key="sk_test_abc")
        result = client.get_approval("c1")

    assert result["status"] == "pending_approval"
    args, kwargs = mock_get.call_args
    assert args[0] == "http://example.test:9000/guard/approvals/c1"
    assert kwargs["headers"] == {"Authorization": "Bearer sk_test_abc"}


def test_get_approval_omits_auth_header_when_no_api_key() -> None:
    with patch("aiguard.client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response({"call_id": "c1", "status": "completed"})
        GuardClient(api_url="http://example.test:9000").get_approval("c1")

    assert mock_get.call_args.kwargs["headers"] == {}


def test_resolve_approval_posts_action_and_actor() -> None:
    with patch("aiguard.client.httpx.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"call_id": "c1", "status": "completed", "decision": {"decision": "allow"}}
        )
        client = GuardClient(api_url="http://example.test:9000")
        result = client.resolve_approval("c1", action="approve", actor="alice")

    assert result["status"] == "completed"
    args, kwargs = mock_post.call_args
    assert args[0] == "http://example.test:9000/guard/approvals/c1"
    assert kwargs["json"] == {"action": "approve", "actor": "alice"}


def test_wait_for_decision_returns_immediately_when_already_resolved() -> None:
    with patch("aiguard.client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response(
            {"call_id": "c1", "status": "completed", "decision": {"decision": "allow"}}
        )
        client = GuardClient(api_url="http://example.test:9000")
        result = client.wait_for_decision("c1", poll_interval=0.01, timeout=1.0)

    assert result["status"] == "completed"
    assert mock_get.call_count == 1


def test_wait_for_decision_polls_until_resolved() -> None:
    responses = [
        _mock_response({"call_id": "c1", "status": "pending_approval"}),
        _mock_response({"call_id": "c1", "status": "pending_approval"}),
        _mock_response({"call_id": "c1", "status": "completed", "decision": {"decision": "allow"}}),
    ]
    with patch("aiguard.client.httpx.get", side_effect=responses) as mock_get:
        client = GuardClient(api_url="http://example.test:9000")
        result = client.wait_for_decision("c1", poll_interval=0.001, timeout=5.0)

    assert result["status"] == "completed"
    assert mock_get.call_count == 3


def test_wait_for_decision_times_out_while_still_pending() -> None:
    with patch("aiguard.client.httpx.get") as mock_get:
        mock_get.return_value = _mock_response({"call_id": "c1", "status": "pending_approval"})
        client = GuardClient(api_url="http://example.test:9000")
        with pytest.raises(TimeoutError):
            client.wait_for_decision("c1", poll_interval=0.01, timeout=0.03)
