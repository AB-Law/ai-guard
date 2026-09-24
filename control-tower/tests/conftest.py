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
