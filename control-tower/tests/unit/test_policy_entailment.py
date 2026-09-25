"""Unit tests for policy entailment judge."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from contracts.schemas import PolicyEntailmentResult, ToolCallRequest
from guardrails.policy_entailment import (
    _llm_entail,
    check_policy_entailment,
    load_policy_entailment_rubric,
    reset_policy_entailment_rubric_cache,
)


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


def test_load_policy_entailment_rubric_nonempty() -> None:
    reset_policy_entailment_rubric_cache()
    text = load_policy_entailment_rubric()
    assert "Violation" in text
    assert "Borderline" in text
    assert "Compliant" in text
    assert "Out of scope" in text
    # Cached read returns the same object/string content.
    assert load_policy_entailment_rubric() == text


def test_llm_entail_injects_rubric_as_system_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    reset_policy_entailment_rubric_cache()
    rubric = load_policy_entailment_rubric()

    captured: list[object] = []
    structured = MagicMock()

    def _invoke(messages: object, *args: object, **kwargs: object) -> PolicyEntailmentResult:
        captured.append(messages)
        return PolicyEntailmentResult(compliant=True, violated_clauses=[], severity="none")

    structured.invoke.side_effect = _invoke
    llm = MagicMock()
    bound = MagicMock()
    llm.bind.return_value = bound
    bound.with_structured_output.return_value = structured

    with patch("guardrails.llm.get_chat_openai", return_value=llm):
        result = _llm_entail(_request(), ["Vendor V-1001: status=active"])

    llm.bind.assert_called_once_with(temperature=0)
    assert result.compliant is True
    assert len(captured) == 1
    messages = captured[0]
    assert isinstance(messages, list)
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == rubric
    assert isinstance(messages[1], HumanMessage)
    assert "create_purchase_order" in messages[1].content
    assert "Vendor V-1001: status=active" in messages[1].content


def test_llm_entail_coerces_noncompliant_none_to_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    structured = MagicMock()
    structured.invoke.return_value = PolicyEntailmentResult(
        compliant=False,
        violated_clauses=["thin evidence"],
        severity="none",
    )
    llm = MagicMock()
    bound = MagicMock()
    llm.bind.return_value = bound
    bound.with_structured_output.return_value = structured

    with patch("guardrails.llm.get_chat_openai", return_value=llm):
        result = _llm_entail(_request(), ["policy"])

    assert result.compliant is False
    assert result.severity == "soft"
