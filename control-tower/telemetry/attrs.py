"""Allowlisted span attributes — never attach prompts, tool args, or PII."""

from __future__ import annotations

from typing import Any

from opentelemetry.trace import Span

# Only these business identifiers may be set on spans.
_ALLOWED = frozenset({"case_id", "call_id", "process", "source_app", "decision"})


def set_aegis_attributes(span: Span, **attrs: Any) -> None:
    """Set allowlisted Aegis attributes on ``span``; ignore empty / unknown keys."""
    for key, value in attrs.items():
        if key not in _ALLOWED or value is None or value == "":
            continue
        span.set_attribute(key, str(value))
