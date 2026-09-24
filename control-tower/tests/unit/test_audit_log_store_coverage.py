"""Tests for audit/log_store.py tamper/restore and edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from audit.log_store import (
    GENESIS_PREV_HASH,
    AppendInput,
    AuditLogStore,
    canonical_json,
    compute_entry_hash,
)
from contracts.schemas import GatewayDecision


def test_canonical_json_sorting() -> None:
    """Test that canonical_json produces sorted, compact JSON."""
    payload = {"z": 1, "a": 2, "m": 3}
    result = canonical_json(payload)
    # Keys should be sorted
    assert result == '{"a":2,"m":3,"z":1}'


def test_canonical_json_nested() -> None:
    """Test canonical JSON with nested structures."""
    payload = {
        "outer": {"z": 1, "a": 2},
        "list": [3, 2, 1],
    }
    result = canonical_json(payload)
    assert '"outer"' in result
    assert '"list"' in result


def test_compute_entry_hash_deterministic() -> None:
    """Test that compute_entry_hash is deterministic."""
    prev_hash = "prev123"
    payload = {"key": "value"}
    timestamp = "2024-01-01T00:00:00Z"
    
    hash1 = compute_entry_hash(prev_hash, payload, timestamp)
    hash2 = compute_entry_hash(prev_hash, payload, timestamp)
    
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest


def test_compute_entry_hash_changes_with_different_inputs() -> None:
    """Test that hash changes when inputs change."""
    payload = {"key": "value"}
    timestamp = "2024-01-01T00:00:00Z"
    
    hash1 = compute_entry_hash("prev1", payload, timestamp)
    hash2 = compute_entry_hash("prev2", payload, timestamp)
    hash3 = compute_entry_hash("prev1", {"key": "different"}, timestamp)
    hash4 = compute_entry_hash("prev1", payload, "2024-01-02T00:00:00Z")
    
    assert hash1 != hash2
    assert hash1 != hash3
    assert hash1 != hash4


def test_audit_log_store_init_creates_db(tmp_path: Path) -> None:
    """Test that AuditLogStore creates database on init."""
    db_path = tmp_path / "test_audit.db"
    store = AuditLogStore(db_path)
    
    assert db_path.exists()
    store.close()


def test_audit_log_store_clear(tmp_path: Path) -> None:
    """Test clearing all audit entries."""
    db_path = tmp_path / "clear_test.db"
    store = AuditLogStore(db_path)
    
    # Add some entries
    store.append(AppendInput(
        process="test",
        step_id="s1",
        event_type="retrieval",
        payload={"data": "test1"},
    ))
    store.append(AppendInput(
        process="test",
        step_id="s2",
        event_type="tool_call",
        payload={"data": "test2"},
    ))
    
    assert len(store.query()) == 2
    
    store.clear()
    assert len(store.query()) == 0
    
    store.close()


def test_audit_log_store_demo_corrupt_entry_without_entry_id(tmp_path: Path) -> None:
    """Test corrupting an entry without specifying entry_id."""
    db_path = tmp_path / "corrupt_test.db"
    store = AuditLogStore(db_path)
    
    # Add several entries
    for i in range(5):
        store.append(AppendInput(
            process="test",
            step_id=f"s{i}",
            event_type="retrieval",
            payload={"index": i},
        ))
    
    # Corrupt without specifying entry_id (should pick one automatically)
    result = store.demo_corrupt_entry()
    
    assert "entry_id" in result
    assert "original_hash" in result
    
    # Verify chain is now invalid
    assert store.verify_chain() is False
    
    store.close()


def test_audit_log_store_demo_corrupt_entry_with_entry_id(tmp_path: Path) -> None:
    """Test corrupting a specific entry."""
    db_path = tmp_path / "corrupt_specific.db"
    store = AuditLogStore(db_path)
    
    # Add entries
    entry1 = store.append(AppendInput(
        process="test",
        step_id="s1",
        event_type="retrieval",
        payload={"data": "test"},
    ))
    
    # Corrupt the specific entry
    result = store.demo_corrupt_entry(entry1.entry_id)
    
    assert result["entry_id"] == entry1.entry_id
    assert result["original_hash"] == entry1.entry_hash
    
    # Chain should be invalid
    valid, first_invalid = store.verify_chain_detailed()
    assert valid is False
    assert first_invalid == entry1.entry_id
    
    store.close()


def test_audit_log_store_demo_corrupt_entry_no_entries_raises(tmp_path: Path) -> None:
    """Test that corrupting with no entries raises ValueError."""
    db_path = tmp_path / "empty_corrupt.db"
    store = AuditLogStore(db_path)
    
    with pytest.raises(ValueError, match="no audit entries to tamper with"):
        store.demo_corrupt_entry()
    
    store.close()


def test_audit_log_store_demo_corrupt_entry_nonexistent_id_raises(tmp_path: Path) -> None:
    """Test that corrupting non-existent entry raises ValueError."""
    db_path = tmp_path / "bad_corrupt.db"
    store = AuditLogStore(db_path)
    
    store.append(AppendInput(
        process="test",
        step_id="s1",
        event_type="retrieval",
        payload={},
    ))
    
    with pytest.raises(ValueError, match="entry .* not found"):
        store.demo_corrupt_entry("nonexistent-entry-id")
    
    store.close()


def test_audit_log_store_demo_restore_entry(tmp_path: Path) -> None:
    """Test restoring a corrupted entry."""
    db_path = tmp_path / "restore_test.db"
    store = AuditLogStore(db_path)
    
    # Add entries
    for i in range(3):
        store.append(AppendInput(
            process="test",
            step_id=f"s{i}",
            event_type="retrieval",
            payload={"index": i},
        ))
    
    # Corrupt
    result = store.demo_corrupt_entry()
    assert store.verify_chain() is False
    
    # Restore
    store.demo_restore_entry(result["entry_id"], result["original_hash"])
    assert store.verify_chain() is True
    
    store.close()


def test_audit_log_store_query_with_process_filter(tmp_path: Path) -> None:
    """Test querying with process filter."""
    db_path = tmp_path / "query_process.db"
    store = AuditLogStore(db_path)
    
    store.append(AppendInput(
        process="procurement",
        step_id="s1",
        event_type="retrieval",
        payload={},
    ))
    store.append(AppendInput(
        process="finance",
        step_id="s2",
        event_type="retrieval",
        payload={},
    ))
    
    results = store.query(process="procurement")
    assert len(results) == 1
    assert results[0].process == "procurement"
    
    store.close()


def test_audit_log_store_query_with_event_type_filter(tmp_path: Path) -> None:
    """Test querying with event_type filter."""
    db_path = tmp_path / "query_event.db"
    store = AuditLogStore(db_path)
    
    store.append(AppendInput(
        process="test",
        step_id="s1",
        event_type="retrieval",
        payload={},
    ))
    store.append(AppendInput(
        process="test",
        step_id="s2",
        event_type="tool_call",
        payload={},
    ))
    
    results = store.query(event_type="tool_call")
    assert len(results) == 1
    assert results[0].event_type == "tool_call"
    
    store.close()


def test_audit_log_store_query_with_limit_and_offset(tmp_path: Path) -> None:
    """Test querying with limit and offset."""
    db_path = tmp_path / "query_limit.db"
    store = AuditLogStore(db_path)
    
    # Add 10 entries
    for i in range(10):
        store.append(AppendInput(
            process="test",
            step_id=f"s{i}",
            event_type="retrieval",
            payload={"index": i},
        ))
    
    # Query with limit
    results = store.query(limit=3, offset=0)
    assert len(results) == 3
    
    # Query with offset
    results = store.query(limit=3, offset=3)
    assert len(results) == 3
    
    store.close()


def test_audit_log_store_query_order_desc(tmp_path: Path) -> None:
    """Test querying with descending order."""
    db_path = tmp_path / "query_order.db"
    store = AuditLogStore(db_path)
    
    entry1 = store.append(AppendInput(
        process="test",
        step_id="s1",
        event_type="retrieval",
        payload={},
    ))
    entry2 = store.append(AppendInput(
        process="test",
        step_id="s2",
        event_type="retrieval",
        payload={},
    ))
    
    # Default order is asc
    results_asc = store.query(order="asc")
    assert results_asc[0].entry_id == entry1.entry_id
    assert results_asc[1].entry_id == entry2.entry_id
    
    # Desc order
    results_desc = store.query(order="desc")
    assert results_desc[0].entry_id == entry2.entry_id
    assert results_desc[1].entry_id == entry1.entry_id
    
    store.close()


def test_audit_log_store_append_with_custom_entry_id_and_timestamp(tmp_path: Path) -> None:
    """Test appending with custom entry_id and timestamp."""
    db_path = tmp_path / "custom_append.db"
    store = AuditLogStore(db_path)
    
    custom_entry_id = "custom-entry-123"
    custom_timestamp = "2024-01-01T12:00:00Z"
    
    entry = store.append(AppendInput(
        process="test",
        step_id="s1",
        event_type="retrieval",
        payload={},
        entry_id=custom_entry_id,
        timestamp=custom_timestamp,
    ))
    
    assert entry.entry_id == custom_entry_id
    assert entry.timestamp == custom_timestamp
    
    store.close()


def test_audit_log_store_append_with_scores(tmp_path: Path) -> None:
    """Test appending entry with gateway decision scores."""
    db_path = tmp_path / "scores_append.db"
    store = AuditLogStore(db_path)
    
    decision = GatewayDecision(
        decision="block",
        reason="Policy violation",
        risk_score=85,
        confidence_score=0.9,
        evidence_score=0.8,
        policy_refs=["chunk:policy:1"],
        call_id="call-123",
    )
    
    entry = store.append(AppendInput(
        process="test",
        step_id="s1",
        event_type="policy_check",
        payload={},
        scores=decision,
    ))
    
    assert entry.scores is not None
    assert entry.scores.decision == "block"
    assert entry.scores.risk_score == 85
    
    # Query it back
    results = store.query()
    assert len(results) == 1
    assert results[0].scores is not None
    assert results[0].scores.decision == "block"
    
    store.close()


def test_audit_log_store_verify_chain_detailed_returns_none_when_valid(tmp_path: Path) -> None:
    """Test that verify_chain_detailed returns None for valid chain."""
    db_path = tmp_path / "valid_chain.db"
    store = AuditLogStore(db_path)
    
    store.append(AppendInput(
        process="test",
        step_id="s1",
        event_type="retrieval",
        payload={},
    ))
    
    valid, first_invalid = store.verify_chain_detailed()
    assert valid is True
    assert first_invalid is None
    
    store.close()


def test_genesis_prev_hash_is_64_zeros() -> None:
    """Test that GENESIS_PREV_HASH is correct."""
    assert GENESIS_PREV_HASH == "0" * 64
    assert len(GENESIS_PREV_HASH) == 64
