import streamlit as st

from core import agents, db, ui


def page():

    st.title("Neighborhood reports")
    st.caption("A cluster is 3+ issues or 10+ resident reports in one area and category within 30 days. Reports state the pattern, not a verdict.")
    ui.show_warnings()
    clusters, saved = db.clusters(), db.saved_reports()
    if not clusters:
        st.info("No clusters in the last 30 days yet.")
        return
    for c in clusters:
        auth = db.authority(c["authority_id"])
        trend = f"{'+' if c['reports'] >= c['prev_reports'] else ''}{round(100 * (c['reports'] - c['prev_reports']) / c['prev_reports'])}% vs previous 30 days" \
            if c["prev_reports"] else "new this window"
        with st.container(border=True):
            a, b = st.columns([4, 1])
            a.markdown(f"### {c['reports']} residents, {c['issues']} {c['category']} issues, {c['sector']}")
            a.caption(f"{c['resolved']} resolved · {c['avg_days_open']} days open on average · {trend} · {auth['name']}")
            r = saved.get(c["cluster_key"])
            if b.button("Rewrite report" if r else "Write report", key=c["cluster_key"], type="primary", use_container_width=True):
                with st.spinner("The Pattern Analyst is writing the report…"):
                    d, mode = agents.neighborhood_report(c, auth["name"])
                    db.save_report(c["cluster_key"], d["headline_stat"], d["report_en"], d["report_ur"])
                st.rerun()
            if r:
                en, ur = st.columns(2)
                en.markdown(f"**{r['headline']}**\n\n{r['report_en']}")
                with ur:
                    ui.local_text(r["report_ur"])
                st.caption(f"Written {r['created_at']:%d %b %Y, %H:%M}")
