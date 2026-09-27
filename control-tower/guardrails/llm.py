"""Shared ChatOpenAI client for guardrail judges — reuse across calls."""

from __future__ import annotations

import os
import threading
from typing import Any
from urllib.parse import urlparse

_lock = threading.Lock()
_llm: Any | None = None
_llm_key: tuple[str, str, str | None] | None = None

# Shared request timeout — long enough for parallel judge wall-clock; evidence
# previously used 30s alone, but three concurrent judges share one client.
_DEFAULT_TIMEOUT = 60.0
# Local OpenAI-compatible servers (LM Studio / Ollama) are much slower than
# hosted OpenAI, especially on CPU or heavy quantizations.
_LOCAL_TIMEOUT = 300.0

# LM Studio's local server defaults to this OpenAI-compatible base URL.
_LM_STUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
_LM_STUDIO_PORT = 1234
# Placeholder keys. Both servers ignore the value unless the user enabled auth;
# the OpenAI client still requires a non-empty key. LM Studio's own examples
# use "lm-studio".
_LM_STUDIO_API_KEY = "lm-studio"
_OLLAMA_API_KEY = "ollama"


def _provider_setting() -> str:
    """Explicit provider: openai, lmstudio, compatible, or empty (auto-detect)."""
    raw = os.environ.get("AEGIS_LLM_PROVIDER", "").strip().lower()
    normalized = raw.replace("-", "").replace("_", "")
    if normalized in {"lmstudio", "openai", "compatible", "ollama"}:
        return "compatible" if normalized == "ollama" else normalized
    return ""


def _url_is_lmstudio(base_url: str) -> bool:
    parsed = urlparse(base_url)
    if parsed.port == _LM_STUDIO_PORT:
        return True
    compact = base_url.lower().replace("-", "").replace("_", "")
    return "lmstudio" in compact


def configured_base_url() -> str | None:
    """Base URL for the active endpoint.

    Unset uses the OpenAI API, except ``AEGIS_LLM_PROVIDER=lmstudio``, which
    defaults to LM Studio's local server. An explicit ``OPENAI_BASE_URL`` is
    used for OpenAI, any other compatible server, or LM Studio on a custom port.
    """
    explicit = os.environ.get("OPENAI_BASE_URL", "").strip()
    if explicit:
        return explicit
    if _provider_setting() == "lmstudio":
        return _LM_STUDIO_BASE_URL
    return None


def endpoint_kind() -> str:
    """``openai``, ``compatible``, or ``lmstudio``.

    ``AEGIS_LLM_PROVIDER`` selects the kind directly (``ollama`` is
    ``compatible``). With no override, ``api.openai.com`` and an unset base
    URL are OpenAI, port 1234 or an ``lmstudio`` host is LM Studio, and every
    other ``OPENAI_BASE_URL`` is a generic OpenAI-compatible server.
    """
    setting = _provider_setting()
    if setting:
        return setting
    url = os.environ.get("OPENAI_BASE_URL", "").strip()
    if url and _url_is_lmstudio(url):
        return "lmstudio"
    if not url:
        return "openai"
    host = (urlparse(url).hostname or "").lower()
    if host == "api.openai.com":
        return "openai"
    return "compatible"


def structured_output_method() -> str:
    """Schema method for judges other than the evidence check.

    OpenAI and other compatible servers use function calling. LM Studio's
    structured-output API is ``json_schema``.
    """
    if endpoint_kind() == "lmstudio":
        return "json_schema"
    return "function_calling"


def evidence_structured_output_method() -> str:
    """Schema method for the evidence judge.

    OpenAI uses function calling. LM Studio and other local compatible
    servers use ``json_schema``.
    """
    if endpoint_kind() == "openai":
        return "function_calling"
    return "json_schema"


def use_decomposed_judges() -> bool:
    """Whether evidence/policy judges should use multi-step prompts.

    Hosted OpenAI stays on the fast one-shot path (already near ceiling).
    Local / compatible endpoints decompose by default — smaller models
    handle narrow sub-questions better than one entangled rubric.

    Override with ``AEGIS_LLM_DECOMPOSE=always|never|auto`` (default auto).
    """
    raw = os.environ.get("AEGIS_LLM_DECOMPOSE", "auto").strip().lower()
    if raw in {"always", "1", "true", "yes"}:
        return True
    if raw in {"never", "0", "false", "no"}:
        return False
    return endpoint_kind() != "openai"


def tool_binding_kwargs() -> dict[str, bool]:
    """Extra ``bind_tools`` kwargs for the active endpoint.

    OpenAI and other compatible servers receive ``parallel_tool_calls``.
    LM Studio's server rejects that field. The caller still requires exactly
    one tool call after the response.
    """
    if endpoint_kind() == "lmstudio":
        return {}
    return {"parallel_tool_calls": False}


def request_timeout() -> float:
    """HTTP timeout for chat completions.

    ``AEGIS_LLM_TIMEOUT`` overrides. Otherwise LM Studio / compatible local
    servers use a longer default than hosted OpenAI.
    """
    raw = os.environ.get("AEGIS_LLM_TIMEOUT", "").strip()
    if raw:
        return float(raw)
    if endpoint_kind() in {"lmstudio", "compatible"}:
        return _LOCAL_TIMEOUT
    return _DEFAULT_TIMEOUT


def chat_openai_kwargs() -> dict[str, Any]:
    """Provider-specific ChatOpenAI kwargs beyond model/key/base_url/timeout.

    LM Studio reasoning models default to thinking on; that can consume the
    whole token budget and leave ``content`` empty. ``reasoning_effort=none``
    turns thinking off on servers that honor it.
    """
    if endpoint_kind() != "lmstudio":
        return {}
    raw = os.environ.get("AEGIS_LMSTUDIO_REASONING_EFFORT", "none").strip()
    if not raw or raw.lower() in {"default", "-"}:
        return {}
    return {"extra_body": {"reasoning_effort": raw}}


def get_chat_openai(model_name: str | None = None) -> Any:
    """Return a process-scoped ChatOpenAI for OpenAI, LM Studio, or another compatible API.

    OpenAI requires ``OPENAI_API_KEY``. LM Studio and other local compatible
    servers accept a placeholder when that key is empty. Reconstruct the
    client when its settings change.
    """
    global _llm, _llm_key
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = configured_base_url()
    kind = endpoint_kind()
    if not api_key and base_url and kind != "openai":
        api_key = _LM_STUDIO_API_KEY if kind == "lmstudio" else _OLLAMA_API_KEY
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
                timeout=request_timeout(),
                **chat_openai_kwargs(),
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