"""Agent tools — bound only via process allow-list; no ambient execution."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from configs.loader import ProcessConfig

DISALLOWED_TOOL_STUBS = (
    "send_payment",
    "modify_vendor_banking_details",
    "disburse_funds",
    "wire_transfer",
    "suspend_account",
    "delete_knowledge_document",
)


@dataclass
class ToolSideEffects:
    """Records tool executions for tests / audit of side effects."""

    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        event = {"tool_name": tool_name, **kwargs}
        self.events.append(event)
        return event

    def clear(self) -> None:
        self.events.clear()


def create_purchase_order(
    *,
    vendor_id: str,
    amount: float,
    item: str | None = None,
    side_effects: ToolSideEffects | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    result = {
        "status": "created",
        "po_id": f"PO-{vendor_id}-{int(amount)}",
        "vendor_id": vendor_id,
        "amount": amount,
        "item": item,
    }
    if side_effects is not None:
        side_effects.record("create_purchase_order", **result)
    return result


def request_approval(
    *,
    call_id: str | None = None,
    reason: str | None = None,
    vendor_id: str | None = None,
    amount: float | None = None,
    item: str | None = None,
    side_effects: ToolSideEffects | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    result = {
        "status": "approval_requested",
        "call_id": call_id,
        "reason": reason or "human approval requested",
        "vendor_id": vendor_id,
        "amount": amount,
        "item": item,
    }
    if side_effects is not None:
        side_effects.record("request_approval", **result)
    return result


def verify_identity(
    *,
    applicant_id: str | None = None,
    vendor_id: str | None = None,
    item: str | None = None,
    side_effects: ToolSideEffects | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Onboarding KYC — mark identity as verified (demo stub)."""
    aid = applicant_id or vendor_id or "unknown"
    result = {
        "status": "verified",
        "applicant_id": aid,
        "item": item,
    }
    if side_effects is not None:
        side_effects.record("verify_identity", **result)
    return result


def send_payment(**kwargs: Any) -> dict[str, Any]:
    """Stub — must never be bound to the agent tool registry."""
    raise RuntimeError("send_payment must not execute; gateway should block first")


def modify_vendor_banking_details(**kwargs: Any) -> dict[str, Any]:
    """Stub — must never be bound to the agent tool registry."""
    raise RuntimeError(
        "modify_vendor_banking_details must not execute; gateway should block first"
    )


def disburse_funds(**kwargs: Any) -> dict[str, Any]:
    """Stub — must never be bound to the agent tool registry."""
    raise RuntimeError("disburse_funds must not execute; gateway should block first")


def submit_expense_report(
    *,
    employee_id: str | None = None,
    vendor_id: str | None = None,
    amount: float,
    item: str | None = None,
    side_effects: ToolSideEffects | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Finance — submit an expense report (demo stub)."""
    eid = employee_id or vendor_id or "unknown"
    result = {
        "status": "submitted",
        "expense_id": f"EXP-{eid}-{int(amount)}",
        "employee_id": eid,
        "amount": amount,
        "item": item,
    }
    if side_effects is not None:
        side_effects.record("submit_expense_report", **result)
    return result


def flag_for_finance_review(
    *,
    call_id: str | None = None,
    reason: str | None = None,
    employee_id: str | None = None,
    vendor_id: str | None = None,
    amount: float | None = None,
    item: str | None = None,
    side_effects: ToolSideEffects | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Finance — low-friction escalate to a human finance reviewer."""
    eid = employee_id or vendor_id
    result = {
        "status": "finance_review_requested",
        "call_id": call_id,
        "reason": reason or "finance review requested",
        "employee_id": eid,
        "amount": amount,
        "item": item,
    }
    if side_effects is not None:
        side_effects.record("flag_for_finance_review", **result)
    return result


def wire_transfer(**kwargs: Any) -> dict[str, Any]:
    """Stub — must never be bound to the agent tool registry."""
    raise RuntimeError("wire_transfer must not execute; gateway should block first")


def assign_risk_rating(
    *,
    customer_id: str | None = None,
    vendor_id: str | None = None,
    amount: float,
    rating: str | None = None,
    item: str | None = None,
    side_effects: ToolSideEffects | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Risk rating — write a severity score (amount = 1–5 scale for gateway)."""
    cid = customer_id or vendor_id or "unknown"
    result = {
        "status": "rated",
        "customer_id": cid,
        "severity": amount,
        "rating": rating or f"severity-{int(amount)}",
        "item": item,
    }
    if side_effects is not None:
        side_effects.record("assign_risk_rating", **result)
    return result


def request_manual_review(
    *,
    call_id: str | None = None,
    reason: str | None = None,
    customer_id: str | None = None,
    vendor_id: str | None = None,
    amount: float | None = None,
    item: str | None = None,
    side_effects: ToolSideEffects | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Risk rating — request a human risk analyst review."""
    cid = customer_id or vendor_id
    result = {
        "status": "manual_review_requested",
        "call_id": call_id,
        "reason": reason or "manual risk review requested",
        "customer_id": cid,
        "amount": amount,
        "item": item,
    }
    if side_effects is not None:
        side_effects.record("request_manual_review", **result)
    return result


def suspend_account(**kwargs: Any) -> dict[str, Any]:
    """Stub — must never be bound to the agent tool registry."""
    raise RuntimeError("suspend_account must not execute; gateway should block first")


def search_knowledge_base(
    *,
    query: str | None = None,
    item: str | None = None,
    side_effects: ToolSideEffects | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """RAG bot — read-only knowledge search (demo stub)."""
    q = query or item or ""
    result = {
        "status": "ok",
        "query": q,
        "hits": [{"snippet": f"(demo) results for: {q}"}],
    }
    if side_effects is not None:
        side_effects.record("search_knowledge_base", **result)
    return result


def escalate_to_human_agent(
    *,
    call_id: str | None = None,
    reason: str | None = None,
    query: str | None = None,
    item: str | None = None,
    side_effects: ToolSideEffects | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """RAG bot — hand off to a human agent."""
    result = {
        "status": "escalated_to_human",
        "call_id": call_id,
        "reason": reason or "human agent requested",
        "query": query or item,
    }
    if side_effects is not None:
        side_effects.record("escalate_to_human_agent", **result)
    return result


def delete_knowledge_document(**kwargs: Any) -> dict[str, Any]:
    """Stub — must never be bound to the agent tool registry."""
    raise RuntimeError(
        "delete_knowledge_document must not execute; gateway should block first"
    )


_TOOL_IMPLS: dict[str, Callable[..., dict[str, Any]]] = {
    "create_purchase_order": create_purchase_order,
    "request_approval": request_approval,
    "verify_identity": verify_identity,
    "send_payment": send_payment,
    "modify_vendor_banking_details": modify_vendor_banking_details,
    "disburse_funds": disburse_funds,
    "submit_expense_report": submit_expense_report,
    "flag_for_finance_review": flag_for_finance_review,
    "wire_transfer": wire_transfer,
    "assign_risk_rating": assign_risk_rating,
    "request_manual_review": request_manual_review,
    "suspend_account": suspend_account,
    "search_knowledge_base": search_knowledge_base,
    "escalate_to_human_agent": escalate_to_human_agent,
    "delete_knowledge_document": delete_knowledge_document,
}


def get_bound_tools(config: ProcessConfig) -> dict[str, Callable[..., dict[str, Any]]]:
    """Return only tools listed in ProcessConfig.allowed_tools."""
    allowed = {t.name for t in config.allowed_tools}
    return {name: _TOOL_IMPLS[name] for name in allowed if name in _TOOL_IMPLS}


def _filter_kwargs(fn: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return kwargs
    allowed = {
        name
        for name, p in sig.parameters.items()
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    return {k: v for k, v in kwargs.items() if k in allowed}


def execute_bound_tool(
    config: ProcessConfig,
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    side_effects: ToolSideEffects | None = None,
) -> dict[str, Any]:
    bound = get_bound_tools(config)
    if tool_name not in bound:
        raise PermissionError(f"Tool {tool_name!r} is not bound for this process")
    fn = bound[tool_name]
    kwargs = _filter_kwargs(fn, dict(tool_args))
    if side_effects is not None and "side_effects" in inspect.signature(fn).parameters:
        kwargs["side_effects"] = side_effects
    return fn(**kwargs)
