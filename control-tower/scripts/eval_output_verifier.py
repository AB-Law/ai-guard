"""Offline / optional-LLM eval for guardrails.output_verifier.

Loads tests/fixtures/output_verifier_eval.jsonl, runs the deterministic
verify() path (and optionally _llm_judge), and reports precision / recall /
F1 for the ungrounded class.

Exit code 1 when heuristic F1 vs fixture labels is below --min-f1 (default 0.85).

Usage (from control-tower/):
  python scripts/eval_output_verifier.py
  python scripts/eval_output_verifier.py --llm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from guardrails.output_verifier import (
    GROUNDED_SCORE_THRESHOLD,
    _llm_judge,
    verify,
)

_DEFAULT_FIXTURE = _ROOT / "tests" / "fixtures" / "output_verifier_eval.jsonl"
_POSITIVE = "ungrounded"


@dataclass(frozen=True)
class Metrics:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    tn: int
    fn: int

    def as_row(self) -> str:
        return (
            f"P={self.precision:.3f} R={self.recall:.3f} F1={self.f1:.3f} "
            f"(tp={self.tp} fp={self.fp} tn={self.tn} fn={self.fn})"
        )


def load_cases(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid JSONL at {path}:{line_no}: {exc}") from exc
        if row.get("expected") not in ("grounded", "ungrounded"):
            raise SystemExit(f"{path}:{line_no}: expected must be grounded|ungrounded")
        rows.append(row)
    return rows


def score_to_label(evidence_score: float, threshold: float = GROUNDED_SCORE_THRESHOLD) -> str:
    return "grounded" if evidence_score >= threshold else "ungrounded"


def binary_metrics(y_true: Sequence[str], y_pred: Sequence[str], *, positive: str = _POSITIVE) -> Metrics:
    tp = fp = tn = fn = 0
    for t, p in zip(y_true, y_pred, strict=True):
        if t == positive and p == positive:
            tp += 1
        elif t != positive and p == positive:
            fp += 1
        elif t != positive and p != positive:
            tn += 1
        else:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        0.0
        if precision + recall == 0
        else 2.0 * precision * recall / (precision + recall)
    )
    return Metrics(precision=precision, recall=recall, f1=f1, tp=tp, fp=fp, tn=tn, fn=fn)


def _predict_heuristic(case: dict[str, Any], threshold: float) -> tuple[str, float]:
    result = verify(
        case["rationale"],
        case.get("context_chunks") or [],
        request_facts=case.get("request_facts"),
    )
    return score_to_label(result.evidence_score, threshold), result.evidence_score


def _predict_llm(case: dict[str, Any], threshold: float) -> tuple[str, float]:
    result = _llm_judge(
        case["rationale"],
        case.get("context_chunks") or [],
        request_facts=case.get("request_facts"),
    )
    return score_to_label(result.evidence_score, threshold), result.evidence_score


def _print_misses(
    cases: Sequence[dict[str, Any]],
    y_true: Sequence[str],
    y_pred: Sequence[str],
    scores: Sequence[float],
) -> None:
    misses = [
        (c["id"], t, p, s)
        for c, t, p, s in zip(cases, y_true, y_pred, scores, strict=True)
        if t != p
    ]
    if not misses:
        print("  misses: (none)")
        return
    print("  misses:")
    for case_id, t, p, s in misses:
        print(f"    - {case_id}: true={t} pred={p} score={s:.3f}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=_DEFAULT_FIXTURE,
        help="Path to JSONL eval fixture",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=GROUNDED_SCORE_THRESHOLD,
        help="evidence_score >= threshold → grounded",
    )
    parser.add_argument(
        "--min-f1",
        type=float,
        default=0.85,
        help="Fail if heuristic F1 vs fixture is below this",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Also run _llm_judge (requires OPENAI_API_KEY)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    cases = load_cases(args.fixture)
    if not (30 <= len(cases) <= 50):
        print(f"warning: expected 30-50 cases, got {len(cases)}", file=sys.stderr)

    labels = [c["expected"] for c in cases]
    heur_preds: list[str] = []
    heur_scores: list[float] = []
    for case in cases:
        pred, score = _predict_heuristic(case, args.threshold)
        heur_preds.append(pred)
        heur_scores.append(score)

    heur_m = binary_metrics(labels, heur_preds)
    print(f"cases: {len(cases)}  threshold: {args.threshold}")
    print(f"heuristic vs fixture: {heur_m.as_row()}")
    _print_misses(cases, labels, heur_preds, heur_scores)

    if args.llm:
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            print("ERROR: --llm requires OPENAI_API_KEY", file=sys.stderr)
            return 2
        llm_preds: list[str] = []
        llm_scores: list[float] = []
        for case in cases:
            pred, score = _predict_llm(case, args.threshold)
            llm_preds.append(pred)
            llm_scores.append(score)
        llm_vs_fix = binary_metrics(labels, llm_preds)
        heur_vs_llm = binary_metrics(llm_preds, heur_preds)
        print(f"llm vs fixture:       {llm_vs_fix.as_row()}")
        _print_misses(cases, labels, llm_preds, llm_scores)
        print(f"heuristic vs llm:     {heur_vs_llm.as_row()}")
        _print_misses(cases, llm_preds, heur_preds, heur_scores)

    if heur_m.f1 < args.min_f1:
        print(f"FAIL: heuristic F1 {heur_m.f1:.3f} < min {args.min_f1}", file=sys.stderr)
        return 1
    print(f"PASS: heuristic F1 {heur_m.f1:.3f} >= {args.min_f1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
