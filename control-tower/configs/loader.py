"""Process config loader — ARCHITECTURE §6."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_CONFIGS_DIR = Path(__file__).resolve().parent
KNOWN_PROCESSES = (
    "procurement_review",
    "onboarding_kyc",
    "finance",
    "risk_rating",
    "rag_bot",
)
_KNOWN_PROCESSES = KNOWN_PROCESSES


class AllowedTool(BaseModel):
    name: str
    max_auto_amount: float | None = None
    # Display hint only — gateway.py compares max_auto_amount against
    # tool_args["amount"] regardless of what that number means. Most tools are
    # dollar-denominated ("usd"); a tool like assign_risk_rating uses the same
    # field for a rating ceiling, so the UI needs to know how to label it.
    unit: str = "usd"


class ApprovalThreshold(BaseModel):
    risk_score_gte: int = Field(ge=0, le=100)


class ProcessConfig(BaseModel):
    process: str
    allowed_tools: list[AllowedTool]
    disallowed_tools: list[str]
    required_evidence_docs: list[str]
    approval_threshold: ApprovalThreshold
    knowledge_base_paths: list[str]


def load_process(name: str, configs_dir: Path | None = None) -> ProcessConfig:
    """Load a process YAML by process name (filename stem)."""
    if name not in _KNOWN_PROCESSES:
        raise ValueError(
            f"Unknown process {name!r}. Known processes: {', '.join(_KNOWN_PROCESSES)}"
        )
    base = configs_dir or _CONFIGS_DIR
    path = base / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Process config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ProcessConfig.model_validate(raw)
