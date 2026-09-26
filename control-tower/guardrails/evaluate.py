"""Orchestrate guardrails and audit logging for a tool call."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from audit.log_store import AppendInput, AuditLogStore
from audit.sensitive_data.detectors import detect_in_text, detect_in_value
from audit.sensitive_data.policy import (
    finding_summaries,
    resolve_policy,
    strongest_decision_action,
)
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
    policy_learning,
    risk_scorer,
)

_DECISION_RANK = {"allow": 0, "escalate": 1, "block": 2}


def _upgrade_decision(
    current: GatewayDecision,
    *,
    action: str,
    reason: str,
    policy_refs: list[str],
) -> GatewayDecision:
    """Upgrade allow→escalate→block; never soften a harder decision."""
    if _DECISION_RANK.get(action, 0) <= _DECISION_RANK.get(current.decision, 0):
        return current
    return GatewayDecision(
        call_id=current.call_id,
        decision=action,  # type: ignore[arg-type]
        reason=reason,
        policy_refs=list(dict.fromkeys([*current.policy_refs, *policy_refs])),
        risk_score=max(current.risk_score, 80 if action == "escalate" else 100),
        confidence_score=current.confidence_score,
        evidence_score=current.evidence_score,
    )


def apply_sensitive_data_policy(
    request: ToolCallRequest,
    config: ProcessConfig,
    decision: GatewayDecision,
    *,
    context_texts: list[str] | None = None,
) -> tuple[GatewayDecision, list[dict[str, object]]]:
    """Opt-in block/escalate from sensitive-data findings.

    Default process configs use action=redact only, so this returns the
    original decision unchanged. Findings summaries never include raw values.
    """
    policy = resolve_policy(config)
    if not policy.enabled:
        return decision, []

    findings = list(detect_in_value(request.tool_args, path="tool_args"))
    findings.extend(detect_in_text(request.agent_rationale or "", path="agent_rationale"))
    for i, text in enumerate(context_texts or []):
        findings.extend(detect_in_text(text or "", path=f"context[{i}]"))

    action = strongest_decision_action(findings, policy)
    summaries = finding_summaries(findings, policy)
    if action is None:
        return decision, summaries

    types = sorted({str(s["type"]) for s in summaries if s.get("action") == action})
    ref = f"sensitive_data:{action}"
    reason = (
        f"Sensitive data policy {action} on detector(s): {', '.join(types) or 'unknown'}"
    )
    upgraded = _upgrade_decision(
        decision, action=action, reason=reason, policy_refs=[ref]
    )
    return upgraded, summaries


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


def _schedule_learning(
    *,
    schedule: Callable[[Callable[[], None]], None] | None,
    request: ToolCallRequest,
    decision: GatewayDecision,
    flags: list[InjectionFlag],
    audit: AuditLogStore,
    case_store: Any | None,
) -> None:
    if not policy_learning.should_propose(decision, flags):
        return

    def _job() -> None:
        policy_learning.record_incident_and_propose(
            process_id=request.process,
            call_id=request.call_id,
            case_id=request.case_id,
            tool_name=request.tool_name,
            decision=decision,
            flags=flags,
            audit=audit,
            case_store=case_store,
        )

    if schedule is not None:
        schedule(_job)
    else:
        _job()


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
    schedule_learning: Callable[[Callable[[], None]], None] | None = None,
    case_store: Any | None = None,
    source_app: str | None = None,
) -> GatewayDecision:
    """Run injection scan, verification, policy entailment, scoring, gateway, audit.

    Dual gate for learned rules:
    1. scan(..., process=) when scanning (graph passes process; evaluate does too)
    2. Always re-check learned rules before judges — even with precomputed flags —
       so /guard/evaluate and LangGraph cannot diverge.

    Learned-rule hits hard-block and skip the evidence/entailment thread pool.
    High-severity proposals are scheduled after the decision (BackgroundTasks
    when schedule_learning is provided); they never alter this decision.
    """
    from telemetry.attrs import set_aegis_attributes
    from telemetry.tracing import current_trace_id, start_span

    with start_span(
        "aegis.guard.evaluate",
        attributes={
            "call_id": request.call_id,
            "process": request.process,
            "case_id": request.case_id,
        },
    ) as span:
        t_eval = time.perf_counter()
        try:
            decision = _evaluate_tool_call_impl(
                request,
                config,
                retrieved_texts=retrieved_texts,
                context_chunks=context_chunks,
                injection_flags=injection_flags,
                retrieved_chunk_ids=retrieved_chunk_ids,
                audit=audit,
                stage_timings_ms=stage_timings_ms,
                schedule_learning=schedule_learning,
                case_store=case_store,
            )
        except Exception:
            try:
                from telemetry.metrics import record_guard_error

                record_guard_error(process=request.process)
            except Exception:  # noqa: BLE001, S110
                pass
            raise
        duration_ms = (time.perf_counter() - t_eval) * 1000.0
        try:
            set_aegis_attributes(span, decision=decision.decision)
            tid = current_trace_id()
            if tid and decision.trace_id is None:
                decision = decision.model_copy(update={"trace_id": tid})
        except Exception:  # noqa: BLE001, S110 — telemetry must not alter decisions
            pass
        try:
            from telemetry.metrics import record_guard_decision

            record_guard_decision(
                process=request.process,
                source_app=source_app,
                decision=decision.decision,
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001, S110
            pass
        return decision


def _evaluate_tool_call_impl(
    request: ToolCallRequest,
    config: ProcessConfig,
    *,
    retrieved_texts: list[str] | None = None,
    context_chunks: list[str] | None = None,
    injection_flags: list[InjectionFlag] | None = None,
    retrieved_chunk_ids: list[str] | None = None,
    audit: AuditLogStore,
    stage_timings_ms: dict[str, float] | None = None,
    schedule_learning: Callable[[Callable[[], None]], None] | None = None,
    case_store: Any | None = None,
) -> GatewayDecision:
    """Internal evaluate body (instrumented by evaluate_tool_call)."""
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
            # A hard block is a certain, rule-based decision (disallowed or
            # unknown tool) — score it like the learned-rule block below
            # (max risk, zero confidence/evidence since no judges ran) so the
            # dashboard never shows a "0/100" risk score next to a block.
            risk_score=100,
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

    texts_for_gate = list(retrieved_texts or context_chunks or [])
    learned_started = time.perf_counter()
    learned_flags = injection_guard.check_learned_rules(request.process, texts_for_gate)
    learned_ms = round((time.perf_counter() - learned_started) * 1000, 2)
    if learned_flags:
        rule_id = learned_flags[0].rule_id or "unknown"
        decision = GatewayDecision(
            call_id=request.call_id,
            decision="block",
            reason=f"Blocked by learned injection rule {rule_id}",
            policy_refs=[f"learned_rule:{rule_id}"],
            risk_score=100,
            confidence_score=0.0,
            evidence_score=0.0,
        )
        timings["injection_ms"] = learned_ms
        timings["evidence_ms"] = 0.0
        timings["entailment_ms"] = 0.0
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        empty_entailment = PolicyEntailmentResult(
            compliant=True, violated_clauses=[], severity="none"
        )
        _append_audits(
            audit,
            [
                AppendInput(
                    process=request.process,
                    step_id=request.step_id,
                    event_type="injection_flag",
                    payload={
                        "call_id": request.call_id,
                        "case_id": request.case_id,
                        "flags": [f.model_dump() for f in learned_flags],
                        "learned_rule_hit": True,
                    },
                ),
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
                        "early_learned_rule_block": True,
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
            flags = list(
                injection_guard.scan(retrieved_texts, process=request.process).flags
            )
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

    timings["injection_ms"] = inj_ms + learned_ms
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

    # Opt-in sensitive-data block/escalate (default configs: redact-only, no-op).
    decision, sensitive_summaries = apply_sensitive_data_policy(
        request,
        config,
        decision,
        context_texts=list(retrieved_texts or context_chunks or chunks or []),
    )

    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    policy_payload: dict[str, Any] = {
        "call_id": request.call_id,
        "case_id": request.case_id,
        "reason": decision.reason,
        "policy_refs": decision.policy_refs,
        "unsupported_claims": verification.unsupported_claims,
        "entailment": entailment.model_dump(),
        "missing_evidence_docs": missing,
        "stage_timings_ms": dict(timings),
    }
    if sensitive_summaries and any(
        s.get("action") in ("block", "escalate") for s in sensitive_summaries
    ):
        policy_payload["sensitive_data_findings"] = [
            s for s in sensitive_summaries if s.get("action") in ("block", "escalate")
        ]

    audit_entries.append(
        AppendInput(
            process=request.process,
            step_id=request.step_id,
            event_type="policy_check",
            payload=policy_payload,
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

    _schedule_learning(
        schedule=schedule_learning,
        request=request,
        decision=decision,
        flags=all_flags,
        audit=audit,
        case_store=case_store,
    )

    return decision
