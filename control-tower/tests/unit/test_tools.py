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


def test_execute_bound_rejects_unbound() -> None:
    config = load_process("procurement_review")
    with pytest.raises(PermissionError):
        execute_bound_tool(config, "send_payment", {"amount": 1})
