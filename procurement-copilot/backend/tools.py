"""The agent's tools. Two are read-only (never gated by Aegis — see
skip_tools in agent.py); the other six have real side effects on this app's
own store and are gated by @aiguard through AiGuardMiddleware before they
ever run.
"""

from __future__ import annotations

from langchain_core.tools import tool

from store import STORE, _next_id, _now
from vendors import lookup as lookup_vendor_record


@tool
def lookup_vendor(vendor_id: str) -> dict:
    """Look up a vendor's status, country, and category on the vendor master
    list. Read-only — always call this before proposing an action for a
    vendor you haven't already looked up in this conversation."""
    v = lookup_vendor_record(vendor_id)
    if v is None:
        return {"found": False, "vendor_id": vendor_id}
    return {
        "found": True,
        "vendor_id": v.vendor_id,
        "name": v.name,
        "status": v.status,
        "country": v.country,
        "category": v.category,
        "recent_orders": STORE.recent_orders.get(vendor_id, [])[-5:],
    }


@tool
def check_budget_remaining(department: str, amount: float) -> dict:
    """Check whether a department has enough budget remaining for a
    purchase, before proposing it. Read-only."""
    dept = department.lower().strip()
    remaining = STORE.budgets.get(dept)
    if remaining is None:
        return {"found": False, "department": department}
    return {
        "found": True,
        "department": dept,
        "remaining": remaining,
        "sufficient": remaining >= amount,
    }


@tool
def create_purchase_order(vendor_id: str, amount: float, item: str, department: str = "") -> dict:
    """Create a real purchase order with a vendor. This is the default
    action for an ordinary, in-policy request — only use it when nothing
    about the request looks unusual."""
    po_id = _next_id("PO")
    record = {
        "po_id": po_id,
        "vendor_id": vendor_id,
        "amount": amount,
        "item": item,
        "department": department,
        "created_at": _now(),
    }
    STORE.purchase_orders.append(record)
    STORE.record_order(vendor_id, amount, item)
    dept = department.lower().strip()
    if dept in STORE.budgets:
        STORE.budgets[dept] -= amount
    return {"status": "created", **record}


@tool
def request_approval(vendor_id: str, amount: float, item: str, reason: str) -> dict:
    """Ask a human to review and approve this request yourself, instead of
    creating the purchase order directly — use this when you're uncertain
    whether the request is safe to auto-approve, even if nothing is
    definitively wrong with it."""
    req_id = _next_id("APR")
    record = {
        "request_id": req_id,
        "vendor_id": vendor_id,
        "amount": amount,
        "item": item,
        "reason": reason,
        "created_at": _now(),
    }
    STORE.approval_requests.append(record)
    return {"status": "approval_requested", **record}


@tool
def flag_duplicate_or_split_po(vendor_id: str, item: str, reason: str) -> dict:
    """Flag this request as a possible duplicate or split purchase order
    (the same vendor/item ordered again shortly after a similar order, or
    what looks like one large purchase broken into several smaller ones to
    dodge an approval threshold). Use this instead of creating the order
    when lookup_vendor's recent_orders looks suspicious."""
    flag_id = _next_id("FRAUD")
    record = {
        "flag_id": flag_id,
        "vendor_id": vendor_id,
        "item": item,
        "reason": reason,
        "created_at": _now(),
    }
    STORE.fraud_flags.append(record)
    return {"status": "flagged", **record}


@tool
def request_documentation(vendor_id: str, item: str, doc_type: str) -> dict:
    """Ask the requester for supporting documentation (e.g. a signed
    Statement of Work for professional services) before this can proceed —
    use this when the request is the kind of category that needs paperwork
    you don't have, rather than approving or rejecting outright."""
    doc_id = _next_id("DOC")
    record = {
        "doc_request_id": doc_id,
        "vendor_id": vendor_id,
        "item": item,
        "doc_type": doc_type,
        "created_at": _now(),
    }
    STORE.documentation_requests.append(record)
    return {"status": "documentation_requested", **record}


@tool
def escalate_to_trade_compliance(vendor_id: str, amount: float, item: str, reason: str) -> dict:
    """Escalate this request to the trade compliance team — use this when a
    vendor's country or the item itself raises an export-control concern,
    rather than the generic request_approval."""
    case_id = _next_id("TC")
    record = {
        "case_id": case_id,
        "vendor_id": vendor_id,
        "amount": amount,
        "item": item,
        "reason": reason,
        "created_at": _now(),
    }
    STORE.compliance_escalations.append(record)
    return {"status": "escalated_to_trade_compliance", **record}


@tool
def reject_request(vendor_id: str, amount: float, item: str, reason: str) -> dict:
    """Decline this request outright — no purchase order, no approval
    request. Use this only for requests that should never be fulfilled
    regardless of who approves them (e.g. a categorically prohibited
    purchase), not for ordinary uncertainty."""
    rejection_id = _next_id("REJ")
    record = {
        "rejection_id": rejection_id,
        "vendor_id": vendor_id,
        "amount": amount,
        "item": item,
        "reason": reason,
        "created_at": _now(),
    }
    STORE.rejections.append(record)
    return {"status": "rejected", **record}


ALL_TOOLS = [
    lookup_vendor,
    check_budget_remaining,
    create_purchase_order,
    request_approval,
    flag_duplicate_or_split_po,
    request_documentation,
    escalate_to_trade_compliance,
    reject_request,
]

READ_ONLY_TOOL_NAMES = {"lookup_vendor", "check_budget_remaining"}

TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
