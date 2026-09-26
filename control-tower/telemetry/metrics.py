"""In-process operational metrics — Prometheus text + JSON snapshot.

Recording never raises into agent / approval paths. OTLP export (when enabled)
failures are swallowed the same way.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from telemetry.labels import (
    bound_approval_outcome,
    bound_guard_decision,
    bound_process,
    bound_request_outcome,
    bound_route,
    bound_source_app,
)
from telemetry.usage import (
    CostEstimate,
    TokenUsage,
    estimate_cost_usd,
    extract_token_usage,
    load_model_pricing,
)

logger = logging.getLogger(__name__)

_LabelKey = tuple[str, ...]


@dataclass
class _Counter:
    value: float = 0.0


@dataclass
class _DurationAgg:
    count: int = 0
    sum_ms: float = 0.0

    def observe(self, ms: float) -> None:
        self.count += 1
        self.sum_ms += ms


@dataclass
class MetricsRegistry:
    """Thread-safe in-process registry for Aegis operational metrics."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    requests: dict[_LabelKey, _Counter] = field(default_factory=lambda: defaultdict(_Counter))
    request_duration: dict[_LabelKey, _DurationAgg] = field(
        default_factory=lambda: defaultdict(_DurationAgg)
    )
    guard_decisions: dict[_LabelKey, _Counter] = field(
        default_factory=lambda: defaultdict(_Counter)
    )
    guard_duration: dict[_LabelKey, _DurationAgg] = field(
        default_factory=lambda: defaultdict(_DurationAgg)
    )
    guard_errors: dict[_LabelKey, _Counter] = field(
        default_factory=lambda: defaultdict(_Counter)
    )
    approvals: dict[_LabelKey, _Counter] = field(default_factory=lambda: defaultdict(_Counter))
    # Model usage — totals only when observed; never seed with zeros.
    prompt_tokens_total: int | None = None
    completion_tokens_total: int | None = None
    estimated_cost_usd_total: float | None = None
    model_calls_with_usage: int = 0
    model_calls_without_usage: int = 0
    cost_estimates_recorded: int = 0

    def reset(self) -> None:
        with self._lock:
            self.requests.clear()
            self.request_duration.clear()
            self.guard_decisions.clear()
            self.guard_duration.clear()
            self.guard_errors.clear()
            self.approvals.clear()
            self.prompt_tokens_total = None
            self.completion_tokens_total = None
            self.estimated_cost_usd_total = None
            self.model_calls_with_usage = 0
            self.model_calls_without_usage = 0
            self.cost_estimates_recorded = 0


_registry = MetricsRegistry()
_otel_instruments: dict[str, Any] | None = None


def get_registry() -> MetricsRegistry:
    return _registry


def reset_metrics_for_tests() -> None:
    """Clear in-process aggregates (tests only)."""
    global _otel_instruments
    _registry.reset()
    _otel_instruments = None


def _inc(counter_map: dict[_LabelKey, _Counter], key: _LabelKey, amount: float = 1.0) -> None:
    counter_map[key].value += amount


def _observe(agg_map: dict[_LabelKey, _DurationAgg], key: _LabelKey, ms: float) -> None:
    agg_map[key].observe(ms)


def record_request(
    *,
    route: object | None,
    process: object | None = None,
    source_app: object | None = None,
    outcome: object | None = None,
    duration_ms: float,
) -> None:
    """Record one HTTP/API request. Never raises."""
    try:
        r = bound_route(route)
        p = bound_process(process)
        s = bound_source_app(source_app)
        o = bound_request_outcome(outcome)
        key = (r, p, s, o)
        with _registry._lock:
            _inc(_registry.requests, key)
            _observe(_registry.request_duration, key, max(0.0, float(duration_ms)))
        _otel_add_request(r, p, s, o, duration_ms)
    except Exception:
        logger.debug("record_request failed", exc_info=True)


def record_guard_decision(
    *,
    process: object | None,
    source_app: object | None = None,
    decision: object | None,
    duration_ms: float,
) -> None:
    """Record a gateway allow/block/escalate + evaluation latency."""
    try:
        p = bound_process(process)
        s = bound_source_app(source_app)
        d = bound_guard_decision(decision)
        key = (p, s, d)
        dur_key = (p, s)
        with _registry._lock:
            _inc(_registry.guard_decisions, key)
            _observe(_registry.guard_duration, dur_key, max(0.0, float(duration_ms)))
        _otel_add_guard(p, s, d, duration_ms)
    except Exception:
        logger.debug("record_guard_decision failed", exc_info=True)


def record_guard_error(
    *,
    process: object | None = None,
    source_app: object | None = None,
) -> None:
    try:
        p = bound_process(process)
        s = bound_source_app(source_app)
        key = (p, s)
        with _registry._lock:
            _inc(_registry.guard_errors, key)
        _otel_add_guard_error(p, s)
    except Exception:
        logger.debug("record_guard_error failed", exc_info=True)


def record_approval(
    *,
    process: object | None = None,
    source_app: object | None = None,
    outcome: object | None,
) -> None:
    try:
        p = bound_process(process)
        s = bound_source_app(source_app)
        o = bound_approval_outcome(outcome)
        key = (p, s, o)
        with _registry._lock:
            _inc(_registry.approvals, key)
        _otel_add_approval(p, s, o)
    except Exception:
        logger.debug("record_approval failed", exc_info=True)


def record_model_usage_from_response(response: Any) -> None:
    """Extract usage from a provider response and record if present."""
    try:
        usage = extract_token_usage(response)
        if usage is None:
            with _registry._lock:
                _registry.model_calls_without_usage += 1
            return
        cost = estimate_cost_usd(usage)
        _record_token_usage(usage, cost)
    except Exception:
        logger.debug("record_model_usage_from_response failed", exc_info=True)


def record_token_usage(usage: TokenUsage, cost: CostEstimate | None = None) -> None:
    """Record explicit usage (tests / callers that already extracted tokens)."""
    try:
        if cost is None:
            cost = estimate_cost_usd(usage)
        _record_token_usage(usage, cost)
    except Exception:
        logger.debug("record_token_usage failed", exc_info=True)


def _record_token_usage(usage: TokenUsage, cost: CostEstimate | None) -> None:
    with _registry._lock:
        if _registry.prompt_tokens_total is None:
            _registry.prompt_tokens_total = 0
        if _registry.completion_tokens_total is None:
            _registry.completion_tokens_total = 0
        _registry.prompt_tokens_total += usage.prompt_tokens
        _registry.completion_tokens_total += usage.completion_tokens
        _registry.model_calls_with_usage += 1
        if cost is not None:
            if _registry.estimated_cost_usd_total is None:
                _registry.estimated_cost_usd_total = 0.0
            _registry.estimated_cost_usd_total += cost.estimated_cost_usd
            _registry.cost_estimates_recorded += 1
    _otel_add_tokens(usage, cost)


def snapshot() -> dict[str, Any]:
    """JSON view for the ops dashboard — uses null for unavailable series."""
    with _registry._lock:
        req_total = sum(c.value for c in _registry.requests.values())
        by_route: dict[str, dict[str, float]] = {}
        for (route, _p, _s, outcome), counter in _registry.requests.items():
            bucket = by_route.setdefault(route, {"count": 0.0, "duration_sum_ms": 0.0, "duration_count": 0})
            bucket["count"] += counter.value
        for (route, _p, _s, _o), agg in _registry.request_duration.items():
            bucket = by_route.setdefault(route, {"count": 0.0, "duration_sum_ms": 0.0, "duration_count": 0})
            bucket["duration_sum_ms"] += agg.sum_ms
            bucket["duration_count"] += agg.count

        route_rows = []
        for route, bucket in sorted(by_route.items()):
            avg = (
                bucket["duration_sum_ms"] / bucket["duration_count"]
                if bucket["duration_count"]
                else None
            )
            route_rows.append(
                {
                    "route": route,
                    "count": int(bucket["count"]),
                    "avg_duration_ms": round(avg, 2) if avg is not None else None,
                }
            )

        by_outcome: dict[str, int] = defaultdict(int)
        for (_r, _p, _s, outcome), counter in _registry.requests.items():
            by_outcome[outcome] += int(counter.value)

        decisions: dict[str, int] = {"allow": 0, "block": 0, "escalate": 0}
        for (_p, _s, decision), counter in _registry.guard_decisions.items():
            decisions[decision] = decisions.get(decision, 0) + int(counter.value)

        guard_count = sum(a.count for a in _registry.guard_duration.values())
        guard_sum = sum(a.sum_ms for a in _registry.guard_duration.values())
        avg_guard = round(guard_sum / guard_count, 2) if guard_count else None

        approvals = {"approved": 0, "denied": 0, "error": 0}
        for (_p, _s, outcome), counter in _registry.approvals.items():
            approvals[outcome] = approvals.get(outcome, 0) + int(counter.value)

        guard_err = sum(int(c.value) for c in _registry.guard_errors.values())

        pricing = load_model_pricing()
        usage_available = _registry.model_calls_with_usage > 0
        pricing_configured = bool(pricing)
        cost_available = (
            usage_available
            and pricing_configured
            and _registry.estimated_cost_usd_total is not None
            and _registry.cost_estimates_recorded > 0
        )

        return {
            "requests": {
                "total": int(req_total),
                "by_route": route_rows,
                "by_outcome": dict(by_outcome),
            },
            "guards": {
                "decisions": decisions,
                "avg_latency_ms": avg_guard,
                "errors": guard_err,
                "evaluations": guard_count,
            },
            "approvals": approvals,
            "model": {
                "usage_available": usage_available,
                "pricing_configured": pricing_configured,
                "prompt_tokens": _registry.prompt_tokens_total if usage_available else None,
                "completion_tokens": (
                    _registry.completion_tokens_total if usage_available else None
                ),
                "estimated_cost_usd": (
                    round(_registry.estimated_cost_usd_total, 6) if cost_available else None
                ),
                "estimated_cost_is_estimate": True,
                "calls_with_usage": _registry.model_calls_with_usage,
                "calls_without_usage": _registry.model_calls_without_usage,
                "unavailable_reason": _model_unavailable_reason(
                    usage_available, pricing_configured, cost_available
                ),
            },
            "generated_at_ms": int(time.time() * 1000),
        }


def _model_unavailable_reason(
    usage_available: bool, pricing_configured: bool, cost_available: bool
) -> str | None:
    if usage_available and cost_available:
        return None
    if not usage_available:
        return "provider_usage_metadata_unavailable"
    if not pricing_configured:
        return "pricing_not_configured"
    return "cost_unavailable"


def render_prometheus() -> str:
    """Prometheus text exposition format (no extra dependency)."""
    lines: list[str] = []
    with _registry._lock:
        lines.append("# HELP aegis_requests_total API requests by route/process/source_app/outcome")
        lines.append("# TYPE aegis_requests_total counter")
        for (route, process, source_app, outcome), counter in sorted(_registry.requests.items()):
            lines.append(
                'aegis_requests_total{'
                f'route="{_prom_escape(route)}",process="{_prom_escape(process)}",'
                f'source_app="{_prom_escape(source_app)}",outcome="{_prom_escape(outcome)}"'
                f"}} {counter.value}"
            )

        lines.append(
            "# HELP aegis_request_duration_ms_sum Request duration sum in milliseconds"
        )
        lines.append("# TYPE aegis_request_duration_ms_sum counter")
        lines.append(
            "# HELP aegis_request_duration_ms_count Request duration observation count"
        )
        lines.append("# TYPE aegis_request_duration_ms_count counter")
        for (route, process, source_app, outcome), agg in sorted(
            _registry.request_duration.items()
        ):
            labels = (
                f'route="{_prom_escape(route)}",process="{_prom_escape(process)}",'
                f'source_app="{_prom_escape(source_app)}",outcome="{_prom_escape(outcome)}"'
            )
            lines.append(f"aegis_request_duration_ms_sum{{{labels}}} {agg.sum_ms}")
            lines.append(f"aegis_request_duration_ms_count{{{labels}}} {agg.count}")

        lines.append(
            "# HELP aegis_guard_decisions_total Guard decisions by process/source_app/decision"
        )
        lines.append("# TYPE aegis_guard_decisions_total counter")
        for (process, source_app, decision), counter in sorted(
            _registry.guard_decisions.items()
        ):
            lines.append(
                "aegis_guard_decisions_total{"
                f'process="{_prom_escape(process)}",source_app="{_prom_escape(source_app)}",'
                f'decision="{_prom_escape(decision)}"'
                f"}} {counter.value}"
            )

        lines.append("# HELP aegis_guard_eval_duration_ms_sum Guard evaluation latency sum")
        lines.append("# TYPE aegis_guard_eval_duration_ms_sum counter")
        lines.append("# HELP aegis_guard_eval_duration_ms_count Guard evaluation latency count")
        lines.append("# TYPE aegis_guard_eval_duration_ms_count counter")
        for (process, source_app), agg in sorted(_registry.guard_duration.items()):
            labels = (
                f'process="{_prom_escape(process)}",source_app="{_prom_escape(source_app)}"'
            )
            lines.append(f"aegis_guard_eval_duration_ms_sum{{{labels}}} {agg.sum_ms}")
            lines.append(f"aegis_guard_eval_duration_ms_count{{{labels}}} {agg.count}")

        lines.append("# HELP aegis_guard_errors_total Guard evaluation errors")
        lines.append("# TYPE aegis_guard_errors_total counter")
        for (process, source_app), counter in sorted(_registry.guard_errors.items()):
            lines.append(
                "aegis_guard_errors_total{"
                f'process="{_prom_escape(process)}",source_app="{_prom_escape(source_app)}"'
                f"}} {counter.value}"
            )

        lines.append("# HELP aegis_approvals_total Approval resolutions")
        lines.append("# TYPE aegis_approvals_total counter")
        for (process, source_app, outcome), counter in sorted(_registry.approvals.items()):
            lines.append(
                "aegis_approvals_total{"
                f'process="{_prom_escape(process)}",source_app="{_prom_escape(source_app)}",'
                f'outcome="{_prom_escape(outcome)}"'
                f"}} {counter.value}"
            )

        # Token / cost series only appear when we have real observations.
        if _registry.prompt_tokens_total is not None:
            lines.append("# HELP aegis_model_prompt_tokens_total Observed prompt tokens")
            lines.append("# TYPE aegis_model_prompt_tokens_total counter")
            lines.append(f"aegis_model_prompt_tokens_total {_registry.prompt_tokens_total}")
        if _registry.completion_tokens_total is not None:
            lines.append(
                "# HELP aegis_model_completion_tokens_total Observed completion tokens"
            )
            lines.append("# TYPE aegis_model_completion_tokens_total counter")
            lines.append(
                f"aegis_model_completion_tokens_total {_registry.completion_tokens_total}"
            )
        if (
            _registry.estimated_cost_usd_total is not None
            and _registry.cost_estimates_recorded > 0
        ):
            lines.append(
                "# HELP aegis_model_estimated_cost_usd_total "
                "Estimated model cost in USD (estimate; requires AEGIS_MODEL_PRICING_JSON)"
            )
            lines.append("# TYPE aegis_model_estimated_cost_usd_total counter")
            lines.append(
                f"aegis_model_estimated_cost_usd_total {_registry.estimated_cost_usd_total}"
            )

    return "\n".join(lines) + "\n"


def _prom_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


# --- Optional OTel instruments (best-effort; never required) -----------------


def bind_otel_instruments(instruments: dict[str, Any] | None) -> None:
    """Attach OTel instruments created during configure_telemetry."""
    global _otel_instruments
    _otel_instruments = instruments


def _otel_add_request(
    route: str, process: str, source_app: str, outcome: str, duration_ms: float
) -> None:
    inst = _otel_instruments
    if not inst:
        return
    try:
        attrs = {
            "route": route,
            "process": process,
            "source_app": source_app,
            "outcome": outcome,
        }
        inst["requests"].add(1, attrs)
        inst["request_duration"].record(duration_ms, attrs)
    except Exception:  # noqa: BLE001, S110
        pass


def _otel_add_guard(process: str, source_app: str, decision: str, duration_ms: float) -> None:
    inst = _otel_instruments
    if not inst:
        return
    try:
        attrs = {"process": process, "source_app": source_app, "decision": decision}
        inst["guard_decisions"].add(1, attrs)
        inst["guard_duration"].record(
            duration_ms, {"process": process, "source_app": source_app}
        )
    except Exception:  # noqa: BLE001, S110
        pass


def _otel_add_guard_error(process: str, source_app: str) -> None:
    inst = _otel_instruments
    if not inst:
        return
    try:
        inst["guard_errors"].add(1, {"process": process, "source_app": source_app})
    except Exception:  # noqa: BLE001, S110
        pass


def _otel_add_approval(process: str, source_app: str, outcome: str) -> None:
    inst = _otel_instruments
    if not inst:
        return
    try:
        inst["approvals"].add(
            1, {"process": process, "source_app": source_app, "outcome": outcome}
        )
    except Exception:  # noqa: BLE001, S110
        pass


def _otel_add_tokens(usage: TokenUsage, cost: CostEstimate | None) -> None:
    inst = _otel_instruments
    if not inst:
        return
    try:
        inst["prompt_tokens"].add(usage.prompt_tokens)
        inst["completion_tokens"].add(usage.completion_tokens)
        if cost is not None:
            inst["estimated_cost"].add(cost.estimated_cost_usd)
    except Exception:  # noqa: BLE001, S110
        pass
