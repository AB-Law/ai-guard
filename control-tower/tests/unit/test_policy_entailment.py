"""Unit tests for policy entailment judge."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from contracts.schemas import PolicyEntailmentResult, ToolCallRequest
from guardrails.policy_entailment import check_policy_entailment


def _request() -> ToolCallRequest:
    return ToolCallRequest(
        call_id="ent-1",
        process="procurement_review",
        step_id="gateway_check",
        tool_name="create_purchase_order",
        tool_args={"vendor_id": "V-1001", "amount": 2500},
        agent_rationale="Vendor is active; amount under limit.",
        context_refs=["chunk:policy:auto_approve", "chunk:vendor:V-1001"],
        timestamp="2026-01-01T00:00:00+00:00",
    )


def test_offline_noop_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = check_policy_entailment(_request(), ["Vendor V-1001: status=active"])
    assert result.compliant is True
    assert result.severity == "none"
    assert result.violated_clauses == []


def test_stubbed_hard_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    hard = PolicyEntailmentResult(
        compliant=False,
        violated_clauses=["vendor must be active"],
        severity="hard",
    )
    with patch("guardrails.policy_entailment._llm_entail", return_value=hard) as mock_llm:
        result = check_policy_entailment(_request(), ["Vendor V-9999: status=blocked"])
    mock_llm.assert_called_once()
    assert result.severity == "hard"
    assert "vendor must be active" in result.violated_clauses


def test_stubbed_soft_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    soft = PolicyEntailmentResult(
        compliant=False,
        violated_clauses=["duplicate-PO check incomplete"],
        severity="soft",
    )
    with patch("guardrails.policy_entailment._llm_entail", return_value=soft):
        result = check_policy_entailment(_request(), ["policy text"])
    assert result.severity == "soft"
    assert result.compliant is False


def test_stubbed_compliant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    ok = PolicyEntailmentResult(compliant=True, violated_clauses=[], severity="none")
    with patch("guardrails.policy_entailment._llm_entail", return_value=ok):
        result = check_policy_entailment(_request(), ["Vendor V-1001: status=active"])
    assert result.compliant is True
    assert result.severity == "none"
