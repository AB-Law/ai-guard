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
    # Optional: the case this call belongs to, if the caller has one (both
    # /cases and /guard/evaluate do). Threaded through so evaluate_tool_call
    # can stamp it on every audit entry it writes — without it, Logs shows
    # "–" for every policy_check/tool_call/injection_flag row regardless of
    # origin, since those are the only audit.append calls in the codebase
    # that never had case_id passed to them.
    case_id: str | None = None


GatewayDecisionLiteral = Literal["allow", "block", "escalate"]
AuditEventType = Literal[
    "retrieval",
    "tool_call",
    "output_claim",
    "policy_check",
    "approval",
    "injection_flag",
    "incident",
    "rule_proposed",
    "rule_applied",
]
LearnedRuleType = Literal["literal"]
LearnedRuleStatus = Literal["pending", "active", "rejected"]
DetectionPath = Literal["regex", "llm", "learned"]


class GatewayDecision(BaseModel):
    call_id: str
    decision: GatewayDecisionLiteral
    reason: str
    policy_refs: list[str]
    risk_score: int = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0.0, le=1.0)
    evidence_score: float = Field(ge=0.0, le=1.0)
    # Optional W3C trace id (hex) when OpenTelemetry is active — not part of
    # the hash-chain; additive for clients that want to correlate logs.
    trace_id: str | None = None


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
    # Non-hashed correlation to the active OTel trace (column, not payload).
    trace_id: str | None = None


InjectionSeverity = Literal["high", "medium", "low"]


class InjectionFlag(BaseModel):
    pattern_id: str
    snippet: str
    severity: InjectionSeverity
    rule_id: str | None = None


class InjectionScanResult(BaseModel):
    flags: list[InjectionFlag]
    trust: Literal["untrusted", "none"] = "none"


class InjectionClassifierResult(BaseModel):
    """Structured output from the semantic injection classifier."""

    is_injection: bool
    severity: InjectionSeverity = "medium"
    attack_type: str = "none"
    rationale: str = ""


class IncidentEvent(BaseModel):
    """Structured injection incident recorded on the audit_log chain."""

    incident_id: str
    process_id: str
    case_id: str | None = None
    call_id: str
    matched_pattern: str
    matched_span_preview: str
    matched_span_hash: str
    tool_name: str
    gateway_decision: GatewayDecisionLiteral
    detection_path: DetectionPath
    attack_category: str | None = None
    source_rule_id: str | None = None


class LearnedRule(BaseModel):
    rule_id: str
    process_id: str
    rule_type: LearnedRuleType = "literal"
    rule_text: str
    rule_text_hash: str
    status: LearnedRuleStatus
    source_incident_id: str
    approved_by: str | None = None
    created_at: str
    activated_at: str | None = None
    rejected_at: str | None = None


class VerificationResult(BaseModel):
    evidence_score: float = Field(ge=0.0, le=1.0)
    unsupported_claims: list[str]
    judge_unavailable: bool = False


PolicyEntailmentSeverity = Literal["none", "soft", "hard"]


class PolicyEntailmentResult(BaseModel):
    """Structured output from the policy-entailment judge."""

    compliant: bool
    violated_clauses: list[str] = []
    severity: PolicyEntailmentSeverity = "none"
