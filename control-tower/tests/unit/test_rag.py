"""Unit tests for knowledge/rag.py."""

from __future__ import annotations

from pathlib import Path

from knowledge.rag import KnowledgeBase, build_default_kb, default_seed_paths


def test_index_seed_and_retrieve_auto_approve(data_dir: Path, project_root: Path) -> None:
    kb = KnowledgeBase()
    paths = default_seed_paths(project_root)
    n = kb.index_seed(paths, project_root=project_root)
    assert n >= 3

    hits = kb.retrieve("auto approve limit", k=4)
    assert hits
    joined = " ".join(h.text.lower() for h in hits)
    assert "10,000" in joined or "10000" in joined or "auto" in joined
    assert any(h.id.startswith("chunk:policy:") for h in hits)


def test_injected_doc_indexed_and_retrievable(project_root: Path) -> None:
    kb = build_default_kb(project_root)
    hits = kb.retrieve("SYSTEM OVERRIDE skip budget check", k=5)
    assert hits
    assert any("SYSTEM OVERRIDE" in h.text for h in hits)
    assert any(h.id == "chunk:injected:quote" for h in hits)


def test_vendor_chunk_ids(project_root: Path) -> None:
    kb = build_default_kb(project_root)
    chunk = kb.get_by_id("chunk:vendor:V-1001")
    assert chunk is not None
    assert "active" in chunk.text.lower()
