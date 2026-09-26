"""Optional OpenTelemetry tracing for Aegis (no-op when disabled)."""

from telemetry.setup import configure_telemetry, is_otel_enabled, shutdown_telemetry
from telemetry.tracing import current_trace_id, get_tracer, start_span

__all__ = [
    "configure_telemetry",
    "current_trace_id",
    "get_tracer",
    "is_otel_enabled",
    "shutdown_telemetry",
    "start_span",
]
