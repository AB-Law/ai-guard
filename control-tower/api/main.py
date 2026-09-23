"""FastAPI surface for cases, audit, and HITL approvals."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from agent.graph import build_graph, initial_state, resume_case, run_case
from agent.tools import ToolSideEffects
from audit.log_store import AuditLogStore
from investigation_assistant.qa_agent import (
    InvestigationAnswer,
    entries_for_case,
    investigate,
)
from knowledge.rag import build_default_kb, uploads_dir
from scripts.demo_pack import REHEARSAL_IDS, load_rehearsal_bodies

_ALLOWED_UPLOAD_SUFFIXES = {".md", ".txt", ".csv"}
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaseRequestBody(BaseModel):
    vendor_id: str
    amount: float
    item: str | None = None


class SubmitCaseBody(BaseModel):
    process: str = "procurement_review"
    request: CaseRequestBody
    mock_agent_plan: dict[str, Any] | None = None
    force_chunk_ids: list[str] | None = None
    case_id: str | None = None


class ApprovalBody(BaseModel):
    action: Literal["approve", "reject"]
    actor: str = Field(min_length=1)


class InvestigateBody(BaseModel):
    question: str = Field(min_length=1)
    case_id: str | None = None
    mock_answer: InvestigationAnswer | None = None


class CaseStore:
    """In-process registry: case_id -> metadata."""

    def __init__(self) -> None:
        self.cases: dict[str, dict[str, Any]] = {}
        self.call_to_case: dict[str, str] = {}


def create_app(
    *,
    audit_path: str | Path | None = None,
    project_root: Path | None = None,
) -> FastAPI:
    root = project_root or _PROJECT_ROOT
    db_path = Path(audit_path) if audit_path else root / "data" / "audit.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    audit = AuditLogStore(db_path)
    kb = build_default_kb(root)
    store = CaseStore()

    app = FastAPI(title="Aegis Control Tower", version="0.1.0")
    app.state.root = root
    app.state.db_path = db_path
    app.state.audit = audit
    app.state.kb = kb
    app.state.store = store
    app.state.side_effects = ToolSideEffects()
    app.state.checkpointer = MemorySaver()
    app.state.graph = build_graph(
        audit=audit,
        kb=kb,
        checkpointer=app.state.checkpointer,
        side_effects=app.state.side_effects,
    )

    def _snapshot_case(case_id: str, result: dict[str, Any]) -> dict[str, Any]:
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
            "created_at": existing.get("created_at") or _utc_now(),
        }
        store.cases[case_id] = record
        if call_id:
            store.call_to_case[call_id] = case_id
        return record

    def _rebuild_runtime() -> None:
        """Fresh checkpointer + side effects after demo reset (HITL threads cleared)."""
        app.state.side_effects = ToolSideEffects()
        app.state.checkpointer = MemorySaver()
        app.state.graph = build_graph(
            audit=app.state.audit,
            kb=app.state.kb,
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
        return _snapshot_case(case_id, result)

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
    def traffic_recent(limit: int = 40) -> dict[str, Any]:
        """Pipeline-stage view of recent cases for the live traffic panel."""
        rows = sorted(
            store.cases.values(),
            key=lambda r: str(r.get("created_at") or ""),
            reverse=True,
        )[:limit]
        all_entries = app.state.audit.query()
        out = []
        for r in rows:
            case_id = r["case_id"]
            entries = _case_entries(case_id, all_entries)
            stages = sorted(
                {e.event_type for e in entries},
                key=lambda t: _STAGE_ORDER.index(t) if t in _STAGE_ORDER else 99,
            )
            decision = r.get("gateway_decision") or {}
            out.append(
                {
                    "case_id": case_id,
                    "process": r.get("process"),
                    "status": r.get("status"),
                    "decision": decision.get("decision"),
                    "risk_score": decision.get("risk_score"),
                    "stages": stages,
                    "created_at": r.get("created_at"),
                }
            )
        return {"cases": out, "total_cases": len(store.cases)}

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
    async def upload_document(file: UploadFile) -> dict[str, Any]:
        """Ingest a document into the live knowledge base — no restart required.

        Saved under data/uploads/ so future investigate() calls (which rebuild
        their doc-resolution KB from default_seed_paths()) can also find it.
        """
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

        dest_dir = uploads_dir(root)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / raw_name
        stem, i = dest.stem, 1
        while dest.exists():
            dest = dest_dir / f"{stem}_{i}{suffix}"
            i += 1
        dest.write_bytes(body)

        before = app.state.kb.size
        app.state.kb.index_seed([dest], project_root=root)
        added = app.state.kb.size - before
        return {
            "ok": True,
            "filename": dest.name,
            "path": str(dest.relative_to(root)),
            "chunks_added": added,
            "kb_size": app.state.kb.size,
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
