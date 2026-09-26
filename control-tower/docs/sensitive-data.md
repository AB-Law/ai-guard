# Sensitive-data protection

Aegis detects common PII and secrets, then redacts them **before** audit
persistence and hashing. Detection is separate from redaction: detectors emit
typed findings with location, severity, and confidence; redaction (and optional
policy actions) consume those findings.

## Defaults (decision-safe)

| Setting | Default | Effect |
|---------|---------|--------|
| `sensitive_data.enabled` | `true` | Detectors run at persist / export |
| `default_action` | `redact` | Minimize at rest only |
| Per-detector `action` | `redact` | Same |
| `block` / `escalate` | Off unless YAML sets them | **Shipped process YAMLs omit overrides** |

Expanding what is redacted in stored audit payloads is intentional.
**Gateway allow / block / escalate outcomes do not change** unless a process
explicitly sets a detector `action` to `block` or `escalate`.

## Supported detector types

| Type | What it matches | Notes |
|------|-----------------|-------|
| `email` | Well-formed `local@domain.tld` | High confidence when domain has a dot |
| `phone` | NANP with separators or E.164 (`+…`) | Bare short digit runs are ignored |
| `gov_id_us_ssn` | `XXX-XX-XXXX` or labeled SSN | US-oriented; not a global ID suite |
| `api_key` | `sk-…`, `AKIA…`, labeled `api_key`/`token` | High confidence for prefixed forms |
| `bearer_token` | `Bearer <token>` | High confidence |
| `iban` | Simplified IBAN shape | Banking continuity with prior redactor |
| `bank_account` | Labeled account numbers; banking keys | Key values hashed when long enough |

Matches are **heuristic candidates**, not certain identification. Each finding
carries a `confidence` in `[0, 1]`. Values below the configured
`min_confidence` are not redacted and do not trigger policy actions.

## Configuration

Optional section on any process YAML (`configs/<process>.yaml`):

```yaml
sensitive_data:
  enabled: true
  default_action: redact   # redact | block | escalate
  min_confidence: 0.55
  detectors:
    api_key:
      enabled: true
      action: block          # opt-in: upgrades gateway decision
      min_confidence: 0.8
    email:
      action: redact
```

When `sensitive_data` is omitted, built-in redact-only defaults apply.

## Pipeline

1. **Detect** — `detect_in_text` / `detect_in_value` → `Finding` list
   (`type`, `path`, `severity`, `confidence`, redacted `preview`, `value_hash`).
2. **Policy** — `resolve_policy(ProcessConfig)` filters by enablement + confidence;
   returns `redact` (default) or opt-in `block` / `escalate`.
3. **Redact** — replacements applied before `compute_entry_hash` in
   SQLite/Postgres audit stores (deterministic for chain verify).
4. **Export** — call `sanitize_for_export` before any telemetry or external
   handoff (same pipeline; stores already redact at append).

Opt-in decision upgrades run in `evaluate_tool_call` **after** the normal
gateway decision and only **upgrade** (allow → escalate → block), never soften
a harder outcome.

## Limitations

- Regex-based; no ML NER. Expect false positives/negatives.
- Government IDs beyond US SSN-shaped patterns are out of scope.
- Unlabeled long digit strings are not treated as account numbers (by design).
- Confidence thresholds are process-tunable; tune per workload.
- Raw secrets must never be logged; findings store previews + hashes only.

## Code entry points

- `audit.redact.redact_payload` — audit persist facade
- `audit.sensitive_data.detect_in_value` — detection only
- `audit.sensitive_data.sanitize_for_export` — telemetry / export
- `guardrails.evaluate.apply_sensitive_data_policy` — opt-in decision upgrade
