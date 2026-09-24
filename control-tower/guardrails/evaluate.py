"""Orchestrate guardrails and audit logging for a tool call."""

from __future__ import annotations

from audit.log_store import AppendInput, AuditLogStore
from configs.loader import ProcessConfig
from contracts.schemas import GatewayDecision, InjectionFlag, ToolCallRequest
from guardrails import gateway, injection_guard, output_verifier, risk_scorer


def evaluate_tool_call(
    request: ToolCallRequest,
    config: ProcessConfig,
    *,
    retrieved_texts: list[str] | None = None,
    context_chunks: list[str] | None = None,
    injection_flags: list[InjectionFlag] | None = None,
    audit: AuditLogStore,
) -> GatewayDecision:
    """Run injection scan, verification, scoring, gateway decision, and audit append.

    When injection_flags is provided (e.g. precomputed by the graph's
    scan_injection node), skip re-scanning so the LLM classifier runs at most
    once per request. Otherwise batch-scan retrieved_texts.
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

    policy_hit = gateway.classify_policy_hit(request, config)
    risk_score, confidence_score, evidence_score = risk_scorer.score(
        injection_flags=all_flags,
        evidence_score=verification.evidence_score,
        policy_hit=policy_hit,
    )

    decision = gateway.decide(
        request,
        config,
        risk_score=risk_score,
        evidence_score=evidence_score,
        confidence_score=confidence_score,
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
