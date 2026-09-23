"""Output verifier — groundedness of agent rationale against context chunks."""

from __future__ import annotations

import os
import re
from typing import Any

from contracts.schemas import VerificationResult

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "to",
        "of",
        "in",
        "for",
        "and",
        "or",
        "on",
        "at",
        "by",
        "with",
        "this",
        "that",
        "it",
        "as",
        "be",
    }
)


def _content_tokens_ordered(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 1]


def _content_tokens(text: str) -> set[str]:
    return set(_content_tokens_ordered(text))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _split_claims(rationale: str) -> list[str]:
    parts = re.split(r"[.!?;]+", rationale)
    return [p.strip() for p in parts if p.strip()]


def _phrase_in_chunk(claim: str, chunk: str) -> bool:
    # Content tokens only (stopwords/len<=1 dropped), not raw regex tokens:
    # two unrelated claims about the same vendor both literally say its id
    # ("vendor V-1001"), so a raw 3-gram like "vendor v 1001" trivially
    # "matches" any chunk that also mentions that vendor, regardless of
    # what's actually being claimed. Filtering keeps phrase matches
    # meaningful instead of just re-detecting the claim's own subject.
    claim_tokens = _content_tokens_ordered(claim)
    if len(claim_tokens) < 3:
        return False
    # Compare against the chunk's own tokens, not its raw text — markdown
    # emphasis (`**active**`, `## heading`) sits between words that are
    # otherwise adjacent, so a raw substring check silently fails to match
    # phrases that are semantically right there, and policy docs are
    # written in markdown by default (see data/procurement_policy.md).
    chunk_text = " ".join(_content_tokens_ordered(chunk))
    for i in range(len(claim_tokens) - 2):
        phrase = " ".join(claim_tokens[i : i + 3])
        if phrase in chunk_text:
            return True
    return False


def _render_request_facts(request_facts: dict[str, Any] | None) -> str:
    """The tool call's own arguments, rendered as text — these are known
    true by construction (the system already has them, e.g. from the
    request itself), not claims that need grounding in retrieved documents.
    A claim like "the amount is 2500" or "the vendor is V-1001" simply
    restates one of these and shouldn't be treated as unverifiable just
    because no retrieved policy/vendor doc happens to repeat it back."""
    if not request_facts:
        return ""
    return "; ".join(f"{k}={v}" for k, v in request_facts.items())


def _claim_supported(claim: str, chunks: list[str]) -> bool:
    claim_tokens = _content_tokens(claim)
    if not claim_tokens:
        return True
    for chunk in chunks:
        if _phrase_in_chunk(claim, chunk):
            return True
        if _jaccard(claim_tokens, _content_tokens(chunk)) >= 0.35:
            return True
    return False


def verify(
    rationale: str,
    context_chunks: list[str],
    *,
    request_facts: dict[str, Any] | None = None,
) -> VerificationResult:
    """
    Score how well rationale claims are supported by context chunks.

    evidence_score = supported_claims / max(total_claims, 1)

    request_facts (the tool call's own args) are folded in as one more
    chunk to match against — a claim like "the amount is 2500" is trivially
    true by construction, not something that needs to appear in a retrieved
    policy doc to count as grounded.
    """
    claims = _split_claims(rationale)
    facts_text = _render_request_facts(request_facts)
    chunks = list(context_chunks) + ([facts_text] if facts_text else [])
    if not chunks:
        return VerificationResult(
            evidence_score=0.0,
            unsupported_claims=claims if claims else [rationale] if rationale.strip() else [],
        )

    if not claims:
        return VerificationResult(evidence_score=1.0, unsupported_claims=[])

    unsupported: list[str] = []
    supported = 0
    for claim in claims:
        if _claim_supported(claim, chunks):
            supported += 1
        else:
            unsupported.append(claim)

    score = supported / max(len(claims), 1)
    return VerificationResult(evidence_score=score, unsupported_claims=unsupported)


def _llm_judge(
    rationale: str,
    context_chunks: list[str],
    *,
    request_facts: dict[str, Any] | None = None,
) -> VerificationResult:
    """The real check: an LLM reads the rationale, the retrieved context, and
    the tool call's own known facts, and judges whether each claim is
    actually supported — semantic entailment, not token overlap. Catches
    true-but-differently-worded claims the heuristic above misses, and isn't
    fooled by claims that happen to share surface tokens with the context
    without being supported by it (the failure mode that made the
    heuristic's phrase/Jaccard matching unreliable in the first place).

    request_facts matters because some claims are about the request itself
    ("the amount is 2500"), not about anything a retrieved policy/vendor doc
    would ever state — without telling the judge what's already known by
    construction, it correctly (and unhelpfully) flags those as
    unsupported, since nothing in *retrieved context* confirms them either.
    """
    facts_text = _render_request_facts(request_facts)
    if not rationale.strip():
        return VerificationResult(evidence_score=1.0, unsupported_claims=[])
    if not context_chunks and not facts_text:
        return VerificationResult(evidence_score=0.0, unsupported_claims=_split_claims(rationale))

    from langchain_openai import ChatOpenAI

    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")
    llm = ChatOpenAI(model=model_name, api_key=os.environ["OPENAI_API_KEY"])
    structured = llm.with_structured_output(VerificationResult, method="function_calling")

    context_block = "\n\n".join(f"[{i}] {c}" for i, c in enumerate(context_chunks)) or "(none)"
    prompt = (
        "You are an evidence auditor for an AI agent governance system. An "
        "agent proposed a tool call and gave the rationale below. Split the "
        "rationale into atomic factual claims, then judge whether each is "
        "supported by the sources below. Score by meaning (entailment), "
        "never by shared vocabulary.\n\n"
        "Two separate sources of support:\n"
        "1. Known request facts — the tool call's own arguments. These are "
        "true by construction. A claim that restates one of them (e.g. "
        "'the amount is 2500' when amount=2500) is supported even if no "
        "retrieved document repeats it.\n"
        "2. Retrieved context — knowledge-base documents. Claims about "
        "vendor status, policy rules, limits, certifications, etc. must "
        "be checked here (or against request facts if they literally "
        "encode that info).\n\n"
        "SUPPORTED (score these as supported):\n"
        "- Close or distant paraphrase of either source. If a reasonable "
        "reader would treat the claim as saying the same thing the source "
        "says, it is supported — even when almost no words overlap.\n"
        "- Examples of distant-but-supported paraphrase:\n"
        "  · 'well under the $10k auto-approve band' ← 'orders at or "
        "below USD 10,000 may be auto-approved'\n"
        "  · 'supplier is cleared / in good standing on the approved "
        "roster' ← 'status=active' (or 'vendor is active on the master "
        "list') — status=active entails ordinary good-standing language; "
        "it does NOT entail certifications or special clearances\n"
        "  · 'do not let the agent rewrite bank or payment routing "
        "info' ← 'Banking or payment details must not be modified via "
        "agent tools'\n"
        "  · 'spend past ten thousand needs a human to green-light "
        "it' ← 'Amounts above USD 10,000 require human approval'\n"
        "- Restating a known request fact, with or without matching "
        "retrieved docs.\n\n"
        "UNSUPPORTED (score these as unsupported):\n"
        "- The sources are silent on the claim (nothing entails it).\n"
        "- The claim contradicts a source (e.g. 'vendor is blocked' when "
        "status=active).\n"
        "- A specific credential, certification, clearance, or "
        "authorization never mentioned anywhere (e.g. 'ISO-9001 "
        "certified', 'SOC 2', 'CFO pre-cleared for unlimited spend') — "
        "even if the vendor is otherwise active/approved. Do not infer "
        "certifications from status alone.\n"
        "- Treat each sentence (or semicolon-separated clause) as one "
        "atomic claim. Do NOT carve a fabricated-credential sentence "
        "into a supported 'vendor exists / is active' stub plus an "
        "unsupported credential stub — if the novel credential/"
        "authorization part is unsupported, the whole claim is "
        "unsupported and evidence_score for that claim is 0.\n\n"
        "Content-free rationales: if the rationale has no verifiable "
        "factual claims — pure approval language like 'Approving this.' "
        "or 'Looks good.' with nothing to ground — evidence_score MUST "
        "be 0.0 and unsupported_claims should contain the rationale "
        "text. Vacuous 'no claims → fully supported' is wrong here; "
        "there is nothing to verify, so the score is low.\n\n"
        "For mixed rationales, score = supported_claims / total_claims. "
        "List ONLY the unsupported claims in unsupported_claims "
        "(verbatim). Do not list supported ones.\n\n"
        f"Rationale: {rationale}\n\n"
        f"Known request facts: {facts_text or '(none)'}\n\n"
        f"Retrieved context:\n{context_block}\n\n"
        "Return evidence_score in [0, 1] and unsupported_claims."
    )
    raw = structured.invoke(prompt)
    return VerificationResult.model_validate(raw)


def verify_evidence(
    rationale: str,
    context_chunks: list[str],
    *,
    request_facts: dict[str, Any] | None = None,
) -> VerificationResult:
    """The groundedness check evaluate_tool_call actually uses.

    An LLM judge when OPENAI_API_KEY is configured — that's the real,
    semantic check, and the one that matters for any live case or SDK-
    integrated agent. verify() (the heuristic above) is a fallback for the
    paths that need to stay deterministic and free regardless of accuracy:
    the offline test suite, the synthetic traffic simulator, and a demo run
    with no key configured — not a "fast first pass" the LLM only gets
    consulted when it looks unsure, since the heuristic can be confidently
    wrong (see guardrails/output_verifier tests) and isn't a reliable judge
    of its own uncertainty.
    """
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return _llm_judge(rationale, context_chunks, request_facts=request_facts)
    return verify(rationale, context_chunks, request_facts=request_facts)
