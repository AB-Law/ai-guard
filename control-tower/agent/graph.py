"""LangGraph procurement agent with gateway HITL."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from agent.state import AgentState
from agent.tools import ToolSideEffects, execute_bound_tool
from audit.log_store import AppendInput, AuditLogStore
from configs.loader import ProcessConfig, load_process
from contracts.schemas import GatewayDecision, InjectionFlag, ToolCallRequest
from guardrails import evaluate_tool_call
from guardrails.injection_guard import scan
from knowledge.rag import KnowledgeBase, build_kb_for_process

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ToolArgs(BaseModel):
    model_config = {"extra": "forbid"}

    vendor_id: str | None = None
    applicant_id: str | None = None
    amount: float | None = None
    item: str | None = None
    call_id: str | None = None
    reason: str | None = None


class ProposedToolPlan(BaseModel):
    tool_name: str
    tool_args: ToolArgs = Field(default_factory=ToolArgs)
    agent_rationale: str
    context_refs: list[str] = Field(default_factory=list)

    def args_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.tool_args.model_dump().items() if v is not None}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _decision_to_dict(decision: GatewayDecision) -> dict[str, Any]:
    return decision.model_dump()


def build_graph(
    *,
    audit: AuditLogStore,
    kb: KnowledgeBase
    | Mapping[str, KnowledgeBase]
    | Callable[[str], KnowledgeBase]
    | None = None,
    config: ProcessConfig | None = None,
    checkpointer: MemorySaver | None = None,
    side_effects: ToolSideEffects | None = None,
    case_store: Any | None = None,
) -> CompiledStateGraph:
    """Compile the agent graph; process config and KB are resolved from state at runtime."""
    checkpointer = checkpointer or MemorySaver()
    effects = side_effects if side_effects is not None else ToolSideEffects()

    def _resolve_config(state: AgentState) -> ProcessConfig:
        if config is not None:
            return config
        return load_process(state["process"])

    def _resolve_kb(state: AgentState) -> KnowledgeBase:
        process = state["process"]
        if kb is None:
            return build_kb_for_process(process, _PROJECT_ROOT)
        if isinstance(kb, KnowledgeBase):
            return kb
        if callable(kb):
            return kb(process)
        if process in kb:
            return kb[process]
        return build_kb_for_process(process, _PROJECT_ROOT)

    def retrieve(state: AgentState) -> dict[str, Any]:
        process_kb = _resolve_kb(state)
        req = state["request"]
        query = (
            f"{req.get('item', '')} vendor {req.get('vendor_id', '')} "
            "auto approve policy amount identity verification"
        ).strip()
        chunks = process_kb.retrieve(query, k=6)
        forced_ids = set(state.get("force_chunk_ids") or [])
        # Keep planted injection out of clean retrieval unless explicitly forced
        # (malicious quote shares line-item text with clean demos).
        by_id = {
            c.id: c
            for c in chunks
            if c.id != "chunk:injected:quote" or c.id in forced_ids
        }

        vendor_id = req.get("vendor_id")
        if vendor_id:
            vendor_chunk = process_kb.get_by_id(f"chunk:vendor:{vendor_id}")
            if vendor_chunk:
                by_id[vendor_chunk.id] = vendor_chunk

        # Policy text is small, bounded, and always relevant to grounding a
        # tool-call rationale — it's this process's required_evidence_docs by
        # definition. Include every section deterministically rather than
        # leaving it to the semantic query above: without OPENAI_API_KEY,
        # retrieval falls back to knowledge/rag.py's DeterministicHashEmbedding
        # (no download, offline-stable, not semantic), which isn't reliable
        # enough to guarantee a governing clause outranks several vendor rows
        # just because the request happens to name a vendor. Concretely: an
        # "Escalation" section ranked below 4 vendor rows for a large-amount
        # case, so the agent's "needs human approval" claim scored unsupported
        # even though the policy document says exactly that — see the
        # evidence_score discussion for high_amount_escalate. Kept even with
        # live OpenAI embeddings: it's cheap, deterministic grounding that
        # only strengthens the semantic result, never competes with it.
        for c in process_kb.all_chunks():
            if c.id == "chunk:injected:quote" and c.id not in forced_ids:
                continue
            if c.id.startswith("chunk:vendor:"):
                continue
            by_id.setdefault(c.id, c)

        for forced in forced_ids:
            forced_chunk = process_kb.get_by_id(forced)
            if forced_chunk:
                by_id[forced_chunk.id] = forced_chunk

        chunk_dicts = [
            {"id": c.id, "text": c.text, "source": c.source} for c in by_id.values()
        ]
        audit.append(
            AppendInput(
                process=state["process"],
                step_id="retrieve",
                event_type="retrieval",
                payload={
                    "case_id": state["case_id"],
                    "query": query,
                    "chunk_ids": [c["id"] for c in chunk_dicts],
                },
            )
        )
        return {"chunks": chunk_dicts, "status": "running"}

    def scan_injection(state: AgentState) -> dict[str, Any]:
        texts = [c.get("text") for c in (state.get("chunks") or [])]
        result = scan(texts, process=state.get("process"))
        return {"injection_flags": [flag.model_dump() for flag in result.flags]}

    def reason(state: AgentState) -> dict[str, Any]:
        # Placeholder node for symmetry with BUILD; propose_tool does the work.
        return {}

    def propose_tool(state: AgentState) -> dict[str, Any]:
        process_config = _resolve_config(state)
        mock = state.get("mock_agent_plan")
        if mock:
            plan = ProposedToolPlan(
                tool_name=mock["tool_name"],
                tool_args=ToolArgs.model_validate(mock.get("tool_args") or {}),
                agent_rationale=mock["agent_rationale"],
                context_refs=list(mock.get("context_refs") or []),
            )
        else:
            plan = _live_propose(state, process_config)

        call_id = state.get("call_id") or str(uuid.uuid4())
        return {
            "call_id": call_id,
            "tool_name": plan.tool_name,
            "tool_args": plan.args_dict(),
            "agent_rationale": plan.agent_rationale,
            "context_refs": plan.context_refs,
        }

    def gateway_check(state: AgentState) -> dict[str, Any]:
        process_config = _resolve_config(state)
        call_id = state["call_id"]
        request = ToolCallRequest(
            call_id=call_id,
            process=state["process"],
            step_id="gateway_check",
            tool_name=state["tool_name"],
            tool_args=state.get("tool_args") or {},
            agent_rationale=state.get("agent_rationale") or "",
            context_refs=list(state.get("context_refs") or []),
            timestamp=_utc_now(),
            case_id=state["case_id"],
        )
        chunk_dicts = list(state.get("chunks") or [])
        texts = [c["text"] for c in chunk_dicts]
        precomputed = [
            InjectionFlag.model_validate(f) for f in (state.get("injection_flags") or [])
        ]
        decision = evaluate_tool_call(
            request,
            process_config,
            retrieved_texts=texts,
            context_chunks=texts,
            injection_flags=precomputed,
            retrieved_chunk_ids=[c["id"] for c in chunk_dicts],
            audit=audit,
            case_store=case_store,
        )
        return {"gateway_decision": _decision_to_dict(decision)}

    def route_after_gateway(
        state: AgentState,
    ) -> Literal["execute", "interrupt_for_approval", "finalize"]:
        decision = (state.get("gateway_decision") or {}).get("decision")
        if decision == "allow":
            return "execute"
        if decision == "escalate":
            return "interrupt_for_approval"
        return "finalize"

    def execute(state: AgentState) -> dict[str, Any]:
        process_config = _resolve_config(state)
        result = execute_bound_tool(
            process_config,
            state["tool_name"],
            state.get("tool_args") or {},
            side_effects=effects,
        )
        return {"tool_result": result, "status": "completed"}

    def interrupt_for_approval(state: AgentState) -> dict[str, Any]:
        payload = {
            "case_id": state["case_id"],
            "call_id": state["call_id"],
            "decision": state.get("gateway_decision"),
            "tool_name": state.get("tool_name"),
            "tool_args": state.get("tool_args"),
        }
        approval = interrupt(payload)
        if not isinstance(approval, dict):
            approval = {"action": "reject", "actor": "unknown", "raw": approval}

        action = str(approval.get("action", "reject")).lower()
        actor = str(approval.get("actor", "unknown"))
        audit.append(
            AppendInput(
                process=state["process"],
                step_id="interrupt_for_approval",
                event_type="approval",
                payload={
                    "case_id": state["case_id"],
                    "call_id": state["call_id"],
                    "action": action,
                    "actor": actor,
                },
                scores=(
                    GatewayDecision.model_validate(state["gateway_decision"])
                    if state.get("gateway_decision")
                    else None
                ),
            )
        )
        if action == "approve":
            return {"approval": approval, "status": "running"}
        return {"approval": approval, "status": "rejected", "tool_result": None}

    def route_after_approval(
        state: AgentState,
    ) -> Literal["execute", "finalize"]:
        approval = state.get("approval") or {}
        if str(approval.get("action", "")).lower() == "approve":
            return "execute"
        return "finalize"

    def finalize(state: AgentState) -> dict[str, Any]:
        decision = (state.get("gateway_decision") or {}).get("decision")
        status = state.get("status")
        if status in ("completed", "rejected"):
            return {"status": status}
        if decision == "block":
            return {"status": "blocked", "tool_result": None}
        if decision == "escalate" and status != "completed":
            return {"status": "rejected" if state.get("approval") else "pending_approval"}
        if decision == "allow" and state.get("tool_result"):
            return {"status": "completed"}
        return {"status": status or "completed"}

    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("scan_injection", scan_injection)
    graph.add_node("reason", reason)
    graph.add_node("propose_tool", propose_tool)
    graph.add_node("gateway_check", gateway_check)
    graph.add_node("execute", execute)
    graph.add_node("interrupt_for_approval", interrupt_for_approval)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "scan_injection")
    graph.add_edge("scan_injection", "reason")
    graph.add_edge("reason", "propose_tool")
    graph.add_edge("propose_tool", "gateway_check")
    graph.add_conditional_edges(
        "gateway_check",
        route_after_gateway,
        {
            "execute": "execute",
            "interrupt_for_approval": "interrupt_for_approval",
            "finalize": "finalize",
        },
    )
    graph.add_edge("execute", "finalize")
    graph.add_conditional_edges(
        "interrupt_for_approval",
        route_after_approval,
        {"execute": "execute", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)


def _live_propose(state: AgentState, config: ProcessConfig) -> ProposedToolPlan:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required when mock_agent_plan is not provided"
        )

    from langchain_openai import ChatOpenAI

    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")
    # Some models (e.g. gpt-5 / o-series) reject temperature=0; use default.
    llm = ChatOpenAI(model=model_name, api_key=api_key)
    structured = llm.with_structured_output(ProposedToolPlan, method="function_calling")
    allowed = [t.name for t in config.allowed_tools]
    user = build_user_prompt(
        process=state["process"],
        request=dict(state["request"]),
        chunks=list(state.get("chunks") or []),
        allowed_tools=allowed,
    )
    result = structured.invoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
    )
    if isinstance(result, ProposedToolPlan):
        return result
    return ProposedToolPlan.model_validate(result)


def initial_state(
    *,
    case_id: str,
    process: str,
    request: dict[str, Any],
    mock_agent_plan: dict[str, Any] | None = None,
    force_chunk_ids: list[str] | None = None,
) -> AgentState:
    state: AgentState = {
        "case_id": case_id,
        "process": process,
        "request": request,  # type: ignore[typeddict-item]
        "chunks": [],
        "injection_flags": [],
        "call_id": "",
        "tool_name": "",
        "tool_args": {},
        "agent_rationale": "",
        "context_refs": [],
        "gateway_decision": None,
        "status": "running",
        "approval": None,
        "tool_result": None,
    }
    if mock_agent_plan is not None:
        state["mock_agent_plan"] = mock_agent_plan  # type: ignore[typeddict-item]
    if force_chunk_ids:
        state["force_chunk_ids"] = force_chunk_ids
    return state


def run_case(
    graph: CompiledStateGraph,
    state: AgentState,
    *,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Invoke graph; returns final state (may be interrupted)."""
    tid = thread_id or state["case_id"]
    config = {"configurable": {"thread_id": tid}}
    return graph.invoke(state, config=config)


def resume_case(
    graph: CompiledStateGraph,
    *,
    thread_id: str,
    action: str,
    actor: str,
) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(
        Command(resume={"action": action, "actor": actor}),
        config=config,
    )


def is_interrupted(result: dict[str, Any]) -> bool:
    """True if invoke returned while waiting on HITL (LangGraph sets __interrupt__)."""
    # After interrupt, status may still be running until resume path sets it;
    # callers should also check graph.get_state for next tasks.
    return bool(result.get("__interrupt__"))
