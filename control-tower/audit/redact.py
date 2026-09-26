"""PII / secret redaction before audit persistence — ARCHITECTURE §9.

Public facade over audit.sensitive_data. Detection is separate from redaction;
callers that need findings should use detect_in_value / detect_in_text.
"""

from __future__ import annotations

from typing import Any

from audit.sensitive_data.detectors import detect_in_text, hash_value, scrub_secretish
from audit.sensitive_data.policy import default_policy
from audit.sensitive_data.redact import apply_redactions, redact_value

_INJECTION_SPAN_PREVIEW = 40
_HASH_PREFIX = "sha256:"


def redact_payload(value: Any) -> Any:
    """Recursively redact PII/secrets using the default sensitive-data policy.

    Used by audit stores before hashing and persistence. Deterministic so the
    hash chain remains verifiable.
    """
    return redact_value(value)


def redact_injection_span(span: str) -> dict[str, str]:
    """Harder redaction for injection snippets (secrets, tokens, emails).

    Returns a truncated preview plus a full sha256 digest — never persist the
    raw attack text in incidents, cases, or approval payloads.
    """
    text = (span or "").replace("\n", " ").strip()
    digest = hash_value(text, full=True).removeprefix(_HASH_PREFIX)
    scrubbed = scrub_secretish(text)
    findings = detect_in_text(scrubbed, path="")
    scrubbed_val = apply_redactions(scrubbed, findings, policy=default_policy())
    scrubbed = scrubbed_val if isinstance(scrubbed_val, str) else str(scrubbed_val)
    preview = scrubbed[:_INJECTION_SPAN_PREVIEW]
    if len(scrubbed) > _INJECTION_SPAN_PREVIEW:
        preview = preview + "…"
    return {
        "matched_span_preview": preview,
        "matched_span_hash": f"{_HASH_PREFIX}{digest}",
    }
