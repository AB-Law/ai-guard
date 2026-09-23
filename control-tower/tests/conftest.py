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
