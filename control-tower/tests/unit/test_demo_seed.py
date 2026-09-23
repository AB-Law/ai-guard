"""Tests for demo_seed script — idempotent reset + fixture pack."""

from __future__ import annotations

from pathlib import Path

from audit.log_store import AuditLogStore
from scripts.demo_seed import seed_fixtures
from scripts.scenario_lib import list_fixtures, load_fixture, run_scenario


def test_demo_seed_idempotent(tmp_path: Path, project_root: Path) -> None:
    db = tmp_path / "demo_audit.db"
    first = seed_fixtures(audit_path=db, project_root=project_root, reset=True)
    assert all(passed for _, passed, _ in first), first
    store1 = AuditLogStore(db)
    assert store1.verify_chain()
    count1 = len(store1.query())
    store1.close()

    second = seed_fixtures(audit_path=db, project_root=project_root, reset=True)
    assert all(passed for _, passed, _ in second), second
    store2 = AuditLogStore(db)
    assert store2.verify_chain()
    # Fresh DB each seed — chain valid and non-empty
    assert len(store2.query()) == count1
    assert count1 > 0
    store2.close()


def test_demo_seed_then_e2e_pack_still_passes(tmp_path: Path, project_root: Path) -> None:
    db = tmp_path / "demo_audit.db"
    results = seed_fixtures(audit_path=db, project_root=project_root, reset=True)
    assert all(passed for _, passed, _ in results)

    for path in list_fixtures():
        fixture = load_fixture(path)
        result = run_scenario(
            fixture,
            project_root=project_root,
            db_path=tmp_path / f"post_seed_{fixture['id']}.db",
        )
        assert result.passed, f"{fixture['id']}: {result.errors}"


def test_rehearse_order_subset(tmp_path: Path, project_root: Path) -> None:
    db = tmp_path / "rehearse.db"
    ids = ["clean_po", "injection_planted", "unauthorized_tool", "high_amount_escalate"]
    results = seed_fixtures(
        audit_path=db,
        project_root=project_root,
        fixture_ids=ids,
        reset=True,
    )
    assert [r[0] for r in results] == ids
    assert all(passed for _, passed, _ in results)
