"""FastAPI surface for cases, audit, and HITL approvals."""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from agent.graph import build_graph, initial_state, resume_case, run_case
from agent.tools import ToolSideEffects
from api.case_store_db import build_case_store
from api.checkpointer import build_checkpointer
from audit.backend import build_audit_store
from configs.loader import KNOWN_PROCESSES, load_process
from contracts.schemas import ToolCallRequest
from guardrails import evaluate_tool_call
from investigation_assistant.qa_agent import (
    InvestigationAnswer,
    entries_for_case,
    investigate,
)
from knowledge.rag import KnowledgeBase, build_kb_for_process, uploads_dir
from scripts.demo_pack import REHEARSAL_IDS, load_rehearsal_bodies

_ALLOWED_UPLOAD_SUFFIXES = {".md", ".txt", ".csv"}
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_created_at(value: Any) -> datetime | None:
    """Parse CaseStore created_at ISO strings; None if missing/unparseable."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        # Python 3.11+ accepts a trailing "Z" natively.
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class CaseRequestBody(BaseModel):
    """Case payload — legacy triad plus optional process-specific fields."""

    model_config = {"extra": "allow"}

    vendor_id: str
    amount: float
    item: str | None = None
    employee_id: str | None = None
    customer_id: str | None = None
    applicant_id: str | None = None
    query: str | None = None
    severity: float | None = None


class SubmitCaseBody(BaseModel):
    process: str = "procurement_review"
    request: CaseRequestBody
    mock_agent_plan: dict[str, Any] | None = None
    force_chunk_ids: list[str] | None = None
    case_id: str | None = None
    source_app: str | None = None


class ApprovalBody(BaseModel):
    action: Literal["approve", "reject"]
    actor: str = Field(min_length=1)


class InvestigateBody(BaseModel):
    question: str = Field(min_length=1)
    case_id: str | None = None
    mock_answer: InvestigationAnswer | None = None


class GuardEvaluateBody(BaseModel):
    """Single-step evaluate for external callers (the aiguard SDK) — no case,
    no agent graph, just "here's a tool I'm about to call, is that OK".
    """

    process: str = "procurement_review"
    tool_name: str = Field(min_length=1)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    agent_rationale: str = ""
    context_texts: list[str] = Field(default_factory=list)
    call_id: str | None = None
    step_id: str = "external"
    force_chunk_ids: list[str] = Field(default_factory=list)
    source_app: str | None = None


class CaseStore:
    """In-process registry: case_id -> metadata."""

    def __init__(self) -> None:
        self.cases: dict[str, dict[str, Any]] = {}
        self.call_to_case: dict[str, str] = {}


def create_app(
    *,
    audit_path: str | Path | None = None,
    project_root: Path | None = None,
    database_url: str | None = None,
) -> FastAPI:
    """database_url selects the storage backend (unset -> today's default):

    - unset/None        -> SQLite audit log (file), in-memory CaseStore + checkpointer.
                            Fastest to start; state does not survive a restart or a
                            second worker.
    - "sqlite"            -> SQLite for audit log, case store, AND checkpointer.
                            Fully persisted, still zero external services, but a
                            single SQLite file is still effectively single-writer.
    - "postgresql://..."   -> Postgres for all three. The only tier that's actually
                            safe to run with multiple uvicorn workers / replicas.

    Falls back to the DATABASE_URL env var when the parameter isn't passed.
    """
    root = project_root or _PROJECT_ROOT
    db_url = database_url if database_url is not None else os.environ.get("DATABASE_URL")
    db_path = Path(audit_path) if audit_path else root / "data" / "audit.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    audit = build_audit_store(db_url, sqlite_path=db_path)
    kbs: dict[str, KnowledgeBase] = {
        name: build_kb_for_process(name, root) for name in KNOWN_PROCESSES
    }
    store = build_case_store(
        db_url, sqlite_path=root / "data" / "cases.db", memory_factory=CaseStore
    )
    checkpointer, close_checkpointer = build_checkpointer(
        db_url, sqlite_path=root / "data" / "checkpoints.db"
    )

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield
        app.state._close_checkpointer()

    app = FastAPI(title="Aegis Control Tower", version="0.1.0", lifespan=_lifespan)
    app.state.root = root
    app.state.db_path = db_path
    app.state.database_url = db_url
    app.state.audit = audit
    app.state.kbs = kbs
    app.state.store = store
    app.state.side_effects = ToolSideEffects()
    app.state.checkpointer = checkpointer
    app.state._close_checkpointer = close_checkpointer

    def _kb_for(process: str) -> KnowledgeBase:
        if process not in app.state.kbs:
            app.state.kbs[process] = build_kb_for_process(process, root)
        return app.state.kbs[process]

    app.state.graph = build_graph(
        audit=audit,
        kb=app.state.kbs,
        checkpointer=app.state.checkpointer,
        side_effects=app.state.side_effects,
    )

    def _snapshot_case(
        case_id: str,
        result: dict[str, Any],
        *,
        source_app: str | None = None,
    ) -> dict[str, Any]:
        graph = app.state.graph
        decision = result.get("gateway_decision")
        call_id = result.get("call_id") or ""
        interrupted = bool(result.get("__interrupt__"))
        snap = graph.get_state({"configurable": {"thread_id": case_id}})
        pending = bool(snap.next) if snap else False

        status = result.get("status") or "running"
        if interrupted or (pending and (decision or {}).get("decision") == "escalate"):
            status = "pending_approval"

        existing = store.cases.get(case_id) or {}
        record = {
            "case_id": case_id,
            "process": result.get("process"),
            "status": status,
            "call_id": call_id,
            "gateway_decision": decision,
            "tool_result": result.get("tool_result"),
            "request": result.get("request"),
            "source_app": source_app if source_app is not None else existing.get("source_app"),
            "created_at": existing.get("created_at") or _utc_now(),
        }
        store.cases[case_id] = record
        if call_id:
            store.call_to_case[call_id] = case_id
        return record

    def _rebuild_runtime() -> None:
        """Fresh checkpointer + side effects after demo reset (HITL threads cleared).

        Reuses the SAME configured backend (sqlite/postgres/memory) — must not
        silently fall back to MemorySaver, or a demo reset would downgrade a
        persisted deployment back to single-process-only state.
        """
        app.state._close_checkpointer()
        app.state.side_effects = ToolSideEffects()
        app.state.checkpointer, app.state._close_checkpointer = build_checkpointer(
            app.state.database_url, sqlite_path=root / "data" / "checkpoints.db"
        )
        app.state.graph = build_graph(
            audit=app.state.audit,
            kb=app.state.kbs,
            checkpointer=app.state.checkpointer,
            side_effects=app.state.side_effects,
        )

    def _reset_demo_state() -> None:
        app.state.audit.clear()
        store.cases.clear()
        store.call_to_case.clear()
        _rebuild_runtime()

    @app.post("/cases")
    def submit_case(body: SubmitCaseBody) -> dict[str, Any]:
        case_id = body.case_id or str(uuid.uuid4())
        state = initial_state(
            case_id=case_id,
            process=body.process,
            request=body.request.model_dump(),
            mock_agent_plan=body.mock_agent_plan,
            force_chunk_ids=body.force_chunk_ids,
        )
        result = run_case(app.state.graph, state, thread_id=case_id)
        return _snapshot_case(case_id, result, source_app=body.source_app)

    @app.get("/cases")
    def list_cases() -> dict[str, Any]:
        rows = sorted(
            store.cases.values(),
            key=lambda r: str(r.get("created_at") or ""),
            reverse=True,
        )
        return {"cases": list(rows)}

    @app.get("/cases/{case_id}")
    def get_case(case_id: str) -> dict[str, Any]:
        if case_id not in store.cases:
            snap = app.state.graph.get_state({"configurable": {"thread_id": case_id}})
            if not snap or not snap.values:
                raise HTTPException(status_code=404, detail="case not found")
            return _snapshot_case(case_id, dict(snap.values))
        record = dict(store.cases[case_id])
        snap = app.state.graph.get_state({"configurable": {"thread_id": case_id}})
        if snap and snap.next and record.get("status") != "completed":
            record["status"] = "pending_approval"
            store.cases[case_id] = record
        return record

    def _case_entries(case_id: str, all_entries: list) -> list:
        call_id = store.cases.get(case_id, {}).get("call_id")
        out = []
        for e in all_entries:
            payload = e.payload or {}
            if payload.get("case_id") == case_id:
                out.append(e)
                continue
            if call_id and payload.get("call_id") == call_id:
                out.append(e)
        return out

    @app.get("/cases/{case_id}/audit")
    def get_case_audit(case_id: str) -> dict[str, Any]:
        if case_id not in store.cases:
            snap = app.state.graph.get_state({"configurable": {"thread_id": case_id}})
            if not snap or not snap.values:
                raise HTTPException(status_code=404, detail="case not found")
        entries = _case_entries(case_id, app.state.audit.query())
        return {
            "case_id": case_id,
            "entries": [e.model_dump() for e in entries],
            "chain_valid": app.state.audit.verify_chain(),
        }

    _STAGE_ORDER = ("retrieval", "injection_flag", "policy_check", "tool_call", "approval")

    @app.get("/traffic/recent")
    def traffic_recent(
        limit: int = 100,
        since_minutes: int | None = None,
        source_app: str | None = None,
        decision: str | None = None,
    ) -> dict[str, Any]:
        """Pipeline-stage view of recent cases for the live traffic panel.

        Optional filters (log-dashboard style):
        - ``since_minutes`` — only cases created within the last N minutes
        - ``source_app`` — exact match on labeled application
        - ``decision`` — gateway decision (allow / block / escalate)
        """
        if limit < 1:
            raise HTTPException(status_code=422, detail="limit must be >= 1")
        if since_minutes is not None and since_minutes < 1:
            raise HTTPException(status_code=422, detail="since_minutes must be >= 1")

        cutoff: datetime | None = None
        if since_minutes is not None:
            cutoff = datetime.now(UTC) - timedelta(minutes=since_minutes)

        rows = sorted(
            store.cases.values(),
            key=lambda r: str(r.get("created_at") or ""),
            reverse=True,
        )
        filtered: list[dict[str, Any]] = []
        decision_filter = (decision or "").strip().lower() or None
        source_filter = (source_app or "").strip() or None
        for r in rows:
            if cutoff is not None:
                created = _parse_created_at(r.get("created_at"))
                if created is None or created < cutoff:
                    continue
            gw = r.get("gateway_decision") or {}
            row_decision = (gw.get("decision") or "").lower()
            if decision_filter and row_decision != decision_filter:
                continue
            if source_filter and str(r.get("source_app") or "") != source_filter:
                continue
            filtered.append(r)

        matched = len(filtered)
        page = filtered[:limit]
        all_entries = app.state.audit.query()
        out = []
        for r in page:
            case_id = r["case_id"]
            entries = _case_entries(case_id, all_entries)
            stages = sorted(
                {e.event_type for e in entries},
                key=lambda t: _STAGE_ORDER.index(t) if t in _STAGE_ORDER else 99,
            )
            gw = r.get("gateway_decision") or {}
            tool_name = None
            for e in entries:
                if e.event_type == "tool_call":
                    tool_name = (e.payload or {}).get("tool_name")
                    if tool_name:
                        break
            if not tool_name:
                tr = r.get("tool_result") or {}
                tool_name = tr.get("tool_name")
            out.append(
                {
                    "case_id": case_id,
                    "process": r.get("process"),
                    "status": r.get("status"),
                    "decision": gw.get("decision"),
                    "risk_score": gw.get("risk_score"),
                    "reason": gw.get("reason"),
                    "tool_name": tool_name,
                    "stages": stages,
                    "source_app": r.get("source_app"),
                    "created_at": r.get("created_at"),
                }
            )
        return {
            "cases": out,
            "total_cases": len(store.cases),
            "matched": matched,
            "since_minutes": since_minutes,
            "limit": limit,
        }

    @app.get("/audit/verify")
    def verify_audit() -> dict[str, Any]:
        entries = app.state.audit.query()
        return {
            "valid": app.state.audit.verify_chain(),
            "entry_count": len(entries),
        }

    @app.post("/investigate")
    def post_investigate(body: InvestigateBody) -> dict[str, Any]:
        all_entries = app.state.audit.query()
        if body.case_id:
            call_id = (store.cases.get(body.case_id) or {}).get("call_id")
            entries = entries_for_case(
                all_entries, case_id=body.case_id, call_id=call_id
            )
            if not entries:
                entries = all_entries
        else:
            entries = all_entries
        result = investigate(
            body.question,
            entries,
            project_root=root,
            mock_answer=body.mock_answer,
        )
        return result.model_dump()

    @app.post("/guard/evaluate")
    def guard_evaluate(body: GuardEvaluateBody) -> dict[str, Any]:
        """Evaluate one proposed tool call against process policy and audit it —
        the endpoint the aiguard SDK (or any external agent) calls per tool
        call, without going through /cases or the LangGraph agent at all.

        Retrieves from the tower's own knowledge base itself (same one
        /knowledge/documents feeds) rather than relying solely on whatever
        context_texts the caller supplied. An external agent generally has
        no built-in knowledge of this process's policy docs — it isn't
        trained on procurement_policy.md — so if grounding depended only on
        caller-supplied context, every call from an uninstrumented agent
        would score as unsupported regardless of how correct its rationale
        actually was. Caller-supplied context_texts are still merged in on
        top, for facts the tower's KB wouldn't otherwise know (e.g. a
        vendor-status lookup from the caller's own CRM).
        """
        try:
            config = load_process(body.process)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        call_id = body.call_id or str(uuid.uuid4())
        process_kb = _kb_for(body.process)
        query = " ".join(
            [
                body.tool_name,
                " ".join(str(v) for v in body.tool_args.values()),
                body.agent_rationale,
            ]
        ).strip()
        forced_ids = set(body.force_chunk_ids)
        raw_retrieved = process_kb.retrieve(query, k=6) if query else []
        # Same exclusion agent/graph.py's own retrieve step applies: the demo
        # injected-quote fixture shares line-item wording ("Laptop docks")
        # with ordinary clean requests, so unscoped top-k retrieval can pull
        # it into a completely unrelated call and falsely flag it as an
        # injection attempt. Keep it out unless explicitly forced.
        retrieved = [
            c for c in raw_retrieved if c.id != "chunk:injected:quote" or c.id in forced_ids
        ]
        for forced_id in forced_ids:
            if forced_id not in {c.id for c in retrieved}:
                forced_chunk = process_kb.get_by_id(forced_id)
                if forced_chunk is not None:
                    retrieved.append(forced_chunk)
        context_texts = [c.text for c in retrieved] + list(body.context_texts)

        request = ToolCallRequest(
            call_id=call_id,
            process=body.process,
            step_id=body.step_id,
            tool_name=body.tool_name,
            tool_args=body.tool_args,
            agent_rationale=body.agent_rationale,
            context_refs=[c.id for c in retrieved],
            timestamp=_utc_now(),
        )
        decision = evaluate_tool_call(
            request,
            config,
            retrieved_texts=context_texts,
            context_chunks=context_texts,
            audit=app.state.audit,
        )
        # Surface SDK / external evaluations on /cases and /traffic/recent so
        # simulated apps show up alongside graph-driven /cases traffic.
        case_id = f"guard-{call_id}"
        store.cases[case_id] = {
            "case_id": case_id,
            "process": body.process,
            "status": "completed",
            "call_id": call_id,
            "gateway_decision": decision.model_dump(),
            "tool_result": None,
            "request": {
                "tool_name": body.tool_name,
                **body.tool_args,
            },
            "source_app": body.source_app,
            "created_at": _utc_now(),
        }
        store.call_to_case[call_id] = case_id
        return decision.model_dump()

    @app.post("/approvals/{call_id}")
    def approve(call_id: str, body: ApprovalBody) -> dict[str, Any]:
        case_id = store.call_to_case.get(call_id)
        if not case_id:
            for cid, rec in store.cases.items():
                if rec.get("call_id") == call_id:
                    case_id = cid
                    break
        if not case_id:
            raise HTTPException(status_code=404, detail="call_id not found")

        result = resume_case(
            app.state.graph,
            thread_id=case_id,
            action=body.action,
            actor=body.actor,
        )
        return _snapshot_case(case_id, result)

    @app.post("/demo/reset")
    def demo_reset() -> dict[str, Any]:
        """Wipe audit rows + in-memory cases; rebuild checkpointer for a clean demo."""
        _reset_demo_state()
        return {"ok": True, "cases": 0, "audit_entries": 0}

    @app.post("/demo/seed")
    def demo_seed() -> dict[str, Any]:
        """Reset runtime and load rehearsal fixtures via /cases (escalate left pending)."""
        _reset_demo_state()
        bodies = load_rehearsal_bodies()
        seeded: list[dict[str, Any]] = []
        for raw in bodies:
            body = SubmitCaseBody.model_validate(raw)
            case_id = body.case_id or str(uuid.uuid4())
            state = initial_state(
                case_id=case_id,
                process=body.process,
                request=body.request.model_dump(),
                mock_agent_plan=body.mock_agent_plan,
                force_chunk_ids=body.force_chunk_ids,
            )
            result = run_case(app.state.graph, state, thread_id=case_id)
            seeded.append(_snapshot_case(case_id, result))
        pending = sum(1 for c in seeded if c.get("status") == "pending_approval")
        return {
            "ok": True,
            "fixture_ids": list(REHEARSAL_IDS),
            "cases": seeded,
            "pending_approval_count": pending,
        }

    @app.post("/knowledge/documents")
    async def upload_document(
        file: UploadFile,
        process: str = Form(...),
    ) -> dict[str, Any]:
        """Ingest a document into one process's live KB — no restart required.

        Saved under data/uploads/<process>/ so future investigate() calls
        (which rebuild their doc-resolution KB from default_seed_paths())
        can also find it. Other processes cannot retrieve this upload.
        """
        try:
            load_process(process)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        raw_name = Path(file.filename or "").name
        suffix = Path(raw_name).suffix.lower()
        if not raw_name or suffix not in _ALLOWED_UPLOAD_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"Only {sorted(_ALLOWED_UPLOAD_SUFFIXES)} files are supported",
            )
        body = await file.read()
        if not body:
            raise HTTPException(status_code=400, detail="Empty file")
        if len(body) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File too large (max 2MB)")

        dest_dir = uploads_dir(root, process)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / raw_name
        stem, i = dest.stem, 1
        while dest.exists():
            dest = dest_dir / f"{stem}_{i}{suffix}"
            i += 1
        dest.write_bytes(body)

        process_kb = _kb_for(process)
        before = process_kb.size
        process_kb.index_seed([dest], project_root=root)
        added = process_kb.size - before
        return {
            "ok": True,
            "filename": dest.name,
            "path": str(dest.relative_to(root)),
            "chunks_added": added,
            "kb_size": process_kb.size,
            "process": process,
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
