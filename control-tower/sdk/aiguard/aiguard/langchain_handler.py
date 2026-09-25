"""LangChain integration — drop into any agent's callbacks list and every
tool call it proposes gets evaluated by the control tower first, with the
agent's own reasoning used as grounding automatically.

Needs langchain-core (``pip install aiguard[langchain]``); imported lazily
here so the base aiguard package (client + @guard decorator) never requires
LangChain for callers who aren't using it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ._langchain_text import extract_text
from .client import GuardClient, default_client
from .exceptions import AiGuardBlocked, AiGuardEscalated

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError as exc:  # pragma: no cover — exercised by the missing-dep test
    raise ImportError(
        "AiGuardCallbackHandler needs langchain-core: pip install aiguard[langchain]"
    ) from exc


class AiGuardCallbackHandler(BaseCallbackHandler):
    """agent.invoke(..., config={"callbacks": [AiGuardCallbackHandler(...)]})

    ``raise_error = True`` is required here, not decorative: LangChain's
    default callback manager swallows exceptions raised inside handler
    methods (logs a warning, keeps going) unless a handler opts in via this
    attribute — without it, a ``block`` decision would be silently ignored
    and the tool would run anyway.

    Grounding (the "why" the tower's evidence/groundedness check needs) is
    captured automatically, not supplied by the caller:

    - ``on_llm_end`` sees the model's own AIMessage — including whatever
      reasoning text (``.content``) it produced alongside a tool call — and
      buffers it as the rationale for the tool call(s) that follow.
    - ``on_retriever_end`` sees whatever documents a retriever step returned
      and buffers their text as context, the same way.

    Both buffers hold "most recent value" — correct for the standard
    single-agent-loop shape (LLM turn -> the tool calls it proposed -> next
    LLM turn), because LangGraph's run ids don't give a clean parent/child
    link between an LLM call and the tool calls it triggered to correlate
    more precisely. This means the handler carries state across callback
    invocations: **construct a fresh instance per agent run**, don't share
    one handler across concurrent invocations, or one run's buffered
    reasoning can leak into another's tool-call evaluation.
    """

    raise_error = True

    def __init__(
        self,
        *,
        api_url: str | None = None,
        process: str | None = None,
        client: GuardClient | None = None,
    ) -> None:
        super().__init__()
        self._client = client or (GuardClient(api_url=api_url) if api_url else default_client())
        self._process = process
        self._last_rationale: str = ""
        self._last_context: list[str] = []

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            message = response.generations[0][0].message
        except (AttributeError, IndexError):
            return
        content = getattr(message, "content", None)
        if content:
            self._last_rationale = extract_text(content)

    def on_retriever_end(
        self,
        documents: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        texts = [getattr(d, "page_content", None) for d in documents]
        texts = [t for t in texts if t]
        if texts:
            self._last_context = texts

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name") or "unknown_tool"
        tool_args = inputs if inputs is not None else {"input": input_str}
        rationale = self._last_rationale or f"LangChain agent proposed tool {tool_name!r}."
        decision = self._client.evaluate(
            tool_name=tool_name,
            tool_args=tool_args,
            agent_rationale=rationale,
            context_texts=list(self._last_context),
            process=self._process,
            call_id=str(run_id),
        )
        if decision["decision"] == "block":
            raise AiGuardBlocked(decision)
        if decision["decision"] == "escalate":
            raise AiGuardEscalated(decision)
