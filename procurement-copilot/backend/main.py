"""Procurement Copilot — standalone demo app. Talks to Aegis only through
the aiguard package (see agent.py); never imports control-tower code.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

# agent.py reads AEGIS_*/OPENAI_* from the environment at call time, so the
# load_dotenv() above must run before these imports touch it indirectly.
from agent import resolve_pending, run_agent, run_agent_for_row  # noqa: E402
from pending import add as pending_add  # noqa: E402
from pending import list_pending, mark_resolved, pop as pending_pop  # noqa: E402
from store import STORE  # noqa: E402

app = FastAPI(title="Procurement Copilot")

_FRONTEND_DIR = _ROOT / "frontend"


class RowBody(BaseModel):
    vendor_id: str
    amount: float
    item: str
    department: str = ""
    notes: str = ""
    row_index: int | None = None


class ChatBody(BaseModel):
    message: str


class ResolveBody(BaseModel):
    action: str  # "approve" | "reject"
    actor: str = "demo-user"


def _register_if_pending(summary: dict[str, Any], *, row: dict[str, Any] | None) -> None:
    pending = summary.get("pending")
    if not pending:
        return
    pending_add(
        pending["call_id"],
        {
            **pending,
            "row": row,
        },
    )


@app.post("/rows/process")
def process_row(body: RowBody) -> dict[str, Any]:
    row = body.model_dump()
    summary = run_agent_for_row(row)
    _register_if_pending(summary, row=row)
    return summary


@app.post("/chat")
def chat(body: ChatBody) -> dict[str, Any]:
    summary = run_agent(body.message)
    _register_if_pending(summary, row=None)
    return summary


@app.get("/pending")
def get_pending() -> dict[str, Any]:
    return {"pending": list_pending()}


@app.post("/pending/{call_id}/resolve")
def resolve(call_id: str, body: ResolveBody) -> dict[str, Any]:
    record = pending_pop(call_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such pending approval")
    result = resolve_pending(
        call_id,
        action=body.action,
        actor=body.actor,
        tool_name=record["tool_name"],
        tool_args=record["tool_args"],
    )
    mark_resolved({**record, "action": body.action, "actor": body.actor, "result": result})
    return result


@app.get("/state")
def state() -> dict[str, Any]:
    return {**STORE.snapshot(), "pending": list_pending()}


@app.post("/upload")
async def upload(file: UploadFile) -> dict[str, Any]:
    raw = await file.read()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for i, r in enumerate(reader):
        rows.append(
            {
                "row_index": i,
                "vendor_id": r.get("vendor_id", "").strip(),
                "amount": float(r.get("amount") or 0),
                "item": r.get("item", "").strip(),
                "department": r.get("department", "").strip(),
                "notes": r.get("notes", "").strip(),
            }
        )
    return {"rows": rows, "count": len(rows)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="static")
