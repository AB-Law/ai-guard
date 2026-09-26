"""Bounded-cardinality metric labels — never high-cardinality IDs."""

from __future__ import annotations

import re

# Cap length so a buggy caller cannot explode the time series set.
_MAX_LEN = 64
_SAFE = re.compile(r"^[a-zA-Z0-9_./:{}\-]+$")

# HTTP outcomes only — keep the enum tiny.
REQUEST_OUTCOMES = frozenset({"ok", "client_error", "server_error"})
GUARD_DECISIONS = frozenset({"allow", "block", "escalate"})
APPROVAL_OUTCOMES = frozenset({"approved", "denied", "error"})

# Prefer FastAPI route templates (params are names, not values).
_ROUTE_ALIASES: dict[str, str] = {
    "/": "/",
}


def sanitize_label(value: object | None, *, default: str = "unknown") -> str:
    """Normalize a label value; reject empty / unsafe / overlong strings."""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if len(text) > _MAX_LEN:
        text = text[:_MAX_LEN]
    if not _SAFE.match(text):
        return default
    # Reject shapes that look like opaque IDs even if they match _SAFE.
    if _looks_like_high_cardinality(text):
        return default
    return text


def _looks_like_high_cardinality(text: str) -> bool:
    """Heuristic: UUIDs / long hex / case-/call-id prefixes are not labels."""
    lower = text.lower()
    if lower.startswith(("case-", "guard-", "call-")):
        return True
    # UUID v4-ish
    if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        lower,
    ):
        return True
    # Long bare hex (trace ids, etc.)
    return bool(re.fullmatch(r"[0-9a-f]{16,}", lower))


def bound_route(route: object | None) -> str:
    """Map a path or FastAPI route template to a low-cardinality route label."""
    if route is None:
        return "unknown"
    text = str(route).strip() or "unknown"
    if text in _ROUTE_ALIASES:
        return _ROUTE_ALIASES[text]
    # Collapse accidental concrete IDs that leaked into the path.
    text = re.sub(
        r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "/{id}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"/(case-|guard-)[A-Za-z0-9_\-]+", r"/\1{id}", text)
    return sanitize_label(text, default="other")


def bound_process(process: object | None) -> str:
    return sanitize_label(process, default="unknown")


def bound_source_app(source_app: object | None) -> str:
    return sanitize_label(source_app, default="unknown")


def bound_request_outcome(outcome: object | None) -> str:
    text = str(outcome or "").strip().lower()
    return text if text in REQUEST_OUTCOMES else "ok"


def bound_guard_decision(decision: object | None) -> str:
    text = str(decision or "").strip().lower()
    return text if text in GUARD_DECISIONS else "allow"


def bound_approval_outcome(outcome: object | None) -> str:
    text = str(outcome or "").strip().lower()
    if text in {"approve", "approved"}:
        return "approved"
    if text in {"reject", "denied", "rejected"}:
        return "denied"
    if text == "error":
        return "error"
    return "error"


def outcome_from_status_code(status_code: int) -> str:
    if status_code >= 500:
        return "server_error"
    if status_code >= 400:
        return "client_error"
    return "ok"
