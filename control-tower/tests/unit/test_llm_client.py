"""Tests for the shared OpenAI-compatible chat client configuration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from guardrails.llm import get_chat_openai, reset_chat_openai_cache


@pytest.fixture(autouse=True)
def reset_client_cache():
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

    with patch("langchain_openai.ChatOpenAI") as chat_openai:
        first = get_chat_openai()
        second = get_chat_openai()

    assert first is second
    chat_openai.assert_called_once_with(
        model="qwen2.5:3b",
        api_key="ollama",
        base_url=base_url,
        timeout=60.0,
    )


def test_client_cache_rebuilds_when_base_url_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://first.example/v1")

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

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        get_chat_openai()