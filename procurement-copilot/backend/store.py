"""This app's own in-memory database — purchase orders, budgets, and every
other side effect its tools produce. Completely separate from Aegis; Aegis
never writes here and never executes anything here. It only tells us,
per tool call, whether we're allowed to.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_id_counter = itertools.count(1)


def _next_id(prefix: str) -> str:
    return f"{prefix}-{next(_id_counter):05d}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Store:
    purchase_orders: list[dict[str, Any]] = field(default_factory=list)
    approval_requests: list[dict[str, Any]] = field(default_factory=list)
    fraud_flags: list[dict[str, Any]] = field(default_factory=list)
    documentation_requests: list[dict[str, Any]] = field(default_factory=list)
    compliance_escalations: list[dict[str, Any]] = field(default_factory=list)
    rejections: list[dict[str, Any]] = field(default_factory=list)
    # Budgets are seeded once, spent down as create_purchase_order runs —
    # gives check_budget_remaining something real to report instead of a
    # random number every call.
    budgets: dict[str, float] = field(
        default_factory=lambda: {
            "engineering": 180_000.0,
            "marketing": 60_000.0,
            "facilities": 90_000.0,
            "sales": 40_000.0,
            "it": 220_000.0,
        }
    )
    # vendor_id -> list of recent order dicts, for flag_duplicate_or_split_po
    # to actually have something to look at instead of guessing.
    recent_orders: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def record_order(self, vendor_id: str, amount: float, item: str) -> None:
        self.recent_orders.setdefault(vendor_id, []).append(
            {"amount": amount, "item": item, "at": _now()}
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "purchase_orders": self.purchase_orders,
            "approval_requests": self.approval_requests,
            "fraud_flags": self.fraud_flags,
            "documentation_requests": self.documentation_requests,
            "compliance_escalations": self.compliance_escalations,
            "rejections": self.rejections,
            "budgets": self.budgets,
        }


STORE = Store()
