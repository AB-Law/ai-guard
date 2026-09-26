"""OpenTelemetry optional instrumentation — disabled, spans, export failure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from audit.log_store import AppendInput, AuditLogStore, compute_entry_hash
from contracts.schemas import GatewayDecision, ToolCallRequest
from telemetry.attrs import set_aegis_attributes
from telemetry.setup import (
    configure_telemetry,
    is_otel_enabled,
    reset_telemetry_for_tests,
    shutdown_telemetry,
)
from telemetry.tracing import current_trace_id, start_span


def _install_memory_provider() -> tuple[TracerProvider, InMemorySpanExporter]:
    """Replace the global TracerProvider with an in-memory one (tests only)."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # OpenTelemetry refuses a second set_tracer_provider(); clear the Once latch.
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace._PROXY_TRACER_PROVIDER = None  # type: ignore[attr-defined]
    once = getattr(trace, "_TRACER_PROVIDER_SET_ONCE", None)
    if once is not None and hasattr(once, "_done"):
        once._done = False  # type: ignore[attr-defined]
    trace.set_tracer_provider(provider)
    import telemetry.setup as setup_mod

    setup_mod._configured = True
    setup_mod._provider = provider
    return provider, exporter


@pytest.fixture(autouse=True)
def _reset_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AEGIS_OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    reset_telemetry_for_tests()
    yield
    reset_telemetry_for_tests()
    monkeypatch.delenv("AEGIS_OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)


def test_disabled_mode_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AEGIS_OTEL_ENABLED", raising=False)
    configure_telemetry()
    assert not is_otel_enabled()
    with start_span("aegis.guard.evaluate", attributes={"call_id": "c1"}) as span:
        assert not span.is_recording()
    assert current_trace_id() is None


def test_enabled_without_endpoint_creates_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AEGIS_OTEL_ENABLED", "1")
    _provider, exporter = _install_memory_provider()

    with start_span(
        "aegis.guard.evaluate",
        attributes={"call_id": "c1", "process": "procurement_review", "decision": "allow"},
    ):
        tid = current_trace_id()
        assert tid is not None
        assert len(tid) == 32

    spans = exporter.get_finished_spans()
    assert any(s.name == "aegis.guard.evaluate" for s in spans)
    guard = next(s for s in spans if s.name == "aegis.guard.evaluate")
    assert guard.attributes.get("call_id") == "c1"
    assert guard.attributes.get("process") == "procurement_review"
    assert "tool_args" not in (guard.attributes or {})


def test_attrs_ignore_disallowed_keys() -> None:
    _provider, exporter = _install_memory_provider()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("t") as span:
        set_aegis_attributes(
            span,
            call_id="c1",
            tool_args={"secret": "x"},
            prompt="do not export",
            decision="block",
        )
    finished = exporter.get_finished_spans()[0]
    assert finished.attributes.get("call_id") == "c1"
    assert finished.attributes.get("decision") == "block"
    assert "tool_args" not in (finished.attributes or {})
    assert "prompt" not in (finished.attributes or {})


def test_w3c_propagation_parent_child_share_trace_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AEGIS_OTEL_ENABLED", "1")
    _install_memory_provider()

    from opentelemetry.propagate import inject
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    carrier: dict[str, str] = {}
    with start_span("client"):
        inject(carrier)
        assert "traceparent" in carrier
        parent_tid = current_trace_id()

    ctx = TraceContextTextMapPropagator().extract(carrier)
    tracer = trace.get_tracer("aegis")
    with tracer.start_as_current_span("aegis.guard.evaluate", context=ctx):
        child_tid = current_trace_id()
    assert parent_tid == child_tid


def test_exporter_failure_does_not_block_decision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AEGIS_OTEL_ENABLED", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")

    with patch(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
        side_effect=RuntimeError("collector unreachable"),
    ):
        configure_telemetry()  # exporter setup fails; must not abort

    from configs.loader import load_process
    from guardrails.evaluate import evaluate_tool_call

    audit = AuditLogStore(tmp_path / "audit.db")
    config = load_process("procurement_review")
    request = ToolCallRequest(
        call_id="otel-fail-1",
        process="procurement_review",
        step_id="external",
        tool_name="not_a_real_tool",
        tool_args={},
        agent_rationale="under limit",
        context_refs=[],
        timestamp="2026-01-01T00:00:00+00:00",
        case_id="case-otel-fail",
    )
    decision = evaluate_tool_call(request, config, audit=audit)
    assert decision.decision == "block"
    assert audit.verify_chain()


def test_audit_trace_id_outside_hash(tmp_path: Path) -> None:
    audit = AuditLogStore(tmp_path / "audit.db")
    entry = audit.append(
        AppendInput(
            process="procurement_review",
            step_id="s",
            event_type="tool_call",
            payload={"call_id": "c1", "decision": "allow"},
            scores=GatewayDecision(
                call_id="c1",
                decision="allow",
                reason="ok",
                policy_refs=[],
                risk_score=1,
                confidence_score=1.0,
                evidence_score=1.0,
            ),
            trace_id="a" * 32,
        )
    )
    assert entry.trace_id == "a" * 32
    assert audit.verify_chain()
    # Hash material must ignore trace_id (payload + prev + timestamp only).
    recomputed = compute_entry_hash(entry.prev_hash, entry.payload, entry.timestamp)
    assert recomputed == entry.entry_hash
    rows = audit.query()
    assert rows[0].trace_id == "a" * 32


def test_configure_swallows_setup_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEGIS_OTEL_ENABLED", "1")
    with patch(
        "telemetry.setup.TracerProvider",
        side_effect=RuntimeError("boom"),
    ):
        configure_telemetry()  # must not raise
    with start_span("x"):
        pass


def test_shutdown_telemetry_safe() -> None:
    configure_telemetry()
    shutdown_telemetry()
    shutdown_telemetry()  # idempotent
