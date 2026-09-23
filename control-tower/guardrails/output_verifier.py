"""Output verifier — groundedness of agent rationale against context chunks."""

from __future__ import annotations

import re

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


def _content_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


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
    claim_tokens = re.findall(r"[a-z0-9]+", claim.lower())
    if len(claim_tokens) < 3:
        return False
    chunk_lower = chunk.lower()
    for i in range(len(claim_tokens) - 2):
        phrase = " ".join(claim_tokens[i : i + 3])
        if phrase in chunk_lower:
            return True
    return False


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


def verify(rationale: str, context_chunks: list[str]) -> VerificationResult:
    """
    Score how well rationale claims are supported by context chunks.

    evidence_score = supported_claims / max(total_claims, 1)
    """
    claims = _split_claims(rationale)
    if not context_chunks:
        return VerificationResult(
            evidence_score=0.0,
            unsupported_claims=claims if claims else [rationale] if rationale.strip() else [],
        )

    if not claims:
        return VerificationResult(evidence_score=1.0, unsupported_claims=[])

    unsupported: list[str] = []
    supported = 0
    for claim in claims:
        if _claim_supported(claim, context_chunks):
            supported += 1
        else:
            unsupported.append(claim)

    score = supported / max(len(claims), 1)
    return VerificationResult(evidence_score=score, unsupported_claims=unsupported)
