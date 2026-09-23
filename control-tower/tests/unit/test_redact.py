"""PII redaction tests."""

from __future__ import annotations

import re

import pytest

from audit.log_store import AppendInput, AuditLogStore
from audit.redact import redact_payload

IBAN_SAMPLE = "DE89370400440532013000"
ACCOUNT_LINE = "Account number: 1234567890123456"


def test_iban_not_in_redacted_payload() -> None:
    raw = {"note": f"Pay to IBAN {IBAN_SAMPLE}", "vendor": "Acme"}
    redacted = redact_payload(raw)
    assert IBAN_SAMPLE not in str(redacted)
    assert "sha256:" in redacted["note"]


def test_sensitive_key_hashed() -> None:
    raw = {"iban": IBAN_SAMPLE, "vendor_id": "V-1"}
    redacted = redact_payload(raw)
    assert redacted["iban"] != IBAN_SAMPLE
    assert IBAN_SAMPLE not in str(redacted)


def test_account_number_pattern_redacted_in_string() -> None:
    redacted = redact_payload({"text": ACCOUNT_LINE})
    assert "1234567890123456" not in redacted["text"]
    assert "***" in redacted["text"]


def test_audit_store_does_not_persist_cleartext_banking(tmp_path) -> None:
    store = AuditLogStore(tmp_path / "audit.db")
    store.append(
        AppendInput(
            process="procurement_review",
            step_id="pay",
            event_type="tool_call",
            payload={
                "iban": IBAN_SAMPLE,
                "memo": f"Wire to {IBAN_SAMPLE}",
                "account_number": "9876543210987654",
            },
            timestamp="2026-01-01T00:00:00+00:00",
            entry_id="e-pii",
        )
    )
    rows = store.query(process="procurement_review")
    blob = str(rows[0].payload)
    assert IBAN_SAMPLE not in blob
    assert "9876543210987654" not in blob
    assert not re.search(r"\b9876543210987654\b", blob)
