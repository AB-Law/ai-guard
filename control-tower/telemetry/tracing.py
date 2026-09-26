"""Span helpers that never raise into agent decision paths."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer

from telemetry.attrs import set_aegis_attributes

_TRACER_NAME = "aegis"


def get_tracer(name: str = _TRACER_NAME) -> Tracer:
    return trace.get_tracer(name)


def current_trace_id() -> str | None:
    """Hex W3C trace id for the active span, or None if none / invalid."""
    try:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None
        return format(ctx.trace_id, "032x")
    except Exception:  # noqa: BLE001 — never fail callers for telemetry
        return None


@contextmanager
def start_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    tracer_name: str = _TRACER_NAME,
) -> Iterator[Span]:
    """Start a child span; swallow provider errors so decisions never fail."""
    try:
        tracer = get_tracer(tracer_name)
    except Exception:  # noqa: BLE001 — fall back to non-recording span
        yield trace.INVALID_SPAN
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            try:
                set_aegis_attributes(span, **attributes)
            except Exception:  # noqa: BLE001, S110 — attributes must not block
                pass
        yield span
