"""Shared ChatOpenAI client for guardrail judges — reuse across calls."""

from __future__ import annotations

import os
import threading
from typing import Any

_lock = threading.Lock()
_llm: Any | None = None
_llm_key: tuple[str, str, str | None] | None = None

# Shared request timeout — long enough for parallel judge wall-clock; evidence
# previously used 30s alone, but three concurrent judges share one client.
_DEFAULT_TIMEOUT = 60.0


def get_chat_openai(model_name: str | None = None) -> Any:
    """Return a process-scoped ChatOpenAI for the configured compatible API.

    Ollama's OpenAI-compatible endpoint ignores its API key, but the client
    requires a non-empty value. Reconstruct the client when its settings change.
    """
    global _llm, _llm_key
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
    if not api_key and base_url:
        api_key = "ollama"
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    selected_model = model_name or os.environ.get("OPENAI_MODEL", "gpt-4o")
    key = (api_key, selected_model, base_url)

    with _lock:
        if _llm is None or _llm_key != key:
            from langchain_openai import ChatOpenAI

            _llm = ChatOpenAI(
                model=selected_model,
                api_key=api_key,
                base_url=base_url,
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


def invoke_structured(structured: Any, prompt: Any) -> Any:
    """Invoke a structured LLM chain and record token usage when exposed.

    Expects runnables built with ``structured_with_raw`` (include_raw=True)
    when the LangChain version supports it. Missing usage is recorded as
    unavailable — never fabricated as zero.
    """
    from telemetry.metrics import record_model_usage_from_response

    result = structured.invoke(prompt)
    if isinstance(result, dict) and "parsed" in result:
        record_model_usage_from_response(result)
        parsed = result.get("parsed")
        err = result.get("parsing_error")
        if parsed is None and err is not None:
            raise err
        return parsed
    record_model_usage_from_response(result)
    return result


def structured_with_raw(llm: Any, schema: Any, *, method: str = "function_calling") -> Any:
    """Build a structured-output runnable that retains the raw AIMessage."""
    try:
        return llm.with_structured_output(schema, method=method, include_raw=True)
    except TypeError:
        return llm.with_structured_output(schema, method=method)