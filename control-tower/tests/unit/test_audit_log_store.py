"""Hash-chained audit log store."""

from __future__ import annotations

import json
import sqlite3

import pytest

from audit.log_store import GENESIS_PREV_HASH, AppendInput, AuditLogStore
from contracts.schemas import GatewayDecision


@pytest.fixture
def store(tmp_path) -> AuditLogStore:
    return AuditLogStore(tmp_path / "audit.db")


def test_genesis_prev_hash_constant() -> None:
    assert len(GENESIS_PREV_HASH) == 64
    assert set(GENESIS_PREV_HASH) == {"0"}


def test_append_chain_verifies(store: AuditLogStore) -> None:
    for i in range(5):
        store.append(
            AppendInput(
                process="procurement_review",
                step_id=f"step_{i}",
                event_type="policy_check",
                payload={"index": i},
                timestamp=f"2026-01-01T00:00:0{i}+00:00",
                entry_id=f"e-{i}",
            )
        )
    assert store.verify_chain() is True


def test_tampered_payload_breaks_chain(store: AuditLogStore) -> None:
    store.append(
        AppendInput(
            process="procurement_review",
            step_id="s1",
            event_type="tool_call",
            payload={"amount": 100},
            timestamp="2026-01-01T00:00:00+00:00",
            entry_id="e-1",
        )
    )
    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "UPDATE audit_log SET payload_json = ? WHERE entry_id = ?",
        (json.dumps({"amount": 999}), "e-1"),
    )
    conn.commit()
    conn.close()
    assert store.verify_chain() is False


def test_sequential_hash_links(store: AuditLogStore) -> None:
    first = store.append(
        AppendInput(
            process="procurement_review",
            step_id="a",
            event_type="retrieval",
            payload={"q": "limit"},
            timestamp="2026-01-01T00:00:00+00:00",
            entry_id="e-a",
        )
    )
    second = store.append(
        AppendInput(
            process="procurement_review",
            step_id="b",
            event_type="tool_call",
            payload={"tool": "create_purchase_order"},
            timestamp="2026-01-01T00:00:01+00:00",
            entry_id="e-b",
        )
    )
    assert first.prev_hash == GENESIS_PREV_HASH
    assert second.prev_hash == first.entry_hash


def test_query_by_process_and_event_type(store: AuditLogStore) -> None:
    store.append(
        AppendInput(
            process="procurement_review",
            step_id="s",
            event_type="retrieval",
            payload={},
            timestamp="2026-01-01T00:00:00+00:00",
            entry_id="e-r",
        )
    )
    store.append(
        AppendInput(
            process="onboarding_kyc",
            step_id="s",
            event_type="policy_check",
            payload={},
            timestamp="2026-01-01T00:00:01+00:00",
            entry_id="e-p",
        )
    )
    hits = store.query(process="procurement_review", event_type="retrieval")
    assert len(hits) == 1
    assert hits[0].entry_id == "e-r"


def test_append_with_scores(store: AuditLogStore) -> None:
    scores = GatewayDecision(
        call_id="c-1",
        decision="allow",
        reason="ok",
        policy_refs=[],
        risk_score=10,
        confidence_score=0.9,
        evidence_score=0.8,
    )
    entry = store.append(
        AppendInput(
            process="procurement_review",
            step_id="gateway",
            event_type="policy_check",
            payload={"call_id": "c-1"},
            scores=scores,
            timestamp="2026-01-01T00:00:00+00:00",
            entry_id="e-sc",
        )
    )
    assert entry.scores is not None
    assert entry.scores.decision == "allow"
