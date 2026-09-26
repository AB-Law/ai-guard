"""Resolve sensitive-data policy from process config (or built-in defaults)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from audit.sensitive_data.types import (
    ALL_DETECTOR_TYPES,
    DetectorType,
    Finding,
    SensitiveAction,
)

if TYPE_CHECKING:
    from configs.loader import ProcessConfig, SensitiveDataConfig

# Built-in defaults: redact-only — never changes allow/block unless YAML opts in.
DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_ACTION: SensitiveAction = "redact"

# Per-type floor confidence used when config does not override.
_DETECTOR_DEFAULT_MIN: dict[str, float] = {
    "email": 0.7,
    "phone": 0.6,
    "gov_id_us_ssn": 0.65,
    "api_key": 0.8,
    "bearer_token": 0.8,
    "iban": 0.55,
    "bank_account": 0.55,
}


@dataclass(frozen=True)
class DetectorPolicy:
    enabled: bool
    action: SensitiveAction
    min_confidence: float


@dataclass(frozen=True)
class SensitiveDataPolicy:
    enabled: bool
    default_action: SensitiveAction
    min_confidence: float
    detectors: dict[str, DetectorPolicy]

    def policy_for(self, detector_type: str) -> DetectorPolicy:
        if detector_type in self.detectors:
            return self.detectors[detector_type]
        return DetectorPolicy(
            enabled=True,
            action=self.default_action,
            min_confidence=_DETECTOR_DEFAULT_MIN.get(
                detector_type, self.min_confidence
            ),
        )

    def should_redact(self, finding: Finding) -> bool:
        if not self.enabled:
            return False
        pol = self.policy_for(finding.type)
        if not pol.enabled:
            return False
        return finding.confidence >= pol.min_confidence

    def decision_action(self, finding: Finding) -> SensitiveAction | None:
        """Return block/escalate when configured; None for redact-only."""
        if not self.should_redact(finding):
            return None
        pol = self.policy_for(finding.type)
        if pol.action in ("block", "escalate"):
            return pol.action
        return None


def default_policy() -> SensitiveDataPolicy:
    detectors = {
        t: DetectorPolicy(
            enabled=True,
            action=DEFAULT_ACTION,
            min_confidence=_DETECTOR_DEFAULT_MIN.get(t, DEFAULT_MIN_CONFIDENCE),
        )
        for t in ALL_DETECTOR_TYPES
    }
    return SensitiveDataPolicy(
        enabled=True,
        default_action=DEFAULT_ACTION,
        min_confidence=DEFAULT_MIN_CONFIDENCE,
        detectors=detectors,
    )


def resolve_policy(config: ProcessConfig | None = None) -> SensitiveDataPolicy:
    """Build policy from ProcessConfig.sensitive_data or built-in defaults."""
    base = default_policy()
    if config is None:
        return base
    sd: SensitiveDataConfig | None = getattr(config, "sensitive_data", None)
    if sd is None:
        return base

    detectors: dict[str, DetectorPolicy] = dict(base.detectors)
    for name, override in (sd.detectors or {}).items():
        prev = detectors.get(
            name,
            DetectorPolicy(
                enabled=True,
                action=sd.default_action,
                min_confidence=sd.min_confidence,
            ),
        )
        detectors[name] = DetectorPolicy(
            enabled=override.enabled,
            action=override.action,
            min_confidence=override.min_confidence,
        )
        # Keep type checker happy for known keys
        _ = prev

    # Fill any missing known types with default_action from config
    for t in ALL_DETECTOR_TYPES:
        if t not in detectors:
            detectors[t] = DetectorPolicy(
                enabled=True,
                action=sd.default_action,
                min_confidence=_DETECTOR_DEFAULT_MIN.get(t, sd.min_confidence),
            )
        elif t not in (sd.detectors or {}):
            # Inherit default_action when not explicitly overridden
            prev = detectors[t]
            detectors[t] = DetectorPolicy(
                enabled=prev.enabled,
                action=sd.default_action,
                min_confidence=prev.min_confidence,
            )

    return SensitiveDataPolicy(
        enabled=sd.enabled,
        default_action=sd.default_action,
        min_confidence=sd.min_confidence,
        detectors=detectors,
    )


def strongest_decision_action(
    findings: list[Finding], policy: SensitiveDataPolicy
) -> SensitiveAction | None:
    """Pick the hardest action among findings (block > escalate > None)."""
    best: SensitiveAction | None = None
    for f in findings:
        action = policy.decision_action(f)
        if action == "block":
            return "block"
        if action == "escalate":
            best = "escalate"
    return best


def finding_summaries(
    findings: list[Finding], policy: SensitiveDataPolicy
) -> list[dict[str, object]]:
    """Sanitized finding dicts for audit (no raw values)."""
    out: list[dict[str, object]] = []
    for f in findings:
        if not policy.should_redact(f):
            continue
        out.append(
            {
                "type": f.type,
                "path": f.path,
                "severity": f.severity,
                "confidence": f.confidence,
                "preview": f.preview,
                "value_hash": f.value_hash,
                "action": policy.policy_for(f.type).action,
            }
        )
    return out


# Re-export for callers that type-hint DetectorType
__all__ = [
    "DEFAULT_ACTION",
    "DEFAULT_MIN_CONFIDENCE",
    "DetectorPolicy",
    "DetectorType",
    "SensitiveDataPolicy",
    "default_policy",
    "finding_summaries",
    "resolve_policy",
    "strongest_decision_action",
]
