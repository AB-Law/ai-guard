"""Tests for the shared OpenAI-compatible chat client configuration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from guardrails.llm import (
    evidence_structured_output_method,
    get_chat_openai,
    reset_chat_openai_cache,
    structured_output_method,
    tool_binding_kwargs,
    use_decomposed_judges,
)


@pytest.fixture(autouse=True)
def reset_client_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AEGIS_LLM_TIMEOUT", raising=False)
    monkeypatch.delenv("AEGIS_LMSTUDIO_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("AEGIS_LLM_DECOMPOSE", raising=False)
    reset_chat_openai_cache()
    yield
    reset_chat_openai_cache()


def test_local_endpoint_uses_ollama_api_key_and_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://127.0.0.1:11434/v1"
    monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    monkeypatch.setenv("OPENAI_MODEL", "qwen2.5:3b")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)

    with patch("langchain_openai.ChatOpenAI") as chat_openai:
        first = get_chat_openai()
        second = get_chat_openai()

    assert first is second
    chat_openai.assert_called_once_with(
        model="qwen2.5:3b",
        api_key="ollama",
        base_url=base_url,
        timeout=300.0,
    )
    assert structured_output_method() == "function_calling"
    assert evidence_structured_output_method() == "json_schema"
    assert tool_binding_kwargs() == {"parallel_tool_calls": False}


def test_client_cache_rebuilds_when_base_url_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://first.example/v1")
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)

    with patch("langchain_openai.ChatOpenAI", side_effect=[object(), object()]) as chat_openai:
        first = get_chat_openai()
        monkeypatch.setenv("OPENAI_BASE_URL", "http://second.example/v1")
        second = get_chat_openai()

    assert first is not second
    assert chat_openai.call_count == 2


def test_missing_api_key_without_base_url_still_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        get_chat_openai()


def test_lmstudio_default_port_uses_placeholder_key_and_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://127.0.0.1:1234/v1"
    monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    monkeypatch.setenv("OPENAI_MODEL", "qwen2.5-7b-instruct")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)

    with patch("langchain_openai.ChatOpenAI") as chat_openai:
        get_chat_openai()

    chat_openai.assert_called_once_with(
        model="qwen2.5-7b-instruct",
        api_key="lm-studio",
        base_url=base_url,
        timeout=300.0,
        extra_body={"reasoning_effort": "none"},
    )
    assert structured_output_method() == "json_schema"
    assert evidence_structured_output_method() == "json_schema"
    assert tool_binding_kwargs() == {}


def test_lmstudio_provider_defaults_base_url_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "lm-studio")
    monkeypatch.setenv("OPENAI_MODEL", "local-model")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with patch("langchain_openai.ChatOpenAI") as chat_openai:
        get_chat_openai()

    chat_openai.assert_called_once_with(
        model="local-model",
        api_key="lm-studio",
        base_url="http://127.0.0.1:1234/v1",
        timeout=300.0,
        extra_body={"reasoning_effort": "none"},
    )


def test_lmstudio_provider_keeps_custom_port_and_explicit_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://host.docker.internal:1235/v1"
    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "lmstudio")
    monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "local-token")
    monkeypatch.setenv("OPENAI_MODEL", "loaded-model")

    with patch("langchain_openai.ChatOpenAI") as chat_openai:
        get_chat_openai()

    chat_openai.assert_called_once_with(
        model="loaded-model",
        api_key="local-token",
        base_url=base_url,
        timeout=300.0,
        extra_body={"reasoning_effort": "none"},
    )
    assert tool_binding_kwargs() == {}


def test_hosted_openai_keeps_function_calling_and_parallel_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)

    assert structured_output_method() == "function_calling"
    assert evidence_structured_output_method() == "function_calling"
    assert tool_binding_kwargs() == {"parallel_tool_calls": False}


def test_openai_base_url_uses_caller_key_and_function_calling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "https://api.openai.com/v1"
    monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)

    with patch("langchain_openai.ChatOpenAI") as chat_openai:
        get_chat_openai()

    chat_openai.assert_called_once_with(
        model="gpt-4o",
        api_key="sk-test",
        base_url=base_url,
        timeout=60.0,
    )
    assert structured_output_method() == "function_calling"
    assert evidence_structured_output_method() == "function_calling"
    assert tool_binding_kwargs() == {"parallel_tool_calls": False}


def test_openai_base_url_without_key_still_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        get_chat_openai()


def test_openai_provider_overrides_lmstudio_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "http://127.0.0.1:1234/v1"
    monkeypatch.setenv("AEGIS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")

    with patch("langchain_openai.ChatOpenAI") as chat_openai:
        get_chat_openai()

    chat_openai.assert_called_once_with(
        model="gpt-4o",
        api_key="sk-test",
        base_url=base_url,
        timeout=60.0,
    )
    assert structured_output_method() == "function_calling"
    assert tool_binding_kwargs() == {"parallel_tool_calls": False}


def test_decomposed_judges_auto_skips_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("AEGIS_LLM_DECOMPOSE", "auto")
    assert use_decomposed_judges() is False


def test_decomposed_judges_auto_on_for_lmstudio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("AEGIS_LLM_DECOMPOSE", "auto")
    assert use_decomposed_judges() is True


def test_decomposed_judges_always_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AEGIS_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("AEGIS_LLM_DECOMPOSE", "always")
    assert use_decomposed_judges() is True
