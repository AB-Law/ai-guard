"""E2E: tamper audit SQLite → verify fails + script exit ≠ 0."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from audit.log_store import AppendInput, AuditLogStore
from contracts.schemas import GatewayDecision


@pytest.fixture
def project_scripts(project_root: Path) -> Path:
    return project_root / "scripts" / "verify_audit_chain.py"


def test_verify_script_ok_then_fail_after_tamper(
    tmp_path: Path, project_scripts: Path, project_root: Path
) -> None:
    db_path = tmp_path / "tamper_audit.db"
    store = AuditLogStore(db_path)
    store.append(
        AppendInput(
            process="procurement_review",
            step_id="policy",
            event_type="policy_check",
            payload={"case_id": "t1", "note": "clean"},
            scores=GatewayDecision(
                call_id="c1",
                decision="allow",
                reason="ok",
                policy_refs=["chunk:policy:auto_approve"],
                risk_score=10,
                confidence_score=0.90,
                evidence_score=0.80,
            ),
            timestamp="2026-01-01T00:00:00+00:00",
            entry_id="e-clean",
        )
    )
    assert store.verify_chain() is True

    ok = subprocess.run(
        [sys.executable, str(project_scripts), "--db", str(db_path)],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0, ok.stderr
    assert "OK" in ok.stdout

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE audit_log SET payload_json = ? WHERE entry_id = ?",
        (json.dumps({"case_id": "t1", "note": "TAMPERED"}), "e-clean"),
    )
    conn.commit()
    conn.close()

    assert store.verify_chain() is False

    bad = subprocess.run(
        [sys.executable, str(project_scripts), "--db", str(db_path)],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode != 0
    assert "FAIL" in (bad.stderr or "") or "FAIL" in (bad.stdout or "")


def test_audit_verify_api_reports_tamper(
    tmp_path: Path, project_root: Path
) -> None:
    db_path = tmp_path / "api_tamper.db"
    store = AuditLogStore(db_path)
    store.append(
        AppendInput(
            process="procurement_review",
            step_id="s",
            event_type="tool_call",
            payload={"amount": 100},
            timestamp="2026-01-01T00:00:00+00:00",
            entry_id="e-api",
        )
    )

    app = create_app(audit_path=db_path, project_root=project_root)
    client = TestClient(app)

    clean = client.get("/audit/verify")
    assert clean.status_code == 200
    assert clean.json()["valid"] is True
    assert clean.json()["entry_count"] == 1

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE audit_log SET payload_json = ? WHERE entry_id = ?",
        (json.dumps({"amount": 999}), "e-api"),
    )
    conn.commit()
    conn.close()

    broken = client.get("/audit/verify")
    assert broken.status_code == 200
    assert broken.json()["valid"] is False
    assert broken.json()["entry_count"] == 1


def test_investigate_api_with_mock(tmp_path: Path, project_root: Path) -> None:
    db_path = tmp_path / "invest.db"
    store = AuditLogStore(db_path)
    store.append(
        AppendInput(
            process="procurement_review",
            step_id="policy",
            event_type="policy_check",
            payload={"case_id": "inv-1", "note": "escalated"},
            scores=GatewayDecision(
                call_id="c-inv",
                decision="escalate",
                reason="Amount flagged over limit",
                policy_refs=["chunk:policy:escalation"],
                risk_score=80,
                confidence_score=0.7,
                evidence_score=0.6,
            ),
            timestamp="2026-01-01T00:00:00+00:00",
            entry_id="entry-inv-flag",
        )
    )
    app = create_app(audit_path=db_path, project_root=project_root)
    client = TestClient(app)
    resp = client.post(
        "/investigate",
        json={
            "question": "why was this flagged",
            "mock_answer": {
                "answer": "Flagged due to amount over limit.",
                "cited_entry_ids": ["entry-inv-flag"],
                "cited_chunk_ids": ["chunk:policy:escalation"],
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "entry-inv-flag" in body["cited_entry_ids"]
    assert "Flagged" in body["answer"]
