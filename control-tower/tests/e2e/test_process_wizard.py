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
