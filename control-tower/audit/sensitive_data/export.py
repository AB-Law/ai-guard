"""Sanitize payloads before any telemetry or external export."""

from __future__ import annotations

from typing import Any

from audit.sensitive_data.policy import SensitiveDataPolicy, default_policy
from audit.sensitive_data.redact import redact_value


def sanitize_for_export(
    value: Any,
    *,
    policy: SensitiveDataPolicy | None = None,
) -> Any:
    """Redact sensitive data before telemetry export or external handoff.

    Same pipeline as audit persistence — never export raw secrets or full
    sensitive values. Call this from any exporter; audit stores already redact
    before hash/persist.
    """
    return redact_value(value, policy=policy or default_policy())
