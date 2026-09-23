"""Live OpenAI smoke tests — skipped when OPENAI_API_KEY is unset."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph, initial_state, run_case
from agent.tools import ToolSideEffects
from audit.log_store import AuditLogStore
from knowledge.rag import build_default_kb

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")


def _require_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        pytest.skip("OPENAI_API_KEY not set")
    return key


@pytest.mark.live
def test_live_clean_po_allow(tmp_path: Path, project_root: Path) -> None:
    _require_key()
    audit = AuditLogStore(tmp_path / "live.db")
    kb = build_default_kb(project_root)
    effects = ToolSideEffects()
    graph = build_graph(
        audit=audit, kb=kb, checkpointer=MemorySaver(), side_effects=effects
    )
    state = initial_state(
        case_id="live-clean",
        process="procurement_review",
        request={
            "vendor_id": "V-1001",
            "amount": 2500,
            "item": "Laptop docks x10",
        },
        # No mock_agent_plan — real LLM proposes the tool.
    )
    result = run_case(graph, state, thread_id="live-clean")
    decision = (result.get("gateway_decision") or {}).get("decision")
    assert decision in ("allow", "escalate"), f"unexpected decision {decision}"
    assert result.get("tool_name") in (
        "create_purchase_order",
        "request_approval",
    )
    assert result.get("status") in ("completed", "pending_approval", "blocked")
    assert audit.verify_chain()
    types = {e.event_type for e in audit.query()}
    assert "retrieval" in types
    assert "policy_check" in types


@pytest.mark.live
def test_live_high_amount_escalates_or_requests_approval(
    tmp_path: Path, project_root: Path
) -> None:
    _require_key()
    audit = AuditLogStore(tmp_path / "live_hi.db")
    kb = build_default_kb(project_root)
    graph = build_graph(audit=audit, kb=kb, checkpointer=MemorySaver())
    state = initial_state(
        case_id="live-high",
        process="procurement_review",
        request={
            "vendor_id": "V-1001",
            "amount": 75000,
            "item": "Data center buildout",
        },
    )
    result = run_case(graph, state, thread_id="live-high")
    decision = (result.get("gateway_decision") or {}).get("decision")
    # Gateway must not silently allow over-limit PO creation.
    if result.get("tool_name") == "create_purchase_order":
        assert decision in ("escalate", "block")
    else:
        # LLM may choose request_approval — also acceptable governance outcome.
        assert result.get("tool_name") in (
            "request_approval",
            "create_purchase_order",
        )
    assert audit.verify_chain()
