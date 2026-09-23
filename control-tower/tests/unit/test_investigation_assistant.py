"""Investigation assistant — offline RAG + mocked LLM citations."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.schemas import AuditLogEntry, GatewayDecision
from investigation_assistant.qa_agent import (
    InvestigationAnswer,
    answer_question,
    build_investigation_kb,
    index_audit_entries,
    referenced_doc_ids,
    retrieve_investigation_context,
)


def _flagged_transcript() -> list[AuditLogEntry]:
    """Fixture audit transcript with a known policy_check escalate entry."""
    return [
        AuditLogEntry(
            entry_id="entry-retrieval-1",
            process="procurement_review",
            step_id="retrieve",
            event_type="retrieval",
            payload={"case_id": "case-flag", "chunk_ids": ["chunk:policy:escalation"]},
            scores=None,
            timestamp="2026-01-01T00:00:00+00:00",
            prev_hash="0" * 64,
            entry_hash="a" * 64,
        ),
        AuditLogEntry(
            entry_id="entry-policy-escalate-42",
            process="procurement_review",
            step_id="evaluate_tool_call",
            event_type="policy_check",
            payload={
                "case_id": "case-flag",
                "call_id": "call-1",
                "tool_name": "create_purchase_order",
            },
            scores=GatewayDecision(
                call_id="call-1",
                decision="escalate",
                reason=(
                    "Amount exceeds auto-approve limit; flagged for human review "
                    "because risk_score >= threshold"
                ),
                policy_refs=["chunk:policy:escalation"],
                risk_score=75,
                confidence_score=0.70,
                evidence_score=0.65,
            ),
            timestamp="2026-01-01T00:00:01+00:00",
            prev_hash="a" * 64,
            entry_hash="b" * 64,
        ),
        AuditLogEntry(
            entry_id="entry-retrieval-clean",
            process="procurement_review",
            step_id="retrieve",
            event_type="retrieval",
            payload={"case_id": "case-ok", "chunk_ids": ["chunk:policy:auto_approve"]},
            scores=None,
            timestamp="2026-01-01T00:00:02+00:00",
            prev_hash="b" * 64,
            entry_hash="c" * 64,
        ),
    ]


def _high_amount_case_entries() -> list[AuditLogEntry]:
    """Escalate case whose reason is on the audit row — must not pull injection quote."""
    return [
        AuditLogEntry(
            entry_id="entry-ha-retrieve",
            process="procurement_review",
            step_id="retrieve",
            event_type="retrieval",
            payload={
                "case_id": "high_amount_escalate",
                "chunk_ids": ["chunk:policy:escalation", "chunk:vendor:V-1001"],
            },
            scores=None,
            timestamp="2026-01-01T00:00:00+00:00",
            prev_hash="0" * 64,
            entry_hash="d" * 64,
        ),
        AuditLogEntry(
            entry_id="entry-ha-escalate",
            process="procurement_review",
            step_id="evaluate_tool_call",
            event_type="policy_check",
            payload={
                "case_id": "high_amount_escalate",
                "call_id": "call-ha",
                "tool_name": "create_purchase_order",
            },
            scores=GatewayDecision(
                call_id="call-ha",
                decision="escalate",
                reason="Amount 50000.0 exceeds auto-approve limit 10000.0",
                policy_refs=["approval_threshold.risk_score_gte:70"],
                risk_score=80,
                confidence_score=0.80,
                evidence_score=0.70,
            ),
            timestamp="2026-01-01T00:00:01+00:00",
            prev_hash="d" * 64,
            entry_hash="e" * 64,
        ),
    ]


def _injection_case_entries() -> list[AuditLogEntry]:
    return [
        AuditLogEntry(
            entry_id="entry-inj-retrieve",
            process="procurement_review",
            step_id="retrieve",
            event_type="retrieval",
            payload={
                "case_id": "injection_planted",
                "chunk_ids": ["chunk:injected:quote", "chunk:policy:auto_approve"],
            },
            scores=None,
            timestamp="2026-01-01T00:00:00+00:00",
            prev_hash="0" * 64,
            entry_hash="f" * 64,
        ),
        AuditLogEntry(
            entry_id="entry-inj-flag",
            process="procurement_review",
            step_id="evaluate_tool_call",
            event_type="policy_check",
            payload={
                "case_id": "injection_planted",
                "call_id": "call-inj",
            },
            scores=GatewayDecision(
                call_id="call-inj",
                decision="block",
                reason="Prompt injection detected in retrieved quote",
                policy_refs=["chunk:injected:quote"],
                risk_score=95,
                confidence_score=0.90,
                evidence_score=0.50,
            ),
            timestamp="2026-01-01T00:00:01+00:00",
            prev_hash="f" * 64,
            entry_hash="1" * 64,
        ),
    ]


def test_index_audit_retrieve_flagged_entry(project_root: Path) -> None:
    entries = _flagged_transcript()
    kb = index_audit_entries(entries)
    hits = kb.retrieve("why was this flagged escalate risk", k=3)
    assert hits
    hit_ids = {h.id for h in hits}
    assert "audit:entry-policy-escalate-42" in hit_ids


def test_mocked_answer_cites_entry_id(project_root: Path) -> None:
    entries = _flagged_transcript()
    flagged_id = "entry-policy-escalate-42"
    kb = build_investigation_kb(entries, project_root=project_root)

    mock = InvestigationAnswer(
        answer=(
            "This case was flagged for escalation because the amount exceeded "
            "the auto-approve limit and risk_score met the threshold."
        ),
        cited_entry_ids=[flagged_id],
        cited_chunk_ids=["chunk:policy:escalation"],
    )
    result = answer_question(
        "why was this flagged",
        kb=kb,
        audit_entries=entries,
        mock_answer=mock,
    )
    assert flagged_id in result.cited_entry_ids
    assert "escalat" in result.answer.lower() or "flagged" in result.answer.lower()


def test_build_investigation_kb_indexes_only_referenced_seed_docs(
    project_root: Path,
) -> None:
    entries = _flagged_transcript()
    kb = build_investigation_kb(entries, project_root=project_root)

    assert kb.get_by_id("chunk:policy:escalation") is not None
    assert kb.get_by_id("chunk:policy:auto_approve") is not None  # case-ok retrieval
    # Planted injection must not enter an escalate case that never retrieved it
    assert kb.get_by_id("chunk:injected:quote") is None
    assert kb.get_by_id("audit:entry-policy-escalate-42") is not None


def test_high_amount_context_excludes_injection_quote(project_root: Path) -> None:
    """Regression: generic 'why flagged?' must not cite the injection fixture."""
    entries = _high_amount_case_entries()
    assert "chunk:injected:quote" not in referenced_doc_ids(entries)

    kb = build_investigation_kb(entries, project_root=project_root)
    hits = retrieve_investigation_context(
        kb,
        "Why was this flagged?",
        audit_entries=entries,
        k=6,
    )
    hit_ids = {h.id for h in hits}
    assert "audit:entry-ha-escalate" in hit_ids
    assert "chunk:injected:quote" not in hit_ids
    assert any("50000" in h.text for h in hits if h.id.startswith("audit:"))
    # Referenced policy/vendor ok; injection never referenced → absent from KB
    assert kb.get_by_id("chunk:injected:quote") is None
    assert kb.get_by_id("chunk:policy:escalation") is not None
    assert "chunk:policy:escalation" in hit_ids


def test_injection_case_still_includes_planted_quote(project_root: Path) -> None:
    entries = _injection_case_entries()
    assert "chunk:injected:quote" in referenced_doc_ids(entries)

    kb = build_investigation_kb(entries, project_root=project_root)
    hits = retrieve_investigation_context(
        kb,
        "Why was this flagged?",
        audit_entries=entries,
        k=6,
    )
    hit_ids = {h.id for h in hits}
    assert "chunk:injected:quote" in hit_ids
    assert "audit:entry-inj-flag" in hit_ids
    assert any("SYSTEM OVERRIDE" in h.text for h in hits)


@pytest.mark.live
def test_live_investigation_answer(project_root: Path) -> None:
    import os

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        pytest.skip("OPENAI_API_KEY not set")

    entries = _flagged_transcript()
    kb = build_investigation_kb(entries, project_root=project_root)
    result = answer_question(
        "why was this flagged for escalation?",
        kb=kb,
        audit_entries=entries,
        mock_answer=None,
    )
    assert result.answer
    assert "entry-policy-escalate-42" in result.cited_entry_ids
