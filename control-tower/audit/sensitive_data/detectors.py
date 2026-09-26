"""Detect PII and secrets in text and nested payloads.

Detectors return structured findings with confidence — matches are heuristic
candidates, not certain identification. Callers must filter by min_confidence
before redacting or applying policy actions.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from audit.sensitive_data.types import Finding, FindingSeverity

_HASH_PREFIX = "sha256:"

# --- Patterns -----------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
)

# NANP with separators or E.164 (+ and 10–15 digits). Avoid bare 7–10 digit runs.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s\-.]?)?(?:\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}|\+\d{10,15})(?!\d)",
)

_SSN_DASHED_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SSN_LABELED_RE = re.compile(
    r"(?i)(?:ssn|social\s*security(?:\s*number)?)\s*[:=]?\s*(\d{3}[-\s]?\d{2}[-\s]?\d{4})",
)

_IBAN_RE = re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}\b", re.IGNORECASE)
_ACCOUNT_LABELED_RE = re.compile(
    r"(account\s*(?:number|no\.?|#)?\s*[:=]?\s*)([0-9]{8,17})",
    re.IGNORECASE,
)

# OpenAI-style keys, AWS access keys, labeled api keys, bearer headers.
_API_KEY_SK_RE = re.compile(r"\bsk-[a-zA-Z0-9_-]{8,}\b")
_API_KEY_AKIA_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_API_KEY_LABELED_RE = re.compile(
    r"(?i)(?:api[_-]?key|token)\s*[=:\s]+\s*([^\s\"']{8,})",
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+(\S+)")

_SENSITIVE_KEY_RE = re.compile(
    r"(iban|account_number|bank_account|routing|swift|sort_code|"
    r"api_key|apikey|access_token|secret|password|ssn|email|phone)",
    re.IGNORECASE,
)

# Shared secret scrubber for injection spans / learned-rule candidates.
SECRETISH_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{8,}|bearer\s+\S+|token[=:\s]+\S+|api[_-]?key[=:\s]+\S+"
    r"|AKIA[0-9A-Z]{16})"
)


def hash_value(value: str, *, full: bool = False) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    if full:
        return f"{_HASH_PREFIX}{digest}"
    return f"{_HASH_PREFIX}{digest[:16]}"


def _preview_email(raw: str) -> str:
    if "@" not in raw:
        return "***"
    local, _, domain = raw.partition("@")
    head = local[:1] if local else "*"
    return f"{head}***@{domain}"


def _preview_generic(raw: str, keep: int = 4) -> str:
    if len(raw) <= keep:
        return "***"
    return f"{raw[:keep]}***"


def _finding(
    *,
    dtype: str,
    path: str,
    start: int,
    end: int,
    raw: str,
    severity: FindingSeverity,
    confidence: float,
    preview: str | None = None,
) -> Finding:
    return Finding(
        type=dtype,  # type: ignore[arg-type]
        path=path,
        start=start,
        end=end,
        severity=severity,
        confidence=confidence,
        preview=preview if preview is not None else _preview_generic(raw),
        value_hash=hash_value(raw),
    )


def detect_in_text(text: str, *, path: str = "") -> list[Finding]:
    """Run all string detectors on a single leaf string."""
    if not text:
        return []
    findings: list[Finding] = []

    for m in _EMAIL_RE.finditer(text):
        raw = m.group(0)
        # Reject obvious non-emails used in prose examples like "user@host"
        if "." not in raw.split("@", 1)[-1]:
            continue
        findings.append(
            _finding(
                dtype="email",
                path=path,
                start=m.start(),
                end=m.end(),
                raw=raw,
                severity="medium",
                confidence=0.9,
                preview=_preview_email(raw),
            )
        )

    for m in _PHONE_RE.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        # Skip short / ambiguous digit clusters
        if len(digits) < 10:
            continue
        conf = 0.75 if ("-" in raw or "(" in raw or raw.startswith("+")) else 0.6
        findings.append(
            _finding(
                dtype="phone",
                path=path,
                start=m.start(),
                end=m.end(),
                raw=raw,
                severity="medium",
                confidence=conf,
                preview=_preview_generic(digits, keep=2),
            )
        )

    for m in _SSN_LABELED_RE.finditer(text):
        raw = m.group(1)
        findings.append(
            _finding(
                dtype="gov_id_us_ssn",
                path=path,
                start=m.start(1),
                end=m.end(1),
                raw=raw,
                severity="high",
                confidence=0.85,
            )
        )
    for m in _SSN_DASHED_RE.finditer(text):
        # Skip if already covered by labeled match overlapping this span
        if any(
            f.type == "gov_id_us_ssn" and f.start <= m.start() < f.end for f in findings
        ):
            continue
        raw = m.group(0)
        findings.append(
            _finding(
                dtype="gov_id_us_ssn",
                path=path,
                start=m.start(),
                end=m.end(),
                raw=raw,
                severity="high",
                confidence=0.7,
            )
        )

    for m in _IBAN_RE.finditer(text):
        raw = m.group(0)
        findings.append(
            _finding(
                dtype="iban",
                path=path,
                start=m.start(),
                end=m.end(),
                raw=raw,
                severity="high",
                confidence=0.85,
                preview=hash_value(raw),
            )
        )

    for m in _ACCOUNT_LABELED_RE.finditer(text):
        raw = m.group(2)
        findings.append(
            _finding(
                dtype="bank_account",
                path=path,
                start=m.start(2),
                end=m.end(2),
                raw=raw,
                severity="high",
                confidence=0.8,
                preview="***",
            )
        )

    for m in _API_KEY_SK_RE.finditer(text):
        raw = m.group(0)
        findings.append(
            _finding(
                dtype="api_key",
                path=path,
                start=m.start(),
                end=m.end(),
                raw=raw,
                severity="high",
                confidence=0.95,
            )
        )
    for m in _API_KEY_AKIA_RE.finditer(text):
        raw = m.group(0)
        findings.append(
            _finding(
                dtype="api_key",
                path=path,
                start=m.start(),
                end=m.end(),
                raw=raw,
                severity="high",
                confidence=0.95,
            )
        )
    for m in _API_KEY_LABELED_RE.finditer(text):
        raw = m.group(1)
        # Avoid double-counting sk-/AKIA already matched
        if _API_KEY_SK_RE.fullmatch(raw) or _API_KEY_AKIA_RE.fullmatch(raw):
            continue
        findings.append(
            _finding(
                dtype="api_key",
                path=path,
                start=m.start(1),
                end=m.end(1),
                raw=raw,
                severity="high",
                confidence=0.85,
            )
        )

    for m in _BEARER_RE.finditer(text):
        raw = m.group(1)
        findings.append(
            _finding(
                dtype="bearer_token",
                path=path,
                start=m.start(1),
                end=m.end(1),
                raw=raw,
                severity="high",
                confidence=0.95,
                preview="***",
            )
        )

    return findings


def _join_path(base: str, part: str) -> str:
    if not base:
        return part
    if part.startswith("["):
        return f"{base}{part}"
    return f"{base}.{part}"


def detect_in_value(value: Any, *, path: str = "") -> list[Finding]:
    """Recursively detect sensitive data in dicts, lists, and strings."""
    findings: list[Finding] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_str = str(key)
            child_path = _join_path(path, key_str)
            if _SENSITIVE_KEY_RE.search(key_str) and isinstance(item, str) and item:
                # Key-based finding for known sensitive fields
                dtype = "bank_account"
                severity: FindingSeverity = "high"
                conf = 0.9
                key_l = key_str.lower()
                if "iban" in key_l:
                    dtype = "iban"
                elif "email" in key_l:
                    dtype = "email"
                    severity = "medium"
                elif "phone" in key_l:
                    dtype = "phone"
                    severity = "medium"
                elif "ssn" in key_l:
                    dtype = "gov_id_us_ssn"
                elif any(
                    s in key_l
                    for s in ("api_key", "apikey", "token", "secret", "password")
                ):
                    dtype = "api_key"
                if dtype == "email":
                    preview = _preview_email(item)
                elif dtype in ("iban", "bank_account") and len(item) > 4:
                    # Preserve prior audit behavior: hash banking key values.
                    preview = hash_value(item)
                elif len(item) > 4 and dtype in ("api_key", "bearer_token", "gov_id_us_ssn"):
                    preview = hash_value(item)
                else:
                    preview = "***"
                findings.append(
                    _finding(
                        dtype=dtype,
                        path=child_path,
                        start=0,
                        end=len(item),
                        raw=item,
                        severity=severity,
                        confidence=conf,
                        preview=preview,
                    )
                )
            findings.extend(detect_in_value(item, path=child_path))
        return findings
    if isinstance(value, list):
        for i, item in enumerate(value):
            findings.extend(detect_in_value(item, path=_join_path(path, f"[{i}]")))
        return findings
    if isinstance(value, str):
        return detect_in_text(value, path=path)
    return findings


def scrub_secretish(text: str) -> str:
    """Replace secret-shaped tokens with [redacted] (injection / learning path)."""
    return SECRETISH_RE.sub("[redacted]", text or "")
