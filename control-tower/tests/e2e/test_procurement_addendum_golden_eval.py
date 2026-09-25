"""Golden eval for the enterprise procurement policy addendum
(data/enterprise_procurement_policy_addendum.md).

Runs each fixture request through the *full* live agent graph — real
retrieval (OpenAI embeddings), real reasoning (no mock_agent_plan), real
policy-entailment and evidence judges — and checks that the addendum's
semantic clauses (vendor holds, export-restricted countries, prohibited
categories, category-based escalation independent of amount) actually
change agent behavior, not just that a document got indexed.

Mirrors tests/e2e/test_evidence_judge_calibration.py's report-all-failures
style instead of aborting on the first miss, so a prompt regression shows
every case it broke, not just the first alphabetically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.graph import build_graph, initial_state, run_case
from audit.log_store import AuditLogStore
from knowledge.rag import build_kb_for_process

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests" / "fixtures" / "procurement_addendum_golden_cases.json"
load_dotenv(_ROOT / ".env")

# Aim for 100% — these are the exact "detect at least three risk types"
# scenarios (unauthorized/blocked vendor, export-control, prohibited
# category, amount-independent policy) the accelerator has to get right.
# If a case goes genuinely borderline after prompt iteration, lower this
# and document which case in the PR rather than silently dropping it.
_MIN_PASS_RATE = 1.0


def _require_key() -> None:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        pytest.skip("OPENAI_API_KEY not set")


def _load_cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _case_passes(case: dict, tool_name: str, decision: str, rationale: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    rationale_lower = (rationale or "").lower()

    for forbidden in case.get("forbidden_tools") or []:
        if tool_name == forbidden:
            reasons.append(f"proposed forbidden tool {forbidden!r}")

    expected_decisions = case.get("expected_decision_in")
    if expected_decisions and decision not in expected_decisions:
        reasons.append(f"decision {decision!r} not in {expected_decisions!r}")

    must_any = case.get("rationale_must_mention_any")
    if must_any and not any(needle.lower() in rationale_lower for needle in must_any):
        reasons.append(f"rationale mentions none of {must_any!r} (got: {rationale!r})")

    must_not_any = case.get("rationale_must_not_mention_any")
    if must_not_any:
        hit = [n for n in must_not_any if n.lower() in rationale_lower]
        if hit:
            reasons.append(f"rationale wrongly mentions {hit!r} (got: {rationale!r})")

    return (not reasons), reasons


@pytest.mark.live
def test_procurement_addendum_golden_eval(tmp_path: Path, project_root: Path) -> None:
    _require_key()
    cases = _load_cases()
    assert cases, f"empty fixture: {_FIXTURE}"

    kb = build_kb_for_process("procurement_review", project_root)
    # Sanity check the addendum is actually wired into this process's KB —
    # a config edit that drops the path would otherwise fail every case
    # below with a confusing, indirect error instead of this direct one.
    addendum_ids = [c.id for c in kb.all_chunks() if "enterprise_procurement_policy_addendum" in c.id]
    assert addendum_ids, "enterprise_procurement_policy_addendum.md is not indexed for procurement_review"

    failures: list[str] = []
    results: list[tuple[str, str, str, bool]] = []

    for case in cases:
        case_id = case["id"]
        audit = AuditLogStore(tmp_path / f"{case_id}.db")
        graph = build_graph(audit=audit, kb=kb)
        state = initial_state(
            case_id=case_id, process="procurement_review", request=case["request"]
        )
        result = run_case(graph, state, thread_id=case_id)
        tool_name = result.get("tool_name") or ""
        decision = (result.get("gateway_decision") or {}).get("decision") or ""
        rationale = result.get("agent_rationale") or ""

        ok, reasons = _case_passes(case, tool_name, decision, rationale)
        results.append((case_id, tool_name, decision, ok))
        if not ok:
            failures.append(
                f"FAIL {case_id}: {'; '.join(reasons)} | label={case.get('label')!r}"
            )
        assert audit.verify_chain(), f"{case_id}: audit chain broken"

    passed = sum(1 for *_rest, ok in results if ok)
    total = len(results)
    pass_rate = passed / total if total else 0.0

    print("\n=== procurement addendum golden eval ===")
    for case_id, tool_name, decision, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {case_id:28s}  tool={tool_name:22s}  decision={decision}")
    print(f"pass_rate={pass_rate:.0%} ({passed}/{total})")
    for line in failures:
        print(f"  {line}")

    assert pass_rate >= _MIN_PASS_RATE, (
        f"golden eval pass_rate {pass_rate:.0%} ({passed}/{total}) below "
        f"{_MIN_PASS_RATE:.0%}. Failures:\n" + "\n".join(failures)
    )
