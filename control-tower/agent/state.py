"""LangGraph agent state."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from contracts.schemas import GatewayDecision, InjectionFlag


class MockAgentPlan(TypedDict):
    tool_name: str
    tool_args: dict[str, Any]
    agent_rationale: str
    context_refs: list[str]


class CaseRequest(TypedDict, total=False):
    vendor_id: str
    amount: float
    item: str


CaseStatus = Literal[
    "running",
    "pending_approval",
    "completed",
    "blocked",
    "rejected",
]


class AgentState(TypedDict):
    case_id: str
    process: str
    request: CaseRequest
    chunks: list[dict[str, str]]
    injection_flags: list[dict[str, Any]]
    call_id: str
    tool_name: str
    tool_args: dict[str, Any]
    agent_rationale: str
    context_refs: list[str]
    gateway_decision: dict[str, Any] | None
    status: CaseStatus
    approval: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    mock_agent_plan: NotRequired[MockAgentPlan | None]
    force_chunk_ids: NotRequired[list[str]]
    error: NotRequired[str | None]
