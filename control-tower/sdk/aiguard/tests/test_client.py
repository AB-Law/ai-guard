"""Unit tests for GuardClient — mocks httpx.post so these run with no server."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import aiguard
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
