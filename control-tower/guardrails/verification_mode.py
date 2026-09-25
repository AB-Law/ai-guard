"""Heuristic vs LLM path selection and failure contracts for guardrails.

Single source of truth for when each path runs and what happens if the LLM
fails. Callers must not soft-degrade LLM → heuristic for evidence, and must
not crash the integrator on injection classifier failure.

Path selection
--------------
+------------------+---------------------------+----------------------------------+
| Subsystem        | When HEURISTIC            | When LLM                         |
+------------------+---------------------------+----------------------------------+
| Evidence         | OPENAI_API_KEY unset      | key set → `_llm_judge` only      |
| (verify_evidence)| → `verify()` only         | (never a "fast first pass")      |
+------------------+---------------------------+----------------------------------+
| Injection (scan) | no key; OR learned hit;   | key set AND no learned/high-regex|
|                  | OR high-severity regex    | short-circuit → classify + merge |
+------------------+---------------------------+----------------------------------+

LLM failure policy
------------------
+------------------+------------------+------------------------------------------+
| Subsystem        | Policy           | Behavior                                 |
+------------------+------------------+------------------------------------------+
| Evidence         | FAIL_CLOSED      | evidence_score=0, judge_unavailable=True |
|                  |                  | (evaluate escalates); never call verify()|
+------------------+------------------+------------------------------------------+
| Injection        | FAIL_OPEN        | return regex/learned flags already found;|
|                  |                  | do not raise to the caller               |
+------------------+------------------+------------------------------------------+
"""

from __future__ import annotations

import os
from enum import Enum

from contracts.schemas import VerificationResult


class PathMode(str, Enum):
    """Which implementation path is selected for a guardrail check."""

    HEURISTIC = "heuristic"
    LLM = "llm"


class LlmFailurePolicy(str, Enum):
    """What to do when the keyed LLM path raises or returns unusable output."""

    FAIL_CLOSED = "fail_closed"
    FAIL_OPEN = "fail_open"


EVIDENCE_FAILURE_POLICY = LlmFailurePolicy.FAIL_CLOSED
INJECTION_FAILURE_POLICY = LlmFailurePolicy.FAIL_OPEN


def llm_configured() -> bool:
    """True when OPENAI_API_KEY is set and non-blank."""
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def evidence_path() -> PathMode:
    """Path for verify_evidence: keyed → LLM only; unkeyed → heuristic only."""
    return PathMode.LLM if llm_configured() else PathMode.HEURISTIC


def injection_path(*, has_learned: bool, has_high_regex: bool) -> PathMode:
    """Path for scan after learned/regex stages.

    Learned hits and high-severity regex short-circuit without calling the LLM.
    Otherwise keyed environments use the LLM classifier; offline stays regex-only.
    """
    if has_learned or has_high_regex:
        return PathMode.HEURISTIC
    return PathMode.LLM if llm_configured() else PathMode.HEURISTIC


def evidence_unavailable_result() -> VerificationResult:
    """Fail-closed evidence result when the LLM judge errors or returns empty."""
    return VerificationResult(
        evidence_score=0.0,
        unsupported_claims=[],
        judge_unavailable=True,
    )
