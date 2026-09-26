"""Apply detection findings to produce redacted values for persistence."""

from __future__ import annotations

from typing import Any

from audit.sensitive_data.detectors import detect_in_value
from audit.sensitive_data.policy import SensitiveDataPolicy, default_policy
from audit.sensitive_data.types import Finding

_REDACTED = "***"
_HASH_PREFIX = "sha256:"


def _replacement_for(finding: Finding) -> str:
    """Stable replacement string for a finding (deterministic for hash-chain)."""
    # Prefer the finding preview when it is already a hash or masked form.
    if finding.preview.startswith(_HASH_PREFIX):
        return finding.preview
    if finding.type == "iban":
        return finding.value_hash
    if finding.type == "email":
        return finding.preview
    if finding.type == "bank_account":
        # Labeled account digits in free text → ***; key-based → hash preview.
        return finding.preview if finding.preview else _REDACTED
    if finding.type in ("bearer_token",):
        return _REDACTED
    if finding.type == "gov_id_us_ssn":
        return finding.preview if finding.preview.startswith(_HASH_PREFIX) else _REDACTED
    if finding.type in ("api_key", "phone"):
        return finding.preview if finding.preview else _REDACTED
    return finding.preview or _REDACTED


def _apply_to_string(text: str, findings: list[Finding]) -> str:
    """Replace spans in a string, right-to-left so offsets stay valid."""
    if not findings:
        return text
    # Only findings whose path is this leaf (empty path or exact) with spans
    spanned = [f for f in findings if f.end > f.start]
    if not spanned:
        # Whole-string key redaction: single finding covering entire value
        if len(findings) == 1 and findings[0].start == 0 and findings[0].end == 0:
            return _replacement_for(findings[0])
        if len(findings) == 1 and findings[0].end >= len(text):
            return _replacement_for(findings[0])
        # Fall back: replace by scanning each finding's raw preview path —
        # for key-based full-value findings, replace entire string once.
        f0 = findings[0]
        if f0.start == 0 and (f0.end == 0 or f0.end == len(text)):
            return _replacement_for(f0)
        return text

    out = text
    for f in sorted(spanned, key=lambda x: x.start, reverse=True):
        if f.start < 0 or f.end > len(out) or f.start >= f.end:
            continue
        out = out[: f.start] + _replacement_for(f) + out[f.end :]
    return out


def _findings_for_path(findings: list[Finding], path: str) -> list[Finding]:
    return [f for f in findings if f.path == path]


def apply_redactions(
    value: Any,
    findings: list[Finding],
    *,
    policy: SensitiveDataPolicy | None = None,
    path: str = "",
) -> Any:
    """Recursively replace detected spans; skip findings below confidence."""
    pol = policy or default_policy()
    actionable = [f for f in findings if pol.should_redact(f)]

    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            # Full-value key findings (dict key matched as sensitive)
            key_findings = [
                f
                for f in actionable
                if f.path == child and f.start == 0 and f.end == len(str(item) if isinstance(item, str) else 0)
            ]
            if key_findings and isinstance(item, str):
                result[key] = _replacement_for(key_findings[0])
            else:
                result[key] = apply_redactions(
                    item, actionable, policy=pol, path=child
                )
        return result
    if isinstance(value, list):
        return [
            apply_redactions(item, actionable, policy=pol, path=f"{path}[{i}]")
            for i, item in enumerate(value)
        ]
    if isinstance(value, str):
        leaf = _findings_for_path(actionable, path)
        if not leaf and path == "":
            leaf = [f for f in actionable if f.path == ""]
        if not leaf:
            return value
        # Prefer span-based replacement; if a key-style finding covers whole string
        whole = [
            f
            for f in leaf
            if f.start == 0 and (f.end == len(value) or f.end == 0)
        ]
        if (
            whole
            and not any(f.end > f.start and f.end < len(value) for f in leaf)
            and all(f.end == 0 or f.end == len(value) for f in whole)
        ):
            return _replacement_for(whole[0])
        return _apply_to_string(value, leaf)
    return value


def redact_value(
    value: Any,
    *,
    policy: SensitiveDataPolicy | None = None,
) -> Any:
    """Detect then redact a payload (dict/list/str). Deterministic."""
    pol = policy or default_policy()
    if not pol.enabled:
        return value
    findings = detect_in_value(value)
    return apply_redactions(value, findings, policy=pol)
