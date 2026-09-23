"""Runnable demo: AiGuardCallbackHandler — the lower-level, broader-
compatibility integration for LangChain code that isn't using
langchain.agents.create_agent (raw tool.run() calls, older agent code, etc).

Prefer AiGuardMiddleware + create_agent (examples/langchain_middleware_demo.py)
when you can: a block/escalate there comes back as a normal message the
model can react to. Here, block/escalate RAISE (AiGuardBlocked/
AiGuardEscalated) — LangChain's default tool-error handling does not catch
these for you, so an uncaught one will end the run. Catch it yourself (as
this demo does) or configure LangGraph's ToolNode(handle_tool_errors=...) if
you're building a graph directly.

Uses a scripted fake chat model instead of a real LLM, so this runs with no
API key. Requires a running Aegis control tower (from control-tower/):
    uvicorn api.main:app --reload

Then, from sdk/aiguard/ (with this package installed, `pip install -e ".[langchain]"`):
    python examples/langchain_callback_demo.py
"""

from __future__ import annotations

import aiguard
from aiguard.langchain_handler import AiGuardCallbackHandler
from langchain.agents import create_agent
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool

aiguard.configure(api_url="http://127.0.0.1:8000", process="procurement_review")

POLICY_TEXT = (
    "Purchase orders at or below USD 10,000 may be auto-approved when the "
    "vendor is active on the vendor master list."
)


class FixedRetriever(BaseRetriever):
    """Stands in for a real vector-store retriever."""

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        return [Document(page_content=POLICY_TEXT)]


class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@tool
def create_purchase_order(vendor_id: str, amount: float, item: str) -> dict:
    """Creates a purchase order — a real allowed tool for this process."""
    print(f"  -> actually executed: PO for {item} (${amount}) to {vendor_id}")
    return {"status": "created", "po_id": f"PO-{vendor_id}-{int(amount)}"}


@tool
def send_payment(vendor_id: str, amount: float) -> dict:
    """Sends a payment directly — NOT on this process's allow-list."""
    print("  -> actually executed: payment sent (this should never print)")
    return {"sent": True}


def run_scenario(*, script: list[AIMessage], tools: list, user_input: str, retrieve: bool = False):
    """Fresh model + fresh agent + fresh handler per scenario — the handler
    buffers reasoning/context across callbacks, so it must not be reused
    across runs (see AiGuardCallbackHandler docstring)."""
    handler = AiGuardCallbackHandler(process="procurement_review")
    if retrieve:
        # Retrieval called directly, not as an agent-visible tool — a
        # retriever wired via create_retriever_tool would also hit
        # on_tool_start and get gateway-evaluated like any other action.
        FixedRetriever().invoke(user_input, config={"callbacks": [handler]})

    model = ScriptedModel(messages=iter(script))
    agent = create_agent(model, tools=tools)
    return agent.invoke(
        {"messages": [HumanMessage(user_input)]}, config={"callbacks": [handler]}
    )


def main() -> None:
    print("1. A clean, grounded purchase order (should ALLOW and execute):")
    run_scenario(
        script=[
            AIMessage(
                content=f"{POLICY_TEXT} V-1001 is active and 2500 is under that threshold.",
                tool_calls=[
                    {
                        "name": "create_purchase_order",
                        "args": {"vendor_id": "V-1001", "amount": 2500, "item": "Laptop docks x10"},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="Done, purchase order created."),
        ],
        tools=[create_purchase_order],
        user_input="Order 10 laptop docks from V-1001, $2500 total.",
        retrieve=True,
    )
    print()

    print("2. An unauthorized tool call — raises AiGuardBlocked, caller must catch it:")
    try:
        run_scenario(
            script=[
                AIMessage(
                    content="I'll pay the vendor directly right away.",
                    tool_calls=[
                        {"name": "send_payment", "args": {"vendor_id": "V-1001", "amount": 500}, "id": "call_2"}
                    ],
                ),
            ],
            tools=[send_payment],
            user_input="Pay V-1001 $500 urgently.",
        )
    except aiguard.AiGuardBlocked as exc:
        print(f"   blocked: {exc.reason} (caught outside the agent run, not inside it)\n")

    print("3. A high-amount request, grounded, still raises AiGuardEscalated:")
    try:
        run_scenario(
            script=[
                AIMessage(
                    content=f"{POLICY_TEXT} V-1001 is active, but $50,000 exceeds that threshold.",
                    tool_calls=[
                        {
                            "name": "create_purchase_order",
                            "args": {"vendor_id": "V-1001", "amount": 50000, "item": "Server racks"},
                            "id": "call_3",
                        }
                    ],
                ),
            ],
            tools=[create_purchase_order],
            user_input="Order server racks from V-1001, $50,000.",
            retrieve=True,
        )
    except aiguard.AiGuardEscalated as exc:
        print(f"   escalated: {exc.reason} (call_id={exc.call_id})")


if __name__ == "__main__":
    main()
