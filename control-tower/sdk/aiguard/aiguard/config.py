"""Global default config — set once with configure(), or override per-call
on GuardClient / @guard for multi-tenant / multi-tower use.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_API_URL = "http://127.0.0.1:8000"


@dataclass
class GuardConfig:
    api_url: str = DEFAULT_API_URL
    process: str = "procurement_review"
    timeout: float = 10.0
    source_app: str | None = None


_config = GuardConfig()


def configure(
    *,
    api_url: str | None = None,
    process: str | None = None,
    timeout: float | None = None,
    source_app: str | None = None,
) -> None:
    """Set defaults for every GuardClient/@guard call that doesn't override them.

    api_url points at a running Aegis control tower — your own self-hosted
    instance (the default, http://127.0.0.1:8000) or a managed one; nothing
    here assumes a specific hosting model.
    """
    if api_url is not None:
        _config.api_url = api_url.rstrip("/")
    if process is not None:
        _config.process = process
    if timeout is not None:
        _config.timeout = timeout
    if source_app is not None:
        _config.source_app = source_app


def get_config() -> GuardConfig:
    return _config
