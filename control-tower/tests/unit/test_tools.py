"""Unit tests for agent tools registry."""

from __future__ import annotations

import pytest

from agent.tools import (
    ToolSideEffects,
    create_purchase_order,
    execute_bound_tool,
    get_bound_tools,
)
from configs.loader import load_process


def test_allowed_tools_callable() -> None:
    effects = ToolSideEffects()
    result = create_purchase_order(
        vendor_id="V-1001", amount=2500, item="Laptop docks", side_effects=effects
    )
    assert result["status"] == "created"
    assert effects.events[0]["tool_name"] == "create_purchase_order"


def test_registry_excludes_disallowed() -> None:
    config = load_process("procurement_review")
    bound = get_bound_tools(config)
    assert "create_purchase_order" in bound
    assert "request_approval" in bound
    for name in ("send_payment", "modify_vendor_banking_details"):
        assert name not in bound
    for name in config.disallowed_tools:
        assert name not in bound


def test_onboarding_bound_tools() -> None:
    config = load_process("onboarding_kyc")
    bound = get_bound_tools(config)
    assert "verify_identity" in bound
    assert "disburse_funds" not in bound
    assert "create_purchase_order" not in bound


def test_finance_bound_tools_exclude_wire_transfer() -> None:
    config = load_process("finance")
    bound = get_bound_tools(config)
    assert "submit_expense_report" in bound
    assert "flag_for_finance_review" in bound
    assert "wire_transfer" not in bound


def test_risk_rating_bound_tools_exclude_suspend() -> None:
    config = load_process("risk_rating")
    bound = get_bound_tools(config)
    assert "assign_risk_rating" in bound
    assert "request_manual_review" in bound
    assert "suspend_account" not in bound


def test_rag_bot_bound_tools_exclude_delete() -> None:
    config = load_process("rag_bot")
    bound = get_bound_tools(config)
    assert "search_knowledge_base" in bound
    assert "escalate_to_human_agent" in bound
    assert "delete_knowledge_document" not in bound


def test_execute_bound_rejects_unbound() -> None:
    config = load_process("procurement_review")
    with pytest.raises(PermissionError):
        execute_bound_tool(config, "send_payment", {"amount": 1})
