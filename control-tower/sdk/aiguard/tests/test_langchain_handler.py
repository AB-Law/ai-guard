"""Tests for AiGuardCallbackHandler — skipped if langchain-core isn't
installed (it's an optional dep: pip install aiguard[langchain])."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("langchain_core")

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

from aiguard import AiGuardBlocked, AiGuardEscalated  # noqa: E402
from aiguard.langchain_handler import AiGuardCallbackHandler  # noqa: E402


def _handler_returning(decision: str) -> tuple[AiGuardCallbackHandler, MagicMock]:
    client = MagicMock()
    client.evaluate.return_value = {
        "call_id": "run-1",
        "decision": decision,
        "reason": "because",
    }
    return AiGuardCallbackHandler(client=client), client


def _llm_result(content: str) -> SimpleNamespace:
    """Minimal stand-in for langchain_core.outputs.LLMResult — only
    .generations[0][0].message is read by on_llm_end."""
    message = SimpleNamespace(content=content)
    return SimpleNamespace(generations=[[SimpleNamespace(message=message)]])


@tool
def create_purchase_order(vendor_id: str, amount: float) -> dict:
    """Creates a purchase order."""
    return {"status": "created", "vendor_id": vendor_id, "amount": amount}


def test_allow_lets_the_tool_run() -> None:
    handler, client = _handler_returning("allow")
    result = create_purchase_order.run({"vendor_id": "V-1001", "amount": 2500}, callbacks=[handler])
    assert result == {"status": "created", "vendor_id": "V-1001", "amount": 2500}
    client.evaluate.assert_called_once()
    assert client.evaluate.call_args.kwargs["tool_name"] == "create_purchase_order"


def test_block_prevents_the_tool_from_running() -> None:
    handler, _ = _handler_returning("block")
    with pytest.raises(AiGuardBlocked):
        create_purchase_order.run({"vendor_id": "V-1001", "amount": 2500}, callbacks=[handler])


def test_escalate_prevents_the_tool_from_running() -> None:
    handler, _ = _handler_returning("escalate")
    with pytest.raises(AiGuardEscalated):
        create_purchase_order.run({"vendor_id": "V-1001", "amount": 50000}, callbacks=[handler])


def test_raise_error_is_set_so_langchain_does_not_swallow_the_block() -> None:
    handler, _ = _handler_returning("block")
    assert handler.raise_error is True


def test_no_llm_end_yet_falls_back_to_generic_rationale_and_empty_context() -> None:
    handler, client = _handler_returning("allow")
    create_purchase_order.run({"vendor_id": "V-1001", "amount": 2500}, callbacks=[handler])
    kwargs = client.evaluate.call_args.kwargs
    assert "create_purchase_order" in kwargs["agent_rationale"]
    assert kwargs["context_texts"] == []


def test_rationale_is_captured_from_llm_end_with_no_caller_action() -> None:
    """The core fix: the model's own reasoning is picked up automatically —
    nothing has to be manually passed in for grounding to work."""
    handler, client = _handler_returning("allow")
    handler.on_llm_end(
        _llm_result("Vendor V-1001 is active and the amount is under the threshold."),
        run_id="r1",
    )
    create_purchase_order.run({"vendor_id": "V-1001", "amount": 2500}, callbacks=[handler])
    kwargs = client.evaluate.call_args.kwargs
    assert kwargs["agent_rationale"] == "Vendor V-1001 is active and the amount is under the threshold."


def test_context_is_captured_from_retriever_end_with_no_caller_action() -> None:
    handler, client = _handler_returning("allow")
    docs = [
        SimpleNamespace(page_content="Policy: auto-approve under $10,000."),
        SimpleNamespace(page_content="Vendor V-1001 is active."),
    ]
    handler.on_retriever_end(docs, run_id="r1")
    create_purchase_order.run({"vendor_id": "V-1001", "amount": 2500}, callbacks=[handler])
    kwargs = client.evaluate.call_args.kwargs
    assert kwargs["context_texts"] == [
        "Policy: auto-approve under $10,000.",
        "Vendor V-1001 is active.",
    ]


def test_rationale_buffer_reflects_the_most_recent_llm_turn() -> None:
    handler, client = _handler_returning("allow")
    handler.on_llm_end(_llm_result("first turn reasoning"), run_id="r1")
    handler.on_llm_end(_llm_result("second turn reasoning"), run_id="r2")
    create_purchase_order.run({"vendor_id": "V-1001", "amount": 2500}, callbacks=[handler])
    assert client.evaluate.call_args.kwargs["agent_rationale"] == "second turn reasoning"


def test_llm_end_with_empty_content_does_not_clear_the_buffer() -> None:
    """A tool-calling turn often has empty .content (just tool_calls) — that
    shouldn't wipe out reasoning text a previous turn already produced."""
    handler, client = _handler_returning("allow")
    handler.on_llm_end(_llm_result("real reasoning"), run_id="r1")
    handler.on_llm_end(_llm_result(""), run_id="r2")
    create_purchase_order.run({"vendor_id": "V-1001", "amount": 2500}, callbacks=[handler])
    assert client.evaluate.call_args.kwargs["agent_rationale"] == "real reasoning"


def test_malformed_llm_response_is_ignored_not_raised() -> None:
    handler, client = _handler_returning("allow")
    handler.on_llm_end(SimpleNamespace(generations=[]), run_id="r1")  # no message inside
    create_purchase_order.run({"vendor_id": "V-1001", "amount": 2500}, callbacks=[handler])
    kwargs = client.evaluate.call_args.kwargs
    assert "create_purchase_order" in kwargs["agent_rationale"]  # fell back cleanly


def test_full_agent_run_captures_real_reasoning_with_zero_extra_code() -> None:
    """End-to-end: a tool-calling agent's own stated reasoning becomes the
    rationale the tower evaluates against, with no aiguard-specific code in
    the agent at all beyond registering the callback handler."""
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class ToolCapableFakeChatModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    tool_call_msg = AIMessage(
        content="Vendor V-1001 is active and the amount is under the USD 10,000 "
        "auto-approve threshold, so I will create the purchase order.",
        tool_calls=[
            {
                "name": "create_purchase_order",
                "args": {"vendor_id": "V-1001", "amount": 2500},
                "id": "call_1",
            }
        ],
    )
    final_msg = AIMessage(content="Done, purchase order created.")

    model = ToolCapableFakeChatModel(messages=iter([tool_call_msg, final_msg]))
    agent = create_agent(model, tools=[create_purchase_order])

    handler, client = _handler_returning("allow")
    agent.invoke(
        {"messages": [HumanMessage("buy laptop docks for V-1001")]},
        config={"callbacks": [handler]},
    )

    kwargs = client.evaluate.call_args.kwargs
    assert kwargs["agent_rationale"] == (
        "Vendor V-1001 is active and the amount is under the USD 10,000 "
        "auto-approve threshold, so I will create the purchase order."
    )
    assert kwargs["tool_name"] == "create_purchase_order"
