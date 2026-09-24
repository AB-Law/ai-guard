"""Unit tests for risk scorer."""

from __future__ import annotations

from contracts.schemas import InjectionFlag
from guardrails.risk_scorer import score


def test_clean_high_evidence_low_risk() -> None:
    risk, confidence, evidence = score(
        injection_flags=[],
        evidence_score=0.9,
        policy_hit="none",
    )
    assert evidence == 0.9
    assert risk < 60
    assert confidence > 0.5


def test_injection_raises_risk_above_threshold() -> None:
    flags = [
        InjectionFlag(
            pattern_id="system_override",
            snippet="SYSTEM OVERRIDE",
            severity="high",
        )
    ]
    risk, _, _ = score(injection_flags=flags, evidence_score=0.9, policy_hit="none")
    assert risk >= 60


def test_low_evidence_alone_can_reach_threshold() -> None:
    risk, _, _ = score(injection_flags=[], evidence_score=0.0, policy_hit="none")
    assert risk >= 60


def test_soft_entailment_raises_risk() -> None:
    risk_clean, _, _ = score(
        injection_flags=[],
        evidence_score=0.9,
        policy_hit="none",
        entailment_severity="none",
    )
    risk_soft, _, _ = score(
        injection_flags=[],
        evidence_score=0.9,
        policy_hit="none",
        entailment_severity="soft",
    )
    assert risk_soft == risk_clean + 30
    assert risk_soft < 60


def test_hard_entailment_raises_risk() -> None:
    risk, _, _ = score(
        injection_flags=[],
        evidence_score=0.9,
        policy_hit="none",
        entailment_severity="hard",
    )
    assert risk >= 50
