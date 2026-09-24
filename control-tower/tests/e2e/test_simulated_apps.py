"""E2E: each simulated app's run_once() produces a mix of decisions over N runs."""

from __future__ import annotations

import random
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from scripts.simulated_apps import finance_app, rag_bot_app, risk_rating_app

_N_RUNS = 30


@pytest.fixture
def tower(tmp_path: Path, project_root: Path) -> TestClient:
    app = create_app(audit_path=tmp_path / "sim_audit.db", project_root=project_root)
    return TestClient(app)


@pytest.fixture
def route_aiguard_through_tower(tower: TestClient):
    """GuardClient uses httpx.post(url); divert those to the in-process TestClient."""

    def _post(url: str, json=None, timeout=None):
        assert str(url).rstrip("/").endswith("/guard/evaluate")
        resp = tower.post("/guard/evaluate", json=json or {})
        mock = MagicMock()
        mock.status_code = resp.status_code

        def _raise() -> None:
            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "error",
                    request=MagicMock(),
                    response=MagicMock(status_code=resp.status_code),
                )

        mock.raise_for_status = _raise
        mock.json = resp.json
        return mock

    with patch("aiguard.client.httpx.post", side_effect=_post):
        yield tower


def _decisions(tower: TestClient) -> list[str]:
    cases = tower.get("/cases").json()["cases"]
    out: list[str] = []
    for c in cases:
        d = (c.get("gateway_decision") or {}).get("decision")
        if d:
            out.append(d)
    return out


def _assert_mixed(decisions: list[str]) -> None:
    """Statistical — at least one allow and one block across the run window."""
    assert decisions, "expected guard evaluations to register as cases"
    assert "allow" in decisions, f"expected at least one allow, got {set(decisions)}"
    assert "block" in decisions, f"expected at least one block, got {set(decisions)}"


def test_finance_app_run_once_mix(route_aiguard_through_tower: TestClient) -> None:
    tower = route_aiguard_through_tower
    rng = random.Random(7)
    for _ in range(_N_RUNS):
        finance_app.run_once(rng, api_url="http://test")
    _assert_mixed(_decisions(tower))
    processes = {c["process"] for c in tower.get("/cases").json()["cases"]}
    assert "finance" in processes


def test_risk_rating_app_run_once_mix(route_aiguard_through_tower: TestClient) -> None:
    tower = route_aiguard_through_tower
    rng = random.Random(11)
    for _ in range(_N_RUNS):
        risk_rating_app.run_once(rng, api_url="http://test")
    _assert_mixed(_decisions(tower))
    processes = {c["process"] for c in tower.get("/cases").json()["cases"]}
    assert "risk_rating" in processes


def test_rag_bot_app_run_once_mix(route_aiguard_through_tower: TestClient) -> None:
    tower = route_aiguard_through_tower
    rng = random.Random(13)
    for _ in range(_N_RUNS):
        rag_bot_app.run_once(rng, api_url="http://test")
    _assert_mixed(_decisions(tower))
    processes = {c["process"] for c in tower.get("/cases").json()["cases"]}
    assert "rag_bot" in processes


def test_guard_evaluate_records_source_app(route_aiguard_through_tower: TestClient) -> None:
    tower = route_aiguard_through_tower
    rag_bot_app.run_once(random.Random(1), api_url="http://test")
    cases = tower.get("/cases").json()["cases"]
    assert any(c.get("source_app") == "rag_bot_app" for c in cases)
