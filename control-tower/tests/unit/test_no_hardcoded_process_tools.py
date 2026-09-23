"""Grep-guard: process-specific tool/process names must not be hardcoded in guardrails/agent."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Process-specific tool names — must come from YAML config, not guardrail code.
_FORBIDDEN_TOOL_LITERALS = (
    "create_purchase_order",
    "send_payment",
    "modify_vendor_banking_details",
    "verify_identity",
    "disburse_funds",
)

_FORBIDDEN_PROCESS_LITERALS = (
    "procurement_review",
    "onboarding_kyc",
)

_GUARDRAILS_DIR = _PROJECT_ROOT / "guardrails"
_AGENT_RUNTIME_FILES = (
    _PROJECT_ROOT / "agent" / "graph.py",
    _PROJECT_ROOT / "knowledge" / "rag.py",
)


def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _string_literals(source: str) -> list[str]:
    return re.findall(r"""(['"])(.*?)\1""", source, flags=re.DOTALL)


@pytest.mark.parametrize("tool_name", _FORBIDDEN_TOOL_LITERALS)
def test_guardrails_have_no_process_specific_tool_literals(tool_name: str) -> None:
    hits: list[str] = []
    for path in _py_files(_GUARDRAILS_DIR):
        text = path.read_text(encoding="utf-8")
        for quote, lit in _string_literals(text):
            if lit == tool_name:
                hits.append(f"{path.relative_to(_PROJECT_ROOT)}: {quote}{tool_name}{quote}")
    assert not hits, f"Hardcoded tool name {tool_name!r} in guardrails:\n" + "\n".join(hits)


@pytest.mark.parametrize("process_name", _FORBIDDEN_PROCESS_LITERALS)
def test_guardrails_have_no_hardcoded_process_names(process_name: str) -> None:
    hits: list[str] = []
    for path in _py_files(_GUARDRAILS_DIR):
        text = path.read_text(encoding="utf-8")
        for quote, lit in _string_literals(text):
            if lit == process_name:
                hits.append(f"{path.relative_to(_PROJECT_ROOT)}")
    assert not hits, f"Hardcoded process {process_name!r} in guardrails: {hits}"


def test_agent_runtime_has_no_hardcoded_procurement_default() -> None:
    """graph/rag must not force procurement_review as a default process string."""
    needle = "procurement_review"
    hits: list[str] = []
    for path in _AGENT_RUNTIME_FILES:
        text = path.read_text(encoding="utf-8")
        for quote, lit in _string_literals(text):
            if lit == needle:
                hits.append(str(path.relative_to(_PROJECT_ROOT)))
    assert not hits, f"Hardcoded {needle!r} in agent runtime: {hits}"
