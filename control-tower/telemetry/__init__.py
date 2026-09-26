"""Optional OpenTelemetry tracing + operational metrics for Aegis."""

from telemetry.metrics import (
    record_approval,
    record_guard_decision,
    record_guard_error,
    record_model_usage_from_response,
    record_request,
    record_token_usage,
    render_prometheus,
    reset_metrics_for_tests,
    snapshot,
)
from telemetry.setup import configure_telemetry, is_otel_enabled, shutdown_telemetry
from telemetry.tracing import current_trace_id, get_tracer, start_span

__all__ = [
    "configure_telemetry",
    "current_trace_id",
    "get_tracer",
    "is_otel_enabled",
    "record_approval",
    "record_guard_decision",
    "record_guard_error",
    "record_model_usage_from_response",
    "record_request",
    "record_token_usage",
    "render_prometheus",
    "reset_metrics_for_tests",
    "shutdown_telemetry",
    "snapshot",
    "start_span",
]
