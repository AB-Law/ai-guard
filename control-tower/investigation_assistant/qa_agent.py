"""Investigation assistant — RAG over audit log + source documents."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from contracts.schemas import AuditLogEntry
from knowledge.rag import KnowledgeBase, RetrievedChunk, default_seed_paths

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InvestigationAnswer(BaseModel):
    answer: str
    cited_entry_ids: list[str] = Field(default_factory=list)
    cited_chunk_ids: list[str] = Field(default_factory=list)


def _entry_to_text(entry: AuditLogEntry) -> str:
    parts = [
        f"Audit entry_id={entry.entry_id}",
        f"event_type={entry.event_type}",
        f"process={entry.process}",
        f"step_id={entry.step_id}",
        f"timestamp={entry.timestamp}",
    ]
    if entry.scores is not None:
        parts.append(
            f"decision={entry.scores.decision} "
            f"risk_score={entry.scores.risk_score} "
            f"reason={entry.scores.reason}"
        )
        if entry.scores.policy_refs:
            parts.append("policy_refs=" + ",".join(entry.scores.policy_refs))
    payload = entry.payload or {}
    if payload:
        parts.append("payload=" + json.dumps(payload, sort_keys=True, default=str))
    return "\n".join(parts)


def referenced_doc_ids(entries: list[AuditLogEntry]) -> set[str]:
    """Chunk ids the case audit trail actually touched (retrieval / policy refs)."""
    ids: set[str] = set()
    for entry in entries:
        payload = entry.payload or {}
        for key in ("chunk_ids", "context_refs", "policy_refs"):
            raw = payload.get(key) or []
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, str) and item.startswith("chunk:"):
                        ids.add(item)
        if entry.scores is not None:
            for ref in entry.scores.policy_refs or []:
                if isinstance(ref, str) and ref.startswith("chunk:"):
                    ids.add(ref)
    return ids


def index_audit_entries(
    entries: list[AuditLogEntry],
    *,
    kb: KnowledgeBase | None = None,
) -> KnowledgeBase:
    """Index audit rows as searchable chunks with id audit:{entry_id}."""
    target = kb or KnowledgeBase(collection_name="aegis_investigation")
    chunks = [
        RetrievedChunk(
            id=f"audit:{e.entry_id}",
            text=_entry_to_text(e),
            source=f"audit:{e.entry_id}",
        )
        for e in entries
    ]
    if chunks:
        target.upsert_chunks(chunks)
    return target


def _resolve_referenced_seed_chunks(
    audit_entries: list[AuditLogEntry],
    *,
    project_root: Path,
) -> list[RetrievedChunk]:
    """Load only seed docs cited by this case's audit trail (never the full corpus)."""
    refs = referenced_doc_ids(audit_entries)
    if not refs:
        return []
    seed_kb = KnowledgeBase(collection_name="aegis_investigation_seed_resolve")
    seed_kb.index_seed(default_seed_paths(project_root), project_root=project_root)
    chunks: list[RetrievedChunk] = []
    for chunk_id in sorted(refs):
        chunk = seed_kb.get_by_id(chunk_id)
        if chunk is not None:
            chunks.append(chunk)
    return chunks


def build_investigation_kb(
    audit_entries: list[AuditLogEntry],
    *,
    project_root: Path | None = None,
) -> KnowledgeBase:
    """KB with this case's audit entries plus only audit-referenced seed docs.

    Global seed docs (policy, vendor master, planted injection quote) are **not**
    mixed into the index unless the case trail cites them — otherwise a generic
    question retrieves another case's distinctive document by embedding similarity.
    """
    root = project_root or _PROJECT_ROOT
    kb = KnowledgeBase(collection_name="aegis_investigation")
    referenced = _resolve_referenced_seed_chunks(audit_entries, project_root=root)
    if referenced:
        kb.upsert_chunks(referenced)
    return index_audit_entries(audit_entries, kb=kb)


def _parse_cited_entry_ids(chunk_ids: list[str]) -> list[str]:
    out: list[str] = []
    for cid in chunk_ids:
        if cid.startswith("audit:"):
            out.append(cid.removeprefix("audit:"))
    return out


def retrieve_investigation_context(
    kb: KnowledgeBase,
    question: str,
    *,
    audit_entries: list[AuditLogEntry],
    k: int = 6,
) -> list[RetrievedChunk]:
    """Case-scoped retrieval: rank audit chunks first, then referenced seed docs only."""
    case_audit_ids = {f"audit:{e.entry_id}" for e in audit_entries}
    allowed_docs = referenced_doc_ids(audit_entries)

    pool_n = max(k * 5, 20)
    # KnowledgeBase has no public size; over-fetch then filter to case scope.
    raw = kb.retrieve(question, k=pool_n)

    ranked_audit = [c for c in raw if c.id in case_audit_ids]
    seen = {c.id for c in ranked_audit}

    # Ensure every case audit row is available (trails are small; avoid missing the reason).
    for entry in audit_entries:
        aid = f"audit:{entry.entry_id}"
        if aid in seen:
            continue
        chunk = kb.get_by_id(aid)
        if chunk is not None:
            ranked_audit.append(chunk)
            seen.add(aid)

    seed_chunks: list[RetrievedChunk] = []
    for doc_id in sorted(allowed_docs):
        chunk = kb.get_by_id(doc_id)
        if chunk is not None and chunk.id not in seen:
            seed_chunks.append(chunk)
            seen.add(chunk.id)

    # Prefer top-k audit hits; always attach referenced evidence docs after.
    selected = ranked_audit[:k] + seed_chunks
    return selected


def _live_answer(question: str, chunks: list[RetrievedChunk]) -> InvestigationAnswer:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required when mock_answer is not provided"
        )

    from langchain_openai import ChatOpenAI

    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")
    llm = ChatOpenAI(model=model_name, api_key=api_key)
    structured = llm.with_structured_output(InvestigationAnswer, method="function_calling")

    context_blocks = []
    allowed_ids: list[str] = []
    for c in chunks:
        allowed_ids.append(c.id)
        context_blocks.append(f"[{c.id}] (source={c.source})\n{c.text}")

    prompt = (
        "You are an investigation assistant for an AI control tower. "
        "Answer the question using ONLY the retrieved context below. "
        "Cite audit entry_ids (from chunk ids like audit:<entry_id>) in cited_entry_ids "
        "and any source doc chunk ids in cited_chunk_ids. "
        "Only cite ids that appear in the context.\n\n"
        f"Question: {question}\n\n"
        "Context:\n" + "\n\n".join(context_blocks)
    )
    raw = structured.invoke(prompt)
    answer = InvestigationAnswer.model_validate(raw)

    allowed_entry = set(_parse_cited_entry_ids(allowed_ids))
    allowed_chunks = {c for c in allowed_ids if not c.startswith("audit:")}
    answer.cited_entry_ids = [e for e in answer.cited_entry_ids if e in allowed_entry]
    answer.cited_chunk_ids = [c for c in answer.cited_chunk_ids if c in allowed_chunks]
    return answer


def answer_question(
    question: str,
    *,
    kb: KnowledgeBase,
    audit_entries: list[AuditLogEntry] | None = None,
    mock_answer: InvestigationAnswer | None = None,
    k: int = 6,
) -> InvestigationAnswer:
    """Answer an investigation question over the investigation KB.

    Offline tests pass ``mock_answer`` to bypass the live LLM.
    When ``audit_entries`` is provided, retrieval is scoped to those rows and
    only seed docs their trail references.
    """
    if mock_answer is not None:
        return mock_answer

    if audit_entries is not None:
        chunks = retrieve_investigation_context(
            kb, question, audit_entries=audit_entries, k=k
        )
    else:
        chunks = kb.retrieve(question, k=k)
    if not chunks:
        return InvestigationAnswer(
            answer="No relevant audit or policy context found.",
            cited_entry_ids=[],
            cited_chunk_ids=[],
        )
    return _live_answer(question, chunks)


def entries_for_case(
    entries: list[AuditLogEntry],
    *,
    case_id: str,
    call_id: str | None = None,
) -> list[AuditLogEntry]:
    """Filter audit entries belonging to a case (payload.case_id or call_id)."""
    filtered: list[AuditLogEntry] = []
    for e in entries:
        payload = e.payload or {}
        if payload.get("case_id") == case_id:
            filtered.append(e)
            continue
        if call_id and payload.get("call_id") == call_id:
            filtered.append(e)
    return filtered


def investigate(
    question: str,
    audit_entries: list[AuditLogEntry],
    *,
    project_root: Path | None = None,
    mock_answer: InvestigationAnswer | dict[str, Any] | None = None,
) -> InvestigationAnswer:
    """Build case-scoped investigation KB and answer with audit-first retrieval."""
    kb = build_investigation_kb(audit_entries, project_root=project_root)
    mock: InvestigationAnswer | None = None
    if mock_answer is not None:
        mock = (
            mock_answer
            if isinstance(mock_answer, InvestigationAnswer)
            else InvestigationAnswer.model_validate(mock_answer)
        )
    return answer_question(
        question, kb=kb, audit_entries=audit_entries, mock_answer=mock
    )
