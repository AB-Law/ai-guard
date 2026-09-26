"""Configure / tear down OpenTelemetry for Aegis (optional, non-blocking)."""

from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import metrics as metrics_api
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import NoOpTracerProvider

from telemetry.metrics import bind_otel_instruments, reset_metrics_for_tests

logger = logging.getLogger(__name__)

_configured = False
_fastapi_instrumented = False
_provider: TracerProvider | NoOpTracerProvider | None = None
_meter_provider: Any | None = None


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_otel_enabled() -> bool:
    return _truthy(os.environ.get("AEGIS_OTEL_ENABLED"))


def configure_telemetry(*, app: Any | None = None) -> None:
    """Install TracerProvider + optional MeterProvider. NoOp when disabled; never raises."""
    global _configured, _provider

    if _configured:
        if app is not None and is_otel_enabled():
            _instrument_fastapi(app)
        return

    try:
        if not is_otel_enabled():
            provider: TracerProvider | NoOpTracerProvider = NoOpTracerProvider()
            trace.set_tracer_provider(provider)
            _provider = provider
            _configure_noop_metrics()
            _configured = True
            return

        service_name = os.environ.get("OTEL_SERVICE_NAME", "aegis").strip() or "aegis"
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        endpoint = (os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                # Exporter reads OTEL_EXPORTER_OTLP_ENDPOINT / HEADERS from the
                # environment; we only construct it when an endpoint is present.
                exporter = OTLPSpanExporter()
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except Exception:
                logger.warning(
                    "OTLP span exporter setup failed; continuing without export",
                    exc_info=True,
                )

        trace.set_tracer_provider(provider)
        _provider = provider
        _configure_metrics(resource=resource, endpoint=endpoint)
        _configured = True

        if app is not None:
            _instrument_fastapi(app)
    except Exception:
        logger.warning("OpenTelemetry setup failed; using NoOp provider", exc_info=True)
        try:
            provider = NoOpTracerProvider()
            trace.set_tracer_provider(provider)
            _provider = provider
            _configure_noop_metrics()
            _configured = True
        except Exception:  # noqa: BLE001 — last resort: mark configured
            _configured = True


def _configure_noop_metrics() -> None:
    global _meter_provider
    try:
        from opentelemetry.sdk.metrics import MeterProvider

        mp = MeterProvider()
        metrics_api.set_meter_provider(mp)
        _meter_provider = mp
        bind_otel_instruments(None)
    except Exception:
        logger.warning("NoOp metrics setup failed", exc_info=True)
        bind_otel_instruments(None)


def _configure_metrics(*, resource: Resource, endpoint: str) -> None:
    """OTLP metrics export when an endpoint is set; in-process Prometheus always works."""
    global _meter_provider
    try:
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        readers: list[Any] = []
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                    OTLPMetricExporter,
                )

                # Same env endpoint/headers as traces; construct only when set.
                metric_exporter = OTLPMetricExporter()
                readers.append(PeriodicExportingMetricReader(metric_exporter))
            except Exception:
                logger.warning(
                    "OTLP metric exporter setup failed; continuing without OTLP metrics",
                    exc_info=True,
                )

        mp = MeterProvider(resource=resource, metric_readers=readers)
        metrics_api.set_meter_provider(mp)
        _meter_provider = mp
        bind_otel_instruments(_build_instruments())
    except Exception:
        logger.warning("OpenTelemetry metrics setup failed", exc_info=True)
        bind_otel_instruments(None)


def _build_instruments() -> dict[str, Any]:
    meter = metrics_api.get_meter("aegis")
    return {
        "requests": meter.create_counter(
            "aegis.requests", unit="1", description="API requests"
        ),
        "request_duration": meter.create_histogram(
            "aegis.request.duration",
            unit="ms",
            description="API request duration milliseconds",
        ),
        "guard_decisions": meter.create_counter(
            "aegis.guard.decisions", unit="1", description="Guard decisions"
        ),
        "guard_duration": meter.create_histogram(
            "aegis.guard.eval.duration",
            unit="ms",
            description="Guard evaluation latency milliseconds",
        ),
        "guard_errors": meter.create_counter(
            "aegis.guard.errors", unit="1", description="Guard evaluation errors"
        ),
        "approvals": meter.create_counter(
            "aegis.approvals", unit="1", description="Approval resolutions"
        ),
        "prompt_tokens": meter.create_counter(
            "aegis.model.prompt_tokens",
            unit="1",
            description="Observed prompt tokens (when provider reports usage)",
        ),
        "completion_tokens": meter.create_counter(
            "aegis.model.completion_tokens",
            unit="1",
            description="Observed completion tokens (when provider reports usage)",
        ),
        "estimated_cost": meter.create_counter(
            "aegis.model.estimated_cost_usd",
            unit="USD",
            description="Estimated model cost USD (requires pricing config)",
        ),
    }


def _instrument_fastapi(app: Any) -> None:
    global _fastapi_instrumented
    if _fastapi_instrumented or not is_otel_enabled():
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        _fastapi_instrumented = True
    except Exception:
        logger.warning("FastAPI OpenTelemetry instrumentation failed", exc_info=True)


def shutdown_telemetry() -> None:
    """Flush exporters if any; never raises."""
    global _configured, _fastapi_instrumented, _provider, _meter_provider
    provider = _provider
    meter_provider = _meter_provider
    _provider = None
    _meter_provider = None
    _configured = False
    _fastapi_instrumented = False
    bind_otel_instruments(None)
    for p in (provider, meter_provider):
        if p is None:
            continue
        try:
            shutdown = getattr(p, "shutdown", None)
            if callable(shutdown):
                shutdown()
        except Exception:
            logger.warning("OpenTelemetry shutdown failed", exc_info=True)


def reset_telemetry_for_tests() -> None:
    """Reset module state between tests (forces TracerProvider override)."""
    global _configured, _fastapi_instrumented, _provider, _meter_provider
    try:
        for p in (_provider, _meter_provider):
            if p is None:
                continue
            shutdown = getattr(p, "shutdown", None)
            if callable(shutdown):
                shutdown()
    except Exception:  # noqa: BLE001, S110 — test cleanup only
        pass
    _provider = None
    _meter_provider = None
    _configured = False
    _fastapi_instrumented = False
    bind_otel_instruments(None)
    reset_metrics_for_tests()
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.uninstrument()
    except Exception:  # noqa: BLE001, S110 — may not have been instrumented
        pass
    # OpenTelemetry refuses a second set_tracer_provider(); reset the Once latch.
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace._PROXY_TRACER_PROVIDER = None  # type: ignore[attr-defined]
    once = getattr(trace, "_TRACER_PROVIDER_SET_ONCE", None)
    if once is not None and hasattr(once, "_done"):
        once._done = False  # type: ignore[attr-defined]
    trace.set_tracer_provider(NoOpTracerProvider())
    try:
        metrics_api._METER_PROVIDER = None  # type: ignore[attr-defined]
        metrics_api._PROXY_METER_PROVIDER = None  # type: ignore[attr-defined]
        m_once = getattr(metrics_api, "_METER_PROVIDER_SET_ONCE", None)
        if m_once is not None and hasattr(m_once, "_done"):
            m_once._done = False  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001, S110
        pass
