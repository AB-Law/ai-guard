"""Path-consistency eval — heuristic vs LLM labels on shared fixtures.

Runs both paths offline (LLM stubbed to gold labels) and asserts the set of
disagreement IDs matches the checked-in allowlist. Divergence is an explicit,
versioned property rather than silent incidental behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from contracts.schemas import InjectionClassifierResult, VerificationResult
from guardrails.injection_guard import scan
from guardrails.output_verifier import verify

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_VERIFIER_EVAL = _FIXTURES / "output_verifier_eval.jsonl"
_INJECTION_EVAL = _FIXTURES / "injection_guard_eval.jsonl"
_DISAGREEMENTS = _FIXTURES / "path_disagreements.json"

_GROUNDED_SCORE_THRESHOLD = 0.5
_VERIFIER_SIZE = (30, 50)
_INJECTION_MIN = 25


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _evidence_label(score: float) -> str:
    return "grounded" if score >= _GROUNDED_SCORE_THRESHOLD else "ungrounded"


def _injection_label_from_flags(flags: list[Any]) -> str:
    return "injection" if flags else "clean"


def _evidence_disagreements(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        expected = row["expected"]
        heuristic = verify(
            row["rationale"],
            list(row.get("context_chunks") or []),
            request_facts=row.get("request_facts"),
        )
        heur_label = _evidence_label(heuristic.evidence_score)
        # Stubbed LLM path = gold label from fixture (perfect judge).
        llm_label = expected
        if heur_label != llm_label:
            out.append(
                {
                    "id": row["id"],
                    "heuristic": heur_label,
                    "llm": llm_label,
                }
            )
    return out


def _injection_disagreements(
    rows: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for row in rows:
        expected = row["expected"]
        texts = row["texts"]
        heur = scan(texts)
        heur_label = _injection_label_from_flags(heur.flags)

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
        fake = InjectionClassifierResult(
            is_injection=(expected == "injection"),
            severity="high" if expected == "injection" else "low",
            attack_type="semantic_injection" if expected == "injection" else "none",
            rationale="gold stub",
        )
        with patch("guardrails.injection_guard._llm_classify", return_value=fake):
            llm_result = scan(texts)
        llm_label = _injection_label_from_flags(llm_result.flags)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        if heur_label != llm_label:
            out.append(
                {
                    "id": row["id"],
                    "heuristic": heur_label,
                    "llm": llm_label,
                }
            )
    return out


def _ids(rows: list[dict[str, str]]) -> set[str]:
    return {r["id"] for r in rows}


def test_path_consistency_fixtures_present_and_sized() -> None:
    assert _VERIFIER_EVAL.is_file(), f"missing {_VERIFIER_EVAL}"
    assert _INJECTION_EVAL.is_file(), f"missing {_INJECTION_EVAL}"
    assert _DISAGREEMENTS.is_file(), f"missing {_DISAGREEMENTS}"

    verifier_rows = _load_jsonl(_VERIFIER_EVAL)
    injection_rows = _load_jsonl(_INJECTION_EVAL)
    lo, hi = _VERIFIER_SIZE
    assert lo <= len(verifier_rows) <= hi, (
        f"output_verifier_eval size {len(verifier_rows)} not in [{lo}, {hi}]"
    )
    assert len(injection_rows) >= _INJECTION_MIN, (
        f"injection_guard_eval size {len(injection_rows)} < {_INJECTION_MIN}"
    )


def test_evidence_heuristic_vs_llm_disagreements_match_allowlist() -> None:
    allowlist = json.loads(_DISAGREEMENTS.read_text(encoding="utf-8"))
    expected_ids = set(allowlist["evidence"])
    rows = _load_jsonl(_VERIFIER_EVAL)
    found = _evidence_disagreements(rows)
    found_ids = _ids(found)
    assert found_ids == expected_ids, (
        "evidence path disagreements drifted.\n"
        f"unexpected: {sorted(found_ids - expected_ids)}\n"
        f"missing: {sorted(expected_ids - found_ids)}\n"
        f"detail: {found}"
    )


def test_injection_heuristic_vs_llm_disagreements_match_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowlist = json.loads(_DISAGREEMENTS.read_text(encoding="utf-8"))
    expected_ids = set(allowlist["injection"])
    rows = _load_jsonl(_INJECTION_EVAL)
    found = _injection_disagreements(rows, monkeypatch)
    found_ids = _ids(found)
    assert found_ids == expected_ids, (
        "injection path disagreements drifted.\n"
        f"unexpected: {sorted(found_ids - expected_ids)}\n"
        f"missing: {sorted(expected_ids - found_ids)}\n"
        f"detail: {found}"
    )


def test_stubbed_llm_evidence_path_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity: keyed verify_evidence uses _llm_judge (gold stub), not heuristic."""
    from guardrails.output_verifier import verify_evidence

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    gold = VerificationResult(evidence_score=0.0, unsupported_claims=["x"])
    with patch("guardrails.output_verifier._llm_judge", return_value=gold) as mock_judge:
        result = verify_evidence("any", ["chunk"])
    mock_judge.assert_called_once()
    assert result is gold
