"""Unit tests for dashboard view-models — scores are pass-through only."""

from __future__ import annotations

from datetime import UTC, datetime

from dashboard.view_models import (
    audit_to_timeline,
    case_kpis,
    cases_to_rows,
    decision_badge_kind,
    decision_to_score_panel,
    format_decision_label,
    format_score_value,
    make_live_case_id,
    offline_investigate_mock,
    pending_approvals,
    relative_age,
    request_to_display,
    short_timestamp,
    status_badge_kind,
    unique_live_case_id,
)


def test_decision_to_score_panel_verbatim() -> None:
    decision = {
        "call_id": "c-1",
        "decision": "escalate",
        "reason": "Amount exceeds max_auto_amount",
        "policy_refs": ["allowed_tools", "create_purchase_order"],
        "risk_score": 72,
        "confidence_score": 0.81,
        "evidence_score": 0.64,
    }
    panel = decision_to_score_panel(decision)
    assert panel is not None
    assert panel["risk_score"] == 72
    assert panel["confidence_score"] == 0.81
    assert panel["evidence_score"] == 0.64
    assert panel["reason"] == "Amount exceeds max_auto_amount"
    assert panel["policy_refs"] == ["allowed_tools", "create_purchase_order"]
    assert panel["decision"] == "escalate"
    assert panel["call_id"] == "c-1"


def test_decision_to_score_panel_none() -> None:
    assert decision_to_score_panel(None) is None
    assert decision_to_score_panel({})["decision"] is None


def test_cases_to_rows_and_pending() -> None:
    cases = [
        {
            "case_id": "a",
            "process": "procurement_review",
            "status": "completed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "call_id": "c-a",
            "gateway_decision": {"decision": "allow", "risk_score": 10},
        },
        {
            "case_id": "b",
            "process": "procurement_review",
            "status": "pending_approval",
            "created_at": "2026-01-02T00:00:00+00:00",
            "call_id": "c-b",
            "gateway_decision": {
                "decision": "escalate",
                "reason": "over limit",
                "risk_score": 80,
            },
        },
    ]
    rows = cases_to_rows(cases)
    assert rows[0]["case_id"] == "a"
    assert rows[0]["decision"] == "allow"
    assert rows[0]["created_at"] == "00:00:00"
    assert "call_id" not in rows[0]
    pending = pending_approvals(cases)
    assert len(pending) == 1
    assert pending[0]["call_id"] == "c-b"
    assert pending[0]["risk_score"] == 80


def test_audit_to_timeline_ordered() -> None:
    entries = [
        {
            "entry_id": "2",
            "event_type": "policy_check",
            "step_id": "gateway_check",
            "timestamp": "2026-01-01T00:00:02+00:00",
            "payload": {"tool_name": "create_purchase_order"},
            "scores": None,
        },
        {
            "entry_id": "1",
            "event_type": "retrieval",
            "step_id": "retrieve",
            "timestamp": "2026-01-01T00:00:01+00:00",
            "payload": {"query": "policy", "chunk_ids": ["a", "b"]},
            "scores": None,
        },
    ]
    timeline = audit_to_timeline(entries)
    assert [r["entry_id"] for r in timeline] == ["1", "2"]
    assert "chunks=2" in timeline[0]["summary"]
    assert timeline[0]["time_short"] == "00:00:01"


def test_audit_to_timeline_score_summary() -> None:
    entries = [
        {
            "entry_id": "1",
            "event_type": "policy_check",
            "step_id": "gateway_check",
            "timestamp": "2026-01-01T00:00:01+00:00",
            "payload": {},
            "scores": {"decision": "block", "risk_score": 90},
        }
    ]
    row = audit_to_timeline(entries)[0]
    assert "decision=block" in row["score_summary"]
    assert "risk=90" in row["score_summary"]


def test_request_to_display_ordered() -> None:
    pairs = request_to_display(
        {"item": "docks", "vendor_id": "V-1001", "amount": 2500, "extra": "x"}
    )
    assert pairs[0] == ("vendor_id", "V-1001")
    assert pairs[1] == ("amount", "2500")
    assert pairs[2] == ("item", "docks")
    assert ("extra", "x") in pairs


def test_submit_case_form_specs_differ_by_process() -> None:
    from dashboard.view_models import (
        build_submit_case_request,
        submit_case_form_spec,
        submit_case_source_app,
    )

    finance = submit_case_form_spec("finance")
    risk = submit_case_form_spec("risk_rating")
    rag = submit_case_form_spec("rag_bot")
    proc = submit_case_form_spec("procurement_review")

    assert finance["party_label"] == "Employee ID"
    assert finance["detail_default"] == "Client workshop travel"
    assert risk["party_label"] == "Customer ID"
    assert risk["amount_label"] == "Severity (1-5)"
    assert rag["detail_label"] == "Question"
    assert rag["show_amount"] is False
    assert proc["detail_default"] == "Laptop docks x10"

    assert submit_case_source_app("finance") == "finance_app"
    assert submit_case_source_app("rag_bot") == "rag_bot_app"
    assert submit_case_source_app("procurement_review") is None

    fin_req = build_submit_case_request(
        "finance", party_id="E-9", amount=900.0, detail="Team offsite catering"
    )
    assert fin_req["employee_id"] == "E-9"
    assert fin_req["vendor_id"] == "E-9"
    assert fin_req["item"] == "Team offsite catering"

    rag_req = build_submit_case_request(
        "rag_bot", party_id="U-1", amount=0.0, detail="How do I reset my password?"
    )
    assert rag_req["query"] == "How do I reset my password?"
    assert rag_req["item"] == "How do I reset my password?"


def test_offline_investigate_mock() -> None:
    mock = offline_investigate_mock(
        "Why?",
        case_id="high_amount_escalate",
        decision={
            "decision": "escalate",
            "reason": "over limit",
            "policy_refs": ["chunk:policy:escalation"],
        },
    )
    assert "escalate" in mock["answer"]
    assert "over limit" in mock["answer"]
    assert mock["cited_chunk_ids"] == ["chunk:policy:escalation"]


def test_case_kpis() -> None:
    cases = [
        {
            "status": "completed",
            "gateway_decision": {"decision": "allow"},
        },
        {
            "status": "blocked",
            "gateway_decision": {"decision": "block"},
        },
        {
            "status": "pending_approval",
            "gateway_decision": {"decision": "escalate"},
        },
        {
            "status": "pending_approval",
            "gateway_decision": {"decision": "escalate"},
        },
    ]
    kpis = case_kpis(cases)
    assert kpis == {
        "total": 4,
        "pending": 2,
        "allow": 1,
        "block": 1,
        "escalate": 2,
    }


def test_badge_kinds_and_labels() -> None:
    assert decision_badge_kind("allow") == "allow"
    assert decision_badge_kind("BLOCK") == "block"
    assert decision_badge_kind(None) == "neutral"
    assert status_badge_kind("pending_approval") == "pending"
    assert status_badge_kind("completed") == "allow"
    assert status_badge_kind("blocked") == "block"
    assert format_decision_label("escalate") == "ESCALATE"
    assert format_decision_label(None) == "—"


def test_make_live_case_id() -> None:
    now = datetime(2026, 9, 23, 19, 45, 32, tzinfo=UTC)
    assert make_live_case_id("V-1001", now=now) == "live-V-1001-194532"
    assert make_live_case_id("weird vendor!!", now=now) == "live-weird-vendor-194532"
    assert make_live_case_id("", now=now) == "live-case-194532"
    assert make_live_case_id("V-1", now=now, suffix="ab12") == "live-V-1-194532-ab12"


def test_unique_live_case_id_collision() -> None:
    now = datetime(2026, 9, 23, 19, 45, 32, tzinfo=UTC)
    base = "live-V-1001-194532"
    assert unique_live_case_id("V-1001", set(), now=now) == base
    collided = unique_live_case_id("V-1001", {base}, now=now)
    assert collided.startswith(base + "-")
    assert len(collided) == len(base) + 1 + 4


def test_format_score_value() -> None:
    assert format_score_value(72) == "72"
    assert format_score_value(0.81) == "0.81"
    assert format_score_value(0.0) == "0.00"
    assert format_score_value(None) == "—"


def test_short_timestamp() -> None:
    assert short_timestamp("2026-01-01T14:30:05+00:00") == "14:30:05"
    assert short_timestamp("14:30:05") == "14:30:05"
    assert short_timestamp(None) == ""


def test_relative_age() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert relative_age("2026-01-01T11:59:50+00:00", now=now) == "now"
    assert relative_age("2026-01-01T11:50:00+00:00", now=now) == "10m"
    assert relative_age("2026-01-01T09:00:00+00:00", now=now) == "3h"
    assert relative_age("2025-12-30T12:00:00+00:00", now=now) == "2d"
    assert relative_age(None, now=now) == ""


def test_traffic_event_blurb() -> None:
    from dashboard.view_models import traffic_event_blurb

    blurb = traffic_event_blurb(
        {
            "stages": ["retrieval", "injection_flag", "policy_check"],
            "decision": "escalate",
            "reason": "Prompt injection indicators detected",
            "tool_name": "answer_from_docs",
        }
    )
    assert "Injection flagged" in blurb
    assert "needs human approval" in blurb
    assert "answer_from_docs" in blurb
    assert "Prompt injection" in blurb
