#!/usr/bin/env python3
"""CLI: run one or all offline scenario fixtures."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/run_scenario.py` from control-tower/
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.scenario_lib import list_fixtures, load_fixture, run_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Aegis scenario fixtures")
    parser.add_argument("fixture_id", nargs="?", help="Fixture id (filename stem)")
    parser.add_argument("--all", action="store_true", help="Run all fixtures")
    args = parser.parse_args(argv)

    fixtures = list_fixtures()
    if not fixtures:
        print("No fixtures found", file=sys.stderr)
        return 2

    if args.all:
        targets = fixtures
    elif args.fixture_id:
        match = [p for p in fixtures if p.stem == args.fixture_id]
        if not match:
            print(f"Unknown fixture: {args.fixture_id}", file=sys.stderr)
            return 2
        targets = match
    else:
        parser.print_help()
        return 2

    failures = 0
    for path in targets:
        fixture = load_fixture(path)
        result = run_scenario(fixture, project_root=_ROOT)
        status = "PASS" if result.passed else "FAIL"
        print(
            f"[{status}] {result.fixture_id} "
            f"decision={result.gateway_decision} status={result.status}"
        )
        for err in result.errors:
            print(f"  - {err}")
            failures += 1
        if not result.passed:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
