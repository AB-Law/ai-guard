"""E2E: the process-creation wizard (POST/PUT /configs) and the policy editor
(POST/PUT/GET/DELETE /knowledge/policies, DELETE /knowledge/documents) —
config-driven, no code changes, same as any other process (ARCHITECTURE §4.3).

Every test writes into the real configs/ and data/uploads/ dirs (project_root
is the real repo root, matching the rest of the e2e suite — see test_api.py)
and cleans up in `finally` so a failed assertion never leaks a stray process.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def client(tmp_path: Path, project_root: Path) -> TestClient:
    app = create_app(audit_path=tmp_path / "wizard_audit.db", project_root=project_root)
    return TestClient(app)


def _cleanup_process(project_root: Path, process_id: str) -> None:
    yaml_path = project_root / "configs" / f"{process_id}.yaml"
    if yaml_path.is_file():
        yaml_path.unlink()
    updir = project_root / "data" / "uploads" / process_id
    if updir.is_dir():
        for p in sorted(updir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
        for p in sorted(updir.rglob("*"), reverse=True):
            if p.is_dir():
                p.rmdir()
        updir.rmdir()


def test_create_process_writes_yaml_and_appears_in_configs(
    client: TestClient, project_root: Path
) -> None:
    process_id = None
    try:
        resp = client.post(
            "/configs",
            json={
                "title": "Claims Review Wizard Test",
                "allowed_tools": [{"name": "approve_claim", "max_auto_amount": 2000}],
                "disallowed_tools": ["pay_out"],
                "approval_threshold": 70,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        process_id = body["id"]
        assert process_id == "claims_review_wizard_test"
        assert (project_root / "configs" / f"{process_id}.yaml").is_file()

        listed = client.get("/configs").json()["processes"]
        match = next(p for p in listed if p["id"] == process_id)
        assert match["title"] == "Claims Review Wizard Test"
        assert match["approval_threshold"]["risk_score_gte"] == 70
        assert match["allowed_tools"][0]["name"] == "approve_claim"
        assert match["uploaded_docs"] == []
    finally:
        if process_id:
            _cleanup_process(project_root, process_id)


def test_create_process_dedupes_slug_collision(client: TestClient, project_root: Path) -> None:
    ids: list[str] = []
    try:
        for _ in range(2):
            resp = client.post("/configs", json={"title": "Dup Slug Test"})
            assert resp.status_code == 200
            ids.append(resp.json()["id"])
        assert ids[0] == "dup_slug_test"
        assert ids[1] == "dup_slug_test_2"
    finally:
        for pid in ids:
            _cleanup_process(project_root, pid)


def test_update_process_thresholds(client: TestClient, project_root: Path) -> None:
    process_id = None
    try:
        created = client.post("/configs", json={"title": "Threshold Edit Test"}).json()
        process_id = created["id"]

        resp = client.put(
            f"/configs/{process_id}",
            json={"approval_threshold": 85, "disallowed_tools": ["dangerous_tool"]},
        )
        assert resp.status_code == 200, resp.text

        listed = client.get("/configs").json()["processes"]
        match = next(p for p in listed if p["id"] == process_id)
        assert match["approval_threshold"]["risk_score_gte"] == 85
        assert match["disallowed_tools"] == ["dangerous_tool"]
    finally:
        if process_id:
            _cleanup_process(project_root, process_id)


def test_update_process_unknown_id_404s(client: TestClient) -> None:
    resp = client.put("/configs/does_not_exist", json={"approval_threshold": 50})
    assert resp.status_code == 404


def test_custom_policy_create_edit_delete_roundtrip(
    client: TestClient, project_root: Path
) -> None:
    process = "procurement_review"
    filename = None
    try:
        created = client.post(
            "/knowledge/policies",
            json={"process": process, "title": "Wizard Custom Policy", "content": "Draft body."},
        )
        assert created.status_code == 200, created.text
        body = created.json()
        filename = body["name"]
        assert body["path"] == f"custom/{filename}"
        assert body["chunks_added"] >= 1

        listed = client.get("/configs").json()["processes"]
        match = next(p for p in listed if p["id"] == process)
        doc = next(d for d in match["uploaded_docs"] if d["name"] == filename)
        assert doc["kind"] == "custom"

        fetched = client.get(f"/knowledge/policies/{process}/{filename}")
        assert fetched.status_code == 200
        assert "Draft body." in fetched.json()["content"]

        updated = client.put(
            f"/knowledge/policies/{process}/{filename}",
            json={"title": "Wizard Custom Policy", "content": "Revised body after edit."},
        )
        assert updated.status_code == 200, updated.text

        refetched = client.get(f"/knowledge/policies/{process}/{filename}")
        assert "Revised body after edit." in refetched.json()["content"]
        assert "Draft body." not in refetched.json()["content"]

        kb = client.app.state.kbs[process]
        assert any("Revised body after edit." in c.text for c in kb.all_chunks())
        assert not any("Draft body." in c.text for c in kb.all_chunks())

        deleted = client.delete(f"/knowledge/documents/{process}/custom/{filename}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["removed_chunks"] >= 1

        listed_after = client.get("/configs").json()["processes"]
        match_after = next(p for p in listed_after if p["id"] == process)
        assert all(d["name"] != filename for d in match_after["uploaded_docs"])
    finally:
        if filename:
            path = project_root / "data" / "uploads" / process / "custom" / filename
            if path.is_file():
                path.unlink()


def test_uploaded_file_is_tagged_uploaded_not_custom(client: TestClient, project_root: Path) -> None:
    process = "procurement_review"
    dest: Path | None = None
    try:
        resp = client.post(
            "/knowledge/documents",
            files={"file": ("wizard_upload_test.md", b"# doc\n\nbody", "text/markdown")},
            data={"process": process},
        )
        assert resp.status_code == 200
        dest = project_root / resp.json()["path"]

        listed = client.get("/configs").json()["processes"]
        match = next(p for p in listed if p["id"] == process)
        doc = next(d for d in match["uploaded_docs"] if d["name"] == "wizard_upload_test.md")
        assert doc["kind"] == "uploaded"
        assert doc["path"] == "wizard_upload_test.md"

        # Uploaded (non-custom) docs can't go through PUT /knowledge/policies.
        edit_attempt = client.put(
            f"/knowledge/policies/{process}/wizard_upload_test.md",
            json={"title": "x", "content": "y"},
        )
        assert edit_attempt.status_code == 404
    finally:
        if dest and dest.is_file():
            dest.unlink()


def test_delete_document_rejects_path_traversal(client: TestClient) -> None:
    resp = client.delete("/knowledge/documents/procurement_review/../../configs/finance.yaml")
    assert resp.status_code in (400, 404)


def test_process_schema_endpoint_exposes_process_config(client: TestClient) -> None:
    resp = client.get("/processes/schema")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["title"] == "ProcessConfig"
    assert "process" in schema["properties"]
    assert "finance_policy" in schema["properties"]["required_evidence_docs"]["items"]["enum"]
    assert "x-known-tools" in schema


def test_post_processes_returns_field_level_errors(client: TestClient) -> None:
    resp = client.post(
        "/processes",
        json={
            "process": "bad_evidence_proc",
            "allowed_tools": [{"name": "approve_claim"}],
            "disallowed_tools": [],
            "required_evidence_docs": ["not_a_real_doc"],
            "approval_threshold": {"risk_score_gte": 60},
            "knowledge_base_paths": [],
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any(e.get("type") == "unknown_evidence_doc" for e in detail)
    assert any(e.get("loc") == ["required_evidence_docs", 0] for e in detail)

    empty_tool = client.post(
        "/processes",
        json={
            "process": "empty_tool_proc",
            "allowed_tools": [{"name": ""}],
            "disallowed_tools": [],
            "required_evidence_docs": ["finance_policy"],
            "approval_threshold": {"risk_score_gte": 60},
            "knowledge_base_paths": [],
        },
    )
    assert empty_tool.status_code == 422
    assert any(e.get("type") == "unknown_tool" for e in empty_tool.json()["detail"])


def test_sixth_process_via_post_processes_enforced_by_gateway_without_reload(
    client: TestClient, project_root: Path
) -> None:
    """Submit a 6th sample process through the schema wizard API; the gateway
    must enforce allow/deny/amount limits with zero code changes and no reload.
    """
    process_id = "claims_review"
    try:
        create = client.post(
            "/processes",
            json={
                "process": process_id,
                "title": "Claims Review",
                "allowed_tools": [
                    {"name": "approve_claim", "max_auto_amount": 2000, "unit": "usd"}
                ],
                "disallowed_tools": ["pay_out"],
                "required_evidence_docs": ["finance_policy"],
                "approval_threshold": {"risk_score_gte": 70},
                "knowledge_base_paths": [],
            },
        )
        assert create.status_code == 200, create.text
        body = create.json()
        assert body["id"] == process_id
        assert (project_root / "configs" / f"{process_id}.yaml").is_file()

        listed = client.get("/configs").json()["processes"]
        assert any(p["id"] == process_id for p in listed)
        # Six processes on disk while this YAML exists (5 shipped + claims_review).
        assert len(listed) >= 6

        blocked = client.post(
            "/guard/evaluate",
            json={
                "process": process_id,
                "tool_name": "pay_out",
                "tool_args": {"amount": 100},
                "agent_rationale": "Pay the claim.",
            },
        )
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["decision"] == "block"

        over_ceiling = client.post(
            "/guard/evaluate",
            json={
                "process": process_id,
                "tool_name": "approve_claim",
                "tool_args": {"amount": 5000},
                "agent_rationale": "Approve a large claim.",
                "force_chunk_ids": ["chunk:policy:auto_approve"],
            },
        )
        assert over_ceiling.status_code == 200, over_ceiling.text
        assert over_ceiling.json()["decision"] == "escalate"
        assert "max_auto" in over_ceiling.json()["reason"].lower() or "2000" in over_ceiling.json()["reason"]
    finally:
        _cleanup_process(project_root, process_id)
