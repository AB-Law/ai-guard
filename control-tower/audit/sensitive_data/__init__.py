"""Configurable PII/secret detection and redaction for Aegis audit."""

from __future__ import annotations

from audit.sensitive_data.detectors import (
    SECRETISH_RE,
    detect_in_text,
    detect_in_value,
    hash_value,
    scrub_secretish,
)
from audit.sensitive_data.export import sanitize_for_export
from audit.sensitive_data.policy import (
    SensitiveDataPolicy,
    default_policy,
    finding_summaries,
    resolve_policy,
    strongest_decision_action,
)
from audit.sensitive_data.redact import apply_redactions, redact_value
from audit.sensitive_data.types import Finding

__all__ = [
    "SECRETISH_RE",
    "Finding",
    "SensitiveDataPolicy",
    "apply_redactions",
    "default_policy",
    "detect_in_text",
    "detect_in_value",
    "finding_summaries",
    "hash_value",
    "redact_value",
    "resolve_policy",
    "sanitize_for_export",
    "scrub_secretish",
    "strongest_decision_action",
]
