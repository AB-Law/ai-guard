"""Contract tests for ARCHITECTURE §6 schemas."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from contracts.schemas import AuditLogEntry, GatewayDecision, ToolCallRequest


def _sample_tool_call() -> ToolCallRequest:
    return ToolCallRequest(
        call_id="c-1",
        process="procurement_review",
        step_id="propose_tool",
        tool_name="create_purchase_order",
        tool_args={"vendor_id": "V-1001", "amount": 2500},
        agent_rationale="Under auto-approve limit.",
        context_refs=["chunk:policy:auto_approve"],
        timestamp="2026-01-01T00:00:00+00:00",
    )


def test_tool_call_request_valid() -> None:
    req = _sample_tool_call()
    assert req.tool_name == "create_purchase_order"


def test_tool_call_request_rejects_missing_field() -> None:
    data = _sample_tool_call().model_dump()
    del data["call_id"]
    with pytest.raises(ValidationError):
        ToolCallRequest.model_validate(data)


def test_gateway_decision_literals() -> None:
    for decision in ("allow", "block", "escalate"):
        gd = GatewayDecision(
            call_id="c-1",
            decision=decision,  # type: ignore[arg-type]
            reason="ok",
            policy_refs=[],
            risk_score=10,
            confidence_score=0.9,
            evidence_score=0.8,
        )
        assert gd.decision == decision


def test_gateway_decision_rejects_bad_literal() -> None:
    with pytest.raises(ValidationError):
        GatewayDecision(
            call_id="c-1",
            decision="deny",  # type: ignore[arg-type]
            reason="no",
            policy_refs=[],
            risk_score=10,
            confidence_score=0.9,
            evidence_score=0.8,
        )


def test_audit_log_entry_rejects_bad_event_type() -> None:
    with pytest.raises(ValidationError):
        AuditLogEntry(
            entry_id="e-1",
            process="procurement_review",
            step_id="s",
            event_type="unknown",  # type: ignore[arg-type]
            payload={},
            scores=None,
            timestamp="2026-01-01T00:00:00+00:00",
            prev_hash="0" * 64,
            entry_hash="a" * 64,
        )


def test_json_round_trip() -> None:
    req = _sample_tool_call()
    restored = ToolCallRequest.model_validate_json(req.model_dump_json())
    assert restored == req

    gd = GatewayDecision(
        call_id="c-1",
        decision="allow",
        reason="ok",
        policy_refs=["policy:1"],
        risk_score=5,
        confidence_score=0.95,
        evidence_score=0.85,
    )
    gd2 = GatewayDecision.model_validate(json.loads(gd.model_dump_json()))
    assert gd2 == gd

    entry = AuditLogEntry(
        entry_id="e-1",
        process="procurement_review",
        step_id="gateway_check",
        event_type="policy_check",
        payload={"k": "v"},
        scores=gd,
        timestamp="2026-01-01T00:00:00+00:00",
        prev_hash="0" * 64,
        entry_hash="b" * 64,
    )
    entry2 = AuditLogEntry.model_validate_json(entry.model_dump_json())
    assert entry2.entry_id == entry.entry_id
    assert entry2.scores is not None
    assert entry2.scores.decision == "allow"
