# aiguard

Drop-in client for the [Aegis control tower](../../README.md). Evaluate a tool call against your policy *before* it runs — from a plain Python function or a LangChain agent — without dragging in the tower's own stack (no chromadb/langgraph/fastapi dependency here, just `httpx`).

This is an **additional** integration surface, not a replacement for the tower's config-driven process YAMLs — the YAML still defines the policy (allowed tools, thresholds, evidence rules); this package just gives you a second way to submit calls for evaluation against it, for when you already have your own agent and don't want to restructure it around the tower's case/process model.

## Install

From this directory:

```bash
pip install -e .              # plain Python / decorator usage
pip install -e ".[langchain]" # + the LangChain callback handler
```

## Setup

Point it at a running Aegis tower (self-hosted by default — `http://127.0.0.1:8000`; swap for your own hosted instance the same way):

```python
import aiguard
aiguard.configure(api_url="http://127.0.0.1:8000", process="procurement_review")
```

## Plain Python

```python
import aiguard

@aiguard.guard(tool_name="create_purchase_order")
def create_purchase_order(vendor_id: str, amount: float, item: str) -> dict:
    ...  # your real implementation — only runs if the tower allows it

try:
    create_purchase_order(vendor_id="V-1001", amount=2500, item="Laptop docks x10")
except aiguard.AiGuardBlocked as exc:
    print(exc.reason)       # tower's reason
except aiguard.AiGuardEscalated as exc:
    print(exc.call_id)      # needs a human — see "Escalation" below
```

`rationale=` and `context=` (static values or callables receiving your function's call args) let you tell the tower *why* the call is justified — without either, groundedness scoring has nothing to check against and calls tend to escalate even when they're clean:

```python
@aiguard.guard(
    rationale=lambda vendor_id, amount, **_: f"{vendor_id} is active, {amount} is under threshold",
    context=lambda **_: [POLICY_TEXT],
)
def create_purchase_order(vendor_id, amount, item): ...
```

**Limitation:** only keyword arguments are sent to the tower as `tool_args` (positional args still reach your function fine, just aren't included in what the tower evaluates) — call guarded functions with kwargs.

## LangChain — `create_agent` (recommended)

```python
from aiguard.langchain_middleware import AiGuardMiddleware
from langchain.agents import create_agent

agent = create_agent(
    model, tools=[...],
    middleware=[AiGuardMiddleware(process="procurement_review")],
)
result = agent.invoke({"messages": [...]})
```

Every tool call the agent proposes is evaluated before it runs. The key property: **a `block`/`escalate` decision comes back as a normal `ToolMessage` (`status="error"`) that the model sees on its next turn and can react to** — apologize to the user, try something else — instead of an unhandled exception that kills the whole `agent.invoke()` call. Either way the real tool function never runs; only how the "no" is communicated differs. This is the integration to reach for if you want blocked calls to just work without the caller having to handle an exception themselves.

**Grounding is automatic, not supplied by you**, and precise per call (no cross-call buffering, unlike the callback handler below): `wrap_tool_call` sees the actual conversation state for *this* tool call, so the most recent `AIMessage`'s content becomes the rationale, and recent `ToolMessage` contents (prior tool results — including retrieval output) become context. Nothing to restate, nothing to keep in sync with your policy docs. If the model produced no reasoning and nothing was retrieved, there's genuinely nothing to ground the call in, and the tower correctly scores it as unsupported — that's the tower refusing to trust a self-reported rationale it can't check against anything, not a bug.

If you wire retrieval as a **tool the model itself calls** (e.g. via `langchain_core.tools.retriever.create_retriever_tool`), that call also goes through this same wrapper — pass its name in `skip_tools={"search_policy"}` so it runs un-evaluated (it's read-only, not an action to gate) while its output still becomes context for whatever real action follows. See `examples/langchain_middleware_demo.py` for a full runnable example (no LLM key needed — uses a scripted fake model).

## LangChain — callback handler (broader compatibility)

For LangChain code not built on `create_agent` (raw `tool.run()` calls, older agent code):

```python
from aiguard.langchain_handler import AiGuardCallbackHandler

handler = AiGuardCallbackHandler(process="procurement_review")
agent.invoke({"messages": [...]}, config={"callbacks": [handler]})
```

Same automatic grounding, via `on_llm_end`/`on_retriever_end` instead — but **`block`/`escalate` raise** (`AiGuardBlocked`/`AiGuardEscalated`) rather than becoming a message the model can react to; catch them yourself, or configure `langgraph.prebuilt.ToolNode(handle_tool_errors=...)` if you're building the graph directly. `raise_error = True` is set for you (LangChain otherwise silently swallows exceptions raised inside callbacks, which would make a `block` a no-op).

Because it buffers rationale/context across separate callback calls (no single "current state" object to read, unlike the middleware above), **construct a fresh handler per agent run** — don't share one instance across concurrent invocations, or one run's reasoning can leak into another's evaluation. Retrieval-as-a-tool has the same evaluation problem as above, with no `skip_tools` escape hatch here — call the retriever directly instead (`retriever.invoke(query, config={"callbacks": [handler]})`, not through the agent's tool loop). See `examples/langchain_callback_demo.py`.

## Escalation

`AiGuardEscalated` carries `decision["call_id"]` — the id a human approver would use against the tower's own `/approvals/{call_id}` endpoint. Resuming *your* code after that approval (vs. the tower's own case/HITL flow) is intentionally out of scope for this version — treat escalation as "stop and hand off," not "block until approved."

## Roadmap (not built yet)

- Raw OpenAI SDK interception (`chat.completions.create` wrapping) — LangChain has a first-class `on_tool_start` hook; OpenAI's SDK doesn't, so this needs custom parsing of `tool_calls` out of responses.
