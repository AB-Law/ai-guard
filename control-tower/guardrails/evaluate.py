"""Orchestrate guardrails and audit logging for a tool call."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from audit.log_store import AppendInput, AuditLogStore
from configs.loader import ProcessConfig
from contracts.schemas import (
    GatewayDecision,
    InjectionFlag,
    PolicyEntailmentResult,
    ToolCallRequest,
    VerificationResult,
)
from guardrails import (
    evidence_docs,
    gateway,
    injection_guard,
    output_verifier,
    policy_entailment,
    risk_scorer,
)


def is_hard_block(request: ToolCallRequest, config: ProcessConfig) -> bool:
    """True when gateway would block without needing LLM judges."""
    if request.tool_name in config.disallowed_tools:
        return True
    allowed = {t.name for t in config.allowed_tools}
    return request.tool_name not in allowed


def _append_audits(audit: AuditLogStore, entries: list[AppendInput]) -> None:
    append_many = getattr(audit, "append_many", None)
    if callable(append_many):
        append_many(entries)
        return
    for entry in entries:
        audit.append(entry)


def evaluate_tool_call(
    request: ToolCallRequest,
    config: ProcessConfig,
    *,
    retrieved_texts: list[str] | None = None,
    context_chunks: list[str] | None = None,
    injection_flags: list[InjectionFlag] | None = None,
    retrieved_chunk_ids: list[str] | None = None,
    audit: AuditLogStore,
    stage_timings_ms: dict[str, float] | None = None,
) -> GatewayDecision:
    """Run injection scan, verification, policy entailment, scoring, gateway, audit.

    When injection_flags is provided (e.g. precomputed by the graph's
    scan_injection node), skip re-scanning so the LLM classifier runs at most
    once per request. Otherwise batch-scan retrieved_texts.

    retrieved_chunk_ids are preferred for the required-evidence presence check;
    falls back to request.context_refs when not supplied.

    Independent LLM judges (injection / evidence / entailment) run concurrently
    when more than one is needed. Deterministic hard blocks (disallowed /
    not-allowed tools) skip judges entirely.
    """
    t0 = time.perf_counter()
    timings: dict[str, float] = {} if stage_timings_ms is None else stage_timings_ms

    # --- Early hard block: no retrieve/LLM needed for decision quality ---
    if is_hard_block(request, config):
        empty_entailment = PolicyEntailmentResult(
            compliant=True, violated_clauses=[], severity="none"
        )
        decision = gateway.decide(
            request,
            config,
            risk_score=0,
            evidence_score=0.0,
            confidence_score=0.0,
            entailment=empty_entailment,
        )
        timings["injection_ms"] = 0.0
        timings["evidence_ms"] = 0.0
        timings["entailment_ms"] = 0.0
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        _append_audits(
            audit,
            [
                AppendInput(
                    process=request.process,
                    step_id=request.step_id,
                    event_type="policy_check",
                    payload={
                        "call_id": request.call_id,
                        "case_id": request.case_id,
                        "reason": decision.reason,
                        "policy_refs": decision.policy_refs,
                        "unsupported_claims": [],
                        "entailment": empty_entailment.model_dump(),
                        "missing_evidence_docs": [],
                        "early_hard_block": True,
                        "stage_timings_ms": dict(timings),
                    },
                    scores=decision,
                ),
                AppendInput(
                    process=request.process,
                    step_id=request.step_id,
                    event_type="tool_call",
                    payload={
                        "call_id": request.call_id,
                        "case_id": request.case_id,
                        "tool_name": request.tool_name,
                        "tool_args": request.tool_args,
                        "decision": decision.decision,
                    },
                    scores=decision,
                ),
            ],
        )
        return decision

    chunks = context_chunks if context_chunks is not None else (retrieved_texts or [])
    chunk_ids = (
        list(retrieved_chunk_ids)
        if retrieved_chunk_ids is not None
        else list(request.context_refs)
    )
    missing = evidence_docs.missing_required_evidence_docs(config, chunk_ids)

    need_injection_scan = injection_flags is None and bool(retrieved_texts)
    need_entailment_llm = not missing

    def _run_injection() -> tuple[list[InjectionFlag], float]:
        started = time.perf_counter()
        if injection_flags is not None:
            flags = list(injection_flags)
        elif retrieved_texts:
            flags = list(injection_guard.scan(retrieved_texts).flags)
        else:
            flags = []
        return flags, round((time.perf_counter() - started) * 1000, 2)

    def _run_evidence() -> tuple[VerificationResult, float]:
        started = time.perf_counter()
        result = output_verifier.verify_evidence(
            request.agent_rationale, chunks, request_facts=request.tool_args
        )
        return result, round((time.perf_counter() - started) * 1000, 2)

    def _run_entailment() -> tuple[PolicyEntailmentResult, float]:
        started = time.perf_counter()
        if missing:
            result = PolicyEntailmentResult(
                compliant=False,
                violated_clauses=[f"missing_evidence:{doc}" for doc in missing],
                severity="hard",
            )
        else:
            result = policy_entailment.check_policy_entailment(request, chunks)
        return result, round((time.perf_counter() - started) * 1000, 2)

    # Pool when ≥2 potentially-slow stages can overlap (injection scan and/or
    # entailment LLM alongside the evidence judge).
    use_pool = need_injection_scan or need_entailment_llm

    if use_pool:
        with ThreadPoolExecutor(max_workers=3) as pool:
            inj_f = pool.submit(_run_injection)
            ver_f = pool.submit(_run_evidence)
            ent_f = pool.submit(_run_entailment)
            all_flags, inj_ms = inj_f.result()
            verification, ver_ms = ver_f.result()
            entailment, ent_ms = ent_f.result()
    else:
        all_flags, inj_ms = _run_injection()
        verification, ver_ms = _run_evidence()
        entailment, ent_ms = _run_entailment()

    timings["injection_ms"] = inj_ms
    timings["evidence_ms"] = ver_ms
    timings["entailment_ms"] = ent_ms

    audit_entries: list[AppendInput] = []
    if all_flags:
        audit_entries.append(
            AppendInput(
                process=request.process,
                step_id=request.step_id,
                event_type="injection_flag",
                payload={
                    "call_id": request.call_id,
                    "case_id": request.case_id,
                    "flags": [f.model_dump() for f in all_flags],
                },
            )
        )

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

    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    audit_entries.append(
        AppendInput(
            process=request.process,
            step_id=request.step_id,
            event_type="policy_check",
            payload={
                "call_id": request.call_id,
                "case_id": request.case_id,
                "reason": decision.reason,
                "policy_refs": decision.policy_refs,
                "unsupported_claims": verification.unsupported_claims,
                "entailment": entailment.model_dump(),
                "missing_evidence_docs": missing,
                "stage_timings_ms": dict(timings),
            },
            scores=decision,
        )
    )
    audit_entries.append(
        AppendInput(
            process=request.process,
            step_id=request.step_id,
            event_type="tool_call",
            payload={
                "call_id": request.call_id,
                "case_id": request.case_id,
                "tool_name": request.tool_name,
                "tool_args": request.tool_args,
                "decision": decision.decision,
            },
            scores=decision,
        )
    )
    _append_audits(audit, audit_entries)

    return decision
