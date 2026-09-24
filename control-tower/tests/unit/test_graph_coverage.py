"""Additional tests for agent/graph.py to increase coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.graph import ProposedToolPlan, ToolArgs, build_graph
from agent.tools import ToolSideEffects
from audit.log_store import AuditLogStore
from configs.loader import load_process
from knowledge.rag import build_kb_for_process


def test_tool_args_model_with_all_fields() -> None:
    """Test ToolArgs model with all fields populated."""
    args = ToolArgs(
        vendor_id="V-1001",
        applicant_id="A-1001",
        amount=1500.50,
        item="Test item",
        call_id="call-123",
        reason="Test reason",
    )
    
    assert args.vendor_id == "V-1001"
    assert args.applicant_id == "A-1001"
    assert args.amount == 1500.50
    assert args.item == "Test item"
    assert args.call_id == "call-123"
    assert args.reason == "Test reason"


def test_tool_args_model_with_partial_fields() -> None:
    """Test ToolArgs model with only some fields."""
    args = ToolArgs(vendor_id="V-1001", amount=100)
    
    assert args.vendor_id == "V-1001"
    assert args.amount == 100
    assert args.applicant_id is None
    assert args.item is None


def test_tool_args_forbids_extra_fields() -> None:
    """Test that ToolArgs forbids extra fields."""
    with pytest.raises(ValueError):
        ToolArgs(vendor_id="V-1001", unknown_field="value")


def test_proposed_tool_plan_model() -> None:
    """Test ProposedToolPlan model."""
    plan = ProposedToolPlan(
        tool_name="create_purchase_order",
        tool_args=ToolArgs(vendor_id="V-1001", amount=2500),
        agent_rationale="Creating PO for approved vendor",
        context_refs=["chunk:policy:1", "chunk:vendor:1"],
    )
    
    assert plan.tool_name == "create_purchase_order"
    assert plan.agent_rationale == "Creating PO for approved vendor"
    assert len(plan.context_refs) == 2


def test_proposed_tool_plan_args_dict() -> None:
    """Test ProposedToolPlan.args_dict() filters None values."""
    args = ToolArgs(
        vendor_id="V-1001",
        amount=1000,
        item="Laptop",
        applicant_id=None,
        call_id=None,
        reason=None,
    )
    plan = ProposedToolPlan(
        tool_name="create_purchase_order",
        tool_args=args,
        agent_rationale="Test",
    )
    
    args_dict = plan.args_dict()
    
    assert "vendor_id" in args_dict
    assert "amount" in args_dict
    assert "item" in args_dict
    assert "applicant_id" not in args_dict
    assert "call_id" not in args_dict
    assert "reason" not in args_dict


def test_proposed_tool_plan_default_context_refs() -> None:
    """Test that context_refs defaults to empty list."""
    plan = ProposedToolPlan(
        tool_name="test_tool",
        agent_rationale="Test",
    )
    
    assert plan.context_refs == []


def test_build_graph_with_explicit_config(tmp_path: Path, project_root: Path) -> None:
    """Test building graph with explicit config."""
    audit = AuditLogStore(tmp_path / "audit.db")
    config = load_process("procurement_review")
    
    graph = build_graph(audit=audit, config=config)
    
    assert graph is not None
    audit.close()


def test_build_graph_with_kb_dict(tmp_path: Path, project_root: Path) -> None:
    """Test building graph with KB dictionary."""
    audit = AuditLogStore(tmp_path / "audit.db")
    kbs = {
        "procurement_review": build_kb_for_process("procurement_review", project_root),
        "onboarding_kyc": build_kb_for_process("onboarding_kyc", project_root),
    }
    
    graph = build_graph(audit=audit, kb=kbs)
    
    assert graph is not None
    audit.close()


def test_build_graph_with_single_kb(tmp_path: Path, project_root: Path) -> None:
    """Test building graph with single KB."""
    audit = AuditLogStore(tmp_path / "audit.db")
    kb = build_kb_for_process("procurement_review", project_root)
    
    graph = build_graph(audit=audit, kb=kb)
    
    assert graph is not None
    audit.close()


def test_build_graph_with_kb_callable(tmp_path: Path, project_root: Path) -> None:
    """Test building graph with KB factory function."""
    audit = AuditLogStore(tmp_path / "audit.db")
    
    def kb_factory(process: str):
        return build_kb_for_process(process, project_root)
    
    graph = build_graph(audit=audit, kb=kb_factory)
    
    assert graph is not None
    audit.close()


def test_build_graph_with_side_effects(tmp_path: Path) -> None:
    """Test building graph with custom side effects."""
    audit = AuditLogStore(tmp_path / "audit.db")
    effects = ToolSideEffects()
    
    graph = build_graph(audit=audit, side_effects=effects)
    
    assert graph is not None
    audit.close()


def test_build_graph_defaults(tmp_path: Path) -> None:
    """Test building graph with minimal arguments uses defaults."""
    audit = AuditLogStore(tmp_path / "audit.db")
    
    graph = build_graph(audit=audit)
    
    assert graph is not None
    audit.close()
