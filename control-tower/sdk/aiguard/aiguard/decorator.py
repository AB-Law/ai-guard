"""@guard — wrap any plain Python function that acts as an agent tool so it's
evaluated by the control tower before it runs.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from .client import GuardClient, default_client
from .exceptions import AiGuardBlocked, AiGuardEscalated

F = TypeVar("F", bound=Callable[..., Any])


def guard(
    *,
    tool_name: str | None = None,
    process: str | None = None,
    rationale: str | Callable[..., str] | None = None,
    context: list[str] | Callable[..., list[str]] | None = None,
    client: GuardClient | None = None,
) -> Callable[[F], F]:
    """Evaluate a call against the tower before running the wrapped function.

    - tool_name: defaults to the function's own name.
    - rationale/context: a static value, or a callable receiving the same
      args/kwargs the wrapped function was called with — use this to explain
      *why* the call should be allowed (e.g. cite the record that justifies
      it) the same way an LLM agent's rationale would.
    - Raises AiGuardBlocked or AiGuardEscalated on anything but "allow"; the
      wrapped function does not run in either case.

    >>> @guard(tool_name="create_purchase_order", process="procurement_review")
    ... def create_purchase_order(vendor_id: str, amount: float) -> dict:
    ...     ...  # your real implementation
    """

    def decorator(fn: F) -> F:
        name = tool_name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            rat = rationale(*args, **kwargs) if callable(rationale) else (rationale or "")
            ctx = context(*args, **kwargs) if callable(context) else list(context or [])
            guard_client = client or default_client()
            decision = guard_client.evaluate(
                tool_name=name,
                tool_args=dict(kwargs),
                agent_rationale=rat,
                context_texts=ctx,
                process=process,
            )
            if decision["decision"] == "block":
                raise AiGuardBlocked(decision)
            if decision["decision"] == "escalate":
                raise AiGuardEscalated(decision)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
