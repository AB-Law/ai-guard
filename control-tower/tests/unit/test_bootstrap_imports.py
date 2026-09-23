"""Bootstrap exit gate — imports and schema types exist."""

from __future__ import annotations

import importlib


def test_key_packages_import() -> None:
    for module in (
        "pydantic",
        "yaml",
        "fastapi",
        "langgraph",
        "langchain_openai",
        "chromadb",
    ):
        importlib.import_module(module)


def test_schema_types_exported() -> None:
    from contracts.schemas import AuditLogEntry, GatewayDecision, ToolCallRequest

    assert ToolCallRequest.__name__ == "ToolCallRequest"
    assert GatewayDecision.__name__ == "GatewayDecision"
    assert AuditLogEntry.__name__ == "AuditLogEntry"
