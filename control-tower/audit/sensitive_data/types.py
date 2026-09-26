"""Shared types for sensitive-data detection."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DetectorType = Literal[
    "email",
    "phone",
    "gov_id_us_ssn",
    "api_key",
    "bearer_token",
    "iban",
    "bank_account",
]

FindingSeverity = Literal["high", "medium", "low"]
SensitiveAction = Literal["redact", "block", "escalate"]

ALL_DETECTOR_TYPES: tuple[DetectorType, ...] = (
    "email",
    "phone",
    "gov_id_us_ssn",
    "api_key",
    "bearer_token",
    "iban",
    "bank_account",
)


class Finding(BaseModel):
    """One sensitive-data match. Never carries the raw matched value."""

    type: DetectorType
    path: str
    start: int = 0
    end: int = 0
    severity: FindingSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    preview: str
    value_hash: str
