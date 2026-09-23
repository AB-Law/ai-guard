"""Offline e2e scenario pack."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.scenario_lib import list_fixtures, load_fixture, run_scenario


FIXTURE_PATHS = list_fixtures()
FIXTURE_IDS = [p.stem for p in FIXTURE_PATHS]


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=FIXTURE_IDS)
def test_e2e_scenario(fixture_path: Path, tmp_path: Path, project_root: Path) -> None:
    fixture = load_fixture(fixture_path)
    result = run_scenario(
        fixture,
        project_root=project_root,
        db_path=tmp_path / f"{fixture['id']}.db",
    )
    assert result.passed, f"{fixture['id']} failed: {result.errors}"
