"""Loads a simulated app's API key from data/demo_agent_keys/<source_app>.env
— written by the control tower the first time it seeds default applications
(api/main.py's _seed_default_applications). Each simulated app impersonates
one registered application and authenticates its calls with that key.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

_ROOT = Path(__file__).resolve().parents[2]
_KEYS_DIR = _ROOT / "data" / "demo_agent_keys"


def load_api_key(source_app: str) -> str | None:
    env_path = _KEYS_DIR / f"{source_app}.env"
    if not env_path.exists():
        return None
    return dotenv_values(env_path).get("AIGUARD_API_KEY") or None
