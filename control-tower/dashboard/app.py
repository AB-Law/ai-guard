"""Streamlit dashboard — live cases, scores, audit timeline, approval queue."""

from __future__ import annotations

import html
import os
import random
import subprocess
import sys
from pathlib import Path

import streamlit as st

from dashboard.api_client import AegisApiClient
from dashboard.styles import (
    badge_html,
    connected_apps_html,
    decision_banner_html,
    inject_css,
    pipeline_stages_checklist_html,
    traffic_row_html,
)
from dashboard.view_models import (
    audit_to_timeline,
    build_submit_case_request,
    case_kpis,
    cases_to_rows,
    decision_badge_kind,
    decision_to_score_panel,
    format_decision_label,
    format_score_value,
    offline_investigate_mock,
    pending_approvals,
    relative_age,
    request_to_display,
    status_badge_kind,
    submit_case_form_spec,
    submit_case_source_app,
    tool_result_to_display,
    unique_live_case_id,
)
from scripts.traffic_lib import random_submit_body

DEFAULT_API_URL = os.environ.get("AEGIS_API_URL", "http://127.0.0.1:8000")
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESS_OPTIONS = (
    "procurement_review",
    "onboarding_kyc",
    "finance",
    "risk_rating",
    "rag_bot",
)

# CLI names for scripts/simulate_workload.py --apps (label, cli_key, KB process).
# legacy_cases = procurement/KYC traffic_lib mix — one "app" for the multi-app story.
SIMULATED_APP_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("Finance", "finance", "finance"),
    ("Risk rating", "risk_rating", "risk_rating"),
    ("RAG bot", "rag_bot", "rag_bot"),
    ("Procurement / KYC (demo traffic)", "legacy_cases", "procurement_review"),
)

# Live traffic log windows: label -> since_minutes (None = all retained cases).
_TRAFFIC_WINDOWS: tuple[tuple[str, int | None], ...] = (
    ("Live · 15 min", 15),
    ("1 hour", 60),
    ("4 hours", 240),
    ("1 day", 1440),
    ("All retained", None),
)
_TRAFFIC_WINDOW_LABELS = [label for label, _ in _TRAFFIC_WINDOWS]
_TRAFFIC_WINDOW_MINUTES = {label: mins for label, mins in _TRAFFIC_WINDOWS}
_TRAFFIC_DECISION_OPTIONS = ("All decisions", "allow", "block", "escalate")
_TRAFFIC_ROW_LIMIT = 200

_DEMO_GUIDE_MD = """
1. Click **Load demo pack** in the sidebar (loads clean → injection → unauthorized → escalate).
2. In **Approval queue**, open the escalate case and click **Approve** (or Reject).
3. In **Cases**, select `clean_po` (allow), `unauthorized_tool` (block), and `injection_planted`.
4. Read **Scores**, policy refs, and the **Trace timeline** for evidence.
5. Expand **Ask investigation assistant** and ask *Why was this flagged?*
6. In **Simulated applications**, start 2–3 apps. Watch **Connected applications** and
   **Live traffic** fill with distinctly labeled sources. Upload a policy doc scoped to
   one app — only that app's subsequent traffic should change.
"""


def _sim_workload_running() -> bool:
    proc = st.session_state.get("sim_workload_proc")
    return bool(proc is not None and proc.poll() is None)


def _stop_sim_workload() -> None:
    proc = st.session_state.get("sim_workload_proc")
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    st.session_state["sim_workload_proc"] = None


def _start_sim_workload(
    *,
    api_url: str,
    apps: list[str],
    duration_sec: float,
) -> subprocess.Popen:
    script = _PROJECT_ROOT / "scripts" / "simulate_workload.py"
    cmd = [
        sys.executable,
        str(script),
        "--api",
        api_url,
        "--duration",
        str(duration_sec),
        "--apps",
        ",".join(apps),
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(_PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

_CASES_COLUMN_CONFIG = {
    "case_id": st.column_config.TextColumn("case_id", width="medium"),
    "process": st.column_config.TextColumn("process", width="medium"),
    "status": st.column_config.TextColumn("status", width="small"),
    "decision": st.column_config.TextColumn("decision", width="small"),
    "risk": st.column_config.NumberColumn("risk", width="small"),
    "created_at": st.column_config.TextColumn("created_at", width="small"),
}

_TIMELINE_COLUMN_CONFIG = {
    "time": st.column_config.TextColumn("time", width="small"),
    "type": st.column_config.TextColumn("type", width="medium"),
    "step": st.column_config.TextColumn("step", width="medium"),
    "summary": st.column_config.TextColumn("summary", width="large"),
    "scores": st.column_config.TextColumn("scores", width="medium"),
}


def _render_header(*, connected: bool, pending_count: int) -> None:
    st.markdown('<h1 class="aegis-title">Aegis — Control Tower</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="aegis-subtitle">Governance layer for enterprise agents — '
        "live traces, policy scores, and human approval.</p>",
        unsafe_allow_html=True,
    )
    health = badge_html("API connected", "ok") if connected else badge_html("API offline", "err")
    pending = badge_html(f"{pending_count} pending", "pending" if pending_count else "neutral")
    st.markdown(
        f'<div class="aegis-header-row">{health} {pending}</div>',
        unsafe_allow_html=True,
    )


def _render_guide(*, expanded: bool) -> None:
    with st.expander("How to demo (5 minutes)", expanded=expanded):
        st.markdown(_DEMO_GUIDE_MD)
        st.caption(
            "Tip: keep the API running without `--reload` during a live demo — "
            "reload clears in-memory cases."
        )


def _render_empty_state() -> None:
    st.markdown(
        """
<div class="empty-steps">
  <strong>No cases yet — start here</strong>
  <ol>
    <li>Confirm the sidebar shows a healthy API connection.</li>
    <li>Click <strong>Load demo pack</strong> (or submit a case below).</li>
    <li>Approve the pending escalate, then walk the cases for allow / block / escalate.</li>
  </ol>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_kv_block(pairs: list[tuple[str, str]]) -> None:
    if not pairs:
        st.write("—")
        return
    rows = "".join(
        f"<dt>{html.escape(k)}</dt><dd>{html.escape(v)}</dd>" for k, v in pairs
    )
    st.markdown(f'<dl class="req-dl">{rows}</dl>', unsafe_allow_html=True)


def _render_request_block(request: dict | None) -> None:
    _render_kv_block(request_to_display(request))


def _default_case_index(rows: list[dict]) -> int:
    for i, row in enumerate(rows):
        if row.get("status") == "pending_approval" or row.get("decision") == "escalate":
            return i
    return 0


def _explain_decision(case: dict) -> str:
    """Short plain-English explanation for the event detail dialog."""
    decision = ((case.get("gateway_decision") or {}).get("decision") or "").lower()
    reason = ((case.get("gateway_decision") or {}).get("reason") or "").strip()
    status = case.get("status") or ""
    tool = (case.get("tool_result") or {}).get("tool_name") or (
        (case.get("tool_result") or {}).get("status")
    )

    if decision == "allow":
        lead = "This call cleared the gateway and was allowed to proceed."
    elif decision == "block":
        lead = "This call was blocked by policy — the tool was not allowed to run."
    elif decision == "escalate":
        if status == "pending_approval":
            lead = "This call is paused for a human to Approve or Reject."
        else:
            lead = "This call was escalated for human review."
    else:
        lead = "No gateway decision is recorded yet."

    bits = [lead]
    if reason:
        bits.append(f"Why: {reason}")
    if tool:
        bits.append(f"Tool outcome: {tool}")
    return "\n\n".join(bits)


def _clear_selected_event() -> None:
    """Drop the Live-traffic event selection (Close button or native ×)."""
    st.session_state.pop("selected_event_id", None)


@st.dialog("Event detail", width="large", on_dismiss=_clear_selected_event)
def _traffic_event_dialog(client: AegisApiClient, case_id: str) -> None:
    """Datadog-style popup: what happened, why, request + tool + timeline."""
    try:
        case = client.get_case(case_id)
        audit_payload = client.get_audit(case_id)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load {case_id}: {exc}")
        return

    decision = case.get("gateway_decision") or {}
    d_kind = decision_badge_kind(decision.get("decision"))
    st.markdown(
        f"**{html.escape(case_id)}** · "
        f"{badge_html(format_decision_label(decision.get('decision')), d_kind)} "
        f"{badge_html(str(case.get('status') or '—'), status_badge_kind(case.get('status')))} "
        f"{badge_html(str(case.get('process') or '—'), 'neutral')}",
        unsafe_allow_html=True,
    )
    if case.get("source_app"):
        st.caption(f"Source app: {case.get('source_app')}")
    if case.get("created_at"):
        st.caption(
            f"Created {case.get('created_at')} "
            f"({relative_age(case.get('created_at')) or '—'})"
        )

    st.markdown("##### What happened")
    st.write(_explain_decision(case))

    stage_types = {
        str(e.get("event_type"))
        for e in (audit_payload.get("entries") or [])
        if e.get("event_type")
    }
    st.markdown("##### Guardrail stages")
    st.caption("Each step the case hit (or skipped) in this request.")
    st.markdown(pipeline_stages_checklist_html(stage_types), unsafe_allow_html=True)

    panel = decision_to_score_panel(decision)
    if panel is not None:
        m1, m2, m3 = st.columns(3)
        m1.metric("Risk", format_score_value(panel.get("risk_score")))
        m2.metric("Confidence", format_score_value(panel.get("confidence_score")))
        m3.metric("Evidence", format_score_value(panel.get("evidence_score")))
        refs = panel.get("policy_refs") or []
        if refs:
            chips = " ".join(
                f'<span class="chip">{html.escape(str(ref))}</span>' for ref in refs
            )
            st.markdown(
                f'<div class="aegis-muted">Policy refs</div>{chips}',
                unsafe_allow_html=True,
            )

    left, right = st.columns(2)
    with left:
        st.markdown("##### Request / message")
        _render_request_block(case.get("request"))
        st.markdown("##### Tool call result")
        tool_result = case.get("tool_result")
        if tool_result:
            _render_kv_block(tool_result_to_display(tool_result))
        else:
            st.caption("No tool executed yet (blocked, or waiting on approval).")
    with right:
        st.markdown("##### Trace")
        timeline = audit_to_timeline(audit_payload.get("entries") or [])
        if not timeline:
            st.caption("No audit events.")
        else:
            for row in timeline:
                tip = row.get("summary") or row.get("score_summary") or ""
                st.markdown(
                    f"`{row.get('time_short') or '—'}` **{row.get('event_type')}**"
                    + (f" — {tip}" if tip else "")
                )

    if st.button("Close", use_container_width=True):
        _clear_selected_event()
        st.rerun(scope="app")


def main() -> None:
    st.set_page_config(
        page_title="Aegis Control Tower",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()

    with st.sidebar:
        st.header("Connection")
        api_url = st.text_input("API base URL", value=DEFAULT_API_URL)
        client = AegisApiClient(api_url)
        actor = st.text_input("Approver actor", value="dashboard_user")
        cols = st.columns(2)
        if cols[0].button("Refresh", type="primary", use_container_width=True):
            st.rerun()
        verify_clicked = cols[1].button("Verify integrity", use_container_width=True)

        st.header("Demo")
        seed_clicked = st.button("Load demo pack", type="primary", use_container_width=True)
        st.caption(
            "Resets the API and loads clean → injection → unauthorized → escalate. "
            "Escalate stays pending for approval."
        )

        st.header("Knowledge base")
        st.caption(
            "Ingest a new policy/vendor doc live — indexed into that process's "
            "KB only, no restart. (.md / .txt / .csv, max 2MB)"
        )
        upload_process = st.selectbox(
            "Upload for process", PROCESS_OPTIONS, index=0, key="kb_upload_process"
        )
        uploaded = st.file_uploader(
            "Add document", type=["md", "txt", "csv"], key="kb_upload"
        )
        if uploaded is not None and st.button(
            "Ingest document", use_container_width=True
        ):
            try:
                with st.spinner(f"Indexing {uploaded.name} into {upload_process}…"):
                    result = client.upload_document(
                        uploaded.name,
                        uploaded.getvalue(),
                        process=upload_process,
                    )
                st.success(
                    f"Indexed {result.get('filename')} "
                    f"(+{result.get('chunks_added')} chunks, "
                    f"KB now {result.get('kb_size')} chunks)."
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ingest failed: {exc}")

        st.header("Simulated applications")
        st.caption(
            "SDK-integrated apps (plus the procurement/KYC demo-traffic mix) firing "
            "independently via `simulate_workload.py` — distinct from the raw burst below."
        )
        selected_sim_apps: list[str] = []
        for label, cli_key, _proc in SIMULATED_APP_OPTIONS:
            if st.checkbox(label, value=True, key=f"sim_app_{cli_key}"):
                selected_sim_apps.append(cli_key)
        sim_duration = st.slider(
            "Duration (seconds)",
            min_value=10,
            max_value=120,
            value=30,
            step=5,
            key="sim_duration",
        )
        sim_cols = st.columns(2)
        start_sim_clicked = sim_cols[0].button(
            "Start simulated apps",
            type="primary",
            use_container_width=True,
            disabled=_sim_workload_running() or not selected_sim_apps,
        )
        stop_sim_clicked = sim_cols[1].button(
            "Stop",
            use_container_width=True,
            disabled=not _sim_workload_running(),
        )
        if _sim_workload_running():
            st.success("Simulated apps running…")
        elif st.session_state.get("sim_workload_proc") is not None:
            st.caption("Last run finished.")

        st.caption("Upload a policy doc scoped to one app — only that process's KB changes.")
        sim_upload_label = st.selectbox(
            "Scope upload to app",
            [label for label, _, _ in SIMULATED_APP_OPTIONS],
            key="sim_app_upload_label",
        )
        sim_upload_process = next(
            proc for label, _, proc in SIMULATED_APP_OPTIONS if label == sim_upload_label
        )
        sim_uploaded = st.file_uploader(
            "Policy / vendor doc for selected app",
            type=["md", "txt", "csv"],
            key="sim_app_kb_upload",
        )
        sim_ingest_clicked = st.button(
            "Ingest for selected app",
            use_container_width=True,
            key="sim_app_ingest",
        )

        st.header("Traffic")
        st.caption(
            "Fire synthetic cases through the real gateway/injection guard/audit "
            "chain (mocked plan — no live LLM) to populate Live traffic below."
        )
        burst_n = st.slider("Cases to fire", min_value=5, max_value=100, value=25, step=5)
        auto_refresh = st.checkbox("Auto-refresh live traffic (2s)", value=True)
        simulate_clicked = st.button(
            "Simulate traffic burst", type="primary", use_container_width=True
        )
        st.caption(
            "For a sustained stream during a live demo, run in a third terminal: "
            "`python scripts/traffic_sim.py --rate 3 --duration 60`"
        )

        st.header("Help")
        st.caption(
            "Open **How to demo** on the main page for the walkthrough. "
            "Need the API? From `control-tower/`: `uvicorn api.main:app`"
        )

    connected = False
    try:
        client.health()
        connected = True
    except Exception as exc:  # noqa: BLE001 — surface connection errors in UI
        _render_header(connected=False, pending_count=0)
        st.error(f"Cannot reach API at {api_url}: {exc}")
        st.info(
            "Start the API in one terminal: `uvicorn api.main:app` from `control-tower/`. "
            "Keep Streamlit in a second terminal."
        )
        _render_guide(expanded=True)
        return

    if seed_clicked:
        try:
            with st.spinner("Loading demo pack…"):
                result = client.seed_demo()
            n = len(result.get("cases") or [])
            pending_n = result.get("pending_approval_count", 0)
            st.session_state.pop("case_select", None)
            st.session_state.pop("focus_case_id", None)
            st.success(f"Demo pack loaded: {n} cases ({pending_n} pending approval).")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Load demo pack failed: {exc}")

    if stop_sim_clicked:
        _stop_sim_workload()
        st.toast("Stopped simulated applications.")
        st.rerun()

    if start_sim_clicked:
        if not selected_sim_apps:
            st.warning("Select at least one simulated application.")
        else:
            _stop_sim_workload()
            proc = _start_sim_workload(
                api_url=api_url,
                apps=selected_sim_apps,
                duration_sec=float(sim_duration),
            )
            st.session_state["sim_workload_proc"] = proc
            st.toast(
                f"Started {len(selected_sim_apps)} app(s) for {sim_duration}s."
            )
            st.rerun()

    if sim_ingest_clicked:
        if sim_uploaded is None:
            st.warning("Choose a document to ingest for the selected app.")
        else:
            try:
                with st.spinner(
                    f"Indexing {sim_uploaded.name} into {sim_upload_process}…"
                ):
                    result = client.upload_document(
                        sim_uploaded.name,
                        sim_uploaded.getvalue(),
                        process=sim_upload_process,
                    )
                st.success(
                    f"Scoped to **{sim_upload_process}**: indexed "
                    f"{result.get('filename')} "
                    f"(+{result.get('chunks_added')} chunks, "
                    f"KB now {result.get('kb_size')} chunks)."
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ingest failed: {exc}")

    if verify_clicked:
        try:
            result = client.verify_audit()
            count = result.get("entry_count", 0)
            if result.get("valid"):
                st.success(f"Audit chain verified ({count} entries).")
            else:
                st.error(f"Audit chain BROKEN — tamper detected ({count} entries).")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Verify failed: {exc}")

    if simulate_clicked:
        rng = random.Random()
        progress = st.progress(0.0, text=f"Firing {burst_n} synthetic cases…")
        ok, err = 0, 0
        for i in range(burst_n):
            body = random_submit_body(rng, seq=i)
            try:
                client.submit_case(
                    process=body["process"],
                    request=body["request"],
                    mock_agent_plan=body.get("mock_agent_plan"),
                    force_chunk_ids=body.get("force_chunk_ids"),
                    case_id=body["case_id"],
                    source_app=body.get("source_app"),
                )
                ok += 1
            except Exception:  # noqa: BLE001 — keep the burst going
                err += 1
            progress.progress((i + 1) / burst_n, text=f"Fired {i + 1}/{burst_n}…")
        progress.empty()
        st.toast(f"Traffic burst done: {ok} submitted, {err} failed.")
        st.rerun()

    try:
        cases = client.list_cases()
    except Exception as exc:  # noqa: BLE001
        _render_header(connected=connected, pending_count=0)
        st.error(f"Failed to list cases: {exc}")
        return

    rows = cases_to_rows(cases)
    pending = pending_approvals(cases)
    kpis = case_kpis(cases)
    existing_ids = {str(c.get("case_id")) for c in cases if c.get("case_id")}

    _render_header(connected=connected, pending_count=kpis["pending"])
    _render_guide(expanded=not rows)

    with st.expander("Submit case", expanded=False):
        st.caption(
            "Runs a live case through the tower for the selected process "
            "(uses the real LLM unless the API is given a mock plan). "
            "Fields change with the process — finance expenses, risk severity, "
            "RAG questions, etc."
        )
        # Process sits outside the form so changing it refreshes field labels/defaults.
        process = st.selectbox(
            "Process",
            PROCESS_OPTIONS,
            index=0,
            key="submit_case_process",
        )
        spec = submit_case_form_spec(process)
        with st.form("submit_case_form"):
            party_id = st.text_input(
                str(spec["party_label"]),
                value=str(spec["party_default"]),
                key=f"submit_party_{process}",
            )
            if spec.get("show_amount", True):
                amount = st.number_input(
                    str(spec["amount_label"]),
                    min_value=float(spec["amount_min"]),
                    value=float(spec["amount_default"]),
                    step=float(spec["amount_step"]),
                    help=spec.get("amount_help"),
                    key=f"submit_amount_{process}",
                )
            else:
                amount = float(spec["amount_default"])
            detail = st.text_input(
                str(spec["detail_label"]),
                value=str(spec["detail_default"]),
                key=f"submit_detail_{process}",
            )
            submitted = st.form_submit_button("Submit", type="primary")
        if submitted:
            request = build_submit_case_request(
                process,
                party_id=party_id,
                amount=float(amount),
                detail=detail,
            )
            case_id = unique_live_case_id(party_id, existing_ids)
            try:
                created = client.submit_case(
                    process=process,
                    request=request,
                    case_id=case_id,
                    source_app=submit_case_source_app(process),
                )
                focused = created.get("case_id") or case_id
                st.session_state["focus_case_id"] = focused
                st.session_state["case_select"] = focused
                st.toast(
                    f"Submitted {focused} → "
                    f"{(created.get('gateway_decision') or {}).get('decision')} "
                    f"({created.get('status')})"
                )
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Submit failed: {exc}")

    st.markdown('<div class="aegis-section-label">Overview</div>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cases", kpis["total"])
    m2.metric("Pending", kpis["pending"])
    m3.metric("Allow", kpis["allow"])
    m4.metric("Block", kpis["block"])

    st.markdown('<div class="aegis-section-label">Live traffic</div>', unsafe_allow_html=True)
    st.caption(
        "Recent events from connected apps. Click View on a row for the full "
        "request, tool call, reason, and stage checklist. "
        "Default storage is in-memory — cases last until the API restarts "
        "(set DATABASE_URL=sqlite or postgres to persist)."
    )

    tw1, tw2, tw3 = st.columns([2.2, 1.4, 1.2])
    with tw1:
        window_label = st.segmented_control(
            "Time range",
            options=_TRAFFIC_WINDOW_LABELS,
            default=_TRAFFIC_WINDOW_LABELS[0],
            key="traffic_window",
            label_visibility="collapsed",
        )
        if window_label is None:
            window_label = _TRAFFIC_WINDOW_LABELS[0]
    with tw2:
        app_choices = sorted(
            {
                str(c.get("source_app"))
                for c in cases
                if c.get("source_app")
            }
        )
        app_filter = st.selectbox(
            "Application",
            options=["All apps", *app_choices],
            index=0,
            key="traffic_app_filter",
        )
    with tw3:
        decision_filter = st.selectbox(
            "Decision",
            options=_TRAFFIC_DECISION_OPTIONS,
            index=0,
            key="traffic_decision_filter",
        )

    since_minutes = _TRAFFIC_WINDOW_MINUTES.get(window_label)
    source_app_param = None if app_filter == "All apps" else app_filter
    decision_param = None if decision_filter == "All decisions" else decision_filter

    @st.fragment(run_every=2 if auto_refresh else None)
    def _live_traffic() -> None:
        try:
            payload = client.traffic_recent(
                limit=_TRAFFIC_ROW_LIMIT,
                since_minutes=since_minutes,
                source_app=source_app_param,
                decision=decision_param,
            )
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Live traffic unavailable: {exc}")
            return
        traffic_cases = payload.get("cases") or []
        matched = int(payload.get("matched") or 0)
        if matched < len(traffic_cases):
            matched = len(traffic_cases)
        total_retained = int(payload.get("total_cases") or 0)

        connected_sources = sorted(
            {
                str(c.get("source_app"))
                for c in traffic_cases
                if c.get("source_app")
            }
        )
        st.markdown(
            '<div class="aegis-section-label">Connected applications</div>',
            unsafe_allow_html=True,
        )
        st.markdown(connected_apps_html(connected_sources), unsafe_allow_html=True)

        window_bits = window_label
        if since_minutes is not None:
            window_bits = f"last {since_minutes} min"
        shown = len(traffic_cases)
        trunc = f" · showing {shown}" if matched > shown else ""
        st.markdown(
            f'<div class="traffic-meta">'
            f"{matched} in window ({window_bits}) · "
            f"{total_retained} retained on API{trunc}"
            f"</div>",
            unsafe_allow_html=True,
        )

        if not traffic_cases:
            st.caption(
                "No traffic in this window — widen the range, clear filters, "
                "start simulated apps, load the demo pack, or fire a traffic burst."
            )
            return

        newest_id = traffic_cases[0].get("case_id")
        prev_newest = st.session_state.get("traffic_newest_id")
        st.session_state["traffic_newest_id"] = newest_id

        # Cap interactive View buttons so fragment refresh stays snappy.
        visible = traffic_cases[:40]
        if len(traffic_cases) > len(visible):
            st.caption(
                f"Showing first {len(visible)} of {len(traffic_cases)} — "
                "narrow the time window to focus."
            )

        for i, c in enumerate(visible):
            cid = str(c.get("case_id") or f"row-{i}")
            row_col, btn_col = st.columns([12, 1], vertical_alignment="center")
            with row_col:
                st.markdown(
                    traffic_row_html(
                        c, is_new=(i == 0 and newest_id != prev_newest)
                    ),
                    unsafe_allow_html=True,
                )
            with btn_col:
                if st.button(
                    "View",
                    key=f"traffic-view-{cid}",
                    use_container_width=True,
                ):
                    # Open from main() — calling the dialog inside this fragment
                    # makes Close's st.rerun() fragment-scoped and leaves the overlay stuck.
                    st.session_state["selected_event_id"] = cid
                    st.rerun(scope="app")

    # Dialog must live outside the auto-refresh fragment so Close can full-app-rerun.
    selected_event_id = st.session_state.get("selected_event_id")
    if selected_event_id:
        _traffic_event_dialog(client, str(selected_event_id))

    _live_traffic()

    st.markdown('<div class="aegis-section-label">Approval queue</div>', unsafe_allow_html=True)
    st.caption("Human-in-the-loop pauses — Approve resumes the agent; Reject blocks it.")
    if not pending:
        st.markdown(
            '<div class="aegis-card"><span class="aegis-muted">'
            "No cases pending approval. Load the demo pack to get an escalate waiting for you."
            "</span></div>",
            unsafe_allow_html=True,
        )
    else:
        for item in pending:
            d_kind = decision_badge_kind(item.get("decision"))
            badges = (
                badge_html(format_decision_label(item.get("decision")), d_kind)
                + " "
                + badge_html("PENDING", "pending")
            )
            st.markdown(
                f'<div class="aegis-card">'
                f'<div class="aegis-card-title">{html.escape(str(item["case_id"]))}</div>'
                f'<div class="aegis-muted">{html.escape(str(item.get("process") or ""))}'
                f' · risk={html.escape(str(item.get("risk_score")))}</div>'
                f'<div style="margin:0.45rem 0">{badges}</div>'
                f'<div class="aegis-muted">{html.escape(item.get("reason") or "")}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )
            b1, b2 = st.columns(2)
            if b1.button(
                "Approve",
                key=f"approve-{item['call_id']}",
                type="primary",
                use_container_width=True,
            ):
                try:
                    client.approve(item["call_id"], action="approve", actor=actor)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Approve failed: {exc}")
            if b2.button(
                "Reject",
                key=f"reject-{item['call_id']}",
                use_container_width=True,
            ):
                try:
                    client.approve(item["call_id"], action="reject", actor=actor)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Reject failed: {exc}")

    st.markdown('<div class="aegis-section-label">Cases</div>', unsafe_allow_html=True)
    if not rows:
        _render_empty_state()
        return

    st.markdown(
        '<div class="legend-row">'
        f'{badge_html("ALLOW", "allow")} auto-approved · '
        f'{badge_html("BLOCK", "block")} policy denial · '
        f'{badge_html("ESCALATE", "escalate")} needs human · '
        f'{badge_html("PENDING", "pending")} waiting in queue'
        "</div>",
        unsafe_allow_html=True,
    )
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config=_CASES_COLUMN_CONFIG,
    )

    case_ids = [r["case_id"] for r in rows if r.get("case_id")]
    default_idx = _default_case_index(rows)
    focus = st.session_state.pop("focus_case_id", None)
    if focus and focus in case_ids:
        st.session_state["case_select"] = focus
    elif st.session_state.get("case_select") not in case_ids:
        st.session_state["case_select"] = case_ids[min(default_idx, len(case_ids) - 1)]

    selected = st.selectbox(
        "Select case",
        case_ids,
        key="case_select",
        help="Defaults to a pending escalate case when available; live submits auto-select.",
    )
    if not selected:
        return

    case = client.get_case(selected)
    audit_payload = client.get_audit(selected)
    entries = audit_payload.get("entries") or []
    timeline = audit_to_timeline(entries)
    panel = decision_to_score_panel(case.get("gateway_decision"))
    status_kind = status_badge_kind(case.get("status"))

    st.markdown(
        f'{badge_html(str(case.get("status") or "—"), status_kind)} '
        f'{badge_html(str(case.get("process") or "—"), "neutral")}',
        unsafe_allow_html=True,
    )

    # Scores full-width (stacked) so laptop panes never show "0..." truncation
    st.markdown('<div class="aegis-section-label">Scores</div>', unsafe_allow_html=True)
    if panel is None:
        st.write("No gateway decision yet.")
    else:
        st.markdown(
            decision_banner_html(panel.get("decision")),
            unsafe_allow_html=True,
        )
        st.metric("Risk", format_score_value(panel.get("risk_score")))
        st.metric("Confidence", format_score_value(panel.get("confidence_score")))
        st.metric("Evidence", format_score_value(panel.get("evidence_score")))

    left, right = st.columns(2)
    with left:
        if panel is not None:
            with st.expander("Reason", expanded=True):
                st.write(panel.get("reason") or "—")
            with st.expander("Policy refs / chunk ids", expanded=True):
                refs = panel.get("policy_refs") or []
                if refs:
                    chips = " ".join(
                        f'<span class="chip">{html.escape(str(ref))}</span>' for ref in refs
                    )
                    st.markdown(chips, unsafe_allow_html=True)
                else:
                    st.write("—")
        st.markdown("**Request**")
        _render_request_block(case.get("request"))

        st.markdown("**Action taken**")
        tool_result = case.get("tool_result")
        if tool_result:
            _render_kv_block(tool_result_to_display(tool_result))
        else:
            st.caption("No tool has executed for this case yet (blocked, or awaiting approval).")

    with right:
        st.markdown('<div class="aegis-section-label">Trace timeline</div>', unsafe_allow_html=True)
        chain = audit_payload.get("chain_valid")
        chain_badge = (
            badge_html("chain valid", "ok") if chain else badge_html("chain broken", "err")
        )
        st.markdown(chain_badge, unsafe_allow_html=True)
        if not timeline:
            st.write("No audit events for this case.")
        else:
            st.dataframe(
                [
                    {
                        "time": r.get("time_short") or r.get("timestamp"),
                        "type": r.get("event_type"),
                        "step": r.get("step_id"),
                        "summary": r.get("summary"),
                        "scores": r.get("score_summary") or "",
                    }
                    for r in timeline
                ],
                use_container_width=True,
                hide_index=True,
                column_config=_TIMELINE_COLUMN_CONFIG,
            )

    with st.expander("Ask investigation assistant", expanded=False):
        st.caption("RAG over the audit log — answers why a case was flagged (offline mock if no API key).")
        question = st.text_input(
            "Question",
            value="Why was this flagged?",
            key=f"invest-q-{selected}",
        )
        if st.button("Ask", key=f"invest-ask-{selected}", type="primary"):
            try:
                result = client.investigate(question, case_id=selected)
            except Exception:
                mock = offline_investigate_mock(
                    question,
                    case_id=selected,
                    decision=case.get("gateway_decision"),
                )
                try:
                    result = client.investigate(
                        question, case_id=selected, mock_answer=mock
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Investigation failed: {exc}")
                    result = None
            if result is not None:
                st.write(result.get("answer") or "—")
                cited = result.get("cited_entry_ids") or []
                if cited:
                    st.caption("Cited entry ids: " + ", ".join(str(c) for c in cited))
                chunks = result.get("cited_chunk_ids") or []
                if chunks:
                    st.caption("Cited chunks: " + ", ".join(str(c) for c in chunks))


if __name__ == "__main__":
    main()
