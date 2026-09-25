"""Shared ChatOpenAI client for guardrail judges — reuse across calls."""

from __future__ import annotations

import os
import threading
from typing import Any

_lock = threading.Lock()
_llm: Any | None = None
_llm_key: tuple[str, str] | None = None

# Shared request timeout — long enough for parallel judge wall-clock; evidence
# previously used 30s alone, but three concurrent judges share one client.
_DEFAULT_TIMEOUT = 60.0


def get_chat_openai() -> Any:
    """Return a process-scoped ChatOpenAI for the current OPENAI_API_KEY/MODEL.

    Reconstructs when key or model env vars change (tests / configure flips).
    """
    global _llm, _llm_key
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")
    key = (api_key, model_name)

    with _lock:
        if _llm is None or _llm_key != key:
            from langchain_openai import ChatOpenAI

            _llm = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                timeout=_DEFAULT_TIMEOUT,
            )
            _llm_key = key
        return _llm


def reset_chat_openai_cache() -> None:
    """Drop the cached client — for tests that flip OPENAI_* between cases."""
    global _llm, _llm_key
    with _lock:
        _llm = None
        _llm_key = None
