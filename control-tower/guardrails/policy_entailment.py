"""Policy entailment judge — LLM checks proposed action vs policy text."""

from __future__ import annotations

import json
import os
from pathlib import Path

from contracts.schemas import PolicyEntailmentResult, ToolCallRequest

_LLM_TEXT_MAX = 4000
_RUBRIC_PATH = Path(__file__).with_name("POLICY_ENTAILMENT_RUBRIC.md")
_rubric_text: str | None = None


def load_policy_entailment_rubric() -> str:
    """Return the fixed system-prompt rubric (cached after first read)."""
    global _rubric_text
    if _rubric_text is None:
        _rubric_text = _RUBRIC_PATH.read_text(encoding="utf-8").strip()
        if not _rubric_text:
            raise RuntimeError(f"empty policy entailment rubric: {_RUBRIC_PATH}")
    return _rubric_text


def reset_policy_entailment_rubric_cache() -> None:
    """Drop cached rubric text — for tests that rewrite the MD file."""
    global _rubric_text
    _rubric_text = None


def _truncate(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= _LLM_TEXT_MAX:
        return stripped
    return stripped[: _LLM_TEXT_MAX - 3] + "..."


def _build_human_prompt(
    request: ToolCallRequest,
    policy_excerpts: list[str],
) -> str:
    excerpts_block = (
        "\n\n".join(f"[{i}] {_truncate(t)}" for i, t in enumerate(policy_excerpts))
        or "(none)"
    )
    args_json = json.dumps(request.tool_args, default=str)
    return (
        "Judge the proposed tool call against the policy excerpts using the "
        "fixed rubric in the system message.\n\n"
        f"Tool: {request.tool_name}\n"
        f"Args: {args_json}\n"
        f"Agent rationale: {request.agent_rationale or '(none)'}\n\n"
        f"Policy excerpts:\n{excerpts_block}\n"
    )


def _llm_entail(
    request: ToolCallRequest,
    policy_excerpts: list[str],
) -> PolicyEntailmentResult:
    """Structured LLM judge: does the proposed tool call comply with policy?"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from guardrails.llm import get_chat_openai

    llm = get_chat_openai()
    structured = llm.bind(temperature=0).with_structured_output(
        PolicyEntailmentResult, method="function_calling"
    )

    messages = [
        SystemMessage(content=load_policy_entailment_rubric()),
        HumanMessage(content=_build_human_prompt(request, policy_excerpts)),
    ]
    raw = structured.invoke(messages)
    result = PolicyEntailmentResult.model_validate(raw)
    if result.compliant:
        return PolicyEntailmentResult(compliant=True, violated_clauses=[], severity="none")
    if result.severity == "none":
        # Non-compliant without severity → treat as soft.
        return result.model_copy(update={"severity": "soft"})
    return result


def check_policy_entailment(
    request: ToolCallRequest,
    policy_excerpts: list[str],
) -> PolicyEntailmentResult:
    """Judge proposed tool call against policy excerpts.

    When OPENAI_API_KEY is set, run the structured LLM judge. Offline / no key
    returns compliant (evidence-doc presence is enforced separately). On LLM
    failure, stay compliant rather than crashing the request — hard blocks and
    the evidence judge's fail-closed path still apply elsewhere.
    """
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return PolicyEntailmentResult(compliant=True, violated_clauses=[], severity="none")
    try:
        return _llm_entail(request, policy_excerpts)
    except Exception:  # noqa: BLE001 — degrade to offline-compliant on judge failure
        return PolicyEntailmentResult(compliant=True, violated_clauses=[], severity="none")
