"""PII redaction before audit persistence — ARCHITECTURE §9."""

from __future__ import annotations

import hashlib
import re
from typing import Any

# ISO 13616 IBAN (simplified: country + check + alphanumerics, 15–34 chars)
_IBAN_RE = re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}\b", re.IGNORECASE)
# US-style account numbers (8–17 digits) when labeled
_ACCOUNT_LABELED_RE = re.compile(
    r"(account\s*(?:number|no\.?|#)?\s*[:=]?\s*)([0-9]{8,17})",
    re.IGNORECASE,
)
_SENSITIVE_KEY_RE = re.compile(
    r"(iban|account_number|bank_account|routing|swift|sort_code)",
    re.IGNORECASE,
)

_REDACTED = "***"
_HASH_PREFIX = "sha256:"


def _hash_value(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{_HASH_PREFIX}{digest[:16]}"


def _redact_string(text: str) -> str:
    out = _IBAN_RE.sub(lambda m: _hash_value(m.group(0)), text)
    out = _ACCOUNT_LABELED_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}", out)
    return out


def redact_payload(value: Any) -> Any:
    """Recursively redact banking-like strings and sensitive dict keys."""
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if _SENSITIVE_KEY_RE.search(str(key)):
                if isinstance(item, str):
                    result[key] = _hash_value(item) if len(item) > 4 else _REDACTED
                else:
                    result[key] = _REDACTED
            else:
                result[key] = redact_payload(item)
        return result
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value
