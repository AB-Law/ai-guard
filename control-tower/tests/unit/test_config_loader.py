"""Process config loader tests."""

from __future__ import annotations

import pytest

from configs.loader import load_process


def test_load_procurement_review() -> None:
    cfg = load_process("procurement_review")
    assert cfg.process == "procurement_review"
    assert cfg.approval_threshold.risk_score_gte == 60
    allowed_names = {t.name for t in cfg.allowed_tools}
    assert "create_purchase_order" in allowed_names
    assert "request_approval" in allowed_names
    po = next(t for t in cfg.allowed_tools if t.name == "create_purchase_order")
    assert po.max_auto_amount == 10000


def test_disallowed_tools_include_payment_and_banking() -> None:
    cfg = load_process("procurement_review")
    assert "send_payment" in cfg.disallowed_tools
    assert "modify_vendor_banking_details" in cfg.disallowed_tools


def test_unknown_process_raises() -> None:
    with pytest.raises(ValueError, match="Unknown process"):
        load_process("claims_processing")


def test_load_onboarding_kyc() -> None:
    cfg = load_process("onboarding_kyc")
    assert cfg.process == "onboarding_kyc"
    allowed = {t.name for t in cfg.allowed_tools}
    assert "verify_identity" in allowed
    assert "create_purchase_order" not in allowed
    assert "disburse_funds" in cfg.disallowed_tools
    assert any("kyc_policy" in p for p in cfg.knowledge_base_paths)


def test_onboarding_and_procurement_tool_sets_differ() -> None:
    proc = load_process("procurement_review")
    kyc = load_process("onboarding_kyc")
    assert {t.name for t in proc.allowed_tools} != {t.name for t in kyc.allowed_tools}
    assert set(proc.disallowed_tools) != set(kyc.disallowed_tools)
