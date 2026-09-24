#!/usr/bin/env python3
"""CLI: fire a stream of synthetic cases at the live API for a load demo.

Uses mock_agent_plan on every case, so this never calls the live LLM — it
exercises the real gateway, injection guard, risk scorer, and audit chain at
a controllable rate without OpenAI cost/latency during a live demo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.traffic_lib import run_traffic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fire synthetic traffic at Aegis")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--rate", type=float, default=2.0, help="cases per second")
    parser.add_argument("--duration", type=float, default=30.0, help="seconds to run")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed")
    args = parser.parse_args(argv)

    base = args.api.rstrip("/")
    counts = {"ok": 0, "error": 0}

    def submit(body: dict) -> dict:
        resp = httpx.post(f"{base}/cases", json=body, timeout=15.0)
        resp.raise_for_status()
        return resp.json()

    def on_result(body: dict, result) -> None:
        if isinstance(result, Exception):
            counts["error"] += 1
            print(f"[ERR ] {body['case_id']}: {result}", file=sys.stderr)
            return
        counts["ok"] += 1
        decision = (result.get("gateway_decision") or {}).get("decision", "?")
        print(f"[{decision.upper():<8}] {body['case_id']}")

    print(f"Firing ~{args.rate}/s for {args.duration}s at {base} ...")
    run_traffic(
        rate_per_sec=args.rate,
        duration_sec=args.duration,
        submit_fn=submit,
        seed=args.seed,
        on_result=on_result,
    )
    print(f"Done. ok={counts['ok']} error={counts['error']}")
    return 0 if counts["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
