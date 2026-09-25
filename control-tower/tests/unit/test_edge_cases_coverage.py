"""Additional edge case tests for better coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.tools import _filter_kwargs
from api.main import (
    _generate_api_key,
    _hash_key,
    _mask_key,
    _parse_created_at,
    _slugify,
    _utc_now,
    create_app,
)


def test_slugify_basic() -> None:
    """Test _slugify with basic input."""
    assert _slugify("Test Application") == "test_application"
    assert _slugify("My-Cool_App") == "my_cool_app"
    assert _slugify("App123") == "app123"


def test_slugify_special_characters() -> None:
    """Test _slugify removes special characters."""
    assert _slugify("Test@App#123") == "test_app_123"
    assert _slugify("Multiple   Spaces") == "multiple_spaces"


def test_slugify_empty_string() -> None:
    """Test _slugify with empty string returns default."""
    assert _slugify("") == "app"
    assert _slugify("!!!") == "app"


def test_generate_api_key_production() -> None:
    """Test API key generation for production."""
    key = _generate_api_key("production")
    assert key.startswith("sk_live_")
    assert len(key) > 20


def test_generate_api_key_staging() -> None:
    """Test API key generation for staging."""
    key = _generate_api_key("staging")
    assert key.startswith("sk_test_")
    assert len(key) > 20


def test_hash_key_deterministic() -> None:
    """Test that _hash_key is deterministic."""
    key = "test-key-123"
    hash1 = _hash_key(key)
    hash2 = _hash_key(key)
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest


def test_hash_key_different_inputs() -> None:
    """Test that different keys produce different hashes."""
    hash1 = _hash_key("key1")
    hash2 = _hash_key("key2")
    assert hash1 != hash2


def test_mask_key() -> None:
    """Test _mask_key masks middle of key."""
    masked = _mask_key("sk_live_", "1234")
    assert masked.startswith("sk_live_")
    assert masked.endswith("1234")
    assert "•" in masked


def test_parse_created_at_valid_iso() -> None:
    """Test parsing valid ISO timestamp."""
    dt = _parse_created_at("2024-01-01T12:00:00Z")
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 1


def test_parse_created_at_with_timezone() -> None:
    """Test parsing timestamp with timezone."""
    dt = _parse_created_at("2024-01-01T12:00:00+00:00")
    assert dt is not None


def test_parse_created_at_none() -> None:
    """Test parsing None returns None."""
    assert _parse_created_at(None) is None


def test_parse_created_at_empty_string() -> None:
    """Test parsing empty string returns None."""
    assert _parse_created_at("") is None
    assert _parse_created_at("   ") is None


def test_parse_created_at_invalid_format() -> None:
    """Test parsing invalid format returns None."""
    assert _parse_created_at("not-a-date") is None
    assert _parse_created_at("2024-99-99") is None


def test_utc_now_returns_iso_string() -> None:
    """Test that _utc_now returns valid ISO string."""
    now = _utc_now()
    assert "T" in now
    # Should be parseable
    dt = _parse_created_at(now)
    assert dt is not None


def test_filter_kwargs_with_var_keyword() -> None:
    """Test _filter_kwargs with function that has **kwargs."""
    def func_with_kwargs(**kwargs):
        pass
    
    result = _filter_kwargs(func_with_kwargs, {"a": 1, "b": 2, "c": 3})
    assert result == {"a": 1, "b": 2, "c": 3}


def test_filter_kwargs_filters_unknown_params() -> None:
    """Test _filter_kwargs removes unknown parameters."""
    def func_specific(a: int, b: str):
        pass
    
    result = _filter_kwargs(func_specific, {"a": 1, "b": "test", "c": 3})
    assert result == {"a": 1, "b": "test"}


def test_filter_kwargs_keeps_keyword_only() -> None:
    """Test _filter_kwargs keeps keyword-only parameters."""
    def func_keyword_only(*, a: int, b: str):
        pass
    
    result = _filter_kwargs(func_keyword_only, {"a": 1, "b": "test", "c": 3})
    assert result == {"a": 1, "b": "test"}


def test_filter_kwargs_with_invalid_callable() -> None:
    """Test _filter_kwargs with non-inspectable callable returns original."""
    result = _filter_kwargs(str, {"a": 1, "b": 2})
    # Should return original kwargs when can't inspect
    assert "a" in result


@pytest.fixture
def client_with_sqlite(tmp_path: Path, project_root: Path) -> TestClient:
    """Client with sqlite database_url."""
    app = create_app(
        audit_path=tmp_path / "audit.db",
        project_root=project_root,
        database_url="sqlite",
    )
    return TestClient(app)


def test_create_app_with_sqlite_database_url(client_with_sqlite: TestClient) -> None:
    """Test that create_app works with database_url='sqlite'."""
    resp = client_with_sqlite.get("/health")
    assert resp.status_code == 200


def test_demo_seed_endpoint(client_with_sqlite: TestClient) -> None:
    """Test POST /demo/seed endpoint."""
    resp = client_with_sqlite.post("/demo/seed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "fixture_ids" in body
    assert "cases" in body
    assert "pending_approval_count" in body


def test_demo_reset_endpoint(client_with_sqlite: TestClient) -> None:
    """Test POST /demo/reset endpoint."""
    # Submit a case first
    client_with_sqlite.post(
        "/cases",
        json={
            "case_id": "reset-test",
            "request": {"vendor_id": "V-1001", "amount": 100, "item": "Test"},
            "mock_agent_plan": {
                "tool_name": "create_purchase_order",
                "tool_args": {"vendor_id": "V-1001", "amount": 100},
                "agent_rationale": "Test",
                "context_refs": [],
            },
        },
    )
    
    # Reset
    resp = client_with_sqlite.post("/demo/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["cases"] == 0
    assert body["audit_entries"] == 0


def test_upload_document_with_collision_renames(
    client_with_sqlite: TestClient, project_root: Path
) -> None:
    """Test that uploading same filename twice renames the second."""
    content = b"# Test Document\n\nSome content."
    filename = "test_doc.md"
    uploaded: list[Path] = []
    try:
        resp1 = client_with_sqlite.post(
            "/knowledge/documents",
            files={"file": (filename, content, "text/markdown")},
            data={"process": "procurement_review"},
        )
        assert resp1.status_code == 200
        body1 = resp1.json()
        path1 = body1["filename"]
        uploaded.append(project_root / body1["path"])

        resp2 = client_with_sqlite.post(
            "/knowledge/documents",
            files={"file": (filename, content, "text/markdown")},
            data={"process": "procurement_review"},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        path2 = body2["filename"]
        uploaded.append(project_root / body2["path"])

        assert path1 != path2
        assert "test_doc" in path2
    finally:
        for dest in uploaded:
            if dest.is_file():
                dest.unlink()


def test_create_app_with_env_database_url(
    tmp_path: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that create_app reads DATABASE_URL from environment."""
    monkeypatch.setenv("DATABASE_URL", "sqlite")
    
    app = create_app(
        audit_path=tmp_path / "audit.db",
        project_root=project_root,
    )
    
    assert app.state.database_url == "sqlite"
