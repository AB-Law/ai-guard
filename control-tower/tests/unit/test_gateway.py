"""Table-driven gateway tests."""

from __future__ import annotations

import pytest

from configs.loader import load_process
from contracts.schemas import ToolCallRequest
from guardrails.gateway import decide


def _request(tool_name: str, amount: float | None) -> ToolCallRequest:
    args: dict = {"vendor_id": "V-1001"}
    if amount is not None:
        args["amount"] = amount
    return ToolCallRequest(
        call_id="gw-1",
        process="procurement_review",
        step_id="gateway_check",
        tool_name=tool_name,
        tool_args=args,
        agent_rationale="test",
        context_refs=[],
        timestamp="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def procurement_config():
    return load_process("procurement_review")


@pytest.mark.parametrize(
    "tool,amount,risk,expected",
    [
        ("send_payment", 100.0, 0, "block"),
        ("delete_vendor", 100.0, 0, "block"),
        ("create_purchase_order", 50000.0, 0, "escalate"),
        ("create_purchase_order", 2500.0, 10, "allow"),
    ],
)
def test_gateway_table(procurement_config, tool, amount, risk, expected) -> None:
    decision = decide(
        _request(tool, amount),
        procurement_config,
        risk_score=risk,
        evidence_score=0.9,
        confidence_score=0.9,
    )
    assert decision.decision == expected


def test_onboarding_gateway_blocks_disburse_and_allows_verify() -> None:
    config = load_process("onboarding_kyc")
    block = decide(
        ToolCallRequest(
            call_id="kyc-block",
            process="onboarding_kyc",
            step_id="gateway_check",
            tool_name="disburse_funds",
            tool_args={"applicant_id": "A-1001"},
            agent_rationale="pay out",
            context_refs=[],
            timestamp="2026-01-01T00:00:00+00:00",
        ),
        config,
        risk_score=0,
        evidence_score=0.9,
        confidence_score=0.9,
    )
    assert block.decision == "block"

    allow = decide(
        ToolCallRequest(
            call_id="kyc-allow",
            process="onboarding_kyc",
            step_id="gateway_check",
            tool_name="verify_identity",
            tool_args={"applicant_id": "A-1001"},
            agent_rationale="ID present",
            context_refs=["chunk:kyc:identity_verification"],
            timestamp="2026-01-01T00:00:00+00:00",
        ),
        config,
        risk_score=10,
        evidence_score=0.9,
        confidence_score=0.9,
    )
    assert allow.decision == "allow"
