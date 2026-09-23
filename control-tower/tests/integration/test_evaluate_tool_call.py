"""Integration tests for evaluate_tool_call pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from audit.log_store import AuditLogStore
from configs.loader import load_process
from contracts.schemas import ToolCallRequest
from guardrails.evaluate import evaluate_tool_call


@pytest.fixture
def store(tmp_path: Path) -> AuditLogStore:
    return AuditLogStore(tmp_path / "audit.db")


def _sample_request(tool_name: str = "create_purchase_order", amount: float = 2500) -> ToolCallRequest:
    return ToolCallRequest(
        call_id="eval-1",
        process="procurement_review",
        step_id="gateway_check",
        tool_name=tool_name,
        tool_args={"vendor_id": "V-1001", "amount": amount},
        agent_rationale=(
            "Purchase orders at or below USD 10,000 may be auto-approved when "
            "the vendor is active on the vendor master list."
        ),
        context_refs=["chunk:policy:auto_approve"],
        timestamp="2026-01-01T00:00:00+00:00",
    )


def test_clean_evaluate_writes_audit_and_chain_verifies(store: AuditLogStore) -> None:
    config = load_process("procurement_review")
    policy = Path(__file__).resolve().parents[2] / "data" / "procurement_policy.md"
    chunk = policy.read_text(encoding="utf-8")

    decision = evaluate_tool_call(
        _sample_request(),
        config,
        retrieved_texts=[chunk],
        context_chunks=[chunk],
        audit=store,
    )
    assert decision.decision == "allow"
    rows = store.query(process="procurement_review")
    assert len(rows) >= 1
    assert store.verify_chain()


def test_malicious_retrieval_logs_injection_flag(
    store: AuditLogStore, data_dir: Path
) -> None:
    config = load_process("procurement_review")
    malicious = (data_dir / "injected_quote_malicious.txt").read_text(encoding="utf-8")

    evaluate_tool_call(
        _sample_request(),
        config,
        retrieved_texts=[malicious],
        context_chunks=[malicious],
        audit=store,
    )
    injection_rows = store.query(event_type="injection_flag")
    assert len(injection_rows) >= 1


def test_unauthorized_tool_blocked_with_audit_rows(store: AuditLogStore) -> None:
    config = load_process("procurement_review")
    decision = evaluate_tool_call(
        _sample_request(tool_name="send_payment"),
        config,
        audit=store,
    )
    assert decision.decision == "block"
    assert store.query(event_type="policy_check")
    assert store.query(event_type="tool_call")
