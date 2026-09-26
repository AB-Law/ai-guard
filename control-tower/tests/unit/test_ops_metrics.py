"""Operational metrics — labels, outcomes, usage/pricing, exporter failure."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from configs.loader import load_process
from contracts.schemas import ToolCallRequest
from guardrails.evaluate import evaluate_tool_call
from telemetry.labels import (
    bound_guard_decision,
    bound_process,
    bound_route,
    bound_source_app,
    sanitize_label,
)
from telemetry.metrics import (
    record_approval,
    record_guard_decision,
    record_request,
    record_token_usage,
    render_prometheus,
    reset_metrics_for_tests,
    snapshot,
)
from telemetry.setup import configure_telemetry, reset_telemetry_for_tests
from telemetry.usage import (
    TokenUsage,
    estimate_cost_usd,
    extract_token_usage,
    load_model_pricing,
)


@pytest.fixture(autouse=True)
def _reset_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AEGIS_OTEL_ENABLED", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("AEGIS_MODEL_PRICING_JSON", raising=False)
    reset_telemetry_for_tests()
    reset_metrics_for_tests()
    yield
    reset_metrics_for_tests()
    reset_telemetry_for_tests()


def test_labels_reject_high_cardinality_ids() -> None:
    assert sanitize_label("case-abc-123") == "unknown"
    assert sanitize_label("a" * 32) == "unknown"  # long hex
    assert sanitize_label("user@example.com") == "unknown"
    assert bound_process("procurement_review") == "procurement_review"
    assert bound_source_app("erp-bot") == "erp-bot"
    assert bound_route("/guard/approvals/{call_id}") == "/guard/approvals/{call_id}"
    assert bound_route("/guard/approvals/550e8400-e29b-41d4-a716-446655440000").endswith(
        "/{id}"
    )
    assert bound_guard_decision("block") == "block"
    assert bound_guard_decision("weird") == "allow"


def test_request_and_guard_outcomes_in_snapshot_and_prometheus() -> None:
    record_request(
        route="/guard/evaluate",
        process="procurement_review",
        source_app="demo-app",
        outcome="ok",
        duration_ms=12.5,
    )
    record_guard_decision(
        process="procurement_review",
        source_app="demo-app",
        decision="escalate",
        duration_ms=40.0,
    )
    record_approval(
        process="procurement_review",
        source_app="demo-app",
        outcome="approved",
    )

    snap = snapshot()
    assert snap["requests"]["total"] == 1
    assert snap["guards"]["decisions"]["escalate"] == 1
    assert snap["guards"]["avg_latency_ms"] == 40.0
    assert snap["approvals"]["approved"] == 1
    assert snap["model"]["usage_available"] is False
    assert snap["model"]["prompt_tokens"] is None
    assert snap["model"]["estimated_cost_usd"] is None

    text = render_prometheus()
    assert 'aegis_requests_total{route="/guard/evaluate"' in text
    assert 'decision="escalate"' in text
    assert "aegis_model_prompt_tokens_total" not in text  # no fabricated zeros


def test_missing_usage_stays_unavailable() -> None:
    assert extract_token_usage(None) is None
    assert extract_token_usage(SimpleNamespace()) is None
    assert extract_token_usage({"parsed": {"x": 1}}) is None
    snap = snapshot()
    assert snap["model"]["unavailable_reason"] == "provider_usage_metadata_unavailable"
    assert snap["model"]["prompt_tokens"] is None
    assert snap["model"]["estimated_cost_usd"] is None


def test_usage_without_pricing_leaves_cost_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AEGIS_MODEL_PRICING_JSON", raising=False)
    usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150, model="gpt-4o")
    assert estimate_cost_usd(usage) is None
    record_token_usage(usage)
    snap = snapshot()
    assert snap["model"]["usage_available"] is True
    assert snap["model"]["prompt_tokens"] == 100
    assert snap["model"]["estimated_cost_usd"] is None
    assert snap["model"]["unavailable_reason"] == "pricing_not_configured"
    assert "aegis_model_prompt_tokens_total 100" in render_prometheus()
    assert "aegis_model_estimated_cost_usd_total" not in render_prometheus()


def test_usage_with_pricing_marks_cost_as_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AEGIS_MODEL_PRICING_JSON",
        '{"gpt-4o":{"input_per_1m":2.5,"output_per_1m":10.0}}',
    )
    raw = SimpleNamespace(
        usage_metadata={"input_tokens": 1_000_000, "output_tokens": 500_000, "total_tokens": 1_500_000},
        response_metadata={"model_name": "gpt-4o"},
    )
    usage = extract_token_usage(raw)
    assert usage is not None
    cost = estimate_cost_usd(usage, pricing=load_model_pricing())
    assert cost is not None
    assert cost.is_estimate is True
    assert cost.estimated_cost_usd == pytest.approx(2.5 + 5.0)
    record_token_usage(usage, cost)
    snap = snapshot()
    assert snap["model"]["estimated_cost_usd"] == pytest.approx(7.5)
    assert snap["model"]["estimated_cost_is_estimate"] is True


def test_metric_record_failure_does_not_block_evaluate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AEGIS_OTEL_ENABLED", "1")
    configure_telemetry()

    with patch(
        "telemetry.metrics._inc",
        side_effect=RuntimeError("metrics boom"),
    ):
        from audit.log_store import AuditLogStore

        audit = AuditLogStore(tmp_path / "audit.db")
        config = load_process("procurement_review")
        request = ToolCallRequest(
            call_id="metrics-fail-1",
            process="procurement_review",
            step_id="external",
            tool_name="not_a_real_tool",
            tool_args={},
            agent_rationale="under limit",
            context_refs=[],
            timestamp="2026-01-01T00:00:00+00:00",
            case_id="case-metrics-fail",
        )
        decision = evaluate_tool_call(
            request, config, audit=audit, source_app="demo-app"
        )
        assert decision.decision == "block"
        assert audit.verify_chain()


def test_otlp_metric_exporter_failure_does_not_block_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AEGIS_OTEL_ENABLED", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")
    with patch(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter",
        side_effect=RuntimeError("collector unreachable"),
    ):
        configure_telemetry()  # must not raise
    record_request(route="/health", outcome="ok", duration_ms=1.0)
    assert snapshot()["requests"]["total"] == 1


def test_metrics_and_ops_endpoints(tmp_path: Path, project_root: Path) -> None:
    from api.main import create_app

    app = create_app(audit_path=tmp_path / "audit.db", project_root=project_root)
    client = TestClient(app)
    record_request(route="/health", outcome="ok", duration_ms=2.0)
    prom = client.get("/metrics")
    assert prom.status_code == 200
    assert "aegis_requests_total" in prom.text
    # Dashboard JWT required — with AEGIS_DISABLE_AUTH (conftest) it passes.
    snap = client.get("/ops/metrics")
    assert snap.status_code == 200
    body = snap.json()
    assert "requests" in body
    assert "guards" in body
    assert body["model"]["estimated_cost_is_estimate"] is True


def test_prometheus_render_failure_returns_comment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, project_root: Path
) -> None:
    from api.main import create_app

    app = create_app(audit_path=tmp_path / "audit.db", project_root=project_root)
    client = TestClient(app)
    with patch(
        "api.main.render_prometheus",
        side_effect=RuntimeError("explode"),
    ):
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "unavailable" in resp.text.lower()


def test_evaluate_records_guard_decision(tmp_path: Path) -> None:
    from audit.log_store import AuditLogStore

    audit = AuditLogStore(tmp_path / "audit.db")
    config = load_process("procurement_review")
    request = ToolCallRequest(
        call_id="metrics-eval-1",
        process="procurement_review",
        step_id="external",
        tool_name="not_a_real_tool",
        tool_args={},
        agent_rationale="x",
        context_refs=[],
        timestamp="2026-01-01T00:00:00+00:00",
        case_id="case-metrics-eval",
    )
    decision = evaluate_tool_call(
        request, config, audit=audit, source_app="sdk-app"
    )
    assert decision.decision == "block"
    snap = snapshot()
    assert snap["guards"]["decisions"]["block"] >= 1
    assert snap["guards"]["evaluations"] >= 1
