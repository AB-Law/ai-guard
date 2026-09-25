"""Exceptions raised when the control tower says no (or not yet)."""

from __future__ import annotations

from typing import Any


class AiGuardError(Exception):
    """Base class for aiguard errors."""


class AiGuardDecisionError(AiGuardError):
    """A guard decision stopped the call — carries the full GatewayDecision
    dict (decision/reason/policy_refs/risk_score/confidence_score/
    evidence_score/call_id) so callers can inspect why."""

    def __init__(self, decision: dict[str, Any]) -> None:
        self.decision = decision
        self.call_id = decision.get("call_id")
        self.reason = decision.get("reason", "")
        super().__init__(f"{self.__class__.__name__}: {self.reason} (call_id={self.call_id})")


class AiGuardBlocked(AiGuardDecisionError):
    """The tower blocked this tool call outright — do not retry as-is."""


class AiGuardEscalated(AiGuardDecisionError):
    """The tower needs a human to approve this call before it can run.

    The wrapped function is NOT executed. decision["call_id"] is the id to
    poll against GuardClient.get_approval()/wait_for_decision(), or to
    resolve directly with GuardClient.resolve_approval() — see README
    "Escalation" for the full pattern, including guard(..., on_escalate=
    "wait") for the decorator-level version that blocks for you.
    """


class AiGuardRejected(AiGuardDecisionError):
    """An escalated call was resolved by a human as "reject", not approved.

    Only ever raised by guard(..., on_escalate="wait") after blocking on
    wait_for_decision() — a plain evaluate()/guard() call never raises this
    directly, since rejection can only happen after escalation, and
    resolution is asynchronous relative to the original call. The wrapped
    function was NOT executed.
    """
