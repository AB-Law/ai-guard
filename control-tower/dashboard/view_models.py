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


def relative_age(value: Any, *, now: datetime | None = None) -> str:
    """Compact age for log rows: ``now``, ``2m``, ``3h``, ``1d``."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        created = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    seconds = max(0, int((anchor - created).total_seconds()))
    if seconds < 45:
        return "now"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def traffic_event_blurb(case: dict[str, Any]) -> str:
    """One-line plain-language summary for a live-traffic row."""
    stages = set(case.get("stages") or [])
    decision = (case.get("decision") or "").lower()
    reason = " ".join(str(case.get("reason") or "").split())
    tool = case.get("tool_name")

    parts: list[str] = []
    if "injection_flag" in stages:
        parts.append("Injection flagged")
    elif "retrieval" in stages:
        parts.append("Retrieved context")
    elif "policy_check" in stages:
        parts.append("Policy checked")

    if decision == "allow":
        parts.append("allowed")
    elif decision == "block":
        parts.append("blocked")
    elif decision == "escalate":
        parts.append("needs human approval")

    if tool:
        parts.append(f"tool={tool}")

    blurb = " · ".join(parts) if parts else "No detail yet"
    if reason:
        clipped = reason if len(reason) <= 90 else reason[:87] + "..."
        blurb = f"{blurb} — {clipped}"
    return blurb


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
    order = (
        "vendor_id",
        "employee_id",
        "customer_id",
        "applicant_id",
        "amount",
        "item",
        "query",
        "severity",
    )
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for key in order:
        if key in request and request[key] is not None:
            pairs.append((key, str(request[key])))
            seen.add(key)
    for key, value in request.items():
        if key not in seen and value is not None:
            pairs.append((str(key), str(value)))
    return pairs


# Process-specific Submit case form: labels + defaults + API field mapping.
# CaseRequestBody still requires vendor_id/amount/item — party ids map into vendor_id
# and the semantic key is also stored when the API allows extras.
_SUBMIT_CASE_FORMS: dict[str, dict[str, Any]] = {
    "procurement_review": {
        "party_label": "Vendor ID",
        "party_default": "V-1001",
        "party_key": "vendor_id",
        "amount_label": "Amount (USD)",
        "amount_default": 2500.0,
        "amount_step": 100.0,
        "amount_min": 0.0,
        "amount_help": "Auto-approve band is typically at or below 10,000.",
        "detail_label": "Item",
        "detail_default": "Laptop docks x10",
        "detail_key": "item",
        "show_amount": True,
        "source_app": None,
    },
    "onboarding_kyc": {
        "party_label": "Applicant ID",
        "party_default": "A-2001",
        "party_key": "applicant_id",
        "amount_label": "Risk score input",
        "amount_default": 40.0,
        "amount_step": 5.0,
        "amount_min": 0.0,
        "amount_help": "Synthetic risk input for the KYC case.",
        "detail_label": "Check type",
        "detail_default": "KYC identity verification",
        "detail_key": "item",
        "show_amount": True,
        "source_app": None,
    },
    "finance": {
        "party_label": "Employee ID",
        "party_default": "E-1001",
        "party_key": "employee_id",
        "amount_label": "Expense amount (USD)",
        "amount_default": 850.0,
        "amount_step": 50.0,
        "amount_min": 0.0,
        "amount_help": "Finance auto-approves expenses at or below USD 5,000.",
        "detail_label": "Expense item",
        "detail_default": "Client workshop travel",
        "detail_key": "item",
        "show_amount": True,
        "source_app": "finance_app",
    },
    "risk_rating": {
        "party_label": "Customer ID",
        "party_default": "C-1001",
        "party_key": "customer_id",
        "amount_label": "Severity (1-5)",
        "amount_default": 2.0,
        "amount_step": 1.0,
        "amount_min": 1.0,
        "amount_help": "Severity at or below 3 may auto-assign; 4+ needs review.",
        "detail_label": "Review notes",
        "detail_default": "Routine credit review",
        "detail_key": "item",
        "show_amount": True,
        "source_app": "risk_rating_app",
    },
    "rag_bot": {
        "party_label": "Caller / session ID",
        "party_default": "U-4001",
        "party_key": "vendor_id",
        "amount_label": "Amount",
        "amount_default": 0.0,
        "amount_step": 1.0,
        "amount_min": 0.0,
        "amount_help": None,
        "detail_label": "Question",
        "detail_default": "What is the return window?",
        "detail_key": "query",
        "show_amount": False,
        "source_app": "rag_bot_app",
    },
}


def submit_case_form_spec(process: str) -> dict[str, Any]:
    """Return label/default metadata for the Submit case form for ``process``."""
    return dict(_SUBMIT_CASE_FORMS.get(process) or _SUBMIT_CASE_FORMS["procurement_review"])


def build_submit_case_request(
    process: str,
    *,
    party_id: str,
    amount: float,
    detail: str,
) -> dict[str, Any]:
    """Build a CaseRequestBody-compatible request dict for the selected process."""
    spec = submit_case_form_spec(process)
    party_key = str(spec["party_key"])
    detail_key = str(spec["detail_key"])
    party = (party_id or "").strip() or str(spec["party_default"])
    text = (detail or "").strip() or str(spec["detail_default"])
    amt = float(amount)

    # Always populate the legacy triad so POST /cases validation passes.
    request: dict[str, Any] = {
        "vendor_id": party,
        "amount": amt,
        "item": text,
    }
    if party_key != "vendor_id":
        request[party_key] = party
    if detail_key == "query":
        request["query"] = text
    if process == "risk_rating":
        request["severity"] = amt
    return request


def submit_case_source_app(process: str) -> str | None:
    """Default source_app label when submitting from the dashboard form."""
    return submit_case_form_spec(process).get("source_app")


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
