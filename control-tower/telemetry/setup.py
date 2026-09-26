"""Configure / tear down OpenTelemetry for Aegis (optional, non-blocking)."""

from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import NoOpTracerProvider

logger = logging.getLogger(__name__)

_configured = False
_fastapi_instrumented = False
_provider: TracerProvider | NoOpTracerProvider | None = None


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_otel_enabled() -> bool:
    return _truthy(os.environ.get("AEGIS_OTEL_ENABLED"))


def configure_telemetry(*, app: Any | None = None) -> None:
    """Install a TracerProvider. NoOp when disabled; never raises."""
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
                    "OTLP exporter setup failed; continuing without export",
                    exc_info=True,
                )

        trace.set_tracer_provider(provider)
        _provider = provider
        _configured = True

        if app is not None:
            _instrument_fastapi(app)
    except Exception:
        logger.warning("OpenTelemetry setup failed; using NoOp provider", exc_info=True)
        try:
            provider = NoOpTracerProvider()
            trace.set_tracer_provider(provider)
            _provider = provider
            _configured = True
        except Exception:  # noqa: BLE001 — last resort: mark configured
            _configured = True


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
    global _configured, _fastapi_instrumented, _provider
    provider = _provider
    _provider = None
    _configured = False
    _fastapi_instrumented = False
    if provider is None:
        return
    try:
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception:
        logger.warning("OpenTelemetry shutdown failed", exc_info=True)


def reset_telemetry_for_tests() -> None:
    """Reset module state between tests (forces TracerProvider override)."""
    global _configured, _fastapi_instrumented, _provider
    try:
        if _provider is not None:
            shutdown = getattr(_provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
    except Exception:  # noqa: BLE001, S110 — test cleanup only
        pass
    _provider = None
    _configured = False
    _fastapi_instrumented = False
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
