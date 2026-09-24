"""Comprehensive tests for agent/tools.py to reach 90%+ coverage."""

from __future__ import annotations

import pytest

from agent.tools import (
    ToolSideEffects,
    assign_risk_rating,
    create_purchase_order,
    delete_knowledge_document,
    disburse_funds,
    escalate_to_human_agent,
    execute_bound_tool,
    flag_for_finance_review,
    get_bound_tools,
    modify_vendor_banking_details,
    request_approval,
    request_manual_review,
    search_knowledge_base,
    send_payment,
    submit_expense_report,
    suspend_account,
    verify_identity,
    wire_transfer,
)
from configs.loader import load_process


def test_create_purchase_order_without_side_effects() -> None:
    result = create_purchase_order(vendor_id="V-1001", amount=2500, item="Laptop")
    assert result["status"] == "created"
    assert result["po_id"] == "PO-V-1001-2500"
    assert result["vendor_id"] == "V-1001"
    assert result["amount"] == 2500
    assert result["item"] == "Laptop"


def test_request_approval_with_side_effects() -> None:
    effects = ToolSideEffects()
    result = request_approval(
        call_id="call-123",
        reason="Needs review",
        vendor_id="V-1001",
        amount=50000,
        item="Servers",
        side_effects=effects,
    )
    assert result["status"] == "approval_requested"
    assert result["call_id"] == "call-123"
    assert result["reason"] == "Needs review"
    assert result["vendor_id"] == "V-1001"
    assert result["amount"] == 50000
    assert result["item"] == "Servers"
    assert len(effects.events) == 1
    assert effects.events[0]["tool_name"] == "request_approval"


def test_request_approval_without_side_effects() -> None:
    result = request_approval(call_id="call-456", reason="Check this")
    assert result["status"] == "approval_requested"
    assert result["call_id"] == "call-456"
    assert result["reason"] == "Check this"


def test_verify_identity_with_applicant_id() -> None:
    effects = ToolSideEffects()
    result = verify_identity(applicant_id="A-1001", item="passport", side_effects=effects)
    assert result["status"] == "verified"
    assert result["applicant_id"] == "A-1001"
    assert result["item"] == "passport"
    assert len(effects.events) == 1


def test_verify_identity_with_vendor_id() -> None:
    result = verify_identity(vendor_id="V-2002", item="documents")
    assert result["status"] == "verified"
    assert result["applicant_id"] == "V-2002"


def test_verify_identity_defaults_to_unknown() -> None:
    result = verify_identity(item="license")
    assert result["status"] == "verified"
    assert result["applicant_id"] == "unknown"


def test_send_payment_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="send_payment must not execute"):
        send_payment(vendor_id="V-1001", amount=100)


def test_modify_vendor_banking_details_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="modify_vendor_banking_details must not execute"):
        modify_vendor_banking_details(vendor_id="V-1001")


def test_disburse_funds_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="disburse_funds must not execute"):
        disburse_funds(amount=1000)


def test_submit_expense_report_with_employee_id() -> None:
    effects = ToolSideEffects()
    result = submit_expense_report(
        employee_id="E-1001",
        amount=150.50,
        item="Travel expenses",
        side_effects=effects,
    )
    assert result["status"] == "submitted"
    assert result["expense_id"] == "EXP-E-1001-150"
    assert result["employee_id"] == "E-1001"
    assert result["amount"] == 150.50
    assert result["item"] == "Travel expenses"
    assert len(effects.events) == 1


def test_submit_expense_report_with_vendor_id_fallback() -> None:
    result = submit_expense_report(vendor_id="V-2002", amount=200)
    assert result["expense_id"] == "EXP-V-2002-200"
    assert result["employee_id"] == "V-2002"


def test_submit_expense_report_defaults_to_unknown() -> None:
    result = submit_expense_report(amount=99.99)
    assert result["employee_id"] == "unknown"


def test_flag_for_finance_review_full_args() -> None:
    effects = ToolSideEffects()
    result = flag_for_finance_review(
        call_id="call-789",
        reason="Unusual amount",
        employee_id="E-2001",
        vendor_id="V-3003",
        amount=5000,
        item="Equipment",
        side_effects=effects,
    )
    assert result["status"] == "finance_review_requested"
    assert result["call_id"] == "call-789"
    assert result["reason"] == "Unusual amount"
    assert result["employee_id"] == "E-2001"
    assert result["amount"] == 5000
    assert result["item"] == "Equipment"
    assert len(effects.events) == 1


def test_flag_for_finance_review_with_vendor_id_fallback() -> None:
    result = flag_for_finance_review(vendor_id="V-4004", amount=300)
    assert result["employee_id"] == "V-4004"


def test_flag_for_finance_review_defaults() -> None:
    result = flag_for_finance_review()
    assert result["status"] == "finance_review_requested"
    assert result["reason"] == "finance review requested"


def test_wire_transfer_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="wire_transfer must not execute"):
        wire_transfer(amount=10000)


def test_assign_risk_rating_with_customer_id() -> None:
    effects = ToolSideEffects()
    result = assign_risk_rating(
        customer_id="C-1001",
        amount=4.5,
        rating="High",
        item="Account review",
        side_effects=effects,
    )
    assert result["status"] == "rated"
    assert result["customer_id"] == "C-1001"
    assert result["severity"] == 4.5
    assert result["rating"] == "High"
    assert result["item"] == "Account review"
    assert len(effects.events) == 1


def test_assign_risk_rating_with_vendor_id_fallback() -> None:
    result = assign_risk_rating(vendor_id="V-5005", amount=3.0)
    assert result["customer_id"] == "V-5005"
    assert result["rating"] == "severity-3"


def test_assign_risk_rating_defaults_to_unknown() -> None:
    result = assign_risk_rating(amount=2.5)
    assert result["customer_id"] == "unknown"


def test_request_manual_review_full_args() -> None:
    effects = ToolSideEffects()
    result = request_manual_review(
        call_id="call-999",
        reason="Suspicious activity",
        customer_id="C-2002",
        vendor_id="V-6006",
        amount=1000,
        item="Transaction",
        side_effects=effects,
    )
    assert result["status"] == "manual_review_requested"
    assert result["call_id"] == "call-999"
    assert result["reason"] == "Suspicious activity"
    assert result["customer_id"] == "C-2002"
    assert result["amount"] == 1000
    assert result["item"] == "Transaction"
    assert len(effects.events) == 1


def test_request_manual_review_with_vendor_id_fallback() -> None:
    result = request_manual_review(vendor_id="V-7007")
    assert result["customer_id"] == "V-7007"


def test_request_manual_review_defaults() -> None:
    result = request_manual_review()
    assert result["reason"] == "manual risk review requested"


def test_suspend_account_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="suspend_account must not execute"):
        suspend_account(customer_id="C-1001")


def test_search_knowledge_base_with_query() -> None:
    effects = ToolSideEffects()
    result = search_knowledge_base(query="procurement policy", side_effects=effects)
    assert result["status"] == "ok"
    assert result["query"] == "procurement policy"
    assert "hits" in result
    assert len(effects.events) == 1


def test_search_knowledge_base_with_item_fallback() -> None:
    result = search_knowledge_base(item="vendor guidelines")
    assert result["query"] == "vendor guidelines"


def test_search_knowledge_base_empty_query() -> None:
    result = search_knowledge_base()
    assert result["query"] == ""


def test_escalate_to_human_agent_full_args() -> None:
    effects = ToolSideEffects()
    result = escalate_to_human_agent(
        call_id="call-escalate",
        reason="Complex inquiry",
        query="What is the refund policy?",
        item="Refund question",
        side_effects=effects,
    )
    assert result["status"] == "escalated_to_human"
    assert result["call_id"] == "call-escalate"
    assert result["reason"] == "Complex inquiry"
    assert result["query"] == "What is the refund policy?"
    assert len(effects.events) == 1


def test_escalate_to_human_agent_with_item_fallback() -> None:
    result = escalate_to_human_agent(item="Help needed")
    assert result["query"] == "Help needed"


def test_escalate_to_human_agent_defaults() -> None:
    result = escalate_to_human_agent()
    assert result["reason"] == "human agent requested"
    assert result["query"] is None


def test_delete_knowledge_document_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="delete_knowledge_document must not execute"):
        delete_knowledge_document(doc_id="doc-123")


def test_tool_side_effects_record() -> None:
    effects = ToolSideEffects()
    event = effects.record("test_tool", arg1="value1", arg2=42)
    assert event["tool_name"] == "test_tool"
    assert event["arg1"] == "value1"
    assert event["arg2"] == 42
    assert len(effects.events) == 1


def test_tool_side_effects_clear() -> None:
    effects = ToolSideEffects()
    effects.record("tool1")
    effects.record("tool2")
    assert len(effects.events) == 2
    effects.clear()
    assert len(effects.events) == 0


def test_execute_bound_tool_with_side_effects() -> None:
    config = load_process("procurement_review")
    effects = ToolSideEffects()
    result = execute_bound_tool(
        config,
        "create_purchase_order",
        {"vendor_id": "V-1001", "amount": 1500},
        side_effects=effects,
    )
    assert result["status"] == "created"
    assert len(effects.events) == 1


def test_execute_bound_tool_filters_unknown_kwargs() -> None:
    """Tools should accept extra kwargs and filter them based on signature."""
    config = load_process("procurement_review")
    result = execute_bound_tool(
        config,
        "create_purchase_order",
        {
            "vendor_id": "V-1001",
            "amount": 1000,
            "item": "Supplies",
            "unknown_param": "should be filtered",
            "another_unknown": 123,
        },
    )
    assert result["status"] == "created"
    assert result["vendor_id"] == "V-1001"


def test_execute_bound_tool_without_side_effects_parameter() -> None:
    """Execute a tool that doesn't have side_effects in its signature."""
    config = load_process("procurement_review")
    effects = ToolSideEffects()
    # This should not crash even though side_effects is passed
    result = execute_bound_tool(
        config,
        "create_purchase_order",
        {"vendor_id": "V-2002", "amount": 500},
        side_effects=effects,
    )
    assert result["status"] == "created"


def test_get_bound_tools_only_returns_allowed() -> None:
    """Verify that get_bound_tools only returns tools in the allow list."""
    config = load_process("procurement_review")
    bound = get_bound_tools(config)
    
    # Should have allowed tools
    assert "create_purchase_order" in bound
    assert "request_approval" in bound
    
    # Should not have disallowed tools
    assert "send_payment" not in bound
    assert "modify_vendor_banking_details" not in bound
    assert "disburse_funds" not in bound
    assert "wire_transfer" not in bound
    assert "suspend_account" not in bound
    assert "delete_knowledge_document" not in bound
