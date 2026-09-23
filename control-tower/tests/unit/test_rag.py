"""Unit tests for knowledge/rag.py."""

from __future__ import annotations

from pathlib import Path

from knowledge.rag import (
    KnowledgeBase,
    build_default_kb,
    build_kb_for_process,
    default_seed_paths,
)


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


def test_build_kb_for_process_isolates_content(project_root: Path) -> None:
    """Each process KB must only retrieve its own docs — never the other's."""
    kb_proc = build_kb_for_process("procurement_review", project_root)
    kb_kyc = build_kb_for_process("onboarding_kyc", project_root)

    assert kb_proc.get_by_id("chunk:vendor:V-1001") is not None
    assert kb_proc.get_by_id("chunk:policy:auto_approve") is not None
    assert kb_proc.get_by_id("chunk:injected:quote") is not None
    assert kb_proc.get_by_id("chunk:kyc:identity_verification") is None

    assert kb_kyc.get_by_id("chunk:kyc:identity_verification") is not None
    assert kb_kyc.get_by_id("chunk:vendor:V-1001") is None
    assert kb_kyc.get_by_id("chunk:policy:auto_approve") is None
    assert kb_kyc.get_by_id("chunk:injected:quote") is None

    proc_hits = kb_proc.retrieve("identity verification KYC applicant", k=6)
    assert not any(h.id.startswith("chunk:kyc:") for h in proc_hits)

    kyc_hits = kb_kyc.retrieve("auto approve vendor purchase order", k=6)
    assert not any(h.id.startswith("chunk:policy:") for h in kyc_hits)
    assert not any(h.id.startswith("chunk:vendor:") for h in kyc_hits)
