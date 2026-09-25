"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIGS_DIR = ROOT / "configs"


@pytest.fixture
def project_root() -> Path:
    return ROOT


@pytest.fixture
def data_dir(project_root: Path) -> Path:
    return project_root / "data"


@pytest.fixture
def configs_dir(project_root: Path) -> Path:
    return project_root / "configs"


@pytest.fixture(autouse=True)
def _isolate_openai_key(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-live tests must not silently pick up a real key: api/main.py calls
    load_dotenv() at import time, and this repo's own .env has one, so once
    any test imports api.main it leaks into os.environ for the rest of the
    pytest process — including guardrails' LLM-judge auto-selection, which
    otherwise keys off OPENAI_API_KEY presence alone (see output_verifier.py).
    Only @pytest.mark.live tests intend to exercise that path for real.

    Set the var to empty (do not delenv): python-dotenv's default
    ``load_dotenv(override=False)`` will not overwrite an existing empty
    value, but *will* re-inject the real key after a delenv — which then
    fails the judge closed and turns clean /guard/evaluate allows into
    escalates mid-suite.
    """
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setenv("OPENAI_API_KEY", "")


@pytest.fixture(autouse=True)
def _test_auth_mode(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirrors _isolate_openai_key above: api/main.py's load_dotenv() would
    otherwise leak this repo's real DASHBOARD_PASSWORD/JWT_SECRET into every
    test process. Most tests don't care about auth at all, so by default this
    sets AEGIS_DISABLE_AUTH=1, which api/auth.py + api/main.py's dependencies
    treat as "skip the check". Tests that exercise auth itself opt back in
    with @pytest.mark.auth and set DASHBOARD_PASSWORD/JWT_SECRET themselves.
    """
    if request.node.get_closest_marker("auth") is None:
        monkeypatch.setenv("AEGIS_DISABLE_AUTH", "1")
        monkeypatch.setenv("JWT_SECRET", "")
        monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    else:
        monkeypatch.delenv("AEGIS_DISABLE_AUTH", raising=False)


@pytest.fixture(autouse=True)
def _isolate_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same leak as _isolate_openai_key above, different variable: this
    repo's own .env can set DATABASE_URL=sqlite for local dev persistence,
    and create_app()'s `database_url if database_url is not None else
    os.environ.get("DATABASE_URL")` fallback means even a test that passes
    database_url=None *explicitly* (to test default in-memory behavior)
    still picks up the leaked env value — silently switching it onto the
    sqlite tier, which then reads/writes the same real data/*.db files
    every other test sharing that tier also touches, corrupting counts and
    isolation across the whole suite. Tests that want a real persisted tier
    pass an explicit non-None database_url ("sqlite" or a postgres URL),
    which always wins over this regardless."""
    monkeypatch.setenv("DATABASE_URL", "")
