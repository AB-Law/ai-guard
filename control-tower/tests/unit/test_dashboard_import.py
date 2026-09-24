"""Smoke: dashboard.app imports (Streamlit module load must succeed)."""

from __future__ import annotations


def test_import_dashboard_app() -> None:
    from dashboard import app

    assert hasattr(app, "main")
    assert hasattr(app, "DEFAULT_API_URL")
