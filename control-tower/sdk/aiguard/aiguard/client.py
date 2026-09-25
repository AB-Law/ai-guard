"""Thin HTTP client for the tower's /guard/* endpoints — POST /guard/evaluate
plus the approval pair (GET/POST /guard/approvals/{call_id}). No chromadb/
langgraph/fastapi dependency; the policy engine and approval state live
entirely on the tower side, this just asks it questions per tool call.
"""

from __future__ import annotations

import time
from typing import Any, Literal, Self

import httpx

from .config import get_config


class GuardClient:
    def __init__(
        self,
        *,
        api_url: str | None = None,
        timeout: float | None = None,
        api_key: str | None = None,
    ) -> None:
        cfg = get_config()
        self.api_url = (api_url or cfg.api_url).rstrip("/")
        self.timeout = timeout if timeout is not None else cfg.timeout
        self.api_key = api_key if api_key is not None else cfg.api_key
        self._http = httpx.Client(timeout=self.timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

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
        resp = self._http.post(
            f"{self.api_url}/guard/evaluate",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def get_approval(self, call_id: str) -> dict[str, Any]:
        """Status of a call submitted via evaluate(). Returns
        {call_id, case_id, process, status, decision, request, source_app,
        created_at} — status is "pending_approval" while waiting, else
        "completed"/"rejected". Works for any call_id this API key
        originated (or any call_id at all, for a dashboard token); a 403
        means it belongs to a different application.
        """
        resp = self._http.get(
            f"{self.api_url}/guard/approvals/{call_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def resolve_approval(
        self, call_id: str, *, action: Literal["approve", "reject"], actor: str
    ) -> dict[str, Any]:
        """Record a human decision on an escalated call. This only flips the
        tower's stored decision (allow on approve, block on reject) and
        writes an audit entry — it never executes anything on your behalf.
        Run your own tool function afterward, gated on the returned
        decision, the same way you would for a decision that was never
        escalated in the first place.
        """
        resp = self._http.post(
            f"{self.api_url}/guard/approvals/{call_id}",
            json={"action": action, "actor": actor},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def wait_for_decision(
        self,
        call_id: str,
        *,
        poll_interval: float = 2.0,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Block until an escalated call_id is resolved (by anyone — your
        own app's UI calling resolve_approval(), a teammate using the
        tower's own dashboard, or another integration entirely) or timeout
        elapses. Returns the same shape as get_approval(); raises
        TimeoutError if still pending_approval when the deadline passes.

        This is the piece that makes "wait for a human" a single call
        instead of you hand-rolling a poll loop — see guard(..., on_escalate
        ="wait") for the decorator-level version of this same pattern.
        """
        deadline = time.monotonic() + timeout
        while True:
            status = self.get_approval(call_id)
            if status.get("status") != "pending_approval":
                return status
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"call_id {call_id!r} still pending_approval after {timeout}s"
                )
            time.sleep(poll_interval)


def default_client() -> GuardClient:
    """A fresh client built from the current global config on every call —
    deliberately not cached, so a configure() call always takes effect on the
    next guarded call even if earlier calls already ran. Each GuardClient
    keeps its own pooled httpx.Client for connection reuse across evaluates.
    """
    return GuardClient()
