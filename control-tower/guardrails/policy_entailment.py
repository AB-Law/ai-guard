"""Policy entailment judge — LLM checks proposed action vs policy text."""

from __future__ import annotations

import json
import os

from contracts.schemas import PolicyEntailmentResult, ToolCallRequest

_LLM_TEXT_MAX = 4000


def _truncate(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= _LLM_TEXT_MAX:
        return stripped
    return stripped[: _LLM_TEXT_MAX - 3] + "..."


def _llm_entail(
    request: ToolCallRequest,
    policy_excerpts: list[str],
) -> PolicyEntailmentResult:
    """Structured LLM judge: does the proposed tool call comply with policy?"""
    from guardrails.llm import get_chat_openai

    llm = get_chat_openai()
    structured = llm.with_structured_output(PolicyEntailmentResult, method="function_calling")

    excerpts_block = (
        "\n\n".join(f"[{i}] {_truncate(t)}" for i, t in enumerate(policy_excerpts))
        or "(none)"
    )
    args_json = json.dumps(request.tool_args, default=str)
    prompt = (
        "You are a policy-compliance judge for an AI agent governance system. "
        "An agent proposed a tool call. Decide whether the proposed action "
        "complies with the semantic rules in the policy excerpts below.\n\n"
        "Focus on semantic / clause-level rules that an allow-list cannot "
        "express, for example:\n"
        "- Vendor must be active / in good standing on the master list\n"
        "- KYC / identity documents must be complete before verification\n"
        "- No split or duplicate POs to bypass amount bands\n"
        "- Required checks (budget, sanctions, receipts) must pass\n\n"
        "Do NOT re-litigate tool allow-lists or numeric amount caps — another "
        "gateway already enforces those. Only flag semantic policy meaning.\n\n"
        "Return:\n"
        "- compliant: true only if the proposal does not violate any semantic "
        "clause in the excerpts (or excerpts are silent / irrelevant)\n"
        "- violated_clauses: short clause labels or paraphrases for each "
        "violation (empty when compliant)\n"
        "- severity: 'none' when compliant; 'soft' for advisory / incomplete-"
        "evidence concerns that raise risk but need not force review alone; "
        "'hard' for clear contradictions (e.g. blocked vendor, incomplete KYC "
        "for auto-verify, explicit split-PO bypass)\n\n"
        f"Tool: {request.tool_name}\n"
        f"Args: {args_json}\n"
        f"Agent rationale: {request.agent_rationale or '(none)'}\n\n"
        f"Policy excerpts:\n{excerpts_block}\n"
    )
    raw = structured.invoke(prompt)
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
