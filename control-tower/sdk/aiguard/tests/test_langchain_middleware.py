"""Tests for AiGuardMiddleware — skipped if langchain (>=1.0) isn't installed."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("langchain.agents.middleware")

from aiguard.langchain_middleware import AiGuardMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool


def _client_returning(decision: str, **extra) -> MagicMock:
    client = MagicMock()
    client.evaluate.return_value = {
        "call_id": "c1",
        "decision": decision,
        "reason": "because",
        **extra,
    }
    return client


@tool
def create_purchase_order(vendor_id: str, amount: float) -> dict:
    """Creates a purchase order."""
    return {"status": "created", "vendor_id": vendor_id, "amount": amount}


def _request(*, messages: list, tool_call: dict):
    from types import SimpleNamespace

    return SimpleNamespace(
        tool_call=tool_call,
        tool=create_purchase_order,
        state={"messages": messages},
        runtime=None,
    )


def test_allow_calls_the_real_handler() -> None:
    client = _client_returning("allow")
    middleware = AiGuardMiddleware(client=client)
    handler = MagicMock(return_value="real result")
    request = _request(
        messages=[HumanMessage("hi")],
        tool_call={"name": "create_purchase_order", "args": {"vendor_id": "V-1001"}, "id": "t1"},
    )

    result = middleware.wrap_tool_call(request, handler)

    assert result == "real result"
    handler.assert_called_once_with(request)


def test_block_returns_a_tool_message_instead_of_raising() -> None:
    client = _client_returning("block")
    middleware = AiGuardMiddleware(client=client)
    handler = MagicMock()
    request = _request(
        messages=[HumanMessage("hi")],
        tool_call={"name": "send_payment", "args": {}, "id": "t1"},
    )

    result = middleware.wrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.tool_call_id == "t1"
    assert "send_payment" in result.content
    assert "was blocked by policy" in result.content  # not "blockd"
    assert "because" in result.content
    handler.assert_not_called()  # the real tool never runs


def test_escalate_also_returns_a_tool_message_not_an_exception() -> None:
    client = _client_returning("escalate")
    middleware = AiGuardMiddleware(client=client)
    request = _request(
        messages=[HumanMessage("hi")],
        tool_call={"name": "create_purchase_order", "args": {}, "id": "t1"},
    )

    result = middleware.wrap_tool_call(request, MagicMock())

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "was escalated by policy" in result.content


def test_decision_is_attached_for_programmatic_inspection() -> None:
    client = _client_returning("block", risk_score=100)
    middleware = AiGuardMiddleware(client=client)
    request = _request(
        messages=[],
        tool_call={"name": "send_payment", "args": {}, "id": "t1"},
    )

    result = middleware.wrap_tool_call(request, MagicMock())

    assert result.additional_kwargs["aiguard_decision"]["risk_score"] == 100


def test_rationale_is_the_most_recent_ai_message_no_buffering_needed() -> None:
    client = _client_returning("allow")
    middleware = AiGuardMiddleware(client=client)
    request = _request(
        messages=[
            HumanMessage("buy stuff"),
            AIMessage(content="Vendor is active, amount is fine, approving."),
        ],
        tool_call={"name": "create_purchase_order", "args": {"vendor_id": "V-1001"}, "id": "t1"},
    )

    middleware.wrap_tool_call(request, MagicMock(return_value="ok"))

    kwargs = client.evaluate.call_args.kwargs
    assert kwargs["agent_rationale"] == "Vendor is active, amount is fine, approving."


def test_context_comes_from_recent_tool_messages() -> None:
    client = _client_returning("allow")
    middleware = AiGuardMiddleware(client=client)
    request = _request(
        messages=[
            HumanMessage("buy stuff"),
            ToolMessage(content="Policy: auto-approve under $10,000.", tool_call_id="prev"),
            AIMessage(content="Approving based on policy."),
        ],
        tool_call={"name": "create_purchase_order", "args": {}, "id": "t1"},
    )

    middleware.wrap_tool_call(request, MagicMock(return_value="ok"))

    kwargs = client.evaluate.call_args.kwargs
    assert kwargs["context_texts"] == ["Policy: auto-approve under $10,000."]


def test_context_limit_caps_how_many_prior_tool_messages_are_sent() -> None:
    client = _client_returning("allow")
    middleware = AiGuardMiddleware(client=client, context_limit=2)
    tool_msgs = [ToolMessage(content=f"fact {i}", tool_call_id=f"t{i}") for i in range(5)]
    request = _request(
        messages=[HumanMessage("hi"), *tool_msgs],
        tool_call={"name": "create_purchase_order", "args": {}, "id": "t1"},
    )

    middleware.wrap_tool_call(request, MagicMock(return_value="ok"))

    kwargs = client.evaluate.call_args.kwargs
    assert kwargs["context_texts"] == ["fact 3", "fact 4"]


def test_skip_tools_runs_the_tool_without_evaluating_it() -> None:
    client = _client_returning("block")  # would block if evaluated
    middleware = AiGuardMiddleware(client=client, skip_tools={"search_policy"})
    handler = MagicMock(return_value="retrieved docs")
    request = _request(
        messages=[],
        tool_call={"name": "search_policy", "args": {"query": "limit"}, "id": "t1"},
    )

    result = middleware.wrap_tool_call(request, handler)

    assert result == "retrieved docs"
    handler.assert_called_once_with(request)
    client.evaluate.assert_not_called()


def test_tools_not_in_skip_list_are_still_evaluated() -> None:
    client = _client_returning("allow")
    middleware = AiGuardMiddleware(client=client, skip_tools={"search_policy"})
    request = _request(
        messages=[],
        tool_call={"name": "create_purchase_order", "args": {}, "id": "t1"},
    )

    middleware.wrap_tool_call(request, MagicMock(return_value="ok"))

    client.evaluate.assert_called_once()


def test_full_agent_run_block_lets_the_model_respond_instead_of_crashing() -> None:
    """End-to-end: blocked call becomes a message the model can react to —
    the run completes normally, it doesn't raise."""
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class ToolCapableFakeChatModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    @tool
    def send_payment(vendor_id: str, amount: float) -> dict:
        """Sends a payment."""
        return {"sent": True}

    tool_call_msg = AIMessage(
        content="Paying now.",
        tool_calls=[{"name": "send_payment", "args": {"vendor_id": "V-1001", "amount": 500}, "id": "c1"}],
    )
    final_msg = AIMessage(content="I could not complete that payment — it was blocked by policy.")

    model = ToolCapableFakeChatModel(messages=iter([tool_call_msg, final_msg]))
    client = _client_returning("block")
    agent = create_agent(model, tools=[send_payment], middleware=[AiGuardMiddleware(client=client)])

    result = agent.invoke({"messages": [HumanMessage("pay V-1001 $500")]})

    kinds = [type(m).__name__ for m in result["messages"]]
    assert "ToolMessage" in kinds
    assert kinds[-1] == "AIMessage"
    assert "blocked" in result["messages"][-1].content.lower()
