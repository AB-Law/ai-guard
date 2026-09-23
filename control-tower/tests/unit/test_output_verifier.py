"""Unit tests for output verifier."""

from __future__ import annotations

from guardrails.output_verifier import verify


def test_rationale_quoting_chunk_high_score() -> None:
    chunk = "Auto-approve limit is USD 10000 for standard vendors."
    rationale = "The amount is under the auto-approve limit of USD 10000."
    result = verify(rationale, [chunk])
    assert result.evidence_score >= 0.7
    assert not result.unsupported_claims


def test_invented_certification_low_score() -> None:
    chunks = ["Vendor V-1001 is active in the master list."]
    rationale = "Vendor is ISO-9001 certified and ready for immediate PO."
    result = verify(rationale, chunks)
    assert result.evidence_score <= 0.4
    assert any("ISO-9001" in c for c in result.unsupported_claims)


def test_empty_context_zero_score() -> None:
    result = verify("Some claim about policy.", [])
    assert result.evidence_score == 0.0
    assert result.unsupported_claims
