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

    The wrapped function is NOT executed. decision["call_id"] is the id a
    human approver would use against the tower's own approval flow — how
    that resumes the caller's own code is intentionally out of scope for v0
    of this SDK (see README "Escalation" for the pattern).
    """
