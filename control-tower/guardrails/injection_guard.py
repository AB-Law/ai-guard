"""Injection guard — scan retrieved text for instruction-like patterns."""

from __future__ import annotations

import re
from re import Pattern

from contracts.schemas import InjectionFlag, InjectionScanResult, InjectionSeverity

_SNIPPET_MAX = 120

_PATTERNS: list[tuple[str, InjectionSeverity, Pattern[str]]] = [
    (
        "system_override",
        "high",
        re.compile(
            r"SYSTEM\s+OVERRIDE|ignore\s+(?:all\s+)?previous|disregard\s+.*policy",
            re.IGNORECASE,
        ),
    ),
    (
        "skip_policy",
        "high",
        re.compile(r"skip\s+(?:the\s+)?budget|skip\s+.*check", re.IGNORECASE),
    ),
    (
        "prompt_injection",
        "medium",
        re.compile(
            r"you\s+are\s+now|new\s+instructions:|reveal\s+(?:the\s+)?system\s+prompt",
            re.IGNORECASE,
        ),
    ),
]


def _snippet(text: str, start: int, end: int) -> str:
    pad = 40
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    snippet = text[lo:hi].replace("\n", " ").strip()
    if len(snippet) > _SNIPPET_MAX:
        snippet = snippet[: _SNIPPET_MAX - 3] + "..."
    return snippet


def scan(text: str | None) -> InjectionScanResult:
    """Scan text for injection patterns; tag non-empty content as untrusted."""
    if not text:
        return InjectionScanResult(flags=[], trust="none")

    flags: list[InjectionFlag] = []
    seen: set[tuple[str, int]] = set()

    for pattern_id, severity, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            key = (pattern_id, match.start())
            if key in seen:
                continue
            seen.add(key)
            flags.append(
                InjectionFlag(
                    pattern_id=pattern_id,
                    snippet=_snippet(text, match.start(), match.end()),
                    severity=severity,
                )
            )

    return InjectionScanResult(flags=flags, trust="untrusted")
