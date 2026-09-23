"""Light ops-console CSS for the Streamlit dashboard."""

from __future__ import annotations

import streamlit as st

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
  width: 11rem;
  min-width: 11rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.traffic-process {
  color: #64748b;
  width: 8.5rem;
  min-width: 8.5rem;
}

.pipeline {
  display: flex;
  align-items: center;
  flex: 1;
}

.pipeline-node {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  color: #cbd5e1;
}

.pipeline-node .dot {
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: #e2e8f0;
  border: 1px solid #cbd5e1;
  flex-shrink: 0;
}

.pipeline-node.hit {
  color: #334155;
}

.pipeline-node.hit .dot {
  background: #14b8a6;
  border-color: #0d9488;
}

.pipeline-node.flag .dot {
  background: #f59e0b;
  border-color: #b45309;
}

.pipeline-label {
  font-size: 0.72rem;
  white-space: nowrap;
}

.pipeline-connector {
  width: 1.1rem;
  height: 1px;
  background: #e2e8f0;
  margin: 0 0.15rem;
}

.traffic-decision {
  width: 5.5rem;
  min-width: 5.5rem;
  text-align: right;
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


PIPELINE_STAGES: tuple[tuple[str, str], ...] = (
    ("retrieval", "Retrieve"),
    ("injection_flag", "Scan"),
    ("policy_check", "Gateway"),
    ("tool_call", "Action"),
    ("approval", "Approval"),
)


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def traffic_row_html(case: dict, *, is_new: bool = False) -> str:
    """One live-traffic pipeline row: case id + stage dots + decision badge."""
    stages = set(case.get("stages") or [])
    nodes: list[str] = []
    for i, (event_type, label) in enumerate(PIPELINE_STAGES):
        hit = event_type in stages
        # injection_flag only fires when something was actually flagged —
        # render it amber (alert), not the default teal "passed" color.
        cls = "pipeline-node"
        if hit:
            cls += " flag" if event_type == "injection_flag" else " hit"
        nodes.append(
            f'<div class="{cls}"><span class="dot"></span>'
            f'<span class="pipeline-label">{label}</span></div>'
        )
        if i < len(PIPELINE_STAGES) - 1:
            nodes.append('<div class="pipeline-connector"></div>')

    decision = (case.get("decision") or "").lower()
    kind = decision if decision in {"allow", "block", "escalate"} else "neutral"
    label = (case.get("decision") or case.get("status") or "—").upper()

    row_cls = "traffic-row is-new" if is_new else "traffic-row"
    return (
        f'<div class="{row_cls}">'
        f'<span class="traffic-id" title="{_esc(case.get("case_id") or "")}">'
        f'{_esc(case.get("case_id") or "—")}</span>'
        f'<span class="traffic-process">{_esc(case.get("process") or "—")}</span>'
        f'<div class="pipeline">{"".join(nodes)}</div>'
        f'<span class="traffic-decision">{badge_html(label, kind)}</span>'
        f"</div>"
    )


def decision_banner_html(decision: str | None) -> str:
    kind = (decision or "unknown").lower()
    if kind not in {"allow", "block", "escalate"}:
        kind = "unknown"
    text = (decision or "no decision").upper()
    return f'<div class="decision-banner {kind}">DECISION · {text}</div>'
