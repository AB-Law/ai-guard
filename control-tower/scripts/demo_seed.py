#!/usr/bin/env python3
"""Reset audit DB and load scenario fixtures for the 5-minute demo script.

Offline mode writes fixtures into a shared audit DB via the scenario runner.
API mode (`--api`) posts the rehearsal pack through a running FastAPI so the
dashboard CaseStore + HITL checkpointer are populated (escalate left pending).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from audit.log_store import AuditLogStore
from scripts.demo_pack import (
    REHEARSAL_EXPECTED_DECISIONS,
    REHEARSAL_IDS,
)
from scripts.scenario_lib import list_fixtures, load_fixture, run_scenario


def reset_audit_db(path: Path) -> None:
    """Remove audit DB file, or wipe rows if the file is locked (Windows)."""
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return
    try:
        path.unlink()
        return
    except PermissionError:
        pass
    conn = sqlite3.connect(path)
    try:
        conn.execute("DELETE FROM audit_log")
        conn.commit()
    finally:
        conn.close()


def seed_fixtures(
    *,
    audit_path: Path,
    project_root: Path,
    fixture_ids: list[str] | None = None,
    reset: bool = True,
) -> list[tuple[str, bool, list[str]]]:
    """Run fixtures into a shared audit DB. Returns (id, passed, errors) rows."""
    if reset:
        reset_audit_db(audit_path)
    audit = AuditLogStore(audit_path)

    paths = list_fixtures()
    if fixture_ids is not None:
        by_stem = {p.stem: p for p in paths}
        missing = [fid for fid in fixture_ids if fid not in by_stem]
        if missing:
            raise SystemExit(f"Unknown fixture id(s): {missing}")
        paths = [by_stem[fid] for fid in fixture_ids]

    results: list[tuple[str, bool, list[str]]] = []
    for path in paths:
        fixture = load_fixture(path)
        result = run_scenario(fixture, audit=audit, project_root=project_root)
        results.append((result.fixture_id, result.passed, result.errors))
    return results


def seed_via_api(
    api_url: str,
    *,
    timeout: float = 60.0,
) -> list[tuple[str, bool, list[str]]]:
    """POST /demo/seed on a running API; validate rehearsal decisions."""
    base = api_url.rstrip("/")
    with httpx.Client(timeout=timeout) as client:
        health = client.get(f"{base}/health")
        health.raise_for_status()
        resp = client.post(f"{base}/demo/seed")
        resp.raise_for_status()
        payload = resp.json()

    cases = {c["case_id"]: c for c in payload.get("cases") or []}
    results: list[tuple[str, bool, list[str]]] = []
    for fixture_id in REHEARSAL_IDS:
        errors: list[str] = []
        case = cases.get(fixture_id)
        if case is None:
            errors.append("case missing from /demo/seed response")
            results.append((fixture_id, False, errors))
            continue
        decision = (case.get("gateway_decision") or {}).get("decision")
        allowed = REHEARSAL_EXPECTED_DECISIONS.get(fixture_id, set())
        if decision not in allowed:
            errors.append(f"gateway_decision={decision!r} expected one of {sorted(allowed)}")
        if fixture_id == "high_amount_escalate":
            if case.get("status") != "pending_approval":
                errors.append(
                    f"status={case.get('status')!r} expected 'pending_approval' "
                    "(escalate must not auto-resume for dashboard demo)"
                )
            if not case.get("call_id"):
                errors.append("missing call_id for pending approval")
        results.append((fixture_id, not errors, errors))
    return results


def print_summary(results: list[tuple[str, bool, list[str]]], *, label: str) -> int:
    failures = 0
    print(f"=== {label} ===")
    for fixture_id, passed, errors in results:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {fixture_id}")
        for err in errors:
            print(f"  - {err}")
            failures += 1
        if not passed:
            failures += 1
    if failures:
        print(f"SUMMARY: FAIL ({failures} issue(s))")
        return 1
    print(f"SUMMARY: PASS ({len(results)} scenarios)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Aegis demo audit DB / API from fixtures")
    parser.add_argument(
        "--audit-db",
        type=Path,
        default=_ROOT / "data" / "audit.db",
        help="Path to audit SQLite DB (offline mode only)",
    )
    parser.add_argument(
        "--api",
        type=str,
        default=None,
        help="Base URL of running FastAPI (e.g. http://127.0.0.1:8000). "
        "Seeds CaseStore via POST /demo/seed so the dashboard shows cases.",
    )
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="Run demo rehearsal sequence and print PASS summary",
    )
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Do not delete existing audit DB before seeding (offline mode only)",
    )
    args = parser.parse_args(argv)

    if args.api:
        # API mode always resets via /demo/seed and uses rehearsal pack
        results = seed_via_api(args.api)
        label = "Demo API rehearsal" if args.rehearse else "Demo API seed"
        return print_summary(results, label=label)

    fixture_ids = list(REHEARSAL_IDS) if args.rehearse else None
    results = seed_fixtures(
        audit_path=args.audit_db,
        project_root=_ROOT,
        fixture_ids=fixture_ids,
        reset=not args.no_reset,
    )
    label = "Demo rehearsal" if args.rehearse else "Demo seed"
    return print_summary(results, label=label)


if __name__ == "__main__":
    raise SystemExit(main())
