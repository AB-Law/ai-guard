"""Tool call gateway — policy checks on proposed tool calls."""

from __future__ import annotations

from configs.loader import AllowedTool, ProcessConfig
from contracts.schemas import GatewayDecision, ToolCallRequest
from guardrails.risk_scorer import PolicyHit


def _allowed_tool_map(config: ProcessConfig) -> dict[str, AllowedTool]:
    return {t.name: t for t in config.allowed_tools}


def _amount_from_request(request: ToolCallRequest) -> float | None:
    raw = request.tool_args.get("amount")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def classify_policy_hit(request: ToolCallRequest, config: ProcessConfig) -> PolicyHit:
    """Return policy_hit for risk scorer: disallowed | unknown | over_limit | none."""
    if request.tool_name in config.disallowed_tools:
        return "disallowed"
    allowed = _allowed_tool_map(config)
    if request.tool_name not in allowed:
        return "unknown"
    tool = allowed[request.tool_name]
    amount = _amount_from_request(request)
    if (
        tool.max_auto_amount is not None
        and amount is not None
        and amount > tool.max_auto_amount
    ):
        return "over_limit"
    return "none"


def decide(
    request: ToolCallRequest,
    config: ProcessConfig,
    *,
    risk_score: int,
    evidence_score: float,
    confidence_score: float,
) -> GatewayDecision:
    """
    Evaluate a tool call against process config and precomputed scores.

    Rule order:
      1. Tool in disallowed_tools -> block
      2. Tool not in allowed_tools -> block
      3. amount > max_auto_amount (when applicable) -> escalate
      4. risk_score >= approval_threshold.risk_score_gte -> escalate
      5. Else -> allow
    """
    allowed = _allowed_tool_map(config)
    threshold = config.approval_threshold.risk_score_gte

    if request.tool_name in config.disallowed_tools:
        return GatewayDecision(
            call_id=request.call_id,
            decision="block",
            reason=f"Tool {request.tool_name!r} is disallowed for this process.",
            policy_refs=["disallowed_tools", request.tool_name],
            risk_score=risk_score,
            confidence_score=confidence_score,
            evidence_score=evidence_score,
        )

    if request.tool_name not in allowed:
        return GatewayDecision(
            call_id=request.call_id,
            decision="block",
            reason=f"Tool {request.tool_name!r} is not on the allow list.",
            policy_refs=["allowed_tools"],
            risk_score=risk_score,
            confidence_score=confidence_score,
            evidence_score=evidence_score,
        )

    tool = allowed[request.tool_name]
    amount = _amount_from_request(request)
    if (
        tool.max_auto_amount is not None
        and amount is not None
        and amount > tool.max_auto_amount
    ):
        ref = f"max_auto_amount:{int(tool.max_auto_amount)}"
        return GatewayDecision(
            call_id=request.call_id,
            decision="escalate",
            reason=(
                f"Amount {amount} exceeds auto-approve limit "
                f"{tool.max_auto_amount} for {request.tool_name!r}."
            ),
            policy_refs=[ref, request.tool_name],
            risk_score=risk_score,
            confidence_score=confidence_score,
            evidence_score=evidence_score,
        )

    if risk_score >= threshold:
        return GatewayDecision(
            call_id=request.call_id,
            decision="escalate",
            reason=f"Risk score {risk_score} is at or above threshold {threshold}.",
            policy_refs=[f"approval_threshold.risk_score_gte:{threshold}"],
            risk_score=risk_score,
            confidence_score=confidence_score,
            evidence_score=evidence_score,
        )

    return GatewayDecision(
        call_id=request.call_id,
        decision="allow",
        reason="Tool allowed and within policy thresholds.",
        policy_refs=["allowed_tools", request.tool_name],
        risk_score=risk_score,
        confidence_score=confidence_score,
        evidence_score=evidence_score,
    )
