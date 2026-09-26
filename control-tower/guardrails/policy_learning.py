"""Propose literal learned rules from high-severity injection incidents.

Does not apply rules — humans approve via origin=policy_change cases.
Safe to call from BackgroundTasks: failures audit as rule_proposed errors
and never change the original gateway decision.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from audit.log_store import AppendInput
from audit.redact import redact_injection_span
from audit.sensitive_data.detectors import scrub_secretish
from contracts.schemas import GatewayDecision, IncidentEvent, InjectionFlag
from guardrails.rule_store import (
    LearnedRuleStore,
    get_rule_store,
    normalize_literal,
)

logger = logging.getLogger(__name__)

_META_STRIP_RE = re.compile(r"[.*+?^${}|()\[\]\\]")


class _AuditLike(Protocol):
    def append(self, entry: AppendInput) -> Any: ...
    def append_many(self, entries: list[AppendInput]) -> Any: ...
    def index_incident(self, **kwargs: Any) -> None: ...


class _CaseStoreLike(Protocol):
    cases: Any
    call_to_case: Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _high_flags(flags: list[InjectionFlag]) -> list[InjectionFlag]:
    return [f for f in flags if f.severity == "high" and not f.rule_id]


def _detection_path(flag: InjectionFlag) -> str:
    if flag.rule_id:
        return "learned"
    if flag.pattern_id.startswith("llm:"):
        return "llm"
    return "regex"


def _scrub_secrets(text: str) -> str:
    return scrub_secretish(text)


def _candidate_literal(flag: InjectionFlag) -> str:
    """Literal fingerprint from the matched snippet — never an open regex.

    Auto-proposals strip metacharacters and obvious secret-shaped tokens
    (snippets are padded and may contain credentials); humans can still
    tighten the literal on approve.
    """
    raw = normalize_literal(_scrub_secrets(flag.snippet or flag.pattern_id))
    cleaned = normalize_literal(_META_STRIP_RE.sub("", raw))
    if cleaned:
        return cleaned
    return normalize_literal(flag.pattern_id.replace(":", " ")) or "injection"


def should_propose(
    decision: GatewayDecision,
    flags: list[InjectionFlag],
) -> bool:
    if decision.decision not in ("block", "escalate"):
        return False
    return bool(_high_flags(flags))


def record_incident_and_propose(
    *,
    process_id: str,
    call_id: str,
    case_id: str | None,
    tool_name: str,
    decision: GatewayDecision,
    flags: list[InjectionFlag],
    audit: _AuditLike,
    case_store: _CaseStoreLike | None = None,
    rule_store: LearnedRuleStore | None = None,
) -> dict[str, Any] | None:
    """Persist incident + pending rule + policy_change case.

    Returns proposal summary or None if skipped. Never raises to callers that
    schedule this in BackgroundTasks — logs and audits errors instead.
    """
    try:
        return _record_incident_and_propose(
            process_id=process_id,
            call_id=call_id,
            case_id=case_id,
            tool_name=tool_name,
            decision=decision,
            flags=flags,
            audit=audit,
            case_store=case_store,
            rule_store=rule_store or get_rule_store(),
        )
    except Exception:
        logger.exception("policy learning failed for call_id=%s", call_id)
        try:
            audit.append(
                AppendInput(
                    process=process_id,
                    step_id="policy_learning",
                    event_type="rule_proposed",
                    payload={
                        "call_id": call_id,
                        "case_id": case_id,
                        "status": "error",
                        "error": "record_incident_and_propose failed",
                    },
                )
            )
        except Exception:
            logger.exception("failed to audit learning error")
        return None


def _record_incident_and_propose(
    *,
    process_id: str,
    call_id: str,
    case_id: str | None,
    tool_name: str,
    decision: GatewayDecision,
    flags: list[InjectionFlag],
    audit: _AuditLike,
    case_store: _CaseStoreLike | None,
    rule_store: LearnedRuleStore,
) -> dict[str, Any] | None:
    highs = _high_flags(flags)
    if decision.decision not in ("block", "escalate") or not highs:
        return None

    primary = highs[0]
    span_meta = redact_injection_span(primary.snippet or "")
    incident_id = str(uuid.uuid4())
    attack_category = None
    if primary.pattern_id.startswith("llm:"):
        attack_category = primary.pattern_id.removeprefix("llm:")

    incident = IncidentEvent(
        incident_id=incident_id,
        process_id=process_id,
        case_id=case_id,
        call_id=call_id,
        matched_pattern=primary.pattern_id,
        matched_span_preview=span_meta["matched_span_preview"],
        matched_span_hash=span_meta["matched_span_hash"],
        tool_name=tool_name,
        gateway_decision=decision.decision,
        detection_path=_detection_path(primary),  # type: ignore[arg-type]
        attack_category=attack_category,
    )

    incident_entry = audit.append(
        AppendInput(
            process=process_id,
            step_id="policy_learning",
            event_type="incident",
            payload=incident.model_dump(),
            scores=decision,
        )
    )
    index = getattr(audit, "index_incident", None)
    if callable(index):
        index(
            incident_id=incident_id,
            entry_id=incident_entry.entry_id,
            process_id=process_id,
            created_at=incident_entry.timestamp,
        )

    candidate = _candidate_literal(primary)
    try:
        rule = rule_store.create_pending(
            process_id=process_id,
            rule_text=candidate,
            source_incident_id=incident_id,
        )
    except ValueError as exc:
        audit.append(
            AppendInput(
                process=process_id,
                step_id="policy_learning",
                event_type="rule_proposed",
                payload={
                    "call_id": call_id,
                    "case_id": case_id,
                    "incident_id": incident_id,
                    "status": "skipped",
                    "reason": str(exc),
                    "matched_span_preview": span_meta["matched_span_preview"],
                    "matched_span_hash": span_meta["matched_span_hash"],
                },
                scores=decision,
            )
        )
        return {"incident_id": incident_id, "status": "skipped", "reason": str(exc)}

    policy_case_id = f"pol-{rule.rule_id[:8]}"
    policy_call_id = f"policy:{rule.rule_id}"
    if case_store is not None:
        case_row = {
            "case_id": policy_case_id,
            "process": process_id,
            "status": "pending_approval",
            "call_id": policy_call_id,
            "origin": "policy_change",
            "request": {
                "tool_name": "apply_learned_rule",
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type,
                "rule_text": rule.rule_text,
                "source_incident_id": incident_id,
                "matched_span_preview": span_meta["matched_span_preview"],
                "matched_span_hash": span_meta["matched_span_hash"],
                "source_call_id": call_id,
                "source_case_id": case_id,
            },
            "gateway_decision": {
                "call_id": policy_call_id,
                "decision": "escalate",
                "reason": "Proposed policy change from high-severity injection incident",
                "policy_refs": [f"incident:{incident_id}", f"rule:{rule.rule_id}"],
                "risk_score": decision.risk_score,
                "confidence_score": decision.confidence_score,
                "evidence_score": decision.evidence_score,
            },
            "tool_result": None,
            "source_app": None,
            "created_at": _utc_now(),
        }
        case_store.cases[policy_case_id] = case_row
        case_store.call_to_case[policy_call_id] = policy_case_id

    audit.append(
        AppendInput(
            process=process_id,
            step_id="policy_learning",
            event_type="rule_proposed",
            payload={
                "call_id": policy_call_id,
                "case_id": policy_case_id,
                "incident_id": incident_id,
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type,
                "rule_text": rule.rule_text,
                "status": "pending",
                "source_call_id": call_id,
                "matched_span_preview": span_meta["matched_span_preview"],
                "matched_span_hash": span_meta["matched_span_hash"],
            },
            scores=decision,
        )
    )
    return {
        "incident_id": incident_id,
        "rule_id": rule.rule_id,
        "case_id": policy_case_id,
        "call_id": policy_call_id,
        "status": "pending",
    }
