"""Load and run offline scenario fixtures end-to-end."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph, initial_state, resume_case, run_case
from agent.tools import ToolSideEffects
from audit.log_store import AuditLogStore
from knowledge.rag import build_default_kb

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CASES_DIR = _PROJECT_ROOT / "tests" / "fixtures" / "cases"


@dataclass
class ScenarioResult:
    fixture_id: str
    passed: bool
    gateway_decision: str | None
    status: str | None
    audit_event_types: list[str]
    errors: list[str]
    evidence_score: float | None = None


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_fixtures(cases_dir: Path | None = None) -> list[Path]:
    base = cases_dir or _CASES_DIR
    return sorted(base.glob("*.json"))


def _decision_matches(actual: str | None, expected: Any) -> bool:
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def run_scenario(
    fixture: dict[str, Any],
    *,
    audit: AuditLogStore | None = None,
    project_root: Path | None = None,
    db_path: Path | None = None,
) -> ScenarioResult:
    root = project_root or _PROJECT_ROOT
    if audit is None:
        path = db_path or (root / "data" / f"scenario_{fixture['id']}.db")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        audit = AuditLogStore(path)

    kb = build_default_kb(root)
    effects = ToolSideEffects()
    graph = build_graph(
        audit=audit,
        kb=kb,
        checkpointer=MemorySaver(),
        side_effects=effects,
    )

    case_id = fixture["id"]
    state = initial_state(
        case_id=case_id,
        process=fixture.get("process", "procurement_review"),
        request=fixture["request"],
        mock_agent_plan=fixture.get("mock_agent_plan"),
        force_chunk_ids=fixture.get("force_chunk_ids"),
    )
    result = run_case(graph, state, thread_id=case_id)
    decision = (result.get("gateway_decision") or {}).get("decision")
    evidence = (result.get("gateway_decision") or {}).get("evidence_score")

    resume = fixture.get("resume")
    if resume and decision == "escalate":
        result = resume_case(
            graph,
            thread_id=case_id,
            action=resume.get("action", "approve"),
            actor=resume.get("actor", "tester"),
        )

    entries = audit.query(process=fixture.get("process", "procurement_review"))
    # Filter to this case when payload has case_id; include gateway rows without case_id
    # by taking all entries written during this run (fresh DB per scenario in tests).
    event_types = [e.event_type for e in entries]

    expected = fixture.get("expected") or {}
    errors: list[str] = []

    if not _decision_matches(decision, expected.get("gateway_decision")):
        errors.append(
            f"gateway_decision={decision!r} expected {expected.get('gateway_decision')!r}"
        )

    for needed in expected.get("audit_event_types") or []:
        if needed not in event_types:
            errors.append(f"missing audit event_type {needed!r}")

    if expected.get("require_injection_flag") and "injection_flag" not in event_types:
        errors.append("expected injection_flag audit event")

    if "min_evidence_score" in expected and evidence is not None and float(
        evidence
    ) < float(expected["min_evidence_score"]):
        errors.append(
            f"evidence_score {evidence} < min {expected['min_evidence_score']}"
        )

    if "max_evidence_score" in expected and evidence is not None and float(
        evidence
    ) > float(expected["max_evidence_score"]):
        errors.append(
            f"evidence_score {evidence} > max {expected['max_evidence_score']}"
        )

    if "final_status" in expected and result.get("status") != expected["final_status"]:
        errors.append(
            f"status={result.get('status')!r} expected {expected['final_status']!r}"
        )

    if not audit.verify_chain():
        errors.append("audit chain verification failed")

    return ScenarioResult(
        fixture_id=case_id,
        passed=not errors,
        gateway_decision=decision,
        status=result.get("status"),
        audit_event_types=event_types,
        errors=errors,
        evidence_score=float(evidence) if evidence is not None else None,
    )
