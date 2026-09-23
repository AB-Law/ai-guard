"""Agent tools — bound only via process allow-list; no ambient execution."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from configs.loader import ProcessConfig

DISALLOWED_TOOL_STUBS = (
    "send_payment",
    "modify_vendor_banking_details",
    "disburse_funds",
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


_TOOL_IMPLS: dict[str, Callable[..., dict[str, Any]]] = {
    "create_purchase_order": create_purchase_order,
    "request_approval": request_approval,
    "verify_identity": verify_identity,
    "send_payment": send_payment,
    "modify_vendor_banking_details": modify_vendor_banking_details,
    "disburse_funds": disburse_funds,
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
