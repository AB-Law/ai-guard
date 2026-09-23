"""Thin HTTP client for POST /guard/evaluate — the only endpoint this SDK
calls. No chromadb/langgraph/fastapi dependency; the policy engine lives
entirely on the tower side, this just asks it a question per tool call.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import get_config


class GuardClient:
    def __init__(self, *, api_url: str | None = None, timeout: float | None = None) -> None:
        cfg = get_config()
        self.api_url = (api_url or cfg.api_url).rstrip("/")
        self.timeout = timeout if timeout is not None else cfg.timeout

    def evaluate(
        self,
        *,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        agent_rationale: str = "",
        context_texts: list[str] | None = None,
        process: str | None = None,
        call_id: str | None = None,
        source_app: str | None = None,
    ) -> dict[str, Any]:
        """Returns the tower's GatewayDecision as a dict:
        {call_id, decision, reason, policy_refs, risk_score, confidence_score,
        evidence_score}. Does not raise on block/escalate — callers that want
        that (the decorator, the LangChain handler) wrap this and raise
        AiGuardBlocked/AiGuardEscalated themselves.
        """
        cfg = get_config()
        payload: dict[str, Any] = {
            "process": process or cfg.process,
            "tool_name": tool_name,
            "tool_args": tool_args or {},
            "agent_rationale": agent_rationale,
            "context_texts": context_texts or [],
        }
        if call_id:
            payload["call_id"] = call_id
        app_name = source_app if source_app is not None else cfg.source_app
        if app_name:
            payload["source_app"] = app_name
        resp = httpx.post(
            f"{self.api_url}/guard/evaluate", json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()


def default_client() -> GuardClient:
    """A fresh client built from the current global config on every call —
    deliberately not cached, so a configure() call always takes effect on the
    next guarded call even if earlier calls already ran."""
    return GuardClient()
