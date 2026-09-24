"""Shared data contracts — ARCHITECTURE §6."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    call_id: str
    process: str
    step_id: str
    tool_name: str
    tool_args: dict
    agent_rationale: str
    context_refs: list[str]
    timestamp: str


GatewayDecisionLiteral = Literal["allow", "block", "escalate"]
AuditEventType = Literal[
    "retrieval",
    "tool_call",
    "output_claim",
    "policy_check",
    "approval",
    "injection_flag",
]


class GatewayDecision(BaseModel):
    call_id: str
    decision: GatewayDecisionLiteral
    reason: str
    policy_refs: list[str]
    risk_score: int = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0.0, le=1.0)
    evidence_score: float = Field(ge=0.0, le=1.0)


class AuditLogEntry(BaseModel):
    entry_id: str
    process: str
    step_id: str
    event_type: AuditEventType
    payload: dict
    scores: GatewayDecision | None
    timestamp: str
    prev_hash: str
    entry_hash: str


InjectionSeverity = Literal["high", "medium", "low"]


class InjectionFlag(BaseModel):
    pattern_id: str
    snippet: str
    severity: InjectionSeverity


class InjectionScanResult(BaseModel):
    flags: list[InjectionFlag]
    trust: Literal["untrusted", "none"] = "none"


class InjectionClassifierResult(BaseModel):
    """Structured output from the semantic injection classifier."""

    is_injection: bool
    severity: InjectionSeverity = "medium"
    attack_type: str = "none"
    rationale: str = ""


class VerificationResult(BaseModel):
    evidence_score: float = Field(ge=0.0, le=1.0)
    unsupported_claims: list[str]
