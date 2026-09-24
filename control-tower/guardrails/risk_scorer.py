"""Risk scorer — aggregate injection, evidence, and policy signals."""

from __future__ import annotations

from typing import Literal

from contracts.schemas import InjectionFlag, PolicyEntailmentSeverity

PolicyHit = Literal["none", "disallowed", "unknown", "over_limit"]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def score(
    *,
    injection_flags: list[InjectionFlag],
    evidence_score: float,
    policy_hit: PolicyHit = "none",
    entailment_severity: PolicyEntailmentSeverity = "none",
) -> tuple[int, float, float]:
    """
    Compute risk_score (0-100), confidence_score (0-1), and pass-through evidence_score.

    Formula:
      injection_component   = 80 if any high flag else 50 if any flag else 0
      evidence_component    = int((1 - evidence_score) * 70)
      policy_component      = 40 if disallowed/unknown else 20 if over_limit else 0
      entailment_component  = 50 if hard else 30 if soft else 0
      risk_score            = min(100, sum of components)
      confidence_score      = 0.5 * evidence_score + 0.5 * (1 if no injection else 0.2)
    """
    has_high = any(f.severity == "high" for f in injection_flags)
    has_any = bool(injection_flags)
    if has_high:
        injection_component = 80
    elif has_any:
        injection_component = 50
    else:
        injection_component = 0

    evidence_component = int((1.0 - evidence_score) * 70)

    if policy_hit in ("disallowed", "unknown"):
        policy_component = 40
    elif policy_hit == "over_limit":
        policy_component = 20
    else:
        policy_component = 0

    if entailment_severity == "hard":
        entailment_component = 50
    elif entailment_severity == "soft":
        entailment_component = 30
    else:
        entailment_component = 0

    risk_score = min(
        100,
        injection_component + evidence_component + policy_component + entailment_component,
    )
    confidence_score = _clamp(
        0.5 * evidence_score + 0.5 * (1.0 if not has_any else 0.2),
        0.0,
        1.0,
    )
    return risk_score, confidence_score, evidence_score
