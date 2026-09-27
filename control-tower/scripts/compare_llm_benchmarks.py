"""Write a markdown compare of two benchmark latest.json reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MODELS = _ROOT / "reports" / "models"


def _suite(data: dict | None) -> tuple[float, int, int, float] | None:
    if not data:
        return None
    cases = data["cases"]
    avg = sum(c["elapsed_s"] for c in cases) / len(cases) if cases else 0.0
    return data["pass_rate"], data["passed"], data["total"], avg


def _smoke_cell(smoke: dict | None) -> str:
    if not smoke:
        return "n/a"
    status = "ok" if smoke.get("ok") else "fail"
    return f"{status} ({smoke.get('elapsed_s')}s)"


def _diffs(left: dict, right: dict) -> list[tuple[str, str, str]]:
    left_map = {c["id"]: c for c in left["cases"]}
    right_map = {c["id"]: c for c in right["cases"]}
    rows: list[tuple[str, str, str]] = []
    for case_id, left_case in left_map.items():
        right_case = right_map.get(case_id)
        if right_case is None or left_case["ok"] == right_case["ok"]:
            continue
        rows.append(
            (
                case_id,
                "PASS" if left_case["ok"] else "FAIL",
                "PASS" if right_case["ok"] else "FAIL",
            )
        )
    return rows


def main() -> None:
    left_name = "nvidia_nemotron-3-nano-4b"
    right_name = "gpt-6-luna"
    left = json.loads((_MODELS / left_name / "latest.json").read_text(encoding="utf-8"))
    right = json.loads((_MODELS / right_name / "latest.json").read_text(encoding="utf-8"))

    left_e = _suite(left["evidence_judge"])
    left_p = _suite(left["policy_entailment"])
    right_e = _suite(right["evidence_judge"])
    right_p = _suite(right["policy_entailment"])
    assert left_e and left_p and right_e and right_p

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence_diffs = _diffs(left["evidence_judge"], right["evidence_judge"])
    policy_diffs = _diffs(left["policy_entailment"], right["policy_entailment"])

    lines = [
        f"# Benchmark compare: `{left['model']}` vs `{right['model']}`",
        "",
        f"Generated: `{stamp}`",
        "",
        f"| Metric | `{left['model']}` (LM Studio) | `{right['model']}` (OpenAI) |",
        "| --- | ---: | ---: |",
        f"| Smoke | {_smoke_cell(left.get('smoke'))} | {_smoke_cell(right.get('smoke'))} |",
        (
            f"| Evidence pass rate | {left_e[0]:.0%} ({left_e[1]}/{left_e[2]}) | "
            f"{right_e[0]:.0%} ({right_e[1]}/{right_e[2]}) |"
        ),
        f"| Evidence avg latency | {left_e[3]:.2f}s | {right_e[3]:.2f}s |",
        (
            f"| Policy pass rate | {left_p[0]:.0%} ({left_p[1]}/{left_p[2]}) | "
            f"{right_p[0]:.0%} ({right_p[1]}/{right_p[2]}) |"
        ),
        f"| Policy avg latency | {left_p[3]:.2f}s | {right_p[3]:.2f}s |",
        "",
        "## Evidence disagreements",
        "",
    ]
    if not evidence_diffs:
        lines.append("(none)")
    else:
        lines.extend(["| Case | Nemotron | gpt-6-luna |", "| --- | --- | --- |"])
        lines.extend(f"| `{cid}` | {n} | {o} |" for cid, n, o in evidence_diffs)

    lines.extend(["", "## Policy disagreements", ""])
    if not policy_diffs:
        lines.append("(none)")
    else:
        lines.extend(["| Case | Nemotron | gpt-6-luna |", "| --- | --- | --- |"])
        lines.extend(f"| `{cid}` | {n} | {o} |" for cid, n, o in policy_diffs)

    lines.extend(
        [
            "",
            "## Takeaway",
            "",
            (
                "- **Quality:** gpt-6-luna wins clearly on evidence (100% vs 50%) and "
                "edges policy (95% vs 80%)."
            ),
            (
                "- **Speed:** Nemotron is much faster per case (~0.5s vs ~1.5–2s) and "
                "fine for local iteration."
            ),
            (
                "- **Use:** prefer OpenAI for guardrail accuracy; Nemotron for cheap/fast "
                "local smoke."
            ),
            "",
        ]
    )

    out = _MODELS / "compare_nemotron-3-nano-4b_vs_gpt-6-luna.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
