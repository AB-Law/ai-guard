"""Unit tests for ProcessConfig JSON Schema + create validation."""

from __future__ import annotations

from pathlib import Path

from configs.validate import process_config_json_schema, validate_new_process


def _valid_payload(**overrides: object) -> dict:
    base: dict = {
        "process": "claims_review",
        "title": "Claims Review",
        "allowed_tools": [{"name": "approve_claim", "max_auto_amount": 2000, "unit": "usd"}],
        "disallowed_tools": ["pay_out"],
        "required_evidence_docs": ["finance_policy"],
        "approval_threshold": {"risk_score_gte": 70},
        "knowledge_base_paths": [],
    }
    base.update(overrides)
    return base


def test_process_config_json_schema_has_evidence_enum() -> None:
    schema = process_config_json_schema()
    assert schema["title"] == "ProcessConfig"
    items = schema["properties"]["required_evidence_docs"]["items"]
    assert "finance_policy" in items["enum"]
    assert "procurement_policy" in items["enum"]
    assert "x-known-tools" in schema
    assert "create_purchase_order" in schema["x-known-tools"]


def test_validate_new_process_accepts_valid(tmp_path: Path) -> None:
    result = validate_new_process(_valid_payload(), configs_dir=tmp_path)
    assert not isinstance(result, list)
    assert result.process == "claims_review"
    assert result.approval_threshold.risk_score_gte == 70


def test_validate_rejects_unknown_evidence_doc(tmp_path: Path) -> None:
    result = validate_new_process(
        _valid_payload(required_evidence_docs=["not_a_real_doc"]),
        configs_dir=tmp_path,
    )
    assert isinstance(result, list)
    assert any(e["type"] == "unknown_evidence_doc" for e in result)
    assert any(e["loc"] == ["required_evidence_docs", 0] for e in result)


def test_validate_rejects_empty_tool_name(tmp_path: Path) -> None:
    result = validate_new_process(
        _valid_payload(allowed_tools=[{"name": "", "max_auto_amount": None}]),
        configs_dir=tmp_path,
    )
    assert isinstance(result, list)
    assert any(e["type"] == "unknown_tool" for e in result)


def test_validate_rejects_invalid_tool_slug(tmp_path: Path) -> None:
    result = validate_new_process(
        _valid_payload(allowed_tools=[{"name": "Bad Tool!", "max_auto_amount": None}]),
        configs_dir=tmp_path,
    )
    assert isinstance(result, list)
    assert any(e["type"] == "unknown_tool" for e in result)


def test_validate_rejects_allow_deny_conflict(tmp_path: Path) -> None:
    result = validate_new_process(
        _valid_payload(
            allowed_tools=[{"name": "pay_out", "max_auto_amount": None}],
            disallowed_tools=["pay_out"],
        ),
        configs_dir=tmp_path,
    )
    assert isinstance(result, list)
    assert any(e["type"] == "allow_deny_conflict" for e in result)


def test_validate_rejects_existing_process(tmp_path: Path) -> None:
    (tmp_path / "claims_review.yaml").write_text("process: claims_review\n", encoding="utf-8")
    result = validate_new_process(_valid_payload(), configs_dir=tmp_path)
    assert isinstance(result, list)
    assert any(e["type"] == "process_exists" for e in result)


def test_validate_rejects_invalid_process_id(tmp_path: Path) -> None:
    result = validate_new_process(
        _valid_payload(process="Claims-Review"),
        configs_dir=tmp_path,
    )
    assert isinstance(result, list)
    assert any(e["type"] == "invalid_process_id" for e in result)


def test_validate_rejects_bad_threshold_via_pydantic(tmp_path: Path) -> None:
    result = validate_new_process(
        _valid_payload(approval_threshold={"risk_score_gte": 200}),
        configs_dir=tmp_path,
    )
    assert isinstance(result, list)
    assert any("approval_threshold" in e["loc"] for e in result)
