"""Unit tests for required-evidence presence check."""

from __future__ import annotations

from configs.loader import load_process
from guardrails.evidence_docs import known_evidence_doc_types, missing_required_evidence_docs


def test_known_evidence_doc_types_covers_shipped_labels() -> None:
    known = set(known_evidence_doc_types())
    assert "finance_policy" in known
    assert "procurement_policy" in known
    assert "vendor_master_list" in known


def test_empty_refs_misses_all_required() -> None:
    config = load_process("procurement_review")
    missing = missing_required_evidence_docs(config, [])
    assert missing == ["procurement_policy", "vendor_master_list"]


def test_vendor_only_misses_policy() -> None:
    config = load_process("procurement_review")
    missing = missing_required_evidence_docs(config, ["chunk:vendor:V-1001"])
    assert missing == ["procurement_policy"]


def test_policy_only_misses_vendor() -> None:
    config = load_process("procurement_review")
    missing = missing_required_evidence_docs(config, ["chunk:policy:auto_approve"])
    assert missing == ["vendor_master_list"]


def test_both_present_returns_empty() -> None:
    config = load_process("procurement_review")
    missing = missing_required_evidence_docs(
        config,
        ["chunk:policy:auto_approve", "chunk:vendor:V-1001"],
    )
    assert missing == []


def test_kyc_prefix_match() -> None:
    config = load_process("onboarding_kyc")
    assert missing_required_evidence_docs(config, []) == ["kyc_policy"]
    assert (
        missing_required_evidence_docs(config, ["chunk:kyc:identity_verification"]) == []
    )
