"""Contract tests — each process YAML loads with the expected allow/deny shape."""

from __future__ import annotations

from configs.loader import KNOWN_PROCESSES, load_process

_EXPECTED = {
    "procurement_review": {
        "allowed": {"create_purchase_order", "request_approval"},
        "disallowed": {"send_payment", "modify_vendor_banking_details"},
        "threshold": 60,
        "max_auto": {"create_purchase_order": 10000.0},
    },
    "onboarding_kyc": {
        "allowed": {"verify_identity", "request_approval"},
        "disallowed": {"disburse_funds"},
        "threshold": 60,
        "max_auto": {},
    },
    "finance": {
        "allowed": {"submit_expense_report", "flag_for_finance_review"},
        "disallowed": {"wire_transfer"},
        "threshold": 60,
        "max_auto": {"submit_expense_report": 5000.0},
    },
    "risk_rating": {
        "allowed": {"assign_risk_rating", "request_manual_review"},
        "disallowed": {"suspend_account"},
        "threshold": 60,
        "max_auto": {"assign_risk_rating": 3.0},
    },
    "rag_bot": {
        "allowed": {"search_knowledge_base", "escalate_to_human_agent"},
        "disallowed": {"delete_knowledge_document"},
        "threshold": 60,
        "max_auto": {},
    },
}


def test_known_processes_cover_expected_set() -> None:
    assert set(KNOWN_PROCESSES) == set(_EXPECTED)


def test_each_process_yaml_matches_contract() -> None:
    for name, expect in _EXPECTED.items():
        cfg = load_process(name)
        assert cfg.process == name
        assert {t.name for t in cfg.allowed_tools} == expect["allowed"]
        assert set(cfg.disallowed_tools) == expect["disallowed"]
        assert cfg.approval_threshold.risk_score_gte == expect["threshold"]
        for tool_name, limit in expect["max_auto"].items():
            tool = next(t for t in cfg.allowed_tools if t.name == tool_name)
            assert tool.max_auto_amount == limit
