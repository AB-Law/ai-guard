"""Unit tests for verification_mode path selection and failure helpers."""

from __future__ import annotations

import pytest

from guardrails.verification_mode import (
    EVIDENCE_FAILURE_POLICY,
    INJECTION_FAILURE_POLICY,
    LlmFailurePolicy,
    PathMode,
    evidence_path,
    evidence_unavailable_result,
    injection_path,
    llm_configured,
)


def test_llm_configured_false_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_configured() is False


def test_llm_configured_false_when_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    assert llm_configured() is False


def test_llm_configured_true_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert llm_configured() is True


def test_evidence_path_heuristic_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert evidence_path() is PathMode.HEURISTIC


def test_evidence_path_llm_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert evidence_path() is PathMode.LLM


def test_injection_path_short_circuits_on_learned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert (
        injection_path(has_learned=True, has_high_regex=False) is PathMode.HEURISTIC
    )


def test_injection_path_short_circuits_on_high_regex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert (
        injection_path(has_learned=False, has_high_regex=True) is PathMode.HEURISTIC
    )


def test_injection_path_llm_when_keyed_and_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert (
        injection_path(has_learned=False, has_high_regex=False) is PathMode.LLM
    )


def test_injection_path_heuristic_when_unkeyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert (
        injection_path(has_learned=False, has_high_regex=False) is PathMode.HEURISTIC
    )


def test_failure_policies_documented() -> None:
    assert EVIDENCE_FAILURE_POLICY is LlmFailurePolicy.FAIL_CLOSED
    assert INJECTION_FAILURE_POLICY is LlmFailurePolicy.FAIL_OPEN


def test_evidence_unavailable_result_fail_closed() -> None:
    result = evidence_unavailable_result()
    assert result.evidence_score == 0.0
    assert result.unsupported_claims == []
    assert result.judge_unavailable is True
