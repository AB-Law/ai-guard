"""LangChain 1.x `create_agent` middleware — the recommended integration for
create_agent-based agents (the callback handler in langchain_handler.py
covers older/callback-based LangChain code instead).

Needs langchain>=1.0 + langchain-core (``pip install aiguard[langchain]``);
imported lazily so the base aiguard package never requires LangChain.
"""

from __future__ import annotations

from typing import Any

from ._langchain_text import extract_text
from .client import GuardClient, default_client

try:
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.messages import ToolMessage
except ImportError as exc:  # pragma: no cover — exercised by the missing-dep test
    raise ImportError(
        "AiGuardMiddleware needs langchain>=1.0 and langchain-core: pip install aiguard[langchain]"
    ) from exc


def _last_ai_content(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if type(msg).__name__ == "AIMessage":
            content = getattr(msg, "content", None)
            if content:
                return extract_text(content)
    return ""


_PAST_TENSE = {"block": "blocked", "escalate": "escalated"}


def _recent_tool_contents(messages: list[Any], *, limit: int) -> list[str]:
    out: list[str] = []
    for msg in reversed(messages):
        if type(msg).__name__ == "ToolMessage":
            content = getattr(msg, "content", None)
            if content:
                out.append(extract_text(content))
        if len(out) >= limit:
            break
    out.reverse()
    return out


class AiGuardMiddleware(AgentMiddleware):
    """create_agent(model, tools=[...], middleware=[AiGuardMiddleware(process=...)])

    Preferred over AiGuardCallbackHandler for create_agent-based agents: a
    ``block``/``escalate`` decision here comes back as a normal ``ToolMessage``
    (``status="error"``) that the model sees on its next turn and can react
    to — explain to the user, try a different approach — instead of an
    unhandled exception that kills the whole ``agent.invoke()`` call. Either
    way the real tool function never runs; only how the "no" is communicated
    differs.

    Grounding is automatic and precise, not buffered across calls like the
    callback handler needs to: ``wrap_tool_call`` gets the actual
    conversation state for *this* run, so the most recent AIMessage's
    content is used as rationale, and recent ToolMessage contents (prior
    tool results — including retrieval output, if a retriever ran as a
    tool) as context. No aiguard-specific code needed in the agent, and no
    "construct a fresh instance per run" caveat — state is passed in fresh
    on every call, this middleware instance holds nothing itself.

    ``skip_tools`` — this wraps *every* tool call the agent makes, including
    a retriever wired up as a tool (e.g. via
    ``langchain_core.tools.retriever.create_retriever_tool``). A read-only
    lookup/retrieval tool usually isn't something your process config lists
    in ``allowed_tools`` (it has no side effect to govern), which would
    otherwise get it blocked outright before it can ever run and produce the
    context a later, real action needs. List such tool names here to run
    them un-evaluated — their ToolMessage output still becomes context for
    whatever's evaluated next, same as any other prior tool result.
    """

    def __init__(
        self,
        *,
        api_url: str | None = None,
        process: str | None = None,
        client: GuardClient | None = None,
        context_limit: int = 5,
        skip_tools: frozenset[str] | set[str] = frozenset(),
    ) -> None:
        super().__init__()
        self._client = client or (GuardClient(api_url=api_url) if api_url else default_client())
        self._process = process
        self._context_limit = context_limit
        self._skip_tools = frozenset(skip_tools)

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        state = request.state if isinstance(request.state, dict) else {}
        messages = list(state.get("messages") or [])
        tool_name = request.tool_call["name"]

        if tool_name in self._skip_tools:
            return handler(request)

        decision = self._client.evaluate(
            tool_name=tool_name,
            tool_args=dict(request.tool_call.get("args") or {}),
            agent_rationale=_last_ai_content(messages),
            context_texts=_recent_tool_contents(messages, limit=self._context_limit),
            process=self._process,
            call_id=request.tool_call.get("id"),
        )

        if decision["decision"] in ("block", "escalate"):
            return ToolMessage(
                content=(
                    f"Tool call {tool_name!r} was "
                    f"{_PAST_TENSE.get(decision['decision'], decision['decision'])} by policy: "
                    f"{decision.get('reason', '')}"
                ),
                tool_call_id=request.tool_call["id"],
                status="error",
                additional_kwargs={"aiguard_decision": decision},
            )
        return handler(request)


__all__ = ["AiGuardMiddleware"]
