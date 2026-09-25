"""Unit tests for @guard — mocks GuardClient.evaluate so these run with no server."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from aiguard import AiGuardBlocked, AiGuardEscalated, AiGuardRejected, guard


def _client_returning(decision: str, **extra) -> MagicMock:
    client = MagicMock()
    client.evaluate.return_value = {
        "call_id": "c1",
        "decision": decision,
        "reason": "because",
        "policy_refs": [],
        **extra,
    }
    return client


def test_allow_runs_the_wrapped_function() -> None:
    client = _client_returning("allow")

    @guard(tool_name="create_purchase_order", client=client)
    def create_purchase_order(vendor_id: str, amount: float) -> dict:
        return {"status": "created", "vendor_id": vendor_id, "amount": amount}

    result = create_purchase_order(vendor_id="V-1001", amount=2500)
    assert result == {"status": "created", "vendor_id": "V-1001", "amount": 2500}
    client.evaluate.assert_called_once()
    assert client.evaluate.call_args.kwargs["tool_name"] == "create_purchase_order"


def test_block_raises_and_never_calls_the_wrapped_function() -> None:
    client = _client_returning("block")
    called = False

    @guard(client=client)
    def send_payment(vendor_id: str, amount: float) -> dict:
        nonlocal called
        called = True
        return {}

    with pytest.raises(AiGuardBlocked):
        send_payment(vendor_id="V-1001", amount=500)
    assert called is False


def test_escalate_raises_and_never_calls_the_wrapped_function() -> None:
    client = _client_returning("escalate")
    called = False

    @guard(client=client)
    def create_purchase_order(amount: float) -> dict:
        nonlocal called
        called = True
        return {}

    with pytest.raises(AiGuardEscalated) as exc_info:
        create_purchase_order(amount=50000)
    assert called is False
    assert exc_info.value.call_id == "c1"


def test_tool_name_defaults_to_function_name() -> None:
    client = _client_returning("allow")

    @guard(client=client)
    def my_custom_tool() -> None:
        return None

    my_custom_tool()
    assert client.evaluate.call_args.kwargs["tool_name"] == "my_custom_tool"


def test_rationale_and_context_callables_receive_call_args() -> None:
    client = _client_returning("allow")

    @guard(
        client=client,
        rationale=lambda vendor_id, amount: f"vendor {vendor_id} amount {amount}",
        context=lambda vendor_id, amount: [f"policy for {vendor_id}"],
    )
    def create_purchase_order(vendor_id: str, amount: float) -> None:
        return None

    create_purchase_order(vendor_id="V-1001", amount=100)
    kwargs = client.evaluate.call_args.kwargs
    assert kwargs["agent_rationale"] == "vendor V-1001 amount 100"
    assert kwargs["context_texts"] == ["policy for V-1001"]


def test_only_kwargs_are_sent_as_tool_args() -> None:
    """Documented limitation: positional args reach the wrapped function fine
    but aren't captured in tool_args sent to the tower — call with kwargs."""
    client = _client_returning("allow")

    @guard(client=client)
    def my_tool(a, b) -> int:
        return a + b

    result = my_tool(1, 2)
    assert result == 3
    assert client.evaluate.call_args.kwargs["tool_args"] == {}


def test_on_escalate_raise_is_the_default_and_never_polls() -> None:
    client = _client_returning("escalate")

    @guard(client=client)
    def create_purchase_order(amount: float) -> dict:
        return {}

    with pytest.raises(AiGuardEscalated):
        create_purchase_order(amount=50000)
    client.wait_for_decision.assert_not_called()


def test_on_escalate_wait_runs_the_wrapped_function_once_approved() -> None:
    client = _client_returning("escalate")
    client.wait_for_decision.return_value = {
        "status": "completed",
        "decision": {"decision": "allow", "call_id": "c1", "reason": "human approved"},
    }
    called_with = {}

    @guard(client=client, on_escalate="wait", wait_poll_interval=0.01, wait_timeout=1.0)
    def create_purchase_order(vendor_id: str, amount: float) -> dict:
        called_with["vendor_id"] = vendor_id
        return {"status": "created"}

    result = create_purchase_order(vendor_id="V-1001", amount=50000)
    assert result == {"status": "created"}
    assert called_with == {"vendor_id": "V-1001"}
    client.wait_for_decision.assert_called_once()
    assert client.wait_for_decision.call_args.args[0] == "c1"
    assert client.wait_for_decision.call_args.kwargs["poll_interval"] == 0.01
    assert client.wait_for_decision.call_args.kwargs["timeout"] == 1.0


def test_on_escalate_wait_raises_rejected_and_never_runs_the_function() -> None:
    client = _client_returning("escalate")
    client.wait_for_decision.return_value = {
        "status": "rejected",
        "decision": {"decision": "block", "call_id": "c1", "reason": "human rejected"},
    }
    called = False

    @guard(client=client, on_escalate="wait")
    def create_purchase_order(amount: float) -> dict:
        nonlocal called
        called = True
        return {}

    with pytest.raises(AiGuardRejected):
        create_purchase_order(amount=50000)
    assert called is False


def test_on_escalate_wait_raises_escalated_not_timeouterror_on_timeout() -> None:
    """A caller catching AiGuardEscalated (the "raise" default's exception)
    must also catch the "wait" mode's timeout case — no separate exception
    type for callers to remember."""
    client = _client_returning("escalate")
    client.wait_for_decision.side_effect = TimeoutError("still pending")
    called = False

    @guard(client=client, on_escalate="wait")
    def create_purchase_order(amount: float) -> dict:
        nonlocal called
        called = True
        return {}

    with pytest.raises(AiGuardEscalated) as exc_info:
        create_purchase_order(amount=50000)
    assert called is False
    assert exc_info.value.call_id == "c1"
