#!/usr/bin/env python3
"""CLI: run simulated apps concurrently against a live control tower.

Each app uses the aiguard SDK (middleware / callback / @guard) and fires
independent staggered intervals — not lockstep — so the live traffic panel
shows a realistic mix across processes.
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.simulated_apps import APP_RUNNERS, DEFAULT_APPS
from scripts.traffic_lib import random_submit_body

_LEGACY_BUNDLE = "legacy_cases"


def _legacy_runner(rng: random.Random, *, api_url: str) -> str:
    """Drive procurement_review + onboarding_kyc via POST /cases."""
    for _ in range(20):
        body = random_submit_body(rng, seq=rng.randint(0, 99999))
        if body["process"] in {"procurement_review", "onboarding_kyc"}:
            resp = httpx.post(f"{api_url.rstrip('/')}/cases", json=body, timeout=30.0)
            resp.raise_for_status()
            return body["process"]
    raise RuntimeError("traffic_lib did not produce a procurement/kyc body")


_WORKLOAD_RUNNERS = {
    **APP_RUNNERS,
    _LEGACY_BUNDLE: _legacy_runner,
}

_DEFAULT_WORKLOAD = (*DEFAULT_APPS, _LEGACY_BUNDLE)


def _app_loop(
    name: str,
    run_once,
    *,
    api_url: str,
    duration_sec: float,
    interval_sec: float,
    seed: int,
    stop: threading.Event,
    lock: threading.Lock,
) -> None:
    rng = random.Random(seed)
    # Stagger start so apps don't fire in lockstep.
    time.sleep(rng.uniform(0.0, min(1.5, interval_sec)))
    end_at = time.monotonic() + duration_sec
    while not stop.is_set() and time.monotonic() < end_at:
        started = time.monotonic()
        try:
            profile = run_once(rng, api_url=api_url)
            with lock:
                print(f"[{name:<18}] profile={profile}")
        except Exception as exc:  # noqa: BLE001 — keep other apps running
            with lock:
                print(f"[{name:<18}] ERROR {exc}", file=sys.stderr)
        elapsed = time.monotonic() - started
        delay = max(0.0, interval_sec - elapsed) + rng.uniform(0.0, interval_sec * 0.3)
        if stop.wait(delay):
            break


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run simulated apps concurrently against Aegis"
    )
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--duration", type=float, default=30.0, help="seconds to run")
    parser.add_argument(
        "--interval",
        type=float,
        default=1.5,
        help="base seconds between calls per app (staggered/jittered)",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed")
    parser.add_argument(
        "--apps",
        default=",".join(_DEFAULT_WORKLOAD),
        help=(
            "comma-separated apps to include "
            f"(choices: {', '.join(_WORKLOAD_RUNNERS)})"
        ),
    )
    args = parser.parse_args(argv)

    selected = [a.strip() for a in args.apps.split(",") if a.strip()]
    unknown = [a for a in selected if a not in _WORKLOAD_RUNNERS]
    if unknown:
        print(
            f"Unknown apps: {unknown}. Known: {list(_WORKLOAD_RUNNERS)}",
            file=sys.stderr,
        )
        return 2

    base_seed = args.seed if args.seed is not None else random.randint(0, 10_000_000)
    stop = threading.Event()
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    print(
        f"Simulating {selected} for {args.duration}s at {args.api} "
        f"(interval~{args.interval}s, seed={base_seed}) ..."
    )
    for i, name in enumerate(selected):
        t = threading.Thread(
            target=_app_loop,
            kwargs={
                "name": name,
                "run_once": _WORKLOAD_RUNNERS[name],
                "api_url": args.api,
                "duration_sec": args.duration,
                "interval_sec": args.interval,
                "seed": base_seed + i * 997,
                "stop": stop,
                "lock": lock,
            },
            daemon=True,
            name=f"sim-{name}",
        )
        threads.append(t)
        t.start()

    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5.0)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
