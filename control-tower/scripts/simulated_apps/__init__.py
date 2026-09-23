"""Registry for simulated applications driven by the aiguard SDK."""

from __future__ import annotations

from scripts.simulated_apps import finance_app, rag_bot_app, risk_rating_app

APP_RUNNERS = {
    "finance": finance_app.run_once,
    "risk_rating": risk_rating_app.run_once,
    "rag_bot": rag_bot_app.run_once,
}

DEFAULT_APPS = tuple(APP_RUNNERS)
