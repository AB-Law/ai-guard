"""Policy entailment judge — LLM checks proposed action vs policy text."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from contracts.schemas import PolicyEntailmentResult, ToolCallRequest

_LLM_TEXT_MAX = 4000
_RUBRIC_PATH = Path(__file__).with_name("POLICY_ENTAILMENT_RUBRIC.md")
_rubric_text: str | None = None


class _ActionShape(BaseModel):
    """First pass of the decomposed policy judge."""

    action_kind: Literal["escalate", "decline", "execute"]
    seeks_human_review: bool = False
    notes: str = ""


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
    *,
    action_shape: _ActionShape | None = None,
) -> str:
    excerpts_block = (
        "\n\n".join(f"[{i}] {_truncate(t)}" for i, t in enumerate(policy_excerpts))
        or "(none)"
    )
    args_json = json.dumps(request.tool_args, default=str)
    shape_block = ""
    if action_shape is not None:
        shape_block = (
            f"Action shape (from prior pass): kind={action_shape.action_kind}, "
            f"seeks_human_review={action_shape.seeks_human_review}, "
            f"notes={action_shape.notes or '(none)'}\n"
            "If kind is escalate/decline and policy would require human review "
            "for this situation, prefer compliant. If kind is execute and "
            "identity/KYC docs are incomplete while verifying, prefer hard "
            "violation.\n\n"
        )
    return (
        "Judge the proposed tool call against the policy excerpts using the "
        "fixed rubric in the system message.\n\n"
        f"{shape_block}"
        f"Tool: {request.tool_name}\n"
        f"Args: {args_json}\n"
        f"Agent rationale: {request.agent_rationale or '(none)'}\n\n"
        f"Policy excerpts:\n{excerpts_block}\n"
    )


def _normalize_entail_result(raw: object) -> PolicyEntailmentResult:
    result = PolicyEntailmentResult.model_validate(raw)
    if result.compliant:
        return PolicyEntailmentResult(compliant=True, violated_clauses=[], severity="none")
    if result.severity == "none":
        return result.model_copy(update={"severity": "soft"})
    return result


def _llm_entail_oneshot(
    request: ToolCallRequest,
    policy_excerpts: list[str],
) -> PolicyEntailmentResult:
    from langchain_core.messages import HumanMessage, SystemMessage

    from guardrails.llm import (
        get_chat_openai,
        invoke_structured,
        structured_output_method,
        structured_with_raw,
    )

    llm = get_chat_openai()
    structured = structured_with_raw(
        llm.bind(temperature=0), PolicyEntailmentResult, method=structured_output_method()
    )
    messages = [
        SystemMessage(content=load_policy_entailment_rubric()),
        HumanMessage(content=_build_human_prompt(request, policy_excerpts)),
    ]
    raw = invoke_structured(structured, messages)
    return _normalize_entail_result(raw)


def _llm_entail_decomposed(
    request: ToolCallRequest,
    policy_excerpts: list[str],
) -> PolicyEntailmentResult:
    """Classify action shape, then apply the full rubric with that hint."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from guardrails.llm import (
        get_chat_openai,
        invoke_structured,
        structured_output_method,
        structured_with_raw,
    )

    llm = get_chat_openai().bind(temperature=0)
    method = structured_output_method()
    shape_runnable = structured_with_raw(llm, _ActionShape, method=method)
    args_json = json.dumps(request.tool_args, default=str)
    shape_raw = invoke_structured(
        shape_runnable,
        (
            "Classify the proposed tool call's action shape.\n"
            "- escalate: seeking human approval / Trade Compliance / sign-off "
            "(e.g. request_approval)\n"
            "- decline: refusing or rejecting the action\n"
            "- execute: performing or auto-approving the business action "
            "(create PO, verify applicant, disburse, etc.)\n"
            "Set seeks_human_review=true when the tool or rationale is asking "
            "a human to review before proceeding.\n\n"
            f"Tool: {request.tool_name}\n"
            f"Args: {args_json}\n"
            f"Agent rationale: {request.agent_rationale or '(none)'}\n"
        ),
    )
    shape = _ActionShape.model_validate(shape_raw)

    judge = structured_with_raw(llm, PolicyEntailmentResult, method=method)
    messages = [
        SystemMessage(content=load_policy_entailment_rubric()),
        HumanMessage(
            content=_build_human_prompt(request, policy_excerpts, action_shape=shape)
        ),
    ]
    raw = invoke_structured(judge, messages)
    return _normalize_entail_result(raw)


def _llm_entail(
    request: ToolCallRequest,
    policy_excerpts: list[str],
) -> PolicyEntailmentResult:
    """Structured LLM judge: does the proposed tool call comply with policy?

    OpenAI uses one-shot. Local / compatible endpoints classify action shape
    first, then apply the rubric with that hint.
    """
    from guardrails.llm import use_decomposed_judges

    if use_decomposed_judges():
        return _llm_entail_decomposed(request, policy_excerpts)
    return _llm_entail_oneshot(request, policy_excerpts)


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
