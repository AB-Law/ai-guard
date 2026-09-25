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

An `escalate` decision means a human needs to sign off before the call can run — the wrapped function never executes on its own. `decision["call_id"]` (on `AiGuardEscalated`, or in the dict `evaluate()` returns directly) is what you resolve it with. The tower **never executes anything on your behalf**, escalated or not — resolving an approval only flips the stored decision; you always run your own function afterward, gated on the result, exactly like a normal `allow`.

Three ways to use it, in increasing order of how much you want this SDK to do for you:

**1. Poll it yourself.** `GuardClient.get_approval(call_id)` returns the same shape every time: `{call_id, case_id, process, status, decision, request, source_app, created_at}`, with `status` moving from `"pending_approval"` to `"completed"` or `"rejected"`. Check `decision["decision"]` (`"allow"` or `"block"`) once it's no longer pending.

**2. Block until resolved.** `GuardClient.wait_for_decision(call_id, poll_interval=2.0, timeout=120.0)` polls `get_approval` for you and returns once resolved, or raises `TimeoutError` if the deadline passes first. Fine for a background worker or a CLI script; don't call it from a request handler you can't afford to hang.

**3. Let the decorator block for you.** `@guard(..., on_escalate="wait")` calls `wait_for_decision` internally — approved, it runs your function like nothing happened; rejected, it raises `AiGuardRejected`; timed out, it raises `AiGuardEscalated` (same exception as the default path, just later) instead of a bare `TimeoutError`, so you only ever need to catch the three `aiguard` exceptions:

```python
@aiguard.guard(tool_name="create_purchase_order", on_escalate="wait", wait_timeout=300)
def create_purchase_order(vendor_id: str, amount: float, item: str) -> dict:
    ...  # only runs once a human approves — see below for who resolves it

try:
    create_purchase_order(vendor_id="V-1001", amount=75000, item="Server rack")
except aiguard.AiGuardRejected as exc:
    print("a human said no:", exc.reason)
except aiguard.AiGuardEscalated as exc:
    print("still pending after the timeout:", exc.call_id)
```

**Who actually clicks approve?** Your own app, not the tower's dashboard. Show the pending `call_id` in your own interface (e.g. a chat bot's "waiting for finance sign-off" card), and when your user clicks Approve, call `GuardClient.resolve_approval(call_id, action="approve", actor="alice@yourcompany.com")` directly — that's what makes "human approval inside your own app" real. If something elsewhere is blocked on `wait_for_decision` (or polling `get_approval`), it picks up the change within one `poll_interval`.

The tower's own dashboard **cannot resolve these** — that action is scoped to the originating application's own API key only, so they're deliberately left out of the dashboard's Approval queue (a queue item with Approve/Reject buttons that just 403 when clicked would be worse than not listing it). This is intentional, not a limitation: approval for an SDK-integrated call belongs inside the application that owns the call, where the person approving has the actual context (the row in your spreadsheet, the customer they're talking to) — not a generic dashboard row. (Contrast with cases submitted through `/cases` directly — those genuinely are approved from the dashboard, since the tower owns that flow end to end.) Full visibility is still there via Logs — every retrieval/policy_check/tool_call/approval event for a guard_evaluate case shows up with its case_id, same as any other case — you just act on it from your own app, not the dashboard.

Authorization in full: an application's own API key can `get_approval`/`resolve_approval` only calls it originated (`source_app` must match) — never another application's. A dashboard session token can `get_approval` (view) any call, but `resolve_approval` from a dashboard token is always a 403 for a guard_evaluate call. Either on an unknown `call_id` is a 404; resolving an already-resolved call is a 409.

## Roadmap (not built yet)

- Raw OpenAI SDK interception (`chat.completions.create` wrapping) — LangChain has a first-class `on_tool_start` hook; OpenAI's SDK doesn't, so this needs custom parsing of `tool_calls` out of responses.
