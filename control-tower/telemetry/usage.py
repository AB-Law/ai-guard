"""Model token usage + estimated cost — only when provider metadata exists."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenUsage:
    """Observed token counts from a provider response (never fabricated)."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str | None = None


@dataclass(frozen=True)
class CostEstimate:
    """USD estimate derived from usage × configured pricing.

    Always treated as an estimate — provider invoices may differ.
    """

    estimated_cost_usd: float
    is_estimate: bool = True
    pricing_source: str = "AEGIS_MODEL_PRICING_JSON"


def _as_nonneg_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def extract_token_usage(response: Any) -> TokenUsage | None:
    """Pull token counts from a LangChain / OpenAI-shaped response.

    Returns None when usage metadata is absent — callers must treat that as
    unavailable, never as zero.
    """
    if response is None:
        return None

    # include_raw=True shape: {"raw": AIMessage, "parsed": ...}
    if isinstance(response, dict) and "raw" in response:
        return extract_token_usage(response.get("raw"))

    usage_meta = getattr(response, "usage_metadata", None)
    if isinstance(usage_meta, dict):
        prompt = _as_nonneg_int(
            usage_meta.get("input_tokens", usage_meta.get("prompt_tokens"))
        )
        completion = _as_nonneg_int(
            usage_meta.get("output_tokens", usage_meta.get("completion_tokens"))
        )
        total = _as_nonneg_int(usage_meta.get("total_tokens"))
        if prompt is not None and completion is not None:
            if total is None:
                total = prompt + completion
            model = _model_from_response(response)
            return TokenUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                model=model,
            )

    meta = getattr(response, "response_metadata", None)
    if isinstance(meta, dict):
        token_usage = meta.get("token_usage") or meta.get("usage") or {}
        if isinstance(token_usage, dict):
            prompt = _as_nonneg_int(
                token_usage.get("prompt_tokens")
                or token_usage.get("input_tokens")
            )
            completion = _as_nonneg_int(
                token_usage.get("completion_tokens")
                or token_usage.get("output_tokens")
            )
            total = _as_nonneg_int(token_usage.get("total_tokens"))
            if prompt is not None and completion is not None:
                if total is None:
                    total = prompt + completion
                model = meta.get("model_name") or meta.get("model") or _model_from_response(
                    response
                )
                return TokenUsage(
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=total,
                    model=str(model) if model else None,
                )

    return None


def _model_from_response(response: Any) -> str | None:
    meta = getattr(response, "response_metadata", None)
    if isinstance(meta, dict):
        name = meta.get("model_name") or meta.get("model")
        if name:
            return str(name)
    return None


def load_model_pricing() -> dict[str, dict[str, float]]:
    """Parse ``AEGIS_MODEL_PRICING_JSON``.

    Expected shape::

        {
          "gpt-4o": {"input_per_1m": 2.5, "output_per_1m": 10.0},
          "default": {"input_per_1m": 2.5, "output_per_1m": 10.0}
        }

    Rates are USD per 1 million tokens. Missing / invalid config → {}.
    """
    raw = (os.environ.get("AEGIS_MODEL_PRICING_JSON") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("AEGIS_MODEL_PRICING_JSON is not valid JSON; cost unavailable")
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for model, rates in parsed.items():
        if not isinstance(rates, dict):
            continue
        try:
            inp = float(rates["input_per_1m"])
            outp = float(rates["output_per_1m"])
        except (KeyError, TypeError, ValueError):
            continue
        if inp < 0 or outp < 0:
            continue
        out[str(model)] = {"input_per_1m": inp, "output_per_1m": outp}
    return out


def estimate_cost_usd(
    usage: TokenUsage,
    *,
    pricing: dict[str, dict[str, float]] | None = None,
) -> CostEstimate | None:
    """Estimate USD cost from usage × pricing. None if pricing missing."""
    table = pricing if pricing is not None else load_model_pricing()
    if not table:
        return None
    model_key = (usage.model or "").strip() or "default"
    rates = table.get(model_key) or table.get("default")
    if rates is None:
        return None
    cost = (
        usage.prompt_tokens / 1_000_000.0 * rates["input_per_1m"]
        + usage.completion_tokens / 1_000_000.0 * rates["output_per_1m"]
    )
    return CostEstimate(estimated_cost_usd=round(cost, 8))
