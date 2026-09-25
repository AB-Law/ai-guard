"""Unit tests for output verifier."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from contracts.schemas import VerificationResult
from guardrails.output_verifier import verify, verify_evidence


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


def test_markdown_formatting_does_not_break_phrase_matching() -> None:
    """A phrase split by markdown emphasis (**active**) must still match —
    policy docs are written in markdown by default."""
    chunk = (
        "## Auto-approval\n\nPurchase orders at or below **USD 10,000** may "
        "be auto-approved when:\n\n- The vendor is **active** on the vendor "
        "master list."
    )
    rationale = "The vendor is active on the vendor master list."
    result = verify(rationale, [chunk])
    assert result.evidence_score >= 0.7


def test_shared_vendor_id_alone_does_not_count_as_support() -> None:
    """Two unrelated claims about the same vendor both literally say its id
    ('Vendor V-1001') — that overlap must not, by itself, make an invented
    claim look grounded."""
    chunk = "Vendor V-1001: name=Acme Supplies Ltd; status=active; country=US"
    rationale = "Vendor V-1001 is ISO-9001 certified and pre-cleared by the CFO for unlimited spend."
    result = verify(rationale, [chunk])
    assert result.evidence_score <= 0.4
    assert result.unsupported_claims


def test_verify_evidence_uses_heuristic_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("guardrails.output_verifier._llm_judge") as mock_judge:
        result = verify_evidence(
            "The amount is under the auto-approve limit of USD 10000.",
            ["Auto-approve limit is USD 10000 for standard vendors."],
        )
    mock_judge.assert_not_called()
    assert result.evidence_score >= 0.7


def test_verify_evidence_uses_llm_judge_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    fake_result = VerificationResult(evidence_score=0.5, unsupported_claims=["something"])
    with patch(
        "guardrails.output_verifier._llm_judge", return_value=fake_result
    ) as mock_judge:
        result = verify_evidence("some rationale", ["some chunk"])
    mock_judge.assert_called_once_with("some rationale", ["some chunk"], request_facts=None)
    assert result is fake_result


def test_verify_evidence_forwards_request_facts_to_llm_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    fake_result = VerificationResult(evidence_score=1.0, unsupported_claims=[])
    facts = {"vendor_id": "V-1001", "amount": 2500}
    with patch(
        "guardrails.output_verifier._llm_judge", return_value=fake_result
    ) as mock_judge:
        verify_evidence("some rationale", ["some chunk"], request_facts=facts)
    mock_judge.assert_called_once_with("some rationale", ["some chunk"], request_facts=facts)


def test_verify_evidence_fail_closed_when_judge_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    with (
        patch(
            "guardrails.output_verifier._llm_judge",
            side_effect=TimeoutError("judge timed out"),
        ),
        patch("guardrails.output_verifier.verify") as mock_verify,
    ):
        result = verify_evidence("some rationale", ["some chunk"])
    mock_verify.assert_not_called()
    assert result.evidence_score == 0.0
    assert result.judge_unavailable is True
    assert result.unsupported_claims == []


def test_verify_evidence_fail_closed_when_judge_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty structured output raises inside _llm_judge; verify_evidence fails closed."""
    from guardrails.llm import reset_chat_openai_cache

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    reset_chat_openai_cache()
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = None
    with (
        patch("guardrails.llm.get_chat_openai", return_value=mock_llm),
        patch("guardrails.output_verifier.verify") as mock_verify,
    ):
        result = verify_evidence("some rationale", ["some chunk"])
    mock_verify.assert_not_called()
    assert result.evidence_score == 0.0
    assert result.judge_unavailable is True


def test_llm_judge_empty_rationale_short_circuits_without_a_call() -> None:
    """No claims to check -> trivially supported, no LLM call needed.
    langchain_openai is imported lazily inside _llm_judge only past this
    short-circuit, so reaching here without ImportError already proves no
    call was attempted."""
    from guardrails.output_verifier import _llm_judge

    result = _llm_judge("", ["some chunk"])
    assert result.evidence_score == 1.0


def test_llm_judge_empty_context_short_circuits_without_a_call() -> None:
    from guardrails.output_verifier import _llm_judge

    result = _llm_judge("Vendor is active.", [])
    assert result.evidence_score == 0.0
    assert result.unsupported_claims


def test_verify_request_fact_alone_supports_a_claim_with_no_context_chunks() -> None:
    """A claim that just restates a request arg (amount=2500) shouldn't need
    to appear in a retrieved policy doc — the request itself already
    establishes it."""
    result = verify(
        "The amount is 2500.",
        [],
        request_facts={"vendor_id": "V-1001", "amount": 2500},
    )
    assert result.evidence_score == 1.0
    assert not result.unsupported_claims


def test_verify_request_facts_combine_with_context_chunks() -> None:
    result = verify(
        "The amount is 2500 and the vendor is active on the master list.",
        ["Vendor V-1001: name=Acme Supplies Ltd; status=active; country=US"],
        request_facts={"vendor_id": "V-1001", "amount": 2500},
    )
    assert result.evidence_score >= 0.5


def test_llm_judge_does_not_short_circuit_when_only_request_facts_are_present() -> None:
    """No context_chunks at all, but request_facts alone is enough reason to
    call the judge instead of auto-failing — a claim might be fully covered
    by the request's own args (e.g. process=onboarding_kyc has no retrieved
    docs but the request itself may still ground simple claims)."""
    from guardrails.llm import reset_chat_openai_cache
    from guardrails.output_verifier import _llm_judge

    reset_chat_openai_cache()
    fake_result = VerificationResult(evidence_score=1.0, unsupported_claims=[])
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = fake_result
    with patch("guardrails.llm.get_chat_openai", return_value=mock_llm) as mock_get:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-not-real"}):
            result = _llm_judge(
                "The amount is 2500.", [], request_facts={"vendor_id": "V-1001", "amount": 2500}
            )
    mock_get.assert_called_once()
    assert result.evidence_score == 1.0


def test_llm_judge_prompt_includes_request_facts() -> None:
    from guardrails.llm import reset_chat_openai_cache
    from guardrails.output_verifier import _llm_judge

    reset_chat_openai_cache()
    fake_result = VerificationResult(evidence_score=1.0, unsupported_claims=[])
    captured_prompt = {}

    def _capture_invoke(prompt: str):
        captured_prompt["value"] = prompt
        return fake_result

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.side_effect = _capture_invoke
    with patch("guardrails.llm.get_chat_openai", return_value=mock_llm):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test-not-real"}):
            _llm_judge(
                "The amount is 2500.",
                ["some policy chunk"],
                request_facts={"vendor_id": "V-1001", "amount": 2500},
            )
    assert "vendor_id=V-1001" in captured_prompt["value"]
    assert "amount=2500" in captured_prompt["value"]
