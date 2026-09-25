"""FastAPI surface for cases, audit, and HITL approvals."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from agent.graph import build_graph, initial_state, resume_case, run_case
from agent.tools import ToolSideEffects
from api import auth
from api.case_store_db import build_case_store, build_kv_store
from api.checkpointer import build_checkpointer
from audit.backend import build_audit_store
from audit.log_store import AppendInput
from configs.loader import (
    ProcessConfig,
    apply_rule,
    clear_process_cache,
    known_processes,
    load_process,
)
from contracts.schemas import GatewayDecision, ToolCallRequest
from guardrails import evaluate_tool_call, is_hard_block
from guardrails.rule_store import get_rule_store
from investigation_assistant.qa_agent import (
    InvestigationAnswer,
    entries_for_case,
    investigate,
)
from knowledge.rag import KnowledgeBase, build_kb_for_process, source_for_path, uploads_dir
from scripts.demo_pack import REHEARSAL_IDS, load_rehearsal_bodies

_ALLOWED_UPLOAD_SUFFIXES = {".md", ".txt", ".csv"}
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "item"


CUSTOM_POLICY_DIRNAME = "custom"


def _list_uploaded_docs(updir: Path) -> list[dict[str, str]]:
    """Every file under a process's upload dir, tagged uploaded vs custom —
    a plain file upload is immutable (delete + re-upload to change it), a
    custom policy (written via POST /knowledge/policies) can be edited in
    place because we authored the file ourselves and know its exact shape."""
    out: list[dict[str, str]] = []
    for path in sorted(updir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(updir)
        kind = "custom" if rel.parts[0] == CUSTOM_POLICY_DIRNAME else "uploaded"
        out.append({"name": path.name, "kind": kind, "path": str(rel).replace("\\", "/")})
    return out


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "app"


def _generate_api_key(environment: str) -> str:
    tag = "live" if environment == "production" else "test"
    return f"sk_{tag}_{secrets.token_hex(16)}"


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _mask_key(key_prefix: str, key_last4: str) -> str:
    return f"{key_prefix}{'•' * 8}{key_last4}"


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
    # Optional tightened literal when approving a policy_change proposal.
    # Dashboard login is the trust boundary for permanent policy writes (same
    # as config edits) — no separate role system in v1.
    rule_text: str | None = None


class DemoTamperBody(BaseModel):
    enable: bool = True


class LoginBody(BaseModel):
    password: str = Field(min_length=1)


class CreateApplicationBody(BaseModel):
    """Registers an agent identity with the tower — ARCHITECTURE §4.2's
    "no ambient tool access; every call allow-listed per process" starts with
    knowing which agent is calling. source_app defaults to a slug of name and
    is the value that agent should send as `source_app` on /cases and
    /guard/evaluate — that's how request stats below are attributed.
    """

    name: str = Field(min_length=1)
    environment: Literal["production", "staging"] = "production"
    process: str
    source_app: str | None = None


class ProcessToolBody(BaseModel):
    name: str = Field(min_length=1)
    max_auto_amount: float | None = None
    unit: str = ""


class CreateProcessBody(BaseModel):
    """Wizard step 1 — a new process is just a new configs/<id>.yaml; the
    gateway and dashboard pick it up with zero code changes (ARCHITECTURE.md
    §4.3, "config-driven process definition")."""

    title: str = Field(min_length=1)
    allowed_tools: list[ProcessToolBody] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)
    approval_threshold: int = Field(default=60, ge=0, le=100)


class UpdateProcessBody(BaseModel):
    """Wizard step 2 (or a later edit) — partial update, only given fields change."""

    allowed_tools: list[ProcessToolBody] | None = None
    disallowed_tools: list[str] | None = None
    approval_threshold: int | None = Field(default=None, ge=0, le=100)


class CreatePolicyBody(BaseModel):
    process: str
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class UpdatePolicyBody(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


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
    rule_store = get_rule_store(
        db_path=root / "data" / "learned_rules.db",
        database_url=db_url,
        reset=True,
    )
    kbs: dict[str, KnowledgeBase] = {
        name: build_kb_for_process(name, root) for name in known_processes(root / "configs")
    }
    store = build_case_store(
        db_url, sqlite_path=root / "data" / "cases.db", memory_factory=CaseStore
    )
    applications = build_kv_store(
        db_url,
        table="applications",
        key_col="app_id",
        sqlite_path=root / "data" / "applications.db",
        memory_factory=dict,
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
    app.state.rule_store = rule_store
    app.state.kbs = kbs
    app.state.store = store
    app.state.applications = applications
    app.state.demo_tamper = None
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
        case_store=store,
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

    def _app_stats(source_app: str) -> dict[str, Any]:
        today = datetime.now(UTC).date()
        requests_today = 0
        last_seen: str | None = None
        for rec in store.cases.values():
            if rec.get("source_app") != source_app:
                continue
            created_raw = rec.get("created_at")
            created = _parse_created_at(created_raw)
            if created is not None and created.date() == today:
                requests_today += 1
            if created_raw and (last_seen is None or str(created_raw) > last_seen):
                last_seen = str(created_raw)
        return {"requests_today": requests_today, "last_seen": last_seen}

    def _application_view(record: dict[str, Any]) -> dict[str, Any]:
        stats = _app_stats(record["source_app"])
        return {
            "app_id": record["app_id"],
            "name": record["name"],
            "environment": record["environment"],
            "process": record["process"],
            "source_app": record["source_app"],
            "status": record["status"],
            "key_display": _mask_key(record["key_prefix"], record["key_last4"]),
            "created_at": record["created_at"],
            "revoked_at": record.get("revoked_at"),
            **stats,
        }

    def _write_demo_agent_key_file(source_app: str, api_key: str, process: str) -> None:
        """Plaintext keys are only ever visible at creation time (the API
        never returns key_hash), so this is a seeded app's one chance to hand
        its key to the matching scripts/simulated_apps/<source_app>.py demo
        script. Written per-app rather than one shared file since each demo
        script only needs (and should only see) its own key.
        """
        keys_dir = root / "data" / "demo_agent_keys"
        keys_dir.mkdir(parents=True, exist_ok=True)
        env_path = keys_dir / f"{source_app}.env"
        env_path.write_text(
            f"AIGUARD_API_KEY={api_key}\n"
            f"AIGUARD_API_URL=http://127.0.0.1:8000\n"
            f"AIGUARD_PROCESS={process}\n",
            encoding="utf-8",
        )

    def _seed_default_applications() -> None:
        """First boot only (store empty) — registers the agents the existing
        traffic simulators already impersonate (scripts/simulated_apps/*.py),
        so Applications shows real request stats the moment that traffic runs
        instead of starting from an empty state every demo rehearsal.
        """
        if len(app.state.applications) > 0:
            return
        defaults = [
            ("Procurement Agent", "production", "procurement_review", "legacy_cases"),
            ("Finance Agent", "production", "finance", "finance_app"),
            ("Risk Rating Agent", "production", "risk_rating", "risk_rating_app"),
            ("RAG Support Bot", "staging", "rag_bot", "rag_bot_app"),
        ]
        for name, environment, process, source_app in defaults:
            app_id = f"app_{uuid.uuid4().hex[:12]}"
            api_key = _generate_api_key(environment)
            app.state.applications[app_id] = {
                "app_id": app_id,
                "name": name,
                "environment": environment,
                "process": process,
                "source_app": source_app,
                "status": "connected",
                "key_hash": _hash_key(api_key),
                "key_prefix": api_key[:12],
                "key_last4": api_key[-4:],
                "created_at": _utc_now(),
                "revoked_at": None,
            }
            _write_demo_agent_key_file(source_app, api_key, process)

    _seed_default_applications()

    def _lookup_application_by_key(api_key: str) -> dict[str, Any] | None:
        key_hash = _hash_key(api_key)
        for record in app.state.applications.values():
            if record.get("key_hash") == key_hash:
                return record
        return None

    async def require_api_key(request: Request) -> dict[str, Any]:
        """Agent-facing auth: Authorization: Bearer sk_... issued via
        POST /applications. Returns the matching application record so
        callers can bind source_app/process to the authenticated identity
        instead of trusting whatever the request body claims.
        """
        if auth.auth_disabled():
            return {"type": "api_key", "source_app": None, "process": None}
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing API key")
        key = header[7:].strip()
        record = _lookup_application_by_key(key)
        if record is None:
            raise HTTPException(status_code=401, detail="invalid API key")
        if record.get("status") == "revoked":
            raise HTTPException(status_code=401, detail="API key revoked")
        return {"type": "api_key", **record}

    async def require_dashboard_token(request: Request) -> dict[str, Any]:
        """Dashboard-facing auth: Authorization: Bearer <jwt> issued via
        POST /auth/login against the shared DASHBOARD_PASSWORD.
        """
        if auth.auth_disabled():
            return {"type": "dashboard"}
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing dashboard session token")
        payload = auth.decode_access_token(header[7:].strip())
        return {"type": "dashboard", **payload}

    async def require_dashboard_or_api_key(request: Request) -> dict[str, Any]:
        """POST/GET /cases is used both by the dashboard (dashboard session)
        and by agents submitting cases directly (API key) — accept either.
        """
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer sk_"):
            return await require_api_key(request)
        return await require_dashboard_token(request)

    # Bound once so route signatures don't call Depends() in a default (ruff B008).
    dashboard_or_api_key = Depends(require_dashboard_or_api_key)
    api_key_required = Depends(require_api_key)

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
            case_store=store,
        )

    def _reset_demo_state() -> None:
        app.state.audit.clear()
        store.cases.clear()
        store.call_to_case.clear()
        app.state.demo_tamper = None
        app.state.rule_store.clear()
        _rebuild_runtime()

    @app.post("/cases")
    def submit_case(
        body: SubmitCaseBody,
        caller: dict[str, Any] = dashboard_or_api_key,
    ) -> dict[str, Any]:
        case_id = body.case_id or str(uuid.uuid4())
        source_app = body.source_app
        if caller.get("type") == "api_key" and caller.get("source_app"):
            source_app = caller["source_app"]
        state = initial_state(
            case_id=case_id,
            process=body.process,
            request=body.request.model_dump(),
            mock_agent_plan=body.mock_agent_plan,
            force_chunk_ids=body.force_chunk_ids,
        )
        result = run_case(app.state.graph, state, thread_id=case_id)
        return _snapshot_case(case_id, result, source_app=source_app)

    @app.get("/cases", dependencies=[Depends(require_dashboard_token)])
    def list_cases() -> dict[str, Any]:
        rows = sorted(
            store.cases.values(),
            key=lambda r: str(r.get("created_at") or ""),
            reverse=True,
        )
        return {"cases": list(rows)}

    @app.get("/cases/{case_id}", dependencies=[Depends(require_dashboard_token)])
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

    @app.get("/cases/{case_id}/audit", dependencies=[Depends(require_dashboard_token)])
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

    @app.get("/traffic/recent", dependencies=[Depends(require_dashboard_token)])
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

    @app.get("/audit/verify", dependencies=[Depends(require_dashboard_token)])
    def verify_audit() -> dict[str, Any]:
        entries = app.state.audit.query()
        valid, first_invalid_entry_id = app.state.audit.verify_chain_detailed()
        return {
            "valid": valid,
            "entry_count": len(entries),
            "first_invalid_entry_id": first_invalid_entry_id,
        }

    @app.post("/investigate", dependencies=[Depends(require_dashboard_token)])
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
    def guard_evaluate(
        body: GuardEvaluateBody,
        background_tasks: BackgroundTasks,
        caller: dict[str, Any] = api_key_required,
    ) -> dict[str, Any]:
        """Evaluate one proposed tool call against process policy and audit it —
        the endpoint the aiguard SDK (or any external agent) calls per tool
        call, without going through /cases or the LangGraph agent at all.

        Requires an application API key (POST /applications). The process
        and source_app are taken from the authenticated application, not the
        request body, so a caller can only evaluate against the process it
        was actually registered for.

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
        process = caller.get("process") or body.process
        source_app = caller.get("source_app") or body.source_app
        try:
            config = load_process(process)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        call_id = body.call_id or str(uuid.uuid4())
        case_id = f"guard-{call_id}"
        stage_timings: dict[str, float] = {}

        request = ToolCallRequest(
            call_id=call_id,
            process=process,
            step_id=body.step_id,
            tool_name=body.tool_name,
            tool_args=body.tool_args,
            agent_rationale=body.agent_rationale,
            context_refs=[],
            timestamp=_utc_now(),
            case_id=case_id,
        )

        # Deterministic hard blocks skip KB retrieve + LLM judges entirely.
        if is_hard_block(request, config):
            stage_timings["retrieve_ms"] = 0.0
            decision = evaluate_tool_call(
                request,
                config,
                audit=app.state.audit,
                stage_timings_ms=stage_timings,
                schedule_learning=background_tasks.add_task,
                case_store=store,
            )
        else:
            process_kb = _kb_for(process)
            query = " ".join(
                [
                    body.tool_name,
                    " ".join(str(v) for v in body.tool_args.values()),
                    body.agent_rationale,
                ]
            ).strip()
            forced_ids = set(body.force_chunk_ids)
            t_retrieve = time.perf_counter()
            raw_retrieved = process_kb.retrieve(query, k=6) if query else []
            # Same exclusion agent/graph.py's own retrieve step applies: the demo
            # injected-quote fixture shares line-item wording ("Laptop docks")
            # with ordinary clean requests, so unscoped top-k retrieval can pull
            # it into a completely unrelated call and falsely flag it as an
            # injection attempt. Keep it out unless explicitly forced.
            retrieved = [
                c
                for c in raw_retrieved
                if c.id != "chunk:injected:quote" or c.id in forced_ids
            ]
            for forced_id in forced_ids:
                if forced_id not in {c.id for c in retrieved}:
                    forced_chunk = process_kb.get_by_id(forced_id)
                    if forced_chunk is not None:
                        retrieved.append(forced_chunk)
            stage_timings["retrieve_ms"] = round(
                (time.perf_counter() - t_retrieve) * 1000, 2
            )
            context_texts = [c.text for c in retrieved] + list(body.context_texts)
            retrieved_ids = [c.id for c in retrieved]
            request = request.model_copy(update={"context_refs": retrieved_ids})
            decision = evaluate_tool_call(
                request,
                config,
                retrieved_texts=context_texts,
                context_chunks=context_texts,
                retrieved_chunk_ids=retrieved_ids,
                audit=app.state.audit,
                stage_timings_ms=stage_timings,
                schedule_learning=background_tasks.add_task,
                case_store=store,
            )
        # Surface SDK / external evaluations on /cases and /traffic/recent so
        # simulated apps show up alongside graph-driven /cases traffic.
        # "escalate" here has no LangGraph thread to resume (unlike /cases) —
        # origin="guard_evaluate" tells the two approval endpoints below
        # (and the dashboard's own POST /approvals/{call_id}) to resolve it
        # via _resolve_guard_evaluate_case instead of resume_case.
        status = "pending_approval" if decision.decision == "escalate" else "completed"
        case_row = {
            "case_id": case_id,
            "process": process,
            "status": status,
            "call_id": call_id,
            "gateway_decision": decision.model_dump(),
            "tool_result": None,
            "request": {
                "tool_name": body.tool_name,
                **body.tool_args,
            },
            "source_app": source_app,
            "created_at": _utc_now(),
            "origin": "guard_evaluate",
        }

        def _persist_case() -> None:
            store.cases[case_id] = case_row
            store.call_to_case[call_id] = case_id

        # Escalate must be visible before the response returns (SDK polling /
        # wait_for_decision). Allow/block can persist after the response.
        if decision.decision == "escalate":
            _persist_case()
        else:
            background_tasks.add_task(_persist_case)
        return decision.model_dump()

    def _guard_case_snapshot(case: dict[str, Any]) -> dict[str, Any]:
        return {
            "call_id": case.get("call_id"),
            "case_id": case.get("case_id"),
            "process": case.get("process"),
            "status": case.get("status"),
            "decision": case.get("gateway_decision"),
            "request": case.get("request"),
            "source_app": case.get("source_app"),
            "created_at": case.get("created_at"),
        }

    def _lookup_guard_case_by_call_id(call_id: str) -> dict[str, Any]:
        case_id = store.call_to_case.get(call_id)
        case = store.cases.get(case_id) if case_id else None
        if case is None or case.get("origin") != "guard_evaluate":
            raise HTTPException(status_code=404, detail="call_id not found")
        return case

    def _authorize_guard_case_view(caller: dict[str, Any], case: dict[str, Any]) -> None:
        """Read access: the tower's dashboard can see any guard_evaluate
        escalation (visibility into everything is the whole point of a
        control tower), and an application's own API key can see its own."""
        if caller.get("type") != "api_key":
            return
        if caller.get("source_app") and caller.get("source_app") != case.get("source_app"):
            raise HTTPException(status_code=403, detail="not authorized for this call_id")

    def _authorize_guard_case_resolve(caller: dict[str, Any], case: dict[str, Any]) -> None:
        """Write access: only the originating application's own API key may
        approve/reject a guard_evaluate escalation. Deliberately narrower
        than view access — this decision belongs inside the application
        that owns the call (its own approval UI), not the tower's dashboard,
        which stays read-only for these cases (contrast with LangGraph-based
        /cases escalations, where the dashboard IS the approver)."""
        if caller.get("type") != "api_key":
            raise HTTPException(
                status_code=403,
                detail=(
                    "guard_evaluate escalations can only be resolved by the "
                    "originating application's own API key, not the dashboard"
                ),
            )
        if caller.get("source_app") and caller.get("source_app") != case.get("source_app"):
            raise HTTPException(status_code=403, detail="not authorized for this call_id")

    def _resolve_guard_evaluate_case(
        case: dict[str, Any], *, action: str, actor: str
    ) -> dict[str, Any]:
        """Resolve a pending guard_evaluate escalation. Never executes the
        caller's tool — that stays the caller's own code, run after it sees
        the resolved decision (via polling or its own approval UI). Mirrors
        agent/graph.py's interrupt_for_approval audit shape (event_type=
        "approval") so this shows up the same way in the audit trail whether
        the call went through /cases or /guard/evaluate."""
        gw = dict(case.get("gateway_decision") or {})
        new_decision = "allow" if action == "approve" else "block"
        original_reason = gw.get("reason", "")
        gw["decision"] = new_decision
        gw["reason"] = f"Escalated call {action}d by {actor}. Original: {original_reason}"
        case["gateway_decision"] = gw
        case["status"] = "completed" if action == "approve" else "rejected"
        case["resolved_at"] = _utc_now()
        case["resolved_by"] = actor

        app.state.audit.append(
            AppendInput(
                process=case["process"],
                step_id="guard_approval",
                event_type="approval",
                payload={
                    "case_id": case["case_id"],
                    "call_id": case["call_id"],
                    "action": action,
                    "actor": actor,
                },
                scores=GatewayDecision.model_validate(gw),
            )
        )
        # DB-backed CaseStore returns copies — must re-assign after mutate.
        store.cases[case["case_id"]] = case
        if case.get("call_id"):
            store.call_to_case[case["call_id"]] = case["case_id"]
        return _guard_case_snapshot(case)

    def _resolve_policy_change_case(
        case: dict[str, Any], *, action: str, actor: str, rule_text: str | None = None
    ) -> dict[str, Any]:
        """Approve/reject a proposed learned rule. Dashboard JWT only.

        Never calls resume_case — there is no LangGraph checkpointer thread.
        """
        req = dict(case.get("request") or {})
        rule_id = req.get("rule_id")
        if not rule_id:
            raise HTTPException(status_code=400, detail="policy_change case missing rule_id")
        if case.get("status") != "pending_approval":
            raise HTTPException(
                status_code=409,
                detail=f"case is not pending approval (status={case.get('status')})",
            )

        incident_id = req.get("source_incident_id")
        if action == "reject":
            try:
                app.state.rule_store.reject(rule_id, actor=actor)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            case["status"] = "rejected"
            case["resolved_at"] = _utc_now()
            case["resolved_by"] = actor
            app.state.audit.append(
                AppendInput(
                    process=case["process"],
                    step_id="policy_change",
                    event_type="approval",
                    payload={
                        "case_id": case["case_id"],
                        "call_id": case["call_id"],
                        "action": "reject",
                        "actor": actor,
                        "rule_id": rule_id,
                        "incident_id": incident_id,
                    },
                )
            )
            store.cases[case["case_id"]] = case
            if case.get("call_id"):
                store.call_to_case[case["call_id"]] = case["case_id"]
            return case

        try:
            activated = apply_rule(
                case["process"],
                rule_id=rule_id,
                approved_by=actor,
                rule_text=rule_text if rule_text is not None else req.get("rule_text"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        case["status"] = "completed"
        case["resolved_at"] = _utc_now()
        case["resolved_by"] = actor
        req["rule_text"] = getattr(activated, "rule_text", req.get("rule_text"))
        case["request"] = req
        gw = dict(case.get("gateway_decision") or {})
        gw["decision"] = "allow"
        gw["reason"] = f"Learned rule {rule_id} applied by {actor}"
        case["gateway_decision"] = gw

        app.state.audit.append(
            AppendInput(
                process=case["process"],
                step_id="policy_change",
                event_type="approval",
                payload={
                    "case_id": case["case_id"],
                    "call_id": case["call_id"],
                    "action": "approve",
                    "actor": actor,
                    "rule_id": rule_id,
                    "incident_id": incident_id,
                    "approved_by": actor,
                },
            )
        )
        app.state.audit.append(
            AppendInput(
                process=case["process"],
                step_id="policy_change",
                event_type="rule_applied",
                payload={
                    "case_id": case["case_id"],
                    "call_id": case["call_id"],
                    "rule_id": rule_id,
                    "process_id": case["process"],
                    "rule_text": getattr(activated, "rule_text", None),
                    "source_incident_id": incident_id,
                    "approved_by": actor,
                },
            )
        )
        store.cases[case["case_id"]] = case
        if case.get("call_id"):
            store.call_to_case[case["call_id"]] = case["case_id"]
        return case

    @app.get("/guard/approvals/{call_id}")
    def get_guard_approval(
        call_id: str, caller: dict[str, Any] = dashboard_or_api_key
    ) -> dict[str, Any]:
        """Status check for a /guard/evaluate call that escalated — what the
        aiguard SDK's wait_for_decision() polls. No LangGraph thread is
        involved; this just reads the case record."""
        case = _lookup_guard_case_by_call_id(call_id)
        _authorize_guard_case_view(caller, case)
        return _guard_case_snapshot(case)

    @app.post("/guard/approvals/{call_id}")
    def resolve_guard_approval(
        call_id: str,
        body: ApprovalBody,
        caller: dict[str, Any] = dashboard_or_api_key,
    ) -> dict[str, Any]:
        """Resolve a /guard/evaluate escalation. Only the originating
        application's own API key can call this — approval for these calls
        happens inside that application's own UI, not the tower's dashboard
        (see _authorize_guard_case_resolve)."""
        case = _lookup_guard_case_by_call_id(call_id)
        _authorize_guard_case_resolve(caller, case)
        if case.get("status") != "pending_approval":
            raise HTTPException(
                status_code=409,
                detail=f"call_id {call_id} is not pending approval (status={case.get('status')})",
            )
        return _resolve_guard_evaluate_case(case, action=body.action, actor=body.actor)

    @app.get("/approvals", dependencies=[Depends(require_dashboard_token)])
    def list_approvals() -> dict[str, Any]:
        """Pending-approval queue as its own resource — the integration point
        for a customer's own system to poll (or later, webhook off of) rather
        than fetching every case and filtering client-side. Approve/reject
        stays POST /approvals/{call_id}, unchanged; this is its GET half.

        Deliberately excludes guard_evaluate-origin escalations: the
        dashboard can't resolve those (see _authorize_guard_case_resolve —
        only the owning application's own API key can), and a queue item
        with Approve/Reject buttons that just 403 when clicked is worse
        than not listing it here at all. Those stay fully visible via Logs
        (every retrieval/policy_check/tool_call/approval event, now with
        case_id on each one) — visibility without implying actionability
        this page doesn't actually have.
        """
        rows = sorted(
            (
                r
                for r in store.cases.values()
                if r.get("status") == "pending_approval" and r.get("origin") != "guard_evaluate"
            ),
            key=lambda r: str(r.get("created_at") or ""),
            reverse=True,
        )
        out = []
        for r in rows:
            gw = r.get("gateway_decision") or {}
            tool_result = r.get("tool_result") or {}
            request_payload = r.get("request") or {}
            out.append(
                {
                    "call_id": r.get("call_id"),
                    "case_id": r.get("case_id"),
                    "process": r.get("process"),
                    "origin": r.get("origin"),
                    "tool_name": tool_result.get("tool_name") or request_payload.get("tool_name"),
                    "reason": gw.get("reason"),
                    "risk_score": gw.get("risk_score"),
                    "confidence_score": gw.get("confidence_score"),
                    "evidence_score": gw.get("evidence_score"),
                    "policy_refs": gw.get("policy_refs") or [],
                    "source_app": r.get("source_app"),
                    "requested_at": r.get("created_at"),
                    # Truncated/hashed only — never raw attack text.
                    "rule_id": request_payload.get("rule_id"),
                    "rule_text": request_payload.get("rule_text"),
                    "matched_span_preview": request_payload.get("matched_span_preview"),
                    "matched_span_hash": request_payload.get("matched_span_hash"),
                    "source_incident_id": request_payload.get("source_incident_id"),
                }
            )
        return {"approvals": out, "count": len(out)}

    @app.post("/approvals/{call_id}", dependencies=[Depends(require_dashboard_token)])
    def approve(call_id: str, body: ApprovalBody) -> dict[str, Any]:
        case_id = store.call_to_case.get(call_id)
        if not case_id:
            for cid, rec in store.cases.items():
                if rec.get("call_id") == call_id:
                    case_id = cid
                    break
        if not case_id:
            raise HTTPException(status_code=404, detail="call_id not found")

        case = store.cases.get(case_id) or {}
        if case.get("origin") == "guard_evaluate":
            # No LangGraph thread here — but more importantly, the dashboard
            # is not the approver for these: resolving a guard_evaluate
            # escalation is scoped to the owning application's own API key
            # (its own UI), not this dashboard-only endpoint. The dashboard
            # can still see it (GET /approvals, origin="guard_evaluate").
            raise HTTPException(
                status_code=403,
                detail=(
                    "This call was submitted via /guard/evaluate — it can only be "
                    "resolved by its owning application's own API key, at "
                    f"POST /guard/approvals/{call_id}, not from the dashboard."
                ),
            )

        if case.get("origin") == "policy_change":
            return _resolve_policy_change_case(
                case, action=body.action, actor=body.actor, rule_text=body.rule_text
            )

        result = resume_case(
            app.state.graph,
            thread_id=case_id,
            action=body.action,
            actor=body.actor,
        )
        return _snapshot_case(case_id, result)

    @app.post("/demo/reset", dependencies=[Depends(require_dashboard_token)])
    def demo_reset() -> dict[str, Any]:
        """Wipe audit rows + in-memory cases; rebuild checkpointer for a clean demo."""
        _reset_demo_state()
        return {"ok": True, "cases": 0, "audit_entries": 0}

    @app.post("/demo/seed", dependencies=[Depends(require_dashboard_token)])
    def demo_seed() -> dict[str, Any]:
        """Reset runtime and load rehearsal fixtures via /cases (escalate left pending)."""
        _reset_demo_state()
        bodies = load_rehearsal_bodies()
        # Attribute each fixture to the registered application for its
        # process, so Applications' "requests today" reflects demo traffic
        # instead of staying at 0 (fixtures carry no source_app of their own).
        process_to_source_app: dict[str, str] = {}
        for record in app.state.applications.values():
            process = record.get("process")
            source_app = record.get("source_app")
            if process and source_app:
                process_to_source_app.setdefault(process, source_app)
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
            seeded.append(
                _snapshot_case(
                    case_id,
                    result,
                    source_app=process_to_source_app.get(body.process),
                )
            )
        pending = sum(1 for c in seeded if c.get("status") == "pending_approval")
        return {
            "ok": True,
            "fixture_ids": list(REHEARSAL_IDS),
            "cases": seeded,
            "pending_approval_count": pending,
        }

    @app.post("/knowledge/documents", dependencies=[Depends(require_dashboard_token)])
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

    @app.get("/configs", dependencies=[Depends(require_dashboard_token)])
    def list_configs() -> dict[str, Any]:
        """Real process configs, parsed from configs/*.yaml — the same file
        the gateway enforces against, not a client-side copy of it. Doc lists
        include both the seed KB paths and anything uploaded live via
        /knowledge/documents, read straight off disk.
        """
        title_overrides = {"onboarding_kyc": "Onboarding KYC", "rag_bot": "RAG Bot"}
        out: list[dict[str, Any]] = []
        for name in known_processes(root / "configs"):
            try:
                cfg = load_process(name, configs_dir=root / "configs")
            except (FileNotFoundError, ValueError):
                continue
            updir = uploads_dir(root, name)
            uploaded = _list_uploaded_docs(updir) if updir.is_dir() else []
            out.append(
                {
                    "id": name,
                    "title": cfg.title or title_overrides.get(name, name.replace("_", " ").title()),
                    "config_path": f"configs/{name}.yaml",
                    "allowed_tools": [t.model_dump() for t in cfg.allowed_tools],
                    "disallowed_tools": cfg.disallowed_tools,
                    "approval_threshold": cfg.approval_threshold.model_dump(),
                    "seed_docs": [Path(p).name for p in cfg.knowledge_base_paths],
                    "uploaded_docs": uploaded,
                }
            )
        return {"processes": out}

    @app.post("/configs/reload", dependencies=[Depends(require_dashboard_token)])
    def reload_configs() -> dict[str, Any]:
        """Clear in-process process + learned-rule caches on this worker.

        Multi-worker deployments need this (or epoch TTL wait) on each worker
        after a rule is applied elsewhere for immediate consistency.
        """
        clear_process_cache()
        app.state.rule_store.clear_cache()
        return {"ok": True, "cleared": ["process_cache", "learned_rules_cache"]}

    def _write_process_yaml(process_id: str, cfg: dict[str, Any]) -> None:
        path = root / "configs" / f"{process_id}.yaml"
        path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    @app.post("/configs", dependencies=[Depends(require_dashboard_token)])
    def create_process(body: CreateProcessBody) -> dict[str, Any]:
        configs_dir = root / "configs"
        configs_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(body.title)
        process_id = slug
        i = 1
        while (configs_dir / f"{process_id}.yaml").is_file():
            i += 1
            process_id = f"{slug}_{i}"
        cfg = {
            "process": process_id,
            "title": body.title,
            "allowed_tools": [t.model_dump() for t in body.allowed_tools],
            "disallowed_tools": body.disallowed_tools,
            "required_evidence_docs": [],
            "approval_threshold": {"risk_score_gte": body.approval_threshold},
            "knowledge_base_paths": [],
        }
        _write_process_yaml(process_id, cfg)
        return {
            "id": process_id,
            "title": body.title,
            "config_path": f"configs/{process_id}.yaml",
            "allowed_tools": cfg["allowed_tools"],
            "disallowed_tools": cfg["disallowed_tools"],
            "approval_threshold": cfg["approval_threshold"],
            "seed_docs": [],
            "uploaded_docs": [],
        }

    @app.put("/configs/{process_id}", dependencies=[Depends(require_dashboard_token)])
    def update_process(process_id: str, body: UpdateProcessBody) -> dict[str, Any]:
        configs_dir = root / "configs"
        path = configs_dir / f"{process_id}.yaml"
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"unknown process {process_id!r}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if body.allowed_tools is not None:
            raw["allowed_tools"] = [t.model_dump() for t in body.allowed_tools]
        if body.disallowed_tools is not None:
            raw["disallowed_tools"] = body.disallowed_tools
        if body.approval_threshold is not None:
            raw["approval_threshold"] = {"risk_score_gte": body.approval_threshold}
        try:
            ProcessConfig.model_validate(raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _write_process_yaml(process_id, raw)
        return {"id": process_id, "config_path": f"configs/{process_id}.yaml"}

    @app.post("/knowledge/policies", dependencies=[Depends(require_dashboard_token)])
    def create_policy(body: CreatePolicyBody) -> dict[str, Any]:
        """A policy authored directly in the dashboard (vs. an uploaded file)
        — stored as its own markdown file under uploads/<process>/custom/ so
        it round-trips through the exact same RAG indexing as any other
        policy doc, but is tagged 'custom' in /configs so the UI knows it can
        be edited in place instead of only deleted."""
        try:
            load_process(body.process, configs_dir=root / "configs")
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        custom_dir = uploads_dir(root, body.process) / CUSTOM_POLICY_DIRNAME
        custom_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(body.title)
        dest = custom_dir / f"{slug}.md"
        i = 1
        while dest.exists():
            i += 1
            dest = custom_dir / f"{slug}_{i}.md"
        dest.write_text(f"## {body.title}\n\n{body.content}\n", encoding="utf-8")

        kb = _kb_for(body.process)
        before = kb.size
        kb.index_seed([dest], project_root=root)
        return {
            "ok": True,
            "name": dest.name,
            "path": f"{CUSTOM_POLICY_DIRNAME}/{dest.name}",
            "chunks_added": kb.size - before,
            "kb_size": kb.size,
            "process": body.process,
        }

    def _resolve_upload_path(process: str, rel_path: str) -> Path:
        base = uploads_dir(root, process).resolve()
        dest = (base / rel_path).resolve()
        if base not in dest.parents:
            raise HTTPException(status_code=400, detail="invalid document path")
        return dest

    @app.put(
        "/knowledge/policies/{process}/{filename}",
        dependencies=[Depends(require_dashboard_token)],
    )
    def update_policy(process: str, filename: str, body: UpdatePolicyBody) -> dict[str, Any]:
        dest = _resolve_upload_path(process, f"{CUSTOM_POLICY_DIRNAME}/{filename}")
        if not dest.is_file():
            raise HTTPException(status_code=404, detail="custom policy not found")
        kb = _kb_for(process)
        kb.remove_source(source_for_path(dest))
        dest.write_text(f"## {body.title}\n\n{body.content}\n", encoding="utf-8")
        before = kb.size
        kb.index_seed([dest], project_root=root)
        return {"ok": True, "name": dest.name, "chunks_added": kb.size - before, "kb_size": kb.size}

    @app.get(
        "/knowledge/policies/{process}/{filename}",
        dependencies=[Depends(require_dashboard_token)],
    )
    def get_policy(process: str, filename: str) -> dict[str, Any]:
        dest = _resolve_upload_path(process, f"{CUSTOM_POLICY_DIRNAME}/{filename}")
        if not dest.is_file():
            raise HTTPException(status_code=404, detail="custom policy not found")
        return {"name": dest.name, "content": dest.read_text(encoding="utf-8")}

    @app.delete(
        "/knowledge/documents/{process}/{doc_path:path}",
        dependencies=[Depends(require_dashboard_token)],
    )
    def delete_document(process: str, doc_path: str) -> dict[str, Any]:
        """Deletes any upload — plain file or custom policy — and drops its
        chunks from the live KB. This is the only way to change an uploaded
        (non-custom) document: delete it, then upload the replacement."""
        dest = _resolve_upload_path(process, doc_path)
        if not dest.is_file():
            raise HTTPException(status_code=404, detail="document not found")
        kb = _kb_for(process)
        removed = kb.remove_source(source_for_path(dest))
        dest.unlink()
        return {"ok": True, "removed_chunks": removed, "kb_size": kb.size}

    @app.post("/applications", dependencies=[Depends(require_dashboard_token)])
    def create_application(body: CreateApplicationBody) -> dict[str, Any]:
        if body.process not in known_processes(root / "configs"):
            raise HTTPException(status_code=400, detail=f"unknown process {body.process!r}")
        app_id = f"app_{uuid.uuid4().hex[:12]}"
        source_app = body.source_app or _slugify(body.name)
        api_key = _generate_api_key(body.environment)
        record = {
            "app_id": app_id,
            "name": body.name,
            "environment": body.environment,
            "process": body.process,
            "source_app": source_app,
            "status": "connected",
            "key_hash": _hash_key(api_key),
            "key_prefix": api_key[:12],
            "key_last4": api_key[-4:],
            "created_at": _utc_now(),
            "revoked_at": None,
        }
        app.state.applications[app_id] = record
        view = _application_view(record)
        # The only response that ever carries the plaintext key — only the
        # hash is stored, so this is the caller's one chance to see it.
        view["api_key"] = api_key
        return view

    @app.get("/applications", dependencies=[Depends(require_dashboard_token)])
    def list_applications() -> dict[str, Any]:
        records = sorted(
            app.state.applications.values(),
            key=lambda r: str(r.get("created_at") or ""),
            reverse=True,
        )
        return {"applications": [_application_view(r) for r in records]}

    @app.post("/applications/{app_id}/revoke", dependencies=[Depends(require_dashboard_token)])
    def revoke_application(app_id: str) -> dict[str, Any]:
        record = app.state.applications.get(app_id)
        if record is None:
            raise HTTPException(status_code=404, detail="application not found")
        record = dict(record)
        record["status"] = "revoked"
        record["revoked_at"] = _utc_now()
        app.state.applications[app_id] = record
        return _application_view(record)

    @app.get("/audit/entries", dependencies=[Depends(require_dashboard_token)])
    def list_audit_entries(
        limit: int = 100,
        offset: int = 0,
        process: str | None = None,
        event_type: str | None = None,
        decision: str | None = None,
    ) -> dict[str, Any]:
        """Global, paginated audit log — every retrieval/decision/tool call/score
        across all processes and cases, most recent first. Powers Logs and
        Audit & Integrity without the per-case N+1 fetch /cases/{id}/audit needs.
        """
        if limit < 1:
            raise HTTPException(status_code=422, detail="limit must be >= 1")
        entries = app.state.audit.query(process=process, event_type=event_type, order="desc")
        if decision:
            entries = [e for e in entries if e.scores is not None and e.scores.decision == decision]
        total = len(entries)
        page = entries[offset : offset + limit]
        return {
            "entries": [e.model_dump() for e in page],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.post("/audit/demo-tamper", dependencies=[Depends(require_dashboard_token)])
    def demo_tamper(body: DemoTamperBody) -> dict[str, Any]:
        """Debug/demo only — genuinely corrupts one stored hash (not a UI
        simulation) so /audit/verify authentically fails, then restores it.
        ARCHITECTURE.md §12's tamper-check demo, done for real.
        """
        state = app.state.demo_tamper
        if body.enable:
            if state is not None:
                return {"tampered": True, "entry_id": state["entry_id"]}
            try:
                result = app.state.audit.demo_corrupt_entry()
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            app.state.demo_tamper = result
            return {"tampered": True, "entry_id": result["entry_id"]}
        if state is None:
            return {"tampered": False, "entry_id": None}
        app.state.audit.demo_restore_entry(state["entry_id"], state["original_hash"])
        app.state.demo_tamper = None
        return {"tampered": False, "entry_id": None}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/login")
    def login(body: LoginBody) -> dict[str, str]:
        expected = os.environ.get("DASHBOARD_PASSWORD")
        if not expected:
            raise HTTPException(
                status_code=500,
                detail="DASHBOARD_PASSWORD is not configured on the server.",
            )
        if not secrets.compare_digest(body.password, expected):
            raise HTTPException(status_code=401, detail="invalid password")
        token = auth.create_access_token("dashboard")
        return {"access_token": token, "token_type": "bearer"}

    return app


app = create_app()
