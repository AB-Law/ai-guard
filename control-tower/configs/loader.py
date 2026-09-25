"""Process config loader — ARCHITECTURE §6."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_CONFIGS_DIR = Path(__file__).resolve().parent

# (resolved path, mtime_ns) -> ProcessConfig
_process_cache: dict[tuple[str, int], ProcessConfig] = {}


def known_processes(configs_dir: Path | None = None) -> tuple[str, ...]:
    """Every process with a config YAML on disk — discovered fresh on each
    call (not a fixed list) so a process created at runtime via POST /configs
    is visible immediately, no restart needed."""
    base = configs_dir or _CONFIGS_DIR
    return tuple(sorted(p.stem for p in base.glob("*.yaml")))


# Snapshot at import time, kept for callers that just want "the processes
# this package ships with" without caring about runtime-created ones.
KNOWN_PROCESSES = known_processes()


class AllowedTool(BaseModel):
    name: str
    max_auto_amount: float | None = None
    # Display hint only — gateway.py compares max_auto_amount against
    # tool_args["amount"] regardless of what that number means. A tool like
    # assign_risk_rating uses the same field for a rating ceiling rather than
    # a dollar amount, so the UI needs to know how to label it. Defaulting to
    # "usd" here used to silently mislabel every tool whose YAML didn't set
    # unit explicitly (including ones with no max_auto_amount at all, where
    # a unit means nothing) — leave it blank rather than assume currency.
    unit: str = ""


class ApprovalThreshold(BaseModel):
    risk_score_gte: int = Field(ge=0, le=100)


class ProcessConfig(BaseModel):
    process: str
    allowed_tools: list[AllowedTool]
    disallowed_tools: list[str]
    required_evidence_docs: list[str]
    approval_threshold: ApprovalThreshold
    knowledge_base_paths: list[str]
    # Optional — the 5 shipped configs don't set this; the dashboard falls
    # back to a title-cased process id for those. Processes created via the
    # POST /configs wizard always set it, since a slugified id makes a poor
    # display name ("claims_review_v2" vs "Claims Review v2").
    title: str | None = None


def clear_process_cache() -> None:
    """Drop cached configs — for tests that rewrite YAML files in place."""
    _process_cache.clear()
    from guardrails.rule_store import clear_rule_caches

    clear_rule_caches()


def apply_rule(
    process_id: str,
    *,
    rule_id: str,
    approved_by: str,
    rule_text: str | None = None,
) -> object:
    """Activate a pending learned rule and invalidate in-process caches.

    Does not rewrite configs/*.yaml — rules live in the learned_rules store.
    Multi-worker: other workers pick up via epoch/TTL or POST /configs/reload.
    """
    from guardrails.rule_store import get_rule_store

    store = get_rule_store()
    rule = store.activate(rule_id, approved_by=approved_by, rule_text=rule_text)
    clear_process_cache()
    return rule


def load_process(name: str, configs_dir: Path | None = None) -> ProcessConfig:
    """Load a process YAML by process name (filename stem).

    Cached by absolute path + mtime so hot-path evaluates skip repeated YAML
    parse; wizard writes bump mtime and pick up the new config automatically.
    """
    base = configs_dir or _CONFIGS_DIR
    available = known_processes(base)
    if name not in available:
        raise ValueError(
            f"Unknown process {name!r}. Known processes: {', '.join(available)}"
        )
    path = (base / f"{name}.yaml").resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Process config not found: {path}")
    mtime_ns = path.stat().st_mtime_ns
    cache_key = (str(path), mtime_ns)
    cached = _process_cache.get(cache_key)
    if cached is not None:
        return cached
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = ProcessConfig.model_validate(raw)
    # Drop stale entries for this path (older mtimes) so the cache stays small.
    stale = [k for k in _process_cache if k[0] == str(path) and k != cache_key]
    for k in stale:
        del _process_cache[k]
    _process_cache[cache_key] = config
    return config
