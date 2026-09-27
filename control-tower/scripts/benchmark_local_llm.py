"""Run live guardrail benchmarks against OpenAI or a local compatible server.

Discovers a loaded LM Studio model (or uses OPENAI_MODEL), runs smoke +
evidence-judge + policy-entailment fixtures, and writes JSON/Markdown under
``reports/models/<model-slug>/``.

Usage (from control-tower/):
  python scripts/benchmark_local_llm.py
  python scripts/benchmark_local_llm.py --provider openai --model gpt-4o
  python scripts/benchmark_local_llm.py --base-url http://127.0.0.1:1234/v1
  python scripts/benchmark_local_llm.py --suites smoke,evidence
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env")

from contracts.schemas import PolicyEntailmentResult, ToolCallRequest
from guardrails.llm import reset_chat_openai_cache
from guardrails.output_verifier import _llm_judge
from guardrails.policy_entailment import _llm_entail

_EVIDENCE_FIXTURE = _ROOT / "tests" / "fixtures" / "evidence_judge_cases.json"
_POLICY_FIXTURE = _ROOT / "tests" / "fixtures" / "policy_entailment_cases.json"
_DEFAULT_LOCAL_BASE = "http://127.0.0.1:1234/v1"
_OPENAI_BASE = "https://api.openai.com/v1"
_REPORTS = _ROOT / "reports" / "models"


@dataclass
class CaseResult:
    id: str
    ok: bool
    elapsed_s: float
    detail: dict[str, Any]
    error: str | None = None


def _case_passes(case: dict[str, Any], score: float, unsupported: list[str]) -> tuple[bool, list[str]]:
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


def _slug(model_id: str) -> str:
    return model_id.strip().replace("/", "_").replace(":", "_").replace(" ", "_")


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    api_key: str = "lm-studio",
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def discover_loaded_llm(base_url: str) -> dict[str, Any] | None:
    """Prefer LM Studio /api/v1/models for loaded-instance detail."""
    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        payload = _http_json(f"{root}/api/v1/models")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    models = payload.get("models") or []
    for model in models:
        if model.get("type") != "llm":
            continue
        if model.get("loaded_instances"):
            return model
    return None


def discover_openai_model(base_url: str, *, api_key: str = "lm-studio") -> str | None:
    try:
        payload = _http_json(f"{base_url.rstrip('/')}/models", api_key=api_key)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    for row in payload.get("data") or []:
        mid = row.get("id")
        if mid and "embed" not in str(mid).lower():
            return str(mid)
    return None


def configure_env(*, provider: str, base_url: str | None, model: str) -> None:
    os.environ["AEGIS_LLM_PROVIDER"] = provider
    os.environ["OPENAI_MODEL"] = model
    if provider == "openai":
        os.environ.pop("OPENAI_BASE_URL", None)
        if base_url:
            os.environ["OPENAI_BASE_URL"] = base_url
        os.environ.pop("AEGIS_LMSTUDIO_REASONING_EFFORT", None)
    else:
        os.environ["OPENAI_BASE_URL"] = base_url or _DEFAULT_LOCAL_BASE
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            os.environ["OPENAI_API_KEY"] = "lm-studio"
        os.environ.setdefault("AEGIS_LLM_TIMEOUT", "300")
        os.environ.setdefault("AEGIS_LMSTUDIO_REASONING_EFFORT", "none")
    reset_chat_openai_cache()


def run_smoke(base_url: str, model: str, *, api_key: str, provider: str) -> dict[str, Any]:
    started = time.perf_counter()
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly the word ok"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    if provider == "lmstudio":
        body["reasoning_effort"] = "none"
    try:
        payload = _http_json(
            f"{base_url.rstrip('/')}/chat/completions",
            method="POST",
            body=body,
            api_key=api_key,
        )
        elapsed = time.perf_counter() - started
        content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
        return {
            "ok": str(content or "").strip().lower().startswith("ok"),
            "elapsed_s": round(elapsed, 3),
            "content": content,
            "usage": payload.get("usage"),
        }
    except Exception as exc:  # noqa: BLE001 — benchmark must record failures
        return {
            "ok": False,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_evidence() -> dict[str, Any]:
    cases = json.loads(_EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    results: list[CaseResult] = []
    for i, case in enumerate(cases, start=1):
        print(f"evidence [{i}/{len(cases)}] {case['id']} ...", flush=True)
        started = time.perf_counter()
        try:
            judged = _llm_judge(
                case["rationale"],
                case.get("context_chunks") or [],
                request_facts=case.get("request_facts"),
            )
            ok, reasons = _case_passes(case, judged.evidence_score, judged.unsupported_claims)
            results.append(
                CaseResult(
                    id=case["id"],
                    ok=ok,
                    elapsed_s=round(time.perf_counter() - started, 3),
                    detail={
                        "evidence_score": judged.evidence_score,
                        "unsupported_claims": judged.unsupported_claims,
                        "judge_unavailable": judged.judge_unavailable,
                        "reasons": reasons,
                        "label": case.get("label"),
                    },
                )
            )
            status = "PASS" if ok else "FAIL"
            print(
                f"evidence [{i}/{len(cases)}] {case['id']} {status} "
                f"score={judged.evidence_score:.3f} "
                f"elapsed_s={results[-1].elapsed_s}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    id=case["id"],
                    ok=False,
                    elapsed_s=round(time.perf_counter() - started, 3),
                    detail={},
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            print(
                f"evidence [{i}/{len(cases)}] {case['id']} ERROR "
                f"{results[-1].error} elapsed_s={results[-1].elapsed_s}",
                flush=True,
            )
    passed = sum(1 for r in results if r.ok)
    return {
        "fixture": str(_EVIDENCE_FIXTURE.relative_to(_ROOT)),
        "passed": passed,
        "total": len(results),
        "pass_rate": (passed / len(results)) if results else 0.0,
        "cases": [asdict(r) for r in results],
    }


def _policy_label(result: PolicyEntailmentResult) -> str:
    if result.compliant:
        return "compliant"
    if result.severity == "hard":
        return "violation"
    return "borderline"


def run_policy() -> dict[str, Any]:
    cases = json.loads(_POLICY_FIXTURE.read_text(encoding="utf-8"))
    results: list[CaseResult] = []
    for i, case in enumerate(cases, start=1):
        print(f"policy [{i}/{len(cases)}] {case['id']} ...", flush=True)
        started = time.perf_counter()
        request = ToolCallRequest(
            call_id=f"bench-{case['id']}",
            process="procurement_review",
            step_id="gateway_check",
            tool_name=case["tool_name"],
            tool_args=case.get("tool_args") or {},
            agent_rationale=case.get("agent_rationale") or "",
            context_refs=[],
            timestamp="2026-01-01T00:00:00+00:00",
        )
        try:
            judged = _llm_entail(request, case.get("policy_excerpts") or [])
            predicted = _policy_label(judged)
            expected = case["expected_label"]
            results.append(
                CaseResult(
                    id=case["id"],
                    ok=predicted == expected,
                    elapsed_s=round(time.perf_counter() - started, 3),
                    detail={
                        "expected": expected,
                        "predicted": predicted,
                        "compliant": judged.compliant,
                        "severity": judged.severity,
                        "violated_clauses": judged.violated_clauses,
                    },
                )
            )
            status = "PASS" if results[-1].ok else "FAIL"
            print(
                f"policy [{i}/{len(cases)}] {case['id']} {status} "
                f"expected={expected} predicted={predicted} "
                f"elapsed_s={results[-1].elapsed_s}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    id=case["id"],
                    ok=False,
                    elapsed_s=round(time.perf_counter() - started, 3),
                    detail={"expected": case.get("expected_label")},
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            print(
                f"policy [{i}/{len(cases)}] {case['id']} ERROR "
                f"{results[-1].error} elapsed_s={results[-1].elapsed_s}",
                flush=True,
            )
    passed = sum(1 for r in results if r.ok)
    return {
        "fixture": str(_POLICY_FIXTURE.relative_to(_ROOT)),
        "passed": passed,
        "total": len(results),
        "pass_rate": (passed / len(results)) if results else 0.0,
        "cases": [asdict(r) for r in results],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _suite_md(name: str, suite: dict[str, Any]) -> list[str]:
    lines = [
        f"## {name}",
        "",
        f"- pass_rate: **{suite['pass_rate']:.0%}** ({suite['passed']}/{suite['total']})",
        f"- fixture: `{suite['fixture']}`",
        "",
        "| Case | Result | Seconds | Notes |",
        "| --- | --- | ---: | --- |",
    ]
    for case in suite["cases"]:
        status = "PASS" if case["ok"] else "FAIL"
        notes = case.get("error") or ""
        if not notes and name == "Evidence judge":
            detail = case.get("detail") or {}
            score = detail.get("evidence_score")
            reasons = detail.get("reasons") or []
            notes = f"score={score}"
            if reasons:
                notes += "; " + "; ".join(reasons)
        if not notes and name == "Policy entailment":
            detail = case.get("detail") or {}
            notes = f"expected={detail.get('expected')} predicted={detail.get('predicted')}"
        lines.append(
            f"| `{case['id']}` | {status} | {case['elapsed_s']:.1f} | {notes} |"
        )
    lines.append("")
    return lines


def write_reports(
    out_dir: Path,
    *,
    model: str,
    model_meta: dict[str, Any] | None,
    smoke: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    policy: dict[str, Any] | None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary = {
        "generated_at": stamp,
        "model": model,
        "model_meta": model_meta,
        "smoke": smoke,
        "evidence_judge": evidence,
        "policy_entailment": policy,
    }
    _write_json(out_dir / "latest.json", summary)
    if model_meta is not None:
        _write_json(out_dir / "model.json", model_meta)

    lines = [
        f"# LLM benchmark — `{model}`",
        "",
        f"Generated: `{stamp}`",
        "",
    ]
    if model_meta:
        lines.extend(
            [
                "## Model",
                "",
                f"- display_name: {model_meta.get('display_name')}",
                f"- key: `{model_meta.get('key')}`",
                f"- params: {model_meta.get('params_string')}",
                f"- quantization: {(model_meta.get('quantization') or {}).get('name')}",
                f"- architecture: {model_meta.get('architecture')}",
                "",
            ]
        )
    if smoke is not None:
        lines.extend(
            [
                "## Smoke",
                "",
                f"- ok: **{smoke.get('ok')}**",
                f"- elapsed_s: {smoke.get('elapsed_s')}",
                f"- content: {smoke.get('content')!r}",
                f"- usage: `{json.dumps(smoke.get('usage'), ensure_ascii=False)}`",
                "",
            ]
        )
        if smoke.get("error"):
            lines.append(f"- error: `{smoke['error']}`")
            lines.append("")
    if evidence is not None:
        lines.extend(_suite_md("Evidence judge", evidence))
    if policy is not None:
        lines.extend(_suite_md("Policy entailment", policy))

    md_path = out_dir / "latest.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("lmstudio", "openai", "compatible"),
        default="lmstudio",
        help="Endpoint kind (openai uses hosted API unless --base-url is set)",
    )
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL") or "")
    parser.add_argument(
        "--suites",
        default="smoke,evidence,policy",
        help="Comma list: smoke,evidence,policy",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Defaults to reports/models/<model-slug>/",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    provider = args.provider
    base_url = args.base_url.strip()
    if not base_url:
        base_url = _OPENAI_BASE if provider == "openai" else _DEFAULT_LOCAL_BASE

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if provider == "openai" and not api_key:
        print("ERROR: OPENAI_API_KEY is required for --provider openai", file=sys.stderr)
        return 2
    if not api_key:
        api_key = "lm-studio"

    model_meta = None if provider == "openai" else discover_loaded_llm(base_url)
    model = args.model.strip()
    if not model and model_meta:
        model = str(model_meta.get("key") or "")
    if not model and provider != "openai":
        model = discover_openai_model(base_url, api_key=api_key) or ""
    if not model:
        print("ERROR: could not discover a model; pass --model", file=sys.stderr)
        return 2

    configure_env(
        provider=provider,
        base_url=None if provider == "openai" else base_url,
        model=model,
    )
    suites = {s.strip().lower() for s in args.suites.split(",") if s.strip()}
    out_dir = args.out_dir or (_REPORTS / _slug(model))

    print(f"provider={provider}", flush=True)
    print(f"model={model}", flush=True)
    print(f"base_url={base_url if provider != 'openai' else '(openai default)'}", flush=True)
    print(f"out_dir={out_dir}", flush=True)

    smoke = (
        run_smoke(base_url, model, api_key=api_key, provider=provider)
        if "smoke" in suites
        else None
    )
    if smoke is not None:
        print(f"smoke ok={smoke.get('ok')} elapsed_s={smoke.get('elapsed_s')}", flush=True)

    evidence = run_evidence() if "evidence" in suites else None
    if evidence is not None:
        print(
            f"evidence pass_rate={evidence['pass_rate']:.0%} "
            f"({evidence['passed']}/{evidence['total']})",
            flush=True,
        )

    policy = run_policy() if "policy" in suites else None
    if policy is not None:
        print(
            f"policy pass_rate={policy['pass_rate']:.0%} "
            f"({policy['passed']}/{policy['total']})",
            flush=True,
        )

    md_path = write_reports(
        out_dir,
        model=model,
        model_meta=model_meta,
        smoke=smoke,
        evidence=evidence,
        policy=policy,
    )
    print(f"wrote {md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
