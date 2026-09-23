"""aiguard — drop-in client for the Aegis control tower.

    import aiguard
    aiguard.configure(api_url="http://127.0.0.1:8000", process="procurement_review")

    @aiguard.guard()
    def create_purchase_order(vendor_id: str, amount: float) -> dict:
        ...

LangChain integration (needs `pip install aiguard[langchain]`) is a separate
import, not re-exported here, so the base package never requires langchain:

    from aiguard.langchain_handler import AiGuardCallbackHandler
"""

from __future__ import annotations

from .client import GuardClient
from .config import configure, get_config
from .decorator import guard
from .exceptions import AiGuardBlocked, AiGuardDecisionError, AiGuardEscalated, AiGuardError

__all__ = [
    "configure",
    "get_config",
    "guard",
    "GuardClient",
    "AiGuardError",
    "AiGuardDecisionError",
    "AiGuardBlocked",
    "AiGuardEscalated",
]
