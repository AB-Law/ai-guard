"""Orchestrate guardrails and audit logging for a tool call."""

from __future__ import annotations

from audit.log_store import AppendInput, AuditLogStore
from configs.loader import ProcessConfig
from contracts.schemas import (
    GatewayDecision,
    InjectionFlag,
    PolicyEntailmentResult,
    ToolCallRequest,
)
from guardrails import (
    evidence_docs,
    gateway,
    injection_guard,
    output_verifier,
    policy_entailment,
    risk_scorer,
)


def evaluate_tool_call(
    request: ToolCallRequest,
    config: ProcessConfig,
    *,
    retrieved_texts: list[str] | None = None,
    context_chunks: list[str] | None = None,
    injection_flags: list[InjectionFlag] | None = None,
    retrieved_chunk_ids: list[str] | None = None,
    audit: AuditLogStore,
) -> GatewayDecision:
    """Run injection scan, verification, policy entailment, scoring, gateway, audit.

    When injection_flags is provided (e.g. precomputed by the graph's
    scan_injection node), skip re-scanning so the LLM classifier runs at most
    once per request. Otherwise batch-scan retrieved_texts.

    retrieved_chunk_ids are preferred for the required-evidence presence check;
    falls back to request.context_refs when not supplied.
    """
    if injection_flags is not None:
        all_flags: list[InjectionFlag] = list(injection_flags)
    elif retrieved_texts:
        all_flags = list(injection_guard.scan(retrieved_texts).flags)
    else:
        all_flags = []

    if all_flags:
        audit.append(
            AppendInput(
                process=request.process,
                step_id=request.step_id,
                event_type="injection_flag",
                payload={
                    "call_id": request.call_id,
                    "flags": [f.model_dump() for f in all_flags],
                },
            )
        )

    chunks = context_chunks if context_chunks is not None else (retrieved_texts or [])
    verification = output_verifier.verify_evidence(
        request.agent_rationale, chunks, request_facts=request.tool_args
    )

    chunk_ids = (
        list(retrieved_chunk_ids)
        if retrieved_chunk_ids is not None
        else list(request.context_refs)
    )
    missing = evidence_docs.missing_required_evidence_docs(config, chunk_ids)
    if missing:
        entailment = PolicyEntailmentResult(
            compliant=False,
            violated_clauses=[f"missing_evidence:{doc}" for doc in missing],
            severity="hard",
        )
    else:
        entailment = policy_entailment.check_policy_entailment(request, chunks)

    policy_hit = gateway.classify_policy_hit(request, config)
    risk_score, confidence_score, evidence_score = risk_scorer.score(
        injection_flags=all_flags,
        evidence_score=verification.evidence_score,
        policy_hit=policy_hit,
        entailment_severity=entailment.severity,
    )

    decision = gateway.decide(
        request,
        config,
        risk_score=risk_score,
        evidence_score=evidence_score,
        confidence_score=confidence_score,
        entailment=entailment,
    )

    # Keyed judge failure: fail closed with an auditable reason. Hard blocks
    # (disallowed / not-allowed tools) still win over escalate.
    if verification.judge_unavailable and decision.decision != "block":
        decision = GatewayDecision(
            call_id=request.call_id,
            decision="escalate",
            reason="Evidence judge unavailable; failing closed.",
            policy_refs=["judge_unavailable"],
            risk_score=risk_score,
            confidence_score=confidence_score,
            evidence_score=0.0,
        )

    audit.append(
        AppendInput(
            process=request.process,
            step_id=request.step_id,
            event_type="policy_check",
            payload={
                "call_id": request.call_id,
                "reason": decision.reason,
                "policy_refs": decision.policy_refs,
                "unsupported_claims": verification.unsupported_claims,
                "entailment": entailment.model_dump(),
                "missing_evidence_docs": missing,
            },
            scores=decision,
        )
    )

    audit.append(
        AppendInput(
            process=request.process,
            step_id=request.step_id,
            event_type="tool_call",
            payload={
                "call_id": request.call_id,
                "tool_name": request.tool_name,
                "tool_args": request.tool_args,
                "decision": decision.decision,
            },
            scores=decision,
        )
    )

    return decision
