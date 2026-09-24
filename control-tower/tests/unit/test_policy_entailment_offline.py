"""Tests for guardrails/policy_entailment.py offline behavior."""

from __future__ import annotations

import pytest

from contracts.schemas import PolicyEntailmentResult, ToolCallRequest
from guardrails.policy_entailment import check_policy_entailment


def test_check_policy_entailment_no_api_key_returns_compliant(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OPENAI_API_KEY is not set, should return compliant without calling LLM."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    request = ToolCallRequest(
        call_id="test-call",
        process="procurement_review",
        step_id="test-step",
        tool_name="create_purchase_order",
        tool_args={"vendor_id": "V-1001", "amount": 5000},
        agent_rationale="Creating a purchase order for approved vendor.",
        context_refs=["chunk:policy:1"],
        timestamp="2024-01-01T00:00:00Z",
    )
    
    policy_excerpts = [
        "Purchase orders under $10,000 may be auto-approved.",
        "Vendor must be on approved list.",
    ]
    
    result = check_policy_entailment(request, policy_excerpts)
    
    assert result.compliant is True
    assert result.violated_clauses == []
    assert result.severity == "none"


def test_check_policy_entailment_empty_api_key_returns_compliant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty API key should also return compliant."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    
    request = ToolCallRequest(
        call_id="test-call",
        process="test_process",
        step_id="test-step",
        tool_name="test_tool",
        tool_args={},
        agent_rationale="Test rationale",
        context_refs=[],
        timestamp="2024-01-01T00:00:00Z",
    )
    
    result = check_policy_entailment(request, [])
    
    assert result.compliant is True
    assert result.violated_clauses == []
    assert result.severity == "none"


def test_check_policy_entailment_whitespace_api_key_returns_compliant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitespace-only API key should return compliant."""
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    
    request = ToolCallRequest(
        call_id="test-call",
        process="test_process",
        step_id="test-step",
        tool_name="test_tool",
        tool_args={},
        agent_rationale="Test",
        context_refs=[],
        timestamp="2024-01-01T00:00:00Z",
    )
    
    result = check_policy_entailment(request, [])
    
    assert result.compliant is True


def test_check_policy_entailment_with_empty_excerpts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty policy excerpts should still work."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    request = ToolCallRequest(
        call_id="test-call",
        process="test_process",
        step_id="test-step",
        tool_name="test_tool",
        tool_args={"param": "value"},
        agent_rationale="Test rationale",
        context_refs=[],
        timestamp="2024-01-01T00:00:00Z",
    )
    
    result = check_policy_entailment(request, [])
    
    assert result.compliant is True
    assert result.violated_clauses == []
    assert result.severity == "none"


def test_policy_entailment_result_model_creation() -> None:
    """Test creating PolicyEntailmentResult directly."""
    result = PolicyEntailmentResult(
        compliant=False,
        violated_clauses=["Vendor not approved", "Amount exceeds limit"],
        severity="hard",
    )
    
    assert result.compliant is False
    assert len(result.violated_clauses) == 2
    assert "Vendor not approved" in result.violated_clauses
    assert result.severity == "hard"


def test_policy_entailment_result_compliant_state() -> None:
    """Test compliant result."""
    result = PolicyEntailmentResult(
        compliant=True,
        violated_clauses=[],
        severity="none",
    )
    
    assert result.compliant is True
    assert result.violated_clauses == []
    assert result.severity == "none"
