"""Integration tests for LangGraph agent + HITL."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph, initial_state, resume_case, run_case
from agent.tools import ToolSideEffects
from audit.log_store import AuditLogStore
from knowledge.rag import build_default_kb


@pytest.fixture
def store(tmp_path: Path) -> AuditLogStore:
    return AuditLogStore(tmp_path / "audit.db")


@pytest.fixture
def kb(project_root: Path):
    return build_default_kb(project_root)


def test_graph_compiles(store: AuditLogStore, kb) -> None:
    graph = build_graph(audit=store, kb=kb, checkpointer=MemorySaver())
    assert graph is not None


def test_mocked_clean_allow_path(store: AuditLogStore, kb) -> None:
    effects = ToolSideEffects()
    graph = build_graph(
        audit=store, kb=kb, checkpointer=MemorySaver(), side_effects=effects
    )
    state = initial_state(
        case_id="case-clean",
        process="procurement_review",
        request={"vendor_id": "V-1001", "amount": 2500, "item": "Laptop docks x10"},
        mock_agent_plan={
            "tool_name": "create_purchase_order",
            "tool_args": {"vendor_id": "V-1001", "amount": 2500, "item": "Laptop docks x10"},
            "agent_rationale": (
                "Purchase orders at or below USD 10,000 may be auto-approved when "
                "the vendor is active on the vendor master list."
            ),
            "context_refs": ["chunk:policy:auto_approve", "chunk:vendor:V-1001"],
        },
    )
    result = run_case(graph, state)
    assert (result.get("gateway_decision") or {}).get("decision") == "allow"
    assert result.get("status") == "completed"
    assert effects.events
    assert effects.events[0]["tool_name"] == "create_purchase_order"

    types = {e.event_type for e in store.query(process="procurement_review")}
    assert "retrieval" in types
    assert "policy_check" in types
    assert "tool_call" in types
    assert store.verify_chain()


def test_mocked_unauthorized_blocks_without_side_effect(store: AuditLogStore, kb) -> None:
    effects = ToolSideEffects()
    graph = build_graph(
        audit=store, kb=kb, checkpointer=MemorySaver(), side_effects=effects
    )
    state = initial_state(
        case_id="case-unauth",
        process="procurement_review",
        request={"vendor_id": "V-1001", "amount": 100, "item": "x"},
        mock_agent_plan={
            "tool_name": "send_payment",
            "tool_args": {"vendor_id": "V-1001", "amount": 100},
            "agent_rationale": "Pay vendor now.",
            "context_refs": ["chunk:vendor:V-1001"],
        },
    )
    result = run_case(graph, state)
    assert (result.get("gateway_decision") or {}).get("decision") == "block"
    assert result.get("status") == "blocked"
    assert effects.events == []


def test_escalation_interrupt_and_resume(store: AuditLogStore, kb) -> None:
    effects = ToolSideEffects()
    checkpointer = MemorySaver()
    graph = build_graph(
        audit=store, kb=kb, checkpointer=checkpointer, side_effects=effects
    )
    state = initial_state(
        case_id="case-escalate",
        process="procurement_review",
        request={"vendor_id": "V-1001", "amount": 50000, "item": "Server racks"},
        mock_agent_plan={
            "tool_name": "create_purchase_order",
            "tool_args": {
                "vendor_id": "V-1001",
                "amount": 50000,
                "item": "Server racks",
            },
            "agent_rationale": (
                "Purchase orders at or below USD 10,000 may be auto-approved when "
                "the vendor is active; this amount requires approval."
            ),
            "context_refs": ["chunk:policy:auto_approve", "chunk:vendor:V-1001"],
        },
    )
    paused = run_case(graph, state, thread_id="case-escalate")
    assert (paused.get("gateway_decision") or {}).get("decision") == "escalate"
    assert paused.get("__interrupt__") or effects.events == []

    snap = graph.get_state({"configurable": {"thread_id": "case-escalate"}})
    assert snap.next  # still has work to do

    resumed = resume_case(
        graph, thread_id="case-escalate", action="approve", actor="auditor-1"
    )
    assert resumed.get("status") == "completed"
    assert effects.events
    assert any(e.event_type == "approval" for e in store.query())
    assert store.verify_chain()
