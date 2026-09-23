"""Light ops-console CSS for the Streamlit dashboard."""

from __future__ import annotations

import streamlit as st

from dashboard.view_models import relative_age, short_timestamp, traffic_event_blurb

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
  font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
}

.stApp {
  background:
    radial-gradient(ellipse 80% 50% at 0% -10%, #d8ebe8 0%, transparent 55%),
    radial-gradient(ellipse 60% 40% at 100% 0%, #e8eef5 0%, transparent 50%),
    #f4f6f8;
  color: #1e293b;
}

[data-testid="stSidebar"] {
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
}

[data-testid="stSidebar"] h2 {
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #64748b;
  margin-top: 0.25rem;
}

h1.aegis-title {
  font-size: 1.85rem;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.02em;
  margin-bottom: 0.15rem;
}

.aegis-subtitle {
  color: #64748b;
  font-size: 0.95rem;
  margin-bottom: 0.75rem;
}

.aegis-header-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.aegis-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 1rem 1.1rem;
  margin-bottom: 0.85rem;
}

.aegis-card-title {
  font-weight: 600;
  color: #0f172a;
  font-size: 1rem;
  margin-bottom: 0.35rem;
}

.aegis-muted {
  color: #64748b;
  font-size: 0.88rem;
}

.aegis-section-label {
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: #64748b;
  font-weight: 600;
  margin-bottom: 0.35rem;
}

.badge {
  display: inline-block;
  padding: 0.2rem 0.55rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 600;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  letter-spacing: 0.02em;
  line-height: 1.3;
}

.badge-allow {
  background: #d1fae5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}

.badge-block {
  background: #fee2e2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.badge-escalate {
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fde68a;
}

.badge-pending {
  background: #ffedd5;
  color: #9a3412;
  border: 1px solid #fed7aa;
}

.badge-ok {
  background: #ccfbf1;
  color: #0f766e;
  border: 1px solid #99f6e4;
}

.badge-err {
  background: #fee2e2;
  color: #991b1b;
  border: 1px solid #fecaca;
}

.badge-neutral {
  background: #e2e8f0;
  color: #334155;
  border: 1px solid #cbd5e1;
}

.decision-banner {
  border-radius: 10px;
  padding: 0.75rem 1rem;
  margin-bottom: 0.85rem;
  font-weight: 700;
  font-size: 1.05rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  letter-spacing: 0.04em;
}

.decision-banner.allow {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
}

.decision-banner.block {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}

.decision-banner.escalate {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
}

.decision-banner.unknown {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #475569;
}

.chip {
  display: inline-block;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  color: #334155;
  border-radius: 6px;
  padding: 0.15rem 0.45rem;
  margin: 0.15rem 0.25rem 0.15rem 0;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.78rem;
}

.legend-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  align-items: center;
  margin: 0.35rem 0 0.75rem 0;
  font-size: 0.82rem;
  color: #64748b;
}

.req-dl {
  display: grid;
  grid-template-columns: 7rem 1fr;
  gap: 0.25rem 0.75rem;
  font-size: 0.9rem;
}

.req-dl dt {
  color: #64748b;
  font-weight: 500;
}

.req-dl dd {
  margin: 0;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  color: #0f172a;
}

.guide-steps {
  margin: 0.25rem 0 0 0;
  padding-left: 1.2rem;
  color: #334155;
  line-height: 1.55;
}

.guide-steps li {
  margin-bottom: 0.35rem;
}

.empty-steps {
  background: #ffffff;
  border: 1px dashed #94a3b8;
  border-radius: 10px;
  padding: 1.1rem 1.25rem;
  color: #334155;
}

.empty-steps ol {
  margin: 0.5rem 0 0 1.1rem;
  padding: 0;
  line-height: 1.6;
}

/* Soften default metric cards into the slate palette */
[data-testid="stMetric"] {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.65rem 0.85rem;
  margin-bottom: 0.35rem;
}

/* Laptop widths: never ellipsize score values (avoids "0...") */
[data-testid="stMetricLabel"],
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"] {
  overflow: visible !important;
  text-overflow: clip !important;
  white-space: nowrap;
}

[data-testid="stMetricValue"] {
  font-size: 1.35rem !important;
  font-variant-numeric: tabular-nums;
}

[data-testid="stExpander"] {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}

/* Live traffic pipeline */
.traffic-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.5rem 0.75rem;
  margin-bottom: 0.4rem;
  font-size: 0.82rem;
}

.traffic-row.is-new {
  animation: traffic-flash 1.6s ease-out 1;
}

@keyframes traffic-flash {
  0% { background: #ecfdf5; border-color: #6ee7b7; }
  100% { background: #ffffff; border-color: #e2e8f0; }
}

.traffic-id {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  color: #0f172a;
  width: 10.5rem;
  min-width: 10.5rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.traffic-time {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  color: #64748b;
  width: 7.5rem;
  min-width: 7.5rem;
  font-size: 0.78rem;
  white-space: nowrap;
  flex-shrink: 0;
}

.traffic-clock {
  color: #475569;
}

.traffic-age {
  color: #94a3b8;
  font-size: 0.72rem;
}

.traffic-process {
  color: #64748b;
  width: 7.5rem;
  min-width: 7.5rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.traffic-source {
  width: 8.5rem;
  min-width: 8.5rem;
}

.source-chip {
  display: inline-block;
  padding: 0.15rem 0.45rem;
  border-radius: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  letter-spacing: 0.01em;
  line-height: 1.25;
  max-width: 9.25rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.source-chip-finance {
  background: #dbeafe;
  color: #1e40af;
  border: 1px solid #93c5fd;
}

.source-chip-risk {
  background: #fce7f3;
  color: #9d174d;
  border: 1px solid #f9a8d4;
}

.source-chip-rag {
  background: #d1fae5;
  color: #065f46;
  border: 1px solid #6ee7b7;
}

.source-chip-demo {
  background: #e0e7ff;
  color: #3730a3;
  border: 1px solid #a5b4fc;
}

.source-chip-internal {
  background: #e2e8f0;
  color: #475569;
  border: 1px solid #cbd5e1;
}

.connected-apps-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin: 0.25rem 0 0.85rem 0;
}

.connected-apps-label {
  font-size: 0.82rem;
  color: #64748b;
  margin-right: 0.25rem;
}

.traffic-blurb {
  flex: 1;
  min-width: 0;
  color: #475569;
  font-size: 0.78rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.traffic-decision {
  width: 5.5rem;
  min-width: 5.5rem;
  text-align: right;
  flex-shrink: 0;
}

.traffic-meta {
  font-size: 0.78rem;
  color: #94a3b8;
  margin: 0.35rem 0 0.55rem 0;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
}


.stage-checklist {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin: 0.35rem 0 0.75rem 0;
}

.stage-item {
  display: grid;
  grid-template-columns: 5.5rem 1fr;
  gap: 0.5rem;
  align-items: start;
  font-size: 0.85rem;
  padding: 0.35rem 0.5rem;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.stage-item.ran {
  background: #ecfdf5;
  border-color: #a7f3d0;
}

.stage-item.flagged {
  background: #fffbeb;
  border-color: #fde68a;
}

.stage-item.idle {
  opacity: 0.65;
}

.stage-status {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.stage-item.ran .stage-status { color: #065f46; }
.stage-item.flagged .stage-status { color: #92400e; }
.stage-item.idle .stage-status { color: #94a3b8; }

.stage-copy strong {
  display: block;
  color: #0f172a;
  font-size: 0.85rem;
}

.stage-copy span {
  color: #64748b;
  font-size: 0.78rem;
}

</style>
"""


def inject_css() -> None:
    """Inject light ops-console styles once per run."""
    st.markdown(_CSS, unsafe_allow_html=True)


def badge_html(label: str, kind: str) -> str:
    """Safe HTML badge for a decision/status label."""
    safe = (
        str(label)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f'<span class="badge badge-{kind}">{safe}</span>'


PIPELINE_STAGES: tuple[tuple[str, str, str], ...] = (
    ("retrieval", "Retrieve", "Pulled policy/context from the knowledge base"),
    ("injection_flag", "Scan", "Checked retrieved text for prompt-injection"),
    ("policy_check", "Gateway", "Scored the tool call against process policy"),
    ("tool_call", "Action", "Agent attempted or completed a tool call"),
    ("approval", "Approval", "Human approve/reject was recorded"),
)

# Distinct chip color per known source_app; anything else / missing ? internal.
_SOURCE_APP_CHIP_CLASS: dict[str, str] = {
    "finance_app": "source-chip-finance",
    "risk_rating_app": "source-chip-risk",
    "rag_bot_app": "source-chip-rag",
    "Aegis Demo Traffic": "source-chip-demo",
}


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def source_app_chip_html(source_app: str | None) -> str:
    """Colored source_app chip; neutral 'internal' when unlabeled."""
    if source_app:
        label = str(source_app)
        cls = _SOURCE_APP_CHIP_CLASS.get(label, "source-chip-internal")
    else:
        label = "internal"
        cls = "source-chip-internal"
    return (
        f'<span class="source-chip {cls}" title="{_esc(label)}">'
        f"{_esc(label)}</span>"
    )


def connected_apps_html(source_apps: list[str]) -> str:
    """KPI-style strip of distinct connected source_app chips."""
    if not source_apps:
        return (
            '<div class="connected-apps-row">'
            '<span class="connected-apps-label">'
            "No labeled applications in recent traffic yet.</span>"
            "</div>"
        )
    chips = " ".join(source_app_chip_html(name) for name in source_apps)
    n = len(source_apps)
    noun = "application" if n == 1 else "applications"
    return (
        f'<div class="connected-apps-row">'
        f'<span class="connected-apps-label">'
        f"{n} {noun} currently sending traffic:</span>"
        f"{chips}"
        f"</div>"
    )


def pipeline_stages_checklist_html(stages: set[str] | list[str] | None) -> str:
    """Labeled checklist for the event detail dialog (not the list rows)."""
    hit = set(stages or [])
    rows: list[str] = []
    for event_type, label, tip in PIPELINE_STAGES:
        if event_type in hit and event_type == "injection_flag":
            state, status = "flagged", "FLAGGED"
        elif event_type in hit:
            state, status = "ran", "RAN"
        else:
            state, status = "idle", "SKIPPED"
        rows.append(
            f'<div class="stage-item {state}">'
            f'<span class="stage-status">{status}</span>'
            f'<div class="stage-copy"><strong>{_esc(label)}</strong>'
            f"<span>{_esc(tip)}</span></div></div>"
        )
    return f'<div class="stage-checklist">{"".join(rows)}</div>'


def traffic_row_html(case: dict, *, is_new: bool = False) -> str:
    """One live-traffic row: time, id, source, process, summary, decision."""
    decision = (case.get("decision") or "").lower()
    kind = decision if decision in {"allow", "block", "escalate"} else "neutral"
    label = (case.get("decision") or case.get("status") or "--").upper()
    source_chip = source_app_chip_html(case.get("source_app"))
    clock = short_timestamp(case.get("created_at")) or "--:--:--"
    age = relative_age(case.get("created_at"))
    time_bits = _esc(clock)
    if age:
        time_bits = f'{time_bits} <span class="traffic-age">{_esc(age)}</span>'
    full_ts = _esc(str(case.get("created_at") or ""))
    blurb = traffic_event_blurb(case)

    row_cls = "traffic-row is-new" if is_new else "traffic-row"
    return (
        f'<div class="{row_cls}">'
        f'<span class="traffic-time" title="{full_ts}">{time_bits}</span>'
        f'<span class="traffic-id" title="{_esc(case.get("case_id") or "")}">'
        f'{_esc(case.get("case_id") or "--")}</span>'
        f'<span class="traffic-source">{source_chip}</span>'
        f'<span class="traffic-process">{_esc(case.get("process") or "--")}</span>'
        f'<span class="traffic-blurb" title="{_esc(blurb)}">{_esc(blurb)}</span>'
        f'<span class="traffic-decision">{badge_html(label, kind)}</span>'
        f"</div>"
    )


def decision_banner_html(decision: str | None) -> str:
    kind = (decision or "unknown").lower()
    if kind not in {"allow", "block", "escalate"}:
        kind = "unknown"
    text = (decision or "no decision").upper()
    return f'<div class="decision-banner {kind}">DECISION | {text}</div>'
