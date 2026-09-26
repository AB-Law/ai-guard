"""Sensitive-data detection / redaction / policy tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from audit.log_store import AppendInput, AuditLogStore
from audit.redact import redact_injection_span, redact_payload
from audit.sensitive_data.detectors import detect_in_text, detect_in_value
from audit.sensitive_data.export import sanitize_for_export
from audit.sensitive_data.policy import (
    DetectorPolicy,
    SensitiveDataPolicy,
    default_policy,
    resolve_policy,
)
from configs.loader import (
    ApprovalThreshold,
    ProcessConfig,
    SensitiveDataConfig,
    SensitiveDetectorConfig,
    load_process,
)
from contracts.schemas import (
    PolicyEntailmentResult,
    ToolCallRequest,
    VerificationResult,
)
from guardrails.evaluate import apply_sensitive_data_policy, evaluate_tool_call

IBAN = "DE89370400440532013000"
API_KEY = "sk-live_secret_key_abc123xyz"
BEARER = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload"
EMAIL = "alice.smith@example.com"
PHONE = "+1 (415) 555-2671"
SSN = "123-45-6789"


def test_detect_email_phone_ssn_secrets() -> None:
    text = f"Contact {EMAIL} or {PHONE}. SSN {SSN}. key={API_KEY} {BEARER}"
    findings = detect_in_text(text)
    types = {f.type for f in findings}
    assert "email" in types
    assert "phone" in types
    assert "gov_id_us_ssn" in types
    assert "api_key" in types
    assert "bearer_token" in types
    for f in findings:
        assert EMAIL not in f.preview or f.type != "email"
        assert API_KEY not in f.preview
        assert f.value_hash.startswith("sha256:")


def test_nested_payload_detection_and_redaction() -> None:
    raw = {
        "tool_args": {
            "memo": f"Wire {IBAN} to {EMAIL}",
            "meta": {"api_key": API_KEY, "items": [f"ssn: {SSN}"]},
        },
        "prompt": f"Call {PHONE}",
    }
    findings = detect_in_value(raw)
    paths = {f.path for f in findings}
    assert any("memo" in p for p in paths)
    assert any("api_key" in p for p in paths)
    redacted = redact_payload(raw)
    blob = str(redacted)
    assert IBAN not in blob
    assert EMAIL not in blob
    assert API_KEY not in blob
    assert SSN not in blob
    assert "415" not in blob or "***" in blob


def test_false_positives_not_over_redacted() -> None:
    # Short digit run / non-email @ mention should not look like phone/email certainty
    text = "Order #12345 ref user@host qty 999"
    findings = detect_in_text(text)
    phones = [f for f in findings if f.type == "phone"]
    emails = [f for f in findings if f.type == "email"]
    assert phones == []
    assert emails == []
    assert redact_payload({"text": text})["text"] == text


def test_secret_patterns_never_in_stored_audit(tmp_path: Path) -> None:
    store = AuditLogStore(tmp_path / "audit.db")
    store.append(
        AppendInput(
            process="procurement_review",
            step_id="tool",
            event_type="tool_call",
            payload={
                "tool_args": {"token": API_KEY, "note": BEARER},
                "context": f"email {EMAIL}",
            },
            timestamp="2026-01-01T00:00:00+00:00",
            entry_id="e-secret",
        )
    )
    assert store.verify_chain()
    blob = str(store.query()[0].payload)
    assert API_KEY not in blob
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in blob
    assert EMAIL not in blob


def test_sanitize_for_export_strips_secrets() -> None:
    payload = {"msg": f"use {API_KEY} and {EMAIL}"}
    out = sanitize_for_export(payload)
    assert API_KEY not in str(out)
    assert EMAIL not in str(out)


def test_redact_injection_span_scrubs_secrets_and_emails() -> None:
    span = f"ignore policy; {API_KEY} contact {EMAIL}"
    meta = redact_injection_span(span)
    assert API_KEY not in meta["matched_span_preview"]
    assert EMAIL not in meta["matched_span_preview"]
    assert meta["matched_span_hash"].startswith("sha256:")
    assert len(meta["matched_span_hash"]) > len("sha256:") + 16


def test_default_policy_is_redact_only() -> None:
    pol = default_policy()
    assert pol.default_action == "redact"
    for name, d in pol.detectors.items():
        assert d.action == "redact", name


def test_shipped_config_resolve_policy_redact_only() -> None:
    cfg = load_process("procurement_review")
    assert cfg.sensitive_data is None
    pol = resolve_policy(cfg)
    assert pol.default_action == "redact"
    assert pol.policy_for("api_key").action == "redact"


def test_apply_sensitive_data_default_does_not_change_allow() -> None:
    cfg = load_process("procurement_review")
    from contracts.schemas import GatewayDecision

    decision = GatewayDecision(
        call_id="c1",
        decision="allow",
        reason="ok",
        policy_refs=[],
        risk_score=10,
        confidence_score=0.9,
        evidence_score=0.9,
    )
    req = ToolCallRequest(
        call_id="c1",
        process="procurement_review",
        step_id="g",
        tool_name="create_purchase_order",
        tool_args={"memo": f"key {API_KEY}"},
        agent_rationale=f"contact {EMAIL}",
        context_refs=[],
        timestamp="2026-01-01T00:00:00+00:00",
    )
    out, summaries = apply_sensitive_data_policy(req, cfg, decision)
    assert out.decision == "allow"
    assert summaries  # findings recorded for redact path
    assert all(s["action"] == "redact" for s in summaries)


def test_opt_in_block_upgrades_decision() -> None:
    from contracts.schemas import GatewayDecision

    cfg = ProcessConfig(
        process="test_sd",
        allowed_tools=[{"name": "create_purchase_order", "max_auto_amount": 10000}],
        disallowed_tools=[],
        required_evidence_docs=[],
        approval_threshold=ApprovalThreshold(risk_score_gte=60),
        knowledge_base_paths=[],
        sensitive_data=SensitiveDataConfig(
            default_action="redact",
            detectors={
                "api_key": SensitiveDetectorConfig(action="block", min_confidence=0.5),
            },
        ),
    )
    decision = GatewayDecision(
        call_id="c2",
        decision="allow",
        reason="ok",
        policy_refs=["policy:ok"],
        risk_score=5,
        confidence_score=0.9,
        evidence_score=0.9,
    )
    req = ToolCallRequest(
        call_id="c2",
        process="test_sd",
        step_id="g",
        tool_name="create_purchase_order",
        tool_args={"token": API_KEY},
        agent_rationale="ok",
        context_refs=[],
        timestamp="2026-01-01T00:00:00+00:00",
    )
    out, summaries = apply_sensitive_data_policy(req, cfg, decision)
    assert out.decision == "block"
    assert "sensitive_data:block" in out.policy_refs
    assert any(s["action"] == "block" for s in summaries)
    assert API_KEY not in str(summaries)


def test_opt_in_block_via_evaluate(tmp_path: Path) -> None:
    store = AuditLogStore(tmp_path / "audit.db")
    cfg = ProcessConfig(
        process="test_sd",
        allowed_tools=[{"name": "create_purchase_order", "max_auto_amount": 10000}],
        disallowed_tools=[],
        required_evidence_docs=[],
        approval_threshold=ApprovalThreshold(risk_score_gte=60),
        knowledge_base_paths=[],
        sensitive_data=SensitiveDataConfig(
            detectors={
                "api_key": SensitiveDetectorConfig(action="block", min_confidence=0.5),
            },
        ),
    )
    req = ToolCallRequest(
        call_id="eval-sd",
        process="test_sd",
        step_id="gateway_check",
        tool_name="create_purchase_order",
        tool_args={"vendor_id": "V-1", "amount": 100, "note": API_KEY},
        agent_rationale="Vendor is approved for this amount.",
        context_refs=[],
        timestamp="2026-01-01T00:00:00+00:00",
    )
    with (
        patch(
            "guardrails.output_verifier.verify_evidence",
            return_value=VerificationResult(
                grounded=True,
                unsupported_claims=[],
                evidence_score=1.0,
                judge_unavailable=False,
            ),
        ),
        patch(
            "guardrails.policy_entailment.check_policy_entailment",
            return_value=PolicyEntailmentResult(
                compliant=True, violated_clauses=[], severity="none"
            ),
        ),
    ):
        decision = evaluate_tool_call(req, cfg, audit=store)
    assert decision.decision == "block"
    blob = str([r.payload for r in store.query()])
    assert API_KEY not in blob
    assert store.verify_chain()


def test_confidence_gate_skips_low_confidence_redaction() -> None:
    pol = SensitiveDataPolicy(
        enabled=True,
        default_action="redact",
        min_confidence=0.99,
        detectors={
            "phone": DetectorPolicy(enabled=True, action="redact", min_confidence=0.99),
        },
    )
    # Phone without separators may score 0.6 — below 0.99
    text = "call 4155552671 now"
    findings = detect_in_text(text)
    phones = [f for f in findings if f.type == "phone"]
    if not phones:
        pytest.skip("phone pattern did not match bare digits")
    from audit.sensitive_data.redact import apply_redactions

    out = apply_redactions(text, findings, policy=pol)
    assert out == text
