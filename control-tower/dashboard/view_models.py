"""Pure view-model builders for the Streamlit dashboard (no Streamlit imports)."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any

_VENDOR_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def cases_to_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn case snapshots into table rows for the live case list.

    Omits ``call_id`` (UUID soup at laptop widths); approval queue still has it.
    """
    rows: list[dict[str, Any]] = []
    for case in cases:
        decision = case.get("gateway_decision") or {}
        rows.append(
            {
                "case_id": case.get("case_id"),
                "process": case.get("process"),
                "status": case.get("status"),
                "decision": decision.get("decision"),
                "risk": decision.get("risk_score"),
                "created_at": short_timestamp(case.get("created_at")),
            }
        )
    return rows


def make_live_case_id(
    vendor_id: str | None,
    *,
    now: datetime | None = None,
    suffix: str | None = None,
) -> str:
    """Human-readable id for dashboard live submits: ``live-{vendor}-{HHMMSS}``."""
    raw = (vendor_id or "").strip() or "case"
    vendor = _VENDOR_SAFE.sub("-", raw).strip("-_") or "case"
    stamp = (now or datetime.now(timezone.utc)).strftime("%H%M%S")
    base = f"live-{vendor}-{stamp}"
    if suffix:
        return f"{base}-{suffix}"
    return base


def format_score_value(value: Any) -> str:
    """Format score for metric display — floats to 2dp so values stay short."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, int):
        return str(value)
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def short_timestamp(value: Any) -> str:
    """Prefer ``HH:MM:SS`` for table scanability; fall back to original string."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    match = re.search(r"(\d{2}:\d{2}:\d{2})", text)
    if match:
        return match.group(1)
    return text


def unique_live_case_id(
    vendor_id: str | None,
    existing_ids: set[str] | list[str],
    *,
    now: datetime | None = None,
) -> str:
    """Generate ``live-…`` id; append a 4-char suffix if the base already exists."""
    existing = set(existing_ids)
    candidate = make_live_case_id(vendor_id, now=now)
    if candidate not in existing:
        return candidate
    return make_live_case_id(
        vendor_id,
        now=now,
        suffix=secrets.token_hex(2),
    )


def audit_to_timeline(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordered timeline rows from audit log entries (oldest first)."""
    ordered = sorted(entries, key=lambda e: str(e.get("timestamp") or ""))
    rows: list[dict[str, Any]] = []
    for entry in ordered:
        payload = entry.get("payload") or {}
        summary_parts: list[str] = []
        if payload.get("query"):
            summary_parts.append(f"query={payload['query']!r}")
        if payload.get("action"):
            summary_parts.append(f"action={payload['action']}")
        if payload.get("tool_name"):
            summary_parts.append(f"tool={payload['tool_name']}")
        if payload.get("chunk_ids"):
            summary_parts.append(f"chunks={len(payload['chunk_ids'])}")
        scores = entry.get("scores")
        score_summary = ""
        if isinstance(scores, dict):
            parts = []
            if scores.get("decision") is not None:
                parts.append(f"decision={scores['decision']}")
            if scores.get("risk_score") is not None:
                parts.append(f"risk={scores['risk_score']}")
            score_summary = "; ".join(parts)
        rows.append(
            {
                "entry_id": entry.get("entry_id"),
                "event_type": entry.get("event_type"),
                "step_id": entry.get("step_id"),
                "timestamp": entry.get("timestamp"),
                "time_short": short_timestamp(entry.get("timestamp")),
                "summary": "; ".join(summary_parts) if summary_parts else "",
                "scores": scores,
                "score_summary": score_summary,
            }
        )
    return rows


def decision_to_score_panel(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pass-through score panel — no invented UI math."""
    if decision is None:
        return None
    return {
        "decision": decision.get("decision"),
        "reason": decision.get("reason"),
        "policy_refs": list(decision.get("policy_refs") or []),
        "risk_score": decision.get("risk_score"),
        "confidence_score": decision.get("confidence_score"),
        "evidence_score": decision.get("evidence_score"),
        "call_id": decision.get("call_id"),
    }


def pending_approvals(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cases awaiting HITL with a call_id for Approve/Reject."""
    out: list[dict[str, Any]] = []
    for case in cases:
        if case.get("status") != "pending_approval":
            continue
        call_id = case.get("call_id") or ""
        if not call_id:
            continue
        decision = case.get("gateway_decision") or {}
        out.append(
            {
                "case_id": case.get("case_id"),
                "call_id": call_id,
                "process": case.get("process"),
                "decision": decision.get("decision"),
                "reason": decision.get("reason"),
                "risk_score": decision.get("risk_score"),
            }
        )
    return out


def request_to_display(request: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Flatten a case request dict into labeled key/value pairs for the UI."""
    if not request:
        return []
    order = ("vendor_id", "amount", "item")
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for key in order:
        if key in request:
            pairs.append((key, str(request[key])))
            seen.add(key)
    for key, value in request.items():
        if key not in seen:
            pairs.append((str(key), str(value)))
    return pairs


def tool_result_to_display(result: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Flatten a tool_result dict into labeled key/value pairs (what the agent did)."""
    if not result:
        return []
    order = ("status", "po_id", "call_id", "reason", "vendor_id", "amount", "item")
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for key in order:
        if key in result and result[key] is not None:
            pairs.append((key, str(result[key])))
            seen.add(key)
    for key, value in result.items():
        if key not in seen and value is not None:
            pairs.append((str(key), str(value)))
    return pairs


def offline_investigate_mock(
    question: str,
    *,
    case_id: str | None,
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deterministic mock answer when OPENAI_API_KEY is unavailable."""
    decision = decision or {}
    reason = decision.get("reason") or "No gateway reason recorded."
    refs = list(decision.get("policy_refs") or [])
    answer = (
        f"Offline investigation for case {case_id or '(all)'}: "
        f"decision={decision.get('decision')!r}. {reason}"
    )
    if refs:
        answer += " Policy refs: " + ", ".join(str(r) for r in refs) + "."
    answer += f" (Asked: {question!r})"
    return {
        "answer": answer,
        "cited_entry_ids": [],
        "cited_chunk_ids": [str(r) for r in refs],
    }


def case_kpis(cases: list[dict[str, Any]]) -> dict[str, int]:
    """Aggregate counts for the dashboard KPI strip (no invented scores)."""
    total = len(cases)
    pending = 0
    allow = 0
    block = 0
    escalate = 0
    for case in cases:
        if case.get("status") == "pending_approval":
            pending += 1
        decision = ((case.get("gateway_decision") or {}).get("decision") or "").lower()
        if decision == "allow":
            allow += 1
        elif decision == "block":
            block += 1
        elif decision == "escalate":
            escalate += 1
    return {
        "total": total,
        "pending": pending,
        "allow": allow,
        "block": block,
        "escalate": escalate,
    }


def decision_badge_kind(decision: str | None) -> str:
    """CSS kind for a gateway decision badge."""
    d = (decision or "").lower()
    if d in {"allow", "block", "escalate"}:
        return d
    return "neutral"


def status_badge_kind(status: str | None) -> str:
    """CSS kind for a case status badge."""
    s = (status or "").lower()
    if s == "pending_approval":
        return "pending"
    if s in {"blocked", "rejected"}:
        return "block"
    if s == "completed":
        return "allow"
    return "neutral"


def format_decision_label(decision: str | None) -> str:
    if not decision:
        return "—"
    return str(decision).upper()
