"""Unit tests for required-evidence presence check."""

from __future__ import annotations

from configs.loader import ApprovalThreshold, ProcessConfig, load_process
from guardrails.evidence_docs import missing_required_evidence_docs


def _config_with_docs(*docs: str) -> ProcessConfig:
    return ProcessConfig(
        process="eval_unknown",
        allowed_tools=[],
        disallowed_tools=[],
        required_evidence_docs=list(docs),
        approval_threshold=ApprovalThreshold(risk_score_gte=60),
        knowledge_base_paths=[],
    )


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


def test_unknown_label_substring_hit() -> None:
    config = _config_with_docs("custom_handbook")
    assert (
        missing_required_evidence_docs(
            config, ["chunk:doc:custom_handbook:section_0"]
        )
        == []
    )


def test_unknown_label_substring_miss() -> None:
    config = _config_with_docs("custom_handbook")
    assert missing_required_evidence_docs(config, ["chunk:policy:auto_approve"]) == [
        "custom_handbook"
    ]
