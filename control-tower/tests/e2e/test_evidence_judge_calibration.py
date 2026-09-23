"""Live calibration eval for guardrails.output_verifier._llm_judge.

Loads tests/fixtures/evidence_judge_cases.json and checks that scores land
on the correct side of expected_min / expected_max. Reports per-case
failures and an overall pass rate instead of aborting on the first miss —
so a human can see which failure mode the prompt still has.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from guardrails.output_verifier import _llm_judge

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _ROOT / "tests" / "fixtures" / "evidence_judge_cases.json"
load_dotenv(_ROOT / ".env")

# Aim for 100%. If a couple of cases stay genuinely borderline after prompt
# iteration, lower this and document which ones in the PR — do not silently
# drop them from the fixture.
_MIN_PASS_RATE = 1.0


def _require_key() -> None:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        pytest.skip("OPENAI_API_KEY not set")


def _load_cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _case_passes(case: dict, score: float, unsupported: list[str]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    min_s = case.get("expected_min_evidence_score")
    max_s = case.get("expected_max_evidence_score")
    if min_s is not None and score < float(min_s):
        reasons.append(f"score {score:.3f} < min {min_s}")
    if max_s is not None and score > float(max_s):
        reasons.append(f"score {score:.3f} > max {max_s}")

    joined = " | ".join(unsupported)
    for needle in case.get("must_flag_substrings") or []:
        if needle.lower() not in joined.lower():
            reasons.append(f"unsupported_claims missing {needle!r} (got {unsupported!r})")
    for needle in case.get("must_not_flag_substrings") or []:
        if any(needle.lower() in u.lower() for u in unsupported):
            reasons.append(
                f"unsupported_claims wrongly includes {needle!r} (got {unsupported!r})"
            )
    return (not reasons), reasons


@pytest.mark.live
def test_evidence_judge_calibration() -> None:
    _require_key()
    cases = _load_cases()
    assert cases, f"empty fixture: {_FIXTURE}"

    failures: list[str] = []
    results: list[tuple[str, float, bool]] = []

    for case in cases:
        case_id = case["id"]
        result = _llm_judge(
            case["rationale"],
            case.get("context_chunks") or [],
            request_facts=case.get("request_facts"),
        )
        ok, reasons = _case_passes(case, result.evidence_score, result.unsupported_claims)
        results.append((case_id, result.evidence_score, ok))
        if not ok:
            failures.append(
                f"FAIL {case_id}: {'; '.join(reasons)} | "
                f"label={case.get('label')!r} | "
                f"unsupported={result.unsupported_claims!r}"
            )

    passed = sum(1 for _, _, ok in results if ok)
    total = len(results)
    pass_rate = passed / total if total else 0.0

    print("\n=== evidence judge calibration ===")
    for case_id, score, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {case_id:40s}  score={score:.3f}")
    print(f"pass_rate={pass_rate:.0%} ({passed}/{total})")
    for line in failures:
        print(f"  {line}")

    assert pass_rate >= _MIN_PASS_RATE, (
        f"evidence judge pass_rate {pass_rate:.0%} ({passed}/{total}) "
        f"below {_MIN_PASS_RATE:.0%}. Failures:\n" + "\n".join(failures)
    )
