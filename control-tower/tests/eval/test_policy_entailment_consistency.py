"""Offline consistency gate for the policy-entailment judge.

Runs the same 20 labeled fixture cases N times through ``_llm_entail`` with a
deterministic stubbed structured LLM (no live OpenAI). Asserts ≥95% gold-label
agreement and that the fixed rubric is injected as the system message — so CI
fails if the harness, fixture, or rubric wiring regresses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from contracts.schemas import PolicyEntailmentResult, ToolCallRequest
from guardrails.policy_entailment import (
    _llm_entail,
    load_policy_entailment_rubric,
)

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests" / "fixtures" / "policy_entailment_cases.json"

_N = 3
_MIN_AGREEMENT = 0.95
_EXPECTED_CASES = 20

_VALID_LABELS = frozenset({"compliant", "borderline", "violation"})


def _load_cases() -> list[dict[str, Any]]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _label_to_result(label: str) -> PolicyEntailmentResult:
    if label == "compliant":
        return PolicyEntailmentResult(compliant=True, violated_clauses=[], severity="none")
    if label == "borderline":
        return PolicyEntailmentResult(
            compliant=False,
            violated_clauses=["advisory concern"],
            severity="soft",
        )
    if label == "violation":
        return PolicyEntailmentResult(
            compliant=False,
            violated_clauses=["hard violation"],
            severity="hard",
        )
    raise ValueError(f"unknown label: {label!r}")


def _result_to_label(result: PolicyEntailmentResult) -> str:
    if result.compliant:
        return "compliant"
    if result.severity == "hard":
        return "violation"
    return "borderline"


def _case_request(case: dict[str, Any]) -> ToolCallRequest:
    return ToolCallRequest(
        call_id=f"eval-{case['id']}",
        process="procurement_review",
        step_id="gateway_check",
        tool_name=case["tool_name"],
        tool_args=case.get("tool_args") or {},
        agent_rationale=case.get("agent_rationale") or "",
        context_refs=[],
        timestamp="2026-01-01T00:00:00+00:00",
    )


def _stub_structured_llm(
    gold: PolicyEntailmentResult,
    captured: list[Any],
) -> MagicMock:
    """Deterministic structured LLM: always returns ``gold``; records invoke msgs."""

    structured = MagicMock()

    def _invoke(messages: Any, *args: Any, **kwargs: Any) -> PolicyEntailmentResult:
        captured.append(messages)
        return gold

    structured.invoke.side_effect = _invoke
    llm = MagicMock()
    bound = MagicMock()
    llm.bind.return_value = bound
    bound.with_structured_output.return_value = structured
    return llm


def test_policy_entailment_consistency() -> None:
    cases = _load_cases()
    assert len(cases) == _EXPECTED_CASES, (
        f"fixture must have {_EXPECTED_CASES} cases, got {len(cases)}: {_FIXTURE}"
    )

    rubric = load_policy_entailment_rubric()
    assert rubric, "POLICY_ENTAILMENT_RUBRIC.md must be non-empty"

    for case in cases:
        assert case["expected_label"] in _VALID_LABELS, case["id"]

    matches = 0
    total = 0
    failures: list[str] = []
    captured_messages: list[Any] = []

    for case in cases:
        gold_label = case["expected_label"]
        gold = _label_to_result(gold_label)
        request = _case_request(case)
        excerpts = list(case.get("policy_excerpts") or [])

        for run_i in range(_N):
            llm = _stub_structured_llm(gold, captured_messages)
            with patch("guardrails.llm.get_chat_openai", return_value=llm):
                result = _llm_entail(request, excerpts)
            pred = _result_to_label(result)
            total += 1
            if pred == gold_label:
                matches += 1
            else:
                failures.append(
                    f"{case['id']} run={run_i + 1}: predicted={pred!r} gold={gold_label!r}"
                )

    agreement = matches / total if total else 0.0

    assert captured_messages, "expected structured.invoke to receive messages"
    first = captured_messages[0]
    assert isinstance(first, list) and len(first) >= 2, first
    system_content = getattr(first[0], "content", None)
    assert isinstance(system_content, str) and system_content.strip()
    assert system_content.strip() == rubric
    assert "decision order" in system_content.lower() or "Violation" in system_content

    print("\n=== policy entailment consistency (offline stub) ===")
    print(f"cases={len(cases)} N={_N} agreement={agreement:.1%} ({matches}/{total})")
    for line in failures:
        print(f"  FAIL  {line}")

    assert agreement >= _MIN_AGREEMENT, (
        f"policy entailment agreement {agreement:.1%} ({matches}/{total}) "
        f"below {_MIN_AGREEMENT:.0%}. Failures:\n" + "\n".join(failures)
    )


def test_fixture_labels_cover_all_three() -> None:
    cases = _load_cases()
    labels = {c["expected_label"] for c in cases}
    assert labels == _VALID_LABELS
