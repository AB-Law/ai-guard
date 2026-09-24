"""Tests for investigation_assistant/qa_agent.py functions."""

from __future__ import annotations

from pathlib import Path

from contracts.schemas import AuditLogEntry, GatewayDecision
from investigation_assistant.qa_agent import (
    InvestigationAnswer,
    _entry_to_text,
    _parse_cited_entry_ids,
    answer_question,
    build_investigation_kb,
    entries_for_case,
    index_audit_entries,
    referenced_doc_ids,
    retrieve_investigation_context,
)
from knowledge.rag import KnowledgeBase


def test_entry_to_text_basic() -> None:
    """Test converting audit entry to text."""
    entry = AuditLogEntry(
        entry_id="entry-123",
        process="procurement_review",
        step_id="step-1",
        event_type="retrieval",
        payload={"case_id": "case-1", "query": "test query"},
        scores=None,
        timestamp="2024-01-01T00:00:00Z",
        prev_hash="prev",
        entry_hash="current",
    )
    
    text = _entry_to_text(entry)
    
    assert "entry_id=entry-123" in text
    assert "event_type=retrieval" in text
    assert "process=procurement_review" in text
    assert "step_id=step-1" in text
    assert "timestamp=2024-01-01T00:00:00Z" in text
    assert "case_id" in text


def test_entry_to_text_with_scores() -> None:
    """Test entry with gateway decision scores."""
    decision = GatewayDecision(
        decision="block",
        reason="Policy violation",
        risk_score=85,
        confidence_score=0.9,
        evidence_score=0.8,
        policy_refs=["chunk:policy:1", "chunk:policy:2"],
        call_id="call-123",
    )
    
    entry = AuditLogEntry(
        entry_id="entry-456",
        process="procurement_review",
        step_id="step-2",
        event_type="policy_check",
        payload={"tool_name": "send_payment"},
        scores=decision,
        timestamp="2024-01-01T00:00:00Z",
        prev_hash="prev",
        entry_hash="current",
    )
    
    text = _entry_to_text(entry)
    
    assert "decision=block" in text
    assert "risk_score=85" in text
    assert "reason=Policy violation" in text
    assert "policy_refs=" in text


def test_referenced_doc_ids_from_payload() -> None:
    """Test extracting doc IDs from audit entry payloads."""
    entries = [
        AuditLogEntry(
            entry_id="e1",
            process="test",
            step_id="s1",
            event_type="retrieval",
            payload={
                "chunk_ids": ["chunk:policy:1", "chunk:vendor:2"],
                "context_refs": ["chunk:policy:3"],
            },
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h",
        ),
    ]
    
    doc_ids = referenced_doc_ids(entries)
    
    assert "chunk:policy:1" in doc_ids
    assert "chunk:vendor:2" in doc_ids
    assert "chunk:policy:3" in doc_ids
    assert len(doc_ids) == 3


def test_referenced_doc_ids_from_scores() -> None:
    """Test extracting doc IDs from scores.policy_refs."""
    decision = GatewayDecision(
        decision="allow",
        reason="Approved",
        risk_score=10,
        confidence_score=0.95,
        evidence_score=0.9,
        policy_refs=["chunk:policy:auto_approve"],
        call_id="call-1",
    )
    
    entries = [
        AuditLogEntry(
            entry_id="e2",
            process="test",
            step_id="s2",
            event_type="policy_check",
            payload={},
            scores=decision,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h",
        ),
    ]
    
    doc_ids = referenced_doc_ids(entries)
    
    assert "chunk:policy:auto_approve" in doc_ids


def test_referenced_doc_ids_filters_non_chunk_ids() -> None:
    """Test that non-chunk IDs are ignored."""
    entries = [
        AuditLogEntry(
            entry_id="e3",
            process="test",
            step_id="s3",
            event_type="retrieval",
            payload={
                "chunk_ids": ["chunk:valid:1", "not-a-chunk", 123, None],
                "other_refs": ["chunk:valid:2"],
            },
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h",
        ),
    ]
    
    doc_ids = referenced_doc_ids(entries)
    
    assert "chunk:valid:1" in doc_ids
    assert "not-a-chunk" not in doc_ids


def test_index_audit_entries_creates_chunks() -> None:
    """Test indexing audit entries into a KB."""
    entries = [
        AuditLogEntry(
            entry_id="e1",
            process="test",
            step_id="s1",
            event_type="retrieval",
            payload={"query": "test"},
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h",
        ),
    ]
    
    kb = index_audit_entries(entries)
    
    chunk = kb.get_by_id("audit:e1")
    assert chunk is not None
    assert "entry_id=e1" in chunk.text
    assert chunk.source == "audit:e1"


def test_index_audit_entries_into_existing_kb() -> None:
    """Test indexing into an existing KB."""
    kb = KnowledgeBase(collection_name="test_kb")
    
    entries = [
        AuditLogEntry(
            entry_id="e1",
            process="test",
            step_id="s1",
            event_type="tool_call",
            payload={},
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h",
        ),
    ]
    
    result_kb = index_audit_entries(entries, kb=kb)
    
    assert result_kb is kb
    assert kb.get_by_id("audit:e1") is not None


def test_parse_cited_entry_ids() -> None:
    """Test parsing entry IDs from chunk IDs."""
    chunk_ids = [
        "audit:entry-1",
        "audit:entry-2",
        "chunk:policy:1",
        "audit:entry-3",
        "not-an-audit-chunk",
    ]
    
    entry_ids = _parse_cited_entry_ids(chunk_ids)
    
    assert entry_ids == ["entry-1", "entry-2", "entry-3"]


def test_entries_for_case_filters_by_case_id() -> None:
    """Test filtering entries by case_id."""
    entries = [
        AuditLogEntry(
            entry_id="e1",
            process="test",
            step_id="s1",
            event_type="retrieval",
            payload={"case_id": "case-123"},
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h1",
        ),
        AuditLogEntry(
            entry_id="e2",
            process="test",
            step_id="s2",
            event_type="tool_call",
            payload={"case_id": "case-456"},
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h2",
        ),
    ]
    
    filtered = entries_for_case(entries, case_id="case-123", call_id=None)
    
    assert len(filtered) == 1
    assert filtered[0].entry_id == "e1"


def test_entries_for_case_filters_by_call_id() -> None:
    """Test filtering entries by call_id."""
    entries = [
        AuditLogEntry(
            entry_id="e1",
            process="test",
            step_id="s1",
            event_type="policy_check",
            payload={"call_id": "call-abc"},
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h1",
        ),
        AuditLogEntry(
            entry_id="e2",
            process="test",
            step_id="s2",
            event_type="tool_call",
            payload={"call_id": "call-xyz"},
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h2",
        ),
    ]
    
    filtered = entries_for_case(entries, case_id="case-123", call_id="call-abc")
    
    assert len(filtered) == 1
    assert filtered[0].entry_id == "e1"


def test_answer_question_with_mock() -> None:
    """Test answering with mock_answer bypasses LLM."""
    kb = KnowledgeBase(collection_name="test_kb")
    
    mock = InvestigationAnswer(
        answer="Mock answer",
        cited_entry_ids=["e1", "e2"],
        cited_chunk_ids=["chunk:policy:1"],
    )
    
    result = answer_question(
        "What happened?",
        kb=kb,
        audit_entries=None,
        mock_answer=mock,
    )
    
    assert result.answer == "Mock answer"
    assert result.cited_entry_ids == ["e1", "e2"]
    assert result.cited_chunk_ids == ["chunk:policy:1"]


def test_answer_question_with_no_chunks_returns_default() -> None:
    """Test when no context is found."""
    kb = KnowledgeBase(collection_name="empty_kb")
    
    # Mock the retrieve to return empty
    result = answer_question(
        "What happened?",
        kb=kb,
        audit_entries=[],
        mock_answer=InvestigationAnswer(
            answer="No relevant audit or policy context found.",
            cited_entry_ids=[],
            cited_chunk_ids=[],
        ),
    )
    
    assert "No relevant" in result.answer


def test_retrieve_investigation_context_with_audit_entries() -> None:
    """Test retrieval scoped to case audit entries."""
    kb = KnowledgeBase(collection_name="test_kb")
    
    # Index some audit entries
    entries = [
        AuditLogEntry(
            entry_id="e1",
            process="test",
            step_id="s1",
            event_type="retrieval",
            payload={"query": "vendor policy"},
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h",
        ),
    ]
    
    kb = index_audit_entries(entries, kb=kb)
    
    chunks = retrieve_investigation_context(
        kb, "vendor policy", audit_entries=entries, k=6
    )
    
    # Should include the indexed audit entry
    audit_ids = [c.id for c in chunks if c.id.startswith("audit:")]
    assert "audit:e1" in audit_ids


def test_build_investigation_kb_indexes_entries(project_root: Path) -> None:
    """Test building investigation KB from audit entries."""
    entries = [
        AuditLogEntry(
            entry_id="e1",
            process="procurement_review",
            step_id="s1",
            event_type="retrieval",
            payload={"chunk_ids": []},
            scores=None,
            timestamp="2024-01-01T00:00:00Z",
            prev_hash="p",
            entry_hash="h",
        ),
    ]
    
    kb = build_investigation_kb(entries, project_root=project_root)
    
    chunk = kb.get_by_id("audit:e1")
    assert chunk is not None
    assert "entry_id=e1" in chunk.text


def test_investigation_answer_model_defaults() -> None:
    """Test InvestigationAnswer model with defaults."""
    answer = InvestigationAnswer(answer="Test answer")
    
    assert answer.answer == "Test answer"
    assert answer.cited_entry_ids == []
    assert answer.cited_chunk_ids == []
