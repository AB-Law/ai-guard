"""ProcessConfig JSON Schema export and field-level create validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from configs.loader import ProcessConfig

_CONFIGS_DIR = Path(__file__).resolve().parent
_PROCESS_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

FieldError = dict[str, Any]


def known_tool_names() -> tuple[str, ...]:
    """Tool names registered in the in-process tool registry (suggestions only)."""
    from agent.tools import _TOOL_IMPLS

    return tuple(sorted(_TOOL_IMPLS))


def process_config_json_schema() -> dict[str, Any]:
    """JSON Schema for ProcessConfig, enriched for the dashboard wizard."""
    from guardrails.evidence_docs import known_evidence_doc_types

    schema = ProcessConfig.model_json_schema()
    schema["title"] = "ProcessConfig"
    props = schema.setdefault("properties", {})

    evidence_enum = list(known_evidence_doc_types())
    req_docs = props.get("required_evidence_docs")
    if isinstance(req_docs, dict):
        items = req_docs.setdefault("items", {})
        if isinstance(items, dict):
            items["enum"] = evidence_enum

    tools = known_tool_names()
    schema["x-known-tools"] = list(tools)
    schema["examples"] = [
        {
            "process": "claims_review",
            "title": "Claims Review",
            "allowed_tools": [{"name": "approve_claim", "max_auto_amount": 2000, "unit": "usd"}],
            "disallowed_tools": ["pay_out"],
            "required_evidence_docs": ["finance_policy"],
            "approval_threshold": {"risk_score_gte": 70},
            "knowledge_base_paths": [],
        }
    ]
    return schema


def _pydantic_errors(exc: ValidationError) -> list[FieldError]:
    out: list[FieldError] = []
    for err in exc.errors():
        loc = [part for part in err.get("loc", ()) if part != "body"]
        out.append(
            {
                "loc": list(loc),
                "msg": err.get("msg", "validation error"),
                "type": err.get("type", "value_error"),
            }
        )
    return out


def validate_new_process(
    raw: dict[str, Any],
    configs_dir: Path | None = None,
) -> ProcessConfig | list[FieldError]:
    """Validate a create-process payload; return ProcessConfig or field errors."""
    from guardrails.evidence_docs import known_evidence_doc_types

    errors: list[FieldError] = []
    base = configs_dir or _CONFIGS_DIR

    process_id = raw.get("process")
    if isinstance(process_id, str):
        if not _PROCESS_ID_RE.match(process_id):
            errors.append(
                {
                    "loc": ["process"],
                    "msg": (
                        "process id must start with a lowercase letter and "
                        "contain only lowercase letters, digits, and underscores"
                    ),
                    "type": "invalid_process_id",
                }
            )
        elif (base / f"{process_id}.yaml").is_file():
            errors.append(
                {
                    "loc": ["process"],
                    "msg": f"process {process_id!r} already exists",
                    "type": "process_exists",
                }
            )
    # else: pydantic will flag missing/wrong type

    try:
        config = ProcessConfig.model_validate(raw)
    except ValidationError as exc:
        return _pydantic_errors(exc) + errors

    allowed_names: list[str] = []
    for i, tool in enumerate(config.allowed_tools):
        name = tool.name.strip() if isinstance(tool.name, str) else ""
        if not name:
            errors.append(
                {
                    "loc": ["allowed_tools", i, "name"],
                    "msg": "unknown tool name ''",
                    "type": "unknown_tool",
                }
            )
        elif not _TOOL_NAME_RE.match(name):
            errors.append(
                {
                    "loc": ["allowed_tools", i, "name"],
                    "msg": f"unknown tool name {name!r}",
                    "type": "unknown_tool",
                }
            )
        else:
            allowed_names.append(name)

    for i, name in enumerate(config.disallowed_tools):
        if not isinstance(name, str) or not name.strip():
            errors.append(
                {
                    "loc": ["disallowed_tools", i],
                    "msg": "unknown tool name ''",
                    "type": "unknown_tool",
                }
            )
        elif not _TOOL_NAME_RE.match(name.strip()):
            errors.append(
                {
                    "loc": ["disallowed_tools", i],
                    "msg": f"unknown tool name {name!r}",
                    "type": "unknown_tool",
                }
            )

    deny_set = {n.strip() for n in config.disallowed_tools if isinstance(n, str)}
    for i, name in enumerate(allowed_names):
        if name in deny_set:
            errors.append(
                {
                    "loc": ["allowed_tools", i, "name"],
                    "msg": f"tool {name!r} cannot be both allowed and disallowed",
                    "type": "allow_deny_conflict",
                }
            )

    known_docs = set(known_evidence_doc_types())
    for i, doc in enumerate(config.required_evidence_docs):
        if not isinstance(doc, str) or not doc.strip():
            errors.append(
                {
                    "loc": ["required_evidence_docs", i],
                    "msg": "missing evidence-doc type",
                    "type": "missing_evidence_doc",
                }
            )
        elif doc not in known_docs:
            errors.append(
                {
                    "loc": ["required_evidence_docs", i],
                    "msg": f"unknown evidence-doc type {doc!r}",
                    "type": "unknown_evidence_doc",
                }
            )

    if errors:
        return errors
    return config
