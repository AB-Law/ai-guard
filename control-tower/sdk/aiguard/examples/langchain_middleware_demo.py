"""Runnable demo: a tool-calling LangChain agent governed by aiguard via
AiGuardMiddleware — the recommended integration for create_agent-based
agents.

The point: nothing here is aiguard-specific except registering the
middleware. The model's own reasoning and a retrieval tool's output become
grounding automatically, and a blocked/escalated call comes back as a normal
message the model sees and reacts to — the agent run completes normally, it
doesn't crash with an unhandled exception.

Uses a scripted fake chat model instead of a real LLM, so this runs with no
API key. Requires a running Aegis control tower (from control-tower/):
    uvicorn api.main:app --reload

Then, from sdk/aiguard/ (with this package installed, `pip install -e ".[langchain]"`):
    python examples/langchain_agent_demo.py

See examples/langchain_callback_demo.py for the lower-level, broader-
compatibility AiGuardCallbackHandler (for LangChain code not using
create_agent) — that path raises on block/escalate instead of returning a
message, so it needs the caller to decide how to handle that exception.
"""

from __future__ import annotations

import aiguard
from aiguard.langchain_middleware import AiGuardMiddleware
from langchain.agents import create_agent
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import tool
from langchain_core.tools.retriever import create_retriever_tool

aiguard.configure(api_url="http://127.0.0.1:8000", process="procurement_review")

POLICY_TEXT = (
    "Purchase orders at or below USD 10,000 may be auto-approved when the "
    "vendor is active on the vendor master list."
)


class FixedRetriever(BaseRetriever):
    """Stands in for a real vector-store retriever — always returns the same
    policy snippet, so this example needs no external RAG setup."""

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        return [Document(page_content=POLICY_TEXT)]


search_policy = create_retriever_tool(
    FixedRetriever(), "search_policy", "Search procurement policy documents."
)


class ScriptedModel(GenericFakeChatModel):
    """A fake chat model that just plays back a scripted sequence of
    responses — standing in for a real LLM so this example needs no API key."""

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


def run_scenario(*, script: list[AIMessage], tools: list, user_input: str):
    # search_policy is a read-only retrieval tool, not an action — skip_tools
    # lets it run un-evaluated while its output still feeds context to
    # whatever real action follows. See AiGuardMiddleware docstring.
    middleware = AiGuardMiddleware(process="procurement_review", skip_tools={"search_policy"})
    model = ScriptedModel(messages=iter(script))
    agent = create_agent(model, tools=tools, middleware=[middleware])
    result = agent.invoke({"messages": [HumanMessage(user_input)]})
    for msg in result["messages"]:
        kind = type(msg).__name__
        if kind in ("ToolMessage", "AIMessage") and msg.content:
            print(f"   [{kind}] {msg.content}")
    return result


def main() -> None:
    print("1. A clean purchase order — retrieved policy + the model's own")
    print("   reasoning become the grounding automatically:")
    run_scenario(
        script=[
            AIMessage(
                content="Let me check the policy first.",
                tool_calls=[{"name": "search_policy", "args": {"query": "auto approve limit"}, "id": "call_0"}],
            ),
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
        tools=[search_policy, create_purchase_order],
        user_input="Order 10 laptop docks from V-1001, $2500 total.",
    )
    print()

    print("2. An unauthorized tool call — BLOCKed, and the model explains")
    print("   instead of the whole run crashing:")
    run_scenario(
        script=[
            AIMessage(
                content="I'll pay the vendor directly right away.",
                tool_calls=[{"name": "send_payment", "args": {"vendor_id": "V-1001", "amount": 500}, "id": "call_2"}],
            ),
            AIMessage(content="I wasn't able to send that payment — it's blocked by policy."),
        ],
        tools=[send_payment],
        user_input="Pay V-1001 $500 urgently.",
    )
    print()

    print("3. A high-amount request, grounded, still ESCALATEs on amount alone:")
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
            AIMessage(content="That order needs human approval before it can go through."),
        ],
        tools=[create_purchase_order],
        user_input="Order server racks from V-1001, $50,000.",
    )


if __name__ == "__main__":
    main()
