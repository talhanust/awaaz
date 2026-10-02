import streamlit as st
from streamlit_folium import st_folium

from core import db, lifecycle, ui
from core.config import secret


def authorized() -> bool:
    pw = secret("DASHBOARD_PASSWORD")
    if not pw:
        st.caption("Department actions are disabled: no DASHBOARD_PASSWORD is configured.")
        return False
    if st.session_state.get("dash_ok"):
        return True
    with st.expander("Department login, to acknowledge issues or mark them fixed"):
        entered = st.text_input("Password", type="password")
        if entered and entered == pw:
            st.session_state.dash_ok = True
            st.rerun()
        elif entered:
            st.error("Wrong password.")
    return False


def page():
    db.sweep_unverified()
    st.title("Authority dashboard")
    st.markdown('<p class="sub">One row per problem, however many residents reported it. Ranked by residents, severity and days open. '
                '“Mark fixed” asks a resident to confirm before the issue closes.</p>', unsafe_allow_html=True)
    ok = authorized()
    rows = db.queue()
    now = db.now()
    overdue = [r for r in rows if r["expected_by"] < now]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Open problems", len(rows))
    k2.metric("Residents waiting", sum(r["report_count"] + (r["confirmations"] or 0) for r in rows))
    k3.metric("Past due date", len(overdue))
    k4.metric("Escalated", sum(1 for r in rows if r["escalation_tier"]))

    tab_q, tab_map, tab_board = st.tabs(["Queue", "Map", "Department performance"])
    with tab_q:
        f1, f2 = st.columns([1, 2])
        depts = {r["authority_id"]: (db.authority(r["authority_id"]) or {}).get("name", r["authority_id"]) for r in rows}
        pick = f1.selectbox("Department", ["All departments"] + sorted(depts.values()))
        view = f2.pills("Show", ["All", "Past due", "Escalated", "Waiting for a resident to confirm"], default="All", key="dash_view")
        shown = [r for r in rows if pick == "All departments" or depts[r["authority_id"]] == pick]
        if view == "Past due":
            shown = [r for r in shown if r["expected_by"] < now]
        elif view == "Escalated":
            shown = [r for r in shown if r["escalation_tier"]]
        elif view == "Waiting for a resident to confirm":
            waiting = {x["issue_id"] for x in db.q("select issue_id from issues where verification_requested_at is not null")}
            shown = [r for r in shown if r["issue_id"] in waiting]
        if not shown:
            st.caption("Nothing matches this filter.")
        for rank, r in enumerate(shown, 1):
            issue = db.get_issue(r["issue_id"])
            with st.container(border=True):
                st.markdown(ui.issue_row(issue, rank=rank), unsafe_allow_html=True)
                if ok:
                    c1, c2, c3, _ = st.columns([1, 1, 1, 1.2])
                    for col, action, label in ((c1, "acknowledge", "Acknowledge"), (c2, "in_progress", "Start work"), (c3, "fixed", "Mark fixed")):
                        if col.button(label, key=f"{action}-{r['issue_id']}", use_container_width=True,
                                      disabled=(action == "acknowledge" and r["status"] != "open") or bool(issue["verification_requested_at"] and action == "fixed")):
                            lifecycle.authority_action(issue, action)
                            st.toast(f"{r['issue_id']}: {label.lower()} recorded" + (". A resident will be asked to confirm." if action == "fixed" else "."))
                            st.rerun()
    with tab_map:
        st_folium(ui.issues_map(db.open_issues_for_map(), zoom=14), height=520, use_container_width=True, returned_objects=[], key="dashmap")
        st.caption("Bigger circles mean more residents. Public locations are rounded to about 100 m.")
    with tab_board:
        st.markdown("**Open problems by type**")
        cats = db.category_breakdown()
        if cats:
            st.bar_chart([{"Type": ui.CAT_LABEL.get(c["category"], c["category"]), "Open problems": c["issues"]} for c in cats],
                         x="Type", y="Open problems", color="#1B2A5E", horizontal=True, height=260)
        st.markdown("**How each department is doing right now**")
        st.dataframe([{"Department": r["name"], "Open": r["open"], "Past due": r["overdue"], "Escalated": r["escalated"],
                       "Avg days open": r["avg_days_open"], "Target days": r["benchmark_days"], "Verified fixes": r["fixed"]}
                      for r in db.response_board()], hide_index=True, use_container_width=True)
        st.markdown("**Track record (last 90 days)**")
        st.dataframe([{"Department": s["name"], "Verified fixes": s["resolved_90d"],
                       "Median days to fix": round(s["median_days"], 1) if s["median_days"] is not None else None,
                       "Fixed within target": f"{round(s['within_benchmark'] * 100)}%" if s["resolved_90d"] >= 10 and s["within_benchmark"] is not None else "Needs 10+ fixes",
                       "Closed without confirmation": s["unverified_90d"]} for s in db.scorecards()], hide_index=True, use_container_width=True)
