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
    with st.expander("🔒 Department login (to acknowledge or mark issues fixed)"):
        entered = st.text_input("Password", type="password")
        if entered and entered == pw:
            st.session_state.dash_ok = True
            st.rerun()
        elif entered:
            st.error("Wrong password.")
    return False


def page():
    ui.css()
    db.sweep_unverified()
    st.title("Authority dashboard")
    st.caption("Duplicates merged into one Issue and ranked by residents × severity × days open. "
               "Marking an issue fixed asks residents to confirm before it closes.")
    ok = authorized()
    rows = db.queue()
    now = db.now()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Open issues", len(rows))
    k2.metric("Resident reports behind them", sum(r["report_count"] for r in rows))
    k3.metric("Average days open", round(sum(r["days_open"] for r in rows) / len(rows)) if rows else 0)
    k4.metric("Within due date", f"{round(100 * sum(1 for r in rows if r['expected_by'] >= now) / len(rows)) if rows else 0}%")

    depts = sorted({r["authority_id"] for r in rows})
    left, right = st.columns([3, 2], gap="large")
    with left:
        pick = st.selectbox("Department", ["All departments"] + depts)
        shown = [r for r in rows if pick == "All departments" or r["authority_id"] == pick]
        for rank, r in enumerate(shown, 1):
            with st.container(border=True):
                a, b = st.columns([6, 1])
                a.markdown(f"**#{rank} · {r['summary']}**  \n{ui.pill(r)} `{r['issue_id']}` · {r['sector']} · {r['authority_id']} · "
                           f"{r['days_open']} days open", unsafe_allow_html=True)
                b.metric("Residents", r["report_count"], label_visibility="visible")
                if ok:
                    c1, c2, c3 = st.columns(3)
                    issue = None
                    for col, action, label in ((c1, "acknowledge", "Acknowledge"), (c2, "in_progress", "In progress"), (c3, "fixed", "Mark fixed")):
                        if col.button(label, key=f"{action}-{r['issue_id']}", use_container_width=True,
                                      disabled=(action == "acknowledge" and r["status"] != "open")):
                            lifecycle.authority_action(db.get_issue(r["issue_id"]), action)
                            st.toast(f"{r['issue_id']}: {label.lower()} recorded" + (" · residents will be asked to confirm" if action == "fixed" else ""))
                            st.rerun()
    with right:
        st.markdown("**Map of open issues**")
        st_folium(ui.issues_map(db.open_issues_for_map(), zoom=14), height=420, use_container_width=True, returned_objects=[], key="dashmap")
        st.caption("Public locations are rounded to about 100 m.")

    st.subheader("Department scorecards (last 90 days)")
    table = [{"Department": s["name"], "Resolved": s["resolved_90d"],
              "Median days": round(s["median_days"], 1) if s["median_days"] is not None else None, "Target (days)": s["benchmark_days"],
              "Within target": f"{round(s['within_benchmark'] * 100)}%" if s["resolved_90d"] >= 10 and s["within_benchmark"] is not None else "Not enough data",
              "Unverified closures": s["unverified_90d"], "Open": s["open_now"], "Escalated": s["escalated_now"]} for s in db.scorecards()]
    st.dataframe(table, hide_index=True, use_container_width=True)
