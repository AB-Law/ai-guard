"""Streamlit dashboard — live cases, scores, audit timeline, approval queue."""

from __future__ import annotations

import html
import os
import random

import streamlit as st

from dashboard.api_client import AegisApiClient
from dashboard.styles import badge_html, decision_banner_html, inject_css, traffic_row_html
from dashboard.view_models import (
    audit_to_timeline,
    case_kpis,
    cases_to_rows,
    decision_badge_kind,
    decision_to_score_panel,
    format_decision_label,
    format_score_value,
    offline_investigate_mock,
    pending_approvals,
    request_to_display,
    status_badge_kind,
    tool_result_to_display,
    unique_live_case_id,
)
from scripts.traffic_lib import random_submit_body

DEFAULT_API_URL = os.environ.get("AEGIS_API_URL", "http://127.0.0.1:8000")
PROCESS_OPTIONS = ("procurement_review", "onboarding_kyc")

_DEMO_GUIDE_MD = """
1. Click **Load demo pack** in the sidebar (loads clean → injection → unauthorized → escalate).
2. In **Approval queue**, open the escalate case and click **Approve** (or Reject).
3. In **Cases**, select `clean_po` (allow), `unauthorized_tool` (block), and `injection_planted`.
4. Read **Scores**, policy refs, and the **Trace timeline** for evidence.
5. Expand **Ask investigation assistant** and ask *Why was this flagged?*
"""

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
            "Ingest a new policy/vendor doc live — indexed into the running tower "
            "immediately, no restart. (.md / .txt / .csv, max 2MB)"
        )
        uploaded = st.file_uploader(
            "Add document", type=["md", "txt", "csv"], key="kb_upload"
        )
        if uploaded is not None and st.button(
            "Ingest document", use_container_width=True
        ):
            try:
                with st.spinner(f"Indexing {uploaded.name}…"):
                    result = client.upload_document(uploaded.name, uploaded.getvalue())
                st.success(
                    f"Indexed {result.get('filename')} "
                    f"(+{result.get('chunks_added')} chunks, "
                    f"KB now {result.get('kb_size')} chunks)."
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ingest failed: {exc}")

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
        st.caption("Runs a live case through the tower (uses the real LLM unless mocked by the API).")
        with st.form("submit_case_form"):
            process = st.selectbox("Process", PROCESS_OPTIONS, index=0)
            vendor_id = st.text_input("Vendor ID", value="V-1001")
            amount = st.number_input("Amount", min_value=0.0, value=2500.0, step=100.0)
            item = st.text_input("Item", value="Laptop docks x10")
            submitted = st.form_submit_button("Submit", type="primary")
        if submitted:
            case_id = unique_live_case_id(vendor_id, existing_ids)
            try:
                created = client.submit_case(
                    process=process,
                    request={
                        "vendor_id": vendor_id,
                        "amount": float(amount),
                        "item": item,
                    },
                    case_id=case_id,
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
        "Every case moving through the guardrail pipeline in real time — "
        "Retrieve → Scan → Gateway → Action → Approval."
    )

    @st.fragment(run_every=2 if auto_refresh else None)
    def _live_traffic() -> None:
        try:
            traffic_cases = client.traffic_recent(limit=25)
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Live traffic unavailable: {exc}")
            return
        if not traffic_cases:
            st.caption("No traffic yet — load the demo pack or fire a traffic burst.")
            return
        newest_id = traffic_cases[0].get("case_id")
        prev_newest = st.session_state.get("traffic_newest_id")
        st.session_state["traffic_newest_id"] = newest_id
        rows_html = "".join(
            traffic_row_html(c, is_new=(i == 0 and newest_id != prev_newest))
            for i, c in enumerate(traffic_cases)
        )
        st.markdown(rows_html, unsafe_allow_html=True)

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
