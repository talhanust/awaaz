"""Live monitor: public accountability for every complaint and every department, by day, week, month or year."""
import html as _html
import math

import altair as alt
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from core import db, simulate, ui
from core.config import secret

C = ui.CHART
PKT = "Asia/Karachi"
GRAN = {  # freq, how many periods to show, label format, words for the current/previous period
    "Daily": ("D", 30, "%d %b", "Today", "yesterday"),
    "Weekly": ("W-SUN", 26, "Week of %d %b", "This week", "last week"),
    "Monthly": ("M", 12, "%b %Y", "This month", "last month"),
    "Yearly": ("Y", 5, "%Y", "This year", "last year"),
}
DEPT_EVENTS = ["acknowledged", "in_progress", "authority_marked_fixed"]
BUCKETS = ["0–3 days", "4–7 days", "8–14 days", "15–30 days", "Over 30 days"]
STATUS_COLOR = {"overdue": C["red"], "escalated": C["red"], "verified": C["action"], "unverified": C["slate"], "progress": C["blue"], "filed": C["ink"]}


# ---------------- data ----------------
def _local(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True).dt.tz_convert(PKT).dt.tz_localize(None)


@st.cache_data(ttl=20, show_spinner=False)
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.DataFrame(db.monitor_issues())
    ev = pd.DataFrame(db.monitor_events(3650))
    if df.empty:
        return df, ev
    auths = db.authorities()
    names, bench = {a["authority_id"]: a["name"] for a in auths}, {a["authority_id"]: a["benchmark_days"] for a in auths}
    now = pd.Timestamp.now(tz=PKT).tz_localize(None)
    df["first_l"], df["expected_l"], df["resolved_l"] = _local(df["first_reported_at"]), _local(df["expected_by"]), _local(df["resolved_at"])
    df["department"] = df["authority_id"].map(names).fillna(df["authority_id"])
    df["target_days"] = df["authority_id"].map(bench).fillna(7)
    df["closed"] = df["status"].isin(["resolved", "closed_unverified"])
    df["age_days"] = ((df["resolved_l"].where(df["closed"], now) - df["first_l"]).dt.total_seconds() / 86400).round(1)
    df["overdue"] = ~df["closed"] & (df["expected_l"] < now)
    df["target_used"] = (df["age_days"] / df["target_days"] * 100).clip(upper=300).round(0)
    df["backers"] = (df["report_count"] + df["confirmations"].fillna(0)).astype(int)
    recs = df.to_dict("records")
    df["stamp"], df["stamp_class"] = [ui.stamp_for(r)[0] for r in recs], [ui.stamp_for(r)[1] for r in recs]
    df["type"] = df["category"].map(ui.CAT_LABEL)
    if not ev.empty:
        ev["at"] = _local(ev["created_at"])
        ev["department"] = ev["authority_id"].map(names).fillna(ev["authority_id"])
    dept_ev = ev[ev["type"].isin(DEPT_EVENTS)] if not ev.empty else ev
    if len(dept_ev):  # a fresh deployment may have no department actions yet
        acts = dept_ev.groupby("issue_id")["at"].agg(["min", "max"]).reset_index()
        df = df.merge(acts, on="issue_id", how="left")
        df["first_response_h"] = ((df["min"] - df["first_l"]).dt.total_seconds() / 3600).round(1)
        df["last_action"] = df["max"].fillna(df["first_l"])
        df = df.drop(columns=["min", "max"])
    else:
        df["first_response_h"], df["last_action"] = math.nan, df["first_l"]
    df["silent_days"] = ((now - df["last_action"]).dt.total_seconds() / 86400).where(~df["closed"]).round(0)
    return df, ev


def periods(gran: str, df: pd.DataFrame) -> pd.PeriodIndex:
    freq, n = GRAN[gran][0], GRAN[gran][1]
    now = pd.Timestamp.now(tz=PKT).tz_localize(None)
    if gran == "Yearly":
        n = max(2, min(5, now.year - df["first_l"].min().year + 1))  # always a previous year to compare with
    return pd.period_range(end=pd.Period(now, freq), periods=n, freq=freq)


def metrics(df: pd.DataFrame, ev: pd.DataFrame, p: pd.Period, until: pd.Timestamp | None = None) -> dict:
    """Figures for one calendar period. `until` cuts the period short, for like-for-like comparison with an in-progress period."""
    s, e = p.start_time, (p + 1).start_time
    if until is not None:
        e = min(e, until)
    now = pd.Timestamp.now(tz=PKT).tz_localize(None)
    end = min(e, now)
    new = df[(df["first_l"] >= s) & (df["first_l"] < e)]
    closed = df[df["closed"] & (df["resolved_l"] >= s) & (df["resolved_l"] < e)]
    fixed = closed[closed["status"] == "resolved"]
    backlog = df[(df["first_l"] < end) & (df["resolved_l"].isna() | (df["resolved_l"] >= end))]
    late = backlog[backlog["expected_l"] < end]
    bounces = 0 if ev.empty else int(((ev["type"] == "fix_disputed") & (ev["at"] >= s) & (ev["at"] < e) & ev["issue_id"].isin(df["issue_id"])).sum())
    median_fix = fixed["age_days"].median() if len(fixed) else math.nan
    return {
        "period": p,
        "New complaints": len(new), "Verified fixes": len(fixed), "Closed unverified": len(closed) - len(fixed),
        "Fixed within target": (fixed["age_days"] <= fixed["target_days"]).mean() * 100 if len(fixed) else math.nan,
        "Median days to fix": median_fix, "First response (hours)": new["first_response_h"].median() if len(new) else math.nan,
        "Backlog at period end": len(backlog), "Past due at period end": len(late), "Bounce-backs": bounces,
        "Escalated share": (new["escalation_tier"] > 0).mean() * 100 if len(new) else math.nan,
        "People-days waiting": int((backlog["backers"] * ((end - backlog["first_l"]).dt.total_seconds() / 86400)).sum()),
        "_closed": len(closed), "_verify": len(fixed) / len(closed) if len(closed) else math.nan,
        "_overdue_share": len(late) / len(backlog) if len(backlog) else 0.0,
    }


def in_progress(p: pd.Period) -> bool:
    now = pd.Timestamp.now(tz=PKT).tz_localize(None)
    return p.start_time <= now < (p + 1).start_time


def label(p: pd.Period, gran: str) -> str:
    return p.start_time.strftime(GRAN[gran][2]) + (" (so far)" if in_progress(p) else "")


def grade(m: dict, target: float, min_closed: int = 3):
    if m["_closed"] < min_closed:
        return "–", None
    within = (m["Fixed within target"] or 0) / 100 if not math.isnan(m["Fixed within target"]) else 0.0
    verify = 0.0 if math.isnan(m["_verify"]) else m["_verify"]
    speed = min(1.0, target / m["Median days to fix"]) if m["Median days to fix"] and not math.isnan(m["Median days to fix"]) else 0.0
    score = round(100 * (0.4 * within + 0.25 * (1 - m["_overdue_share"]) + 0.2 * verify + 0.15 * speed))
    return ("A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D" if score >= 40 else "E"), score


# ---------------- sections ----------------
def kpi_tiles(df, ev, ps, gran):
    now = pd.Timestamp.now(tz=PKT).tz_localize(None)
    elapsed = now - ps[-1].start_time
    cur = metrics(df, ev, ps[-1])
    prev = metrics(df, ev, ps[-2], until=ps[-2].start_time + elapsed) if len(ps) > 1 else None  # same elapsed time: a fair comparison
    word_cur, word_prev = GRAN[gran][3], GRAN[gran][4]
    if len(ps) < 2:
        span = f"so far ({ps[-1].start_time:%d %b}–{now:%d %b}). There's no earlier period to compare with yet"
    elif gran == "Daily":
        span = f"until {now:%H:%M}, compared with {word_prev} until the same time"
    else:
        a, b = ps[-1].start_time, now
        pa, pb = ps[-2].start_time, ps[-2].start_time + elapsed
        span = f"so far ({a:%d %b}–{b:%d %b}), compared with the same stretch of {word_prev} ({pa:%d %b}–{pb:%d %b})"
    st.markdown(f"**{word_cur}** {span}.")
    def delta(key, fmt="{:+.0f}"):
        if not prev or any(isinstance(x, float) and math.isnan(x) for x in (cur[key], prev[key])):
            return None
        return fmt.format(cur[key] - prev[key])
    def val(key, fmt):
        v = cur[key]
        return "–" if isinstance(v, float) and math.isnan(v) else fmt.format(v)
    r1 = st.columns(4)
    r1[0].metric("New complaints", val("New complaints", "{:.0f}"), delta("New complaints"), delta_color="off")
    r1[1].metric("Verified fixes", val("Verified fixes", "{:.0f}"), delta("Verified fixes"), help="Fixes a resident confirmed.")
    r1[2].metric("Fixed within target", val("Fixed within target", "{:.0f}%"), delta("Fixed within target", "{:+.0f} pts"))
    r1[3].metric("Median days to fix", val("Median days to fix", "{:.1f}"), delta("Median days to fix", "{:+.1f}"), delta_color="inverse")
    r2 = st.columns(4)
    r2[0].metric("First response", val("First response (hours)", "{:.0f} h"), delta("First response (hours)", "{:+.0f} h"), delta_color="inverse",
                 help="Median time until the department first acted on a new complaint.")
    r2[1].metric("Backlog", val("Backlog at period end", "{:.0f}"), delta("Backlog at period end"), delta_color="inverse",
                 help="Complaints still open at the end of the period (or now).")
    r2[2].metric("Bounce-backs", val("Bounce-backs", "{:.0f}"), delta("Bounce-backs"), delta_color="inverse",
                 help="Fixes a resident rejected as not actually fixed.")
    r2[3].metric("People-days waiting", f"{cur['People-days waiting']:,}", delta("People-days waiting", "{:+,.0f}"), delta_color="inverse",
                 help="Residents affected × days waiting, across all open complaints. The human cost of delay.")


def trends(df, ev, ps, gran):
    rows = [metrics(df, ev, p) for p in ps]
    table = pd.DataFrame([{**{k: v for k, v in r.items() if not k.startswith("_") and k not in ("period", "label")},
                           "Period": label(r["period"], gran), "start": r["period"].start_time, "In progress": in_progress(r["period"])} for r in rows])
    choice = st.pills("Measure", ["New complaints", "Verified fixes", "Backlog at period end", "Fixed within target", "Median days to fix",
                                  "First response (hours)", "Bounce-backs", "People-days waiting"], default="New complaints", key="tr_metric")
    choice = choice or "New complaints"
    pct = choice in ("Fixed within target",)
    sel = alt.selection_point(name="period", fields=["Period"], on="click", clear="dblclick")
    lower_better = choice in ("Median days to fix", "First response (hours)", "Backlog at period end", "Bounce-backs", "People-days waiting")
    chart = alt.Chart(table).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("Period:N", sort=alt.SortField("start"), title=None, axis=alt.Axis(labelAngle=-40 if len(table) > 12 else 0)),
        y=alt.Y(f"{choice}:Q", title=choice + (" (%)" if pct else "")),
        color=alt.condition(sel, alt.value(C["action"] if not lower_better else C["blue"]), alt.value(C["pale"])),
        opacity=alt.Opacity("In progress:N", scale=alt.Scale(domain=[False, True], range=[1, 0.45]), legend=None),
        tooltip=["Period", alt.Tooltip(f"{choice}:Q", format=".1f" if pct or "Median" in choice else ",.0f")]).add_params(sel)
    ev_sel = st.altair_chart(chart.properties(height=300), use_container_width=True, on_select="rerun", key=f"trend-{gran}-{choice}")
    st.caption("Click a bar to break that period down by department; double-click to clear. The faded bar is the period still in progress.")
    picked = (ev_sel or {}).get("selection", {}).get("period") or []
    if picked:
        pl = picked[0]["Period"]
        p = next(x for x in ps if label(x, gran) == pl)
        st.markdown(f"**{pl} by department**")
        out = []
        for dept, g in df.groupby("department"):
            m = metrics(g, ev, p)
            gr, sc = grade(m, g["target_days"].iloc[0])
            out.append({"Department": dept, "Grade": gr, "New": m["New complaints"], "Verified fixes": m["Verified fixes"],
                        "Within target": None if math.isnan(m["Fixed within target"]) else round(m["Fixed within target"]),
                        "Median days to fix": None if math.isnan(m["Median days to fix"]) else round(m["Median days to fix"], 1),
                        "Backlog": m["Backlog at period end"], "Bounce-backs": m["Bounce-backs"]})
        st.dataframe(pd.DataFrame(out).sort_values("New", ascending=False), hide_index=True, use_container_width=True,
                     column_config={"Within target": st.column_config.NumberColumn(format="%d%%")})
    st.markdown(f"**Every department, {gran.lower()}**")
    spark = []
    for dept, g in df.groupby("department"):
        ms = [metrics(g, ev, p) for p in ps]
        spark.append({"Department": dept, "New complaints": [m["New complaints"] for m in ms],
                      f"{GRAN[gran][3]}": ms[-1]["New complaints"], "Backlog now": ms[-1]["Backlog at period end"],
                      "Fixed within target (trend)": [0 if math.isnan(m["Fixed within target"]) else m["Fixed within target"] for m in ms]})
    st.dataframe(pd.DataFrame(spark), hide_index=True, use_container_width=True, column_config={
        "New complaints": st.column_config.LineChartColumn(f"New complaints, last {len(ps)} periods", y_min=0),
        "Fixed within target (trend)": st.column_config.BarChartColumn("Fixed within target (%)", y_min=0, y_max=100)})


def report_cards(df, ev, ps, gran):
    if gran == "Daily":
        st.info("Report cards need enough closed complaints to be fair. Switch View by to Weekly, Monthly or Yearly.", icon="ℹ️")
        return
    cells = []
    for dept, g in df.groupby("department"):
        target = g["target_days"].iloc[0]
        for p in ps:
            m = metrics(g, ev, p)
            gr, sc = grade(m, target)
            wt = None if math.isnan(m["Fixed within target"]) else round(m["Fixed within target"])
            cells.append({"Department": dept, "Period": label(p, gran), "start": p.start_time, "Grade": gr, "Score": sc,
                          "Score ": "–" if sc is None else f"{sc}/100", "Within target": "–" if wt is None else f"{wt}%",
                          "Verified fixes": m["Verified fixes"], "Backlog": m["Backlog at period end"]})
    data = pd.DataFrame(cells)
    sel = alt.selection_point(name="cell", fields=["Department", "Period"], on="click", clear="dblclick")
    base = alt.Chart(data).encode(
        x=alt.X("Period:N", sort=alt.SortField("start"), title=None, axis=alt.Axis(orient="top", labelAngle=0 if len(ps) <= 8 else -40)),
        y=alt.Y("Department:N", title=None, axis=alt.Axis(labelLimit=240)))
    rect = base.mark_rect(stroke="#FFFFFF", strokeWidth=2).encode(
        color=alt.Color("Grade:N", scale=alt.Scale(domain=list(ui.GRADE_COLORS), range=list(ui.GRADE_COLORS.values())), legend=alt.Legend(orient="bottom", title="Grade")),
        opacity=alt.condition(sel, alt.value(1), alt.value(0.35)),
        tooltip=["Department", "Period", "Grade", alt.Tooltip("Score :N", title="Score"), "Verified fixes", "Within target", "Backlog"]).add_params(sel)
    text = base.mark_text(fontWeight=700, fontSize=13).encode(text="Grade:N", color=alt.condition("datum.Grade == '–'", alt.value("#8A978E"), alt.value("#FFFFFF")))
    ev_sel = st.altair_chart((rect + text).properties(height=alt.Step(34)), use_container_width=True, on_select="rerun", key=f"cards-{gran}")
    st.caption("Grades use complaints closed in each period (at least 3 needed). Click a square to see what's behind it.")
    picked = (ev_sel or {}).get("selection", {}).get("cell") or []
    if picked:
        dept, pl = picked[0]["Department"], picked[0]["Period"]
        p = next(x for x in ps if label(x, gran) == pl)
        s, e = p.start_time, (p + 1).start_time
        g = df[df["department"] == dept]
        sub = g[((g["first_l"] >= s) & (g["first_l"] < e)) | (g["closed"] & (g["resolved_l"] >= s) & (g["resolved_l"] < e))]
        with st.container(border=True):
            row = data[(data["Department"] == dept) & (data["Period"] == pl)].iloc[0]
            st.markdown(f"**{dept}, {pl}**: grade {row['Grade']}" + (f" ({int(row['Score'])}/100)" if row["Score"] is not None and not pd.isna(row["Score"]) else ""))
            st.dataframe(pd.DataFrame({"Reference": sub["issue_id"], "Status": sub["stamp"], "Problem": sub["summary"], "Days": sub["age_days"],
                                       "Target days": sub["target_days"].astype(int), "Residents": sub["backers"]}),
                         hide_index=True, use_container_width=True, height=min(360, 38 + 35 * len(sub)))
    with st.expander("How grades are calculated"):
        st.markdown("Each department is scored out of 100 for each period:\n"
                    "- **40%** fixes completed within the department's target time\n"
                    "- **25%** open complaints that were *not* past due at the end of the period\n"
                    "- **20%** fixes confirmed by a resident, rather than closed unverified\n"
                    "- **15%** speed: target time divided by the median time to fix, capped at 100%\n\n"
                    "A is 85 or more, B 70, C 55, D 40, otherwise E. A period with fewer than 3 closed complaints shows “–”.")


def early_warnings(df, ev):
    now = pd.Timestamp.now(tz=PKT).tz_localize(None)
    open_ = df[~df["closed"]]
    silent = open_[open_["silent_days"] >= 7].sort_values("silent_days", ascending=False)
    wk = df[df["first_l"] >= now - pd.Timedelta(days=7)]
    base4 = df[(df["first_l"] < now - pd.Timedelta(days=7)) & (df["first_l"] >= now - pd.Timedelta(days=35))]
    spikes = []
    for (typ, area), g in wk.groupby(["type", "sector"]):
        usual = len(base4[(base4["type"] == typ) & (base4["sector"] == area)]) / 4
        if len(g) >= 3 and len(g) >= 2 * max(usual, 0.5):
            spikes.append({"Problem type": typ, "Area": area, "This week": len(g), "Usual per week": round(usual, 1),
                           "Times usual": "new" if usual == 0 else f"{len(g) / usual:.1f}×", "Department": g["department"].mode().iloc[0]})
    bounced = ev[ev["type"] == "fix_disputed"]["issue_id"].unique() if not ev.empty else []
    bounce_df = df[df["issue_id"].isin(bounced)]
    recent = df[df["first_l"] >= now - pd.Timedelta(days=180)].dropna(subset=["lat", "lng"]).copy()
    recent["spot"] = recent["lat"].round(3).astype(str) + "," + recent["lng"].round(3).astype(str)
    repeats = []
    for (spot, typ), g in recent.groupby(["spot", "type"]):
        if len(g) >= 3:
            repeats.append({"Area": g["sector"].mode().iloc[0], "Problem type": typ, "Reports at this spot (180 days)": len(g),
                            "Fixed before": int((g["status"] == "resolved").sum()), "Still open": int((~g["closed"]).sum()),
                            "Department": g["department"].mode().iloc[0], "Latest": g["first_l"].max().strftime("%d %b")})
    c = st.columns(4)
    c[0].metric("Silent complaints", len(silent), help="Open complaints with no action from the department for 7+ days.")
    c[1].metric("Spike alerts", len(spikes), help="A problem type in one area at twice its usual weekly rate or more.")
    c[2].metric("Bounce-backs", len(bounce_df), help="Fixes residents rejected as not actually fixed.")
    c[3].metric("Repeat locations", len(repeats), help="Spots with 3+ reports of the same problem in 180 days: often a patch, not a fix.")
    st.markdown("**Spike alerts this week**")
    st.dataframe(pd.DataFrame(spikes), hide_index=True, use_container_width=True) if spikes else st.caption("No unusual rise this week.")
    st.markdown("**Silent complaints: no department action for 7 days or more**")
    if len(silent):
        st.dataframe(pd.DataFrame({"Reference": silent["issue_id"], "Problem": silent["summary"], "Department": silent["department"],
                                   "Silent for (days)": silent["silent_days"].astype(int), "Residents": silent["backers"], "Status": silent["stamp"]}).head(25),
                     hide_index=True, use_container_width=True)
    else:
        st.caption("Every open complaint has had department action in the last week.")
    a, b = st.columns(2)
    with a:
        st.markdown("**Repeat locations**")
        st.dataframe(pd.DataFrame(repeats).sort_values("Reports at this spot (180 days)", ascending=False), hide_index=True, use_container_width=True) \
            if repeats else st.caption("No spot has 3 or more reports of the same problem.")
    with b:
        st.markdown("**Bounce-backs: fixes residents rejected**")
        st.dataframe(pd.DataFrame({"Reference": bounce_df["issue_id"], "Problem": bounce_df["summary"], "Department": bounce_df["department"],
                                   "Now": bounce_df["stamp"]}), hide_index=True, use_container_width=True) if len(bounce_df) else st.caption("No rejected fixes.")


def complaints_table(df: pd.DataFrame):
    q_ = st.text_input("Search complaints", placeholder="Reference, problem, area or department", key="mon_search")
    view = st.pills("Show", ["Open", "Past due", "Silent 7+ days", "Escalated", "Verified fixed", "Closed unverified", "All"], default="Open", key="mon_status")
    d = df.copy()
    if q_:
        hay = (d["issue_id"] + " " + d["summary"] + " " + d["sector"] + " " + d["department"]).str.lower()
        d = d[hay.str.contains(q_.lower(), regex=False)]
    d = {"Open": d[~d["closed"]], "Past due": d[d["overdue"]], "Silent 7+ days": d[d["silent_days"] >= 7], "Escalated": d[d["escalation_tier"] > 0],
         "Verified fixed": d[d["status"] == "resolved"], "Closed unverified": d[d["status"] == "closed_unverified"]}.get(view or "All", d)
    d = d.sort_values(["overdue", "backers", "age_days"], ascending=False)
    base_url = (secret("APP_URL") or "https://awaaz-pk.streamlit.app").rstrip("/")
    table = pd.DataFrame({
        "Reference": d["issue_id"], "Status": d["stamp"], "Problem": d["summary"], "Department": d["department"], "Residents": d["backers"],
        "Days": d["age_days"], "Target used": d["target_used"], "Silent": d["silent_days"], "Due": d["expected_l"].dt.strftime("%d %b"),
        "Area": d["sector"], "Type": d["type"], "Source": d["simulated"].map({True: "Simulated", False: "Resident"}),
        "Open": base_url + "/track?ref=" + d["issue_id"]})
    st.caption(f"{len(table)} complaints. Select a row to see its full history.")
    ev = st.dataframe(table, hide_index=True, use_container_width=True, height=420, on_select="rerun", selection_mode="single-row", key="mon_table",
                      column_config={
                          "Target used": st.column_config.ProgressColumn("Target used", help="Share of the target time used. Over 100% is late.",
                                                                         format="%d%%", min_value=0, max_value=200),
                          "Days": st.column_config.NumberColumn("Days open", format="%.0f"),
                          "Silent": st.column_config.NumberColumn("Silent days", format="%.0f", help="Days since the department last acted."),
                          "Open": st.column_config.LinkColumn("Track", display_text="Open"),
                          "Problem": st.column_config.TextColumn(width="medium")})
    rows = ev.selection.rows if ev and getattr(ev, "selection", None) else []
    if rows:
        ref = table.iloc[rows[0]]["Reference"]
        i = db.get_issue(ref)
        with st.container(border=True):
            a, b = st.columns([3, 1])
            a.markdown(f"**{ui.esc(i['issue_id'])}** {ui.esc(i['summary'])}")
            b.markdown(f'<div style="text-align:right">{ui.stamp(i)}</div>', unsafe_allow_html=True)
            events = db.timeline(ref)
            st.markdown(ui.tracker(i, events), unsafe_allow_html=True)
            lis = "".join(f'<li><time>{e["created_at"]:%d %b}</time><div>{ui.esc(ui.EVENT_TEXT.get(e["type"], e["type"]))}</div></li>' for e in events[:8])
            st.markdown(f'<ul class="feed">{lis}</ul>', unsafe_allow_html=True)


def departments(df, ev, ps, gran):
    start = ps[0].start_time
    rows = []
    for dept, g in df.groupby("department"):
        closed = g[g["closed"] & (g["resolved_l"] >= start)]
        res = closed[closed["status"] == "resolved"]
        m = {"_closed": len(closed), "Fixed within target": (res["age_days"] <= res["target_days"]).mean() * 100 if len(res) else math.nan,
             "_verify": len(res) / len(closed) if len(closed) else math.nan,
             "Median days to fix": res["age_days"].median() if len(res) else math.nan,
             "_overdue_share": g[~g["closed"]]["overdue"].mean() if (~g["closed"]).any() else 0.0}
        gr, sc = grade(m, g["target_days"].iloc[0], min_closed=5)
        rows.append({"Grade": gr, "Department": dept, "Score": sc, "Open": int((~g["closed"]).sum()), "Past due": int(g["overdue"].sum()),
                     "Silent 7+ days": int((g["silent_days"] >= 7).sum()), "Verified fixes": len(res),
                     "Within target": None if math.isnan(m["Fixed within target"]) else round(m["Fixed within target"]),
                     "Median days to fix": None if math.isnan(m["Median days to fix"]) else round(m["Median days to fix"], 1),
                     "First response (h)": None if g["first_response_h"].isna().all() else round(g["first_response_h"].median()),
                     "Target days": int(g["target_days"].iloc[0])})
    out = pd.DataFrame(rows).sort_values(["Score", "Past due"], ascending=[False, True], na_position="last")
    st.markdown(f"**Overall since {start:%d %b %Y}** (the range shown under View by)")
    st.dataframe(out, hide_index=True, use_container_width=True, column_config={
        "Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
        "Within target": st.column_config.NumberColumn(format="%d%%")})
    open_ = df[~df["closed"]]
    if not open_.empty:
        agg = open_.groupby("department").agg(median_age=("age_days", "median"), target=("target_days", "first"), n=("issue_id", "count")).reset_index()
        agg["late"] = agg["median_age"] > agg["target"]
        base = alt.Chart(agg).encode(y=alt.Y("department:N", title=None, sort=alt.SortField("median_age", order="descending"), axis=alt.Axis(labelLimit=240)))
        bars = base.mark_bar(cornerRadiusEnd=3, height=16).encode(x=alt.X("median_age:Q", title="Typical days waiting (open complaints)"),
                                                                  color=alt.condition("datum.late", alt.value(C["red"]), alt.value(C["action"])),
                                                                  tooltip=[alt.Tooltip("department:N", title="Department"), alt.Tooltip("median_age:Q", title="Median days waiting", format=".1f"),
                                                                           alt.Tooltip("target:Q", title="Target days"), alt.Tooltip("n:Q", title="Open")])
        ticks = base.mark_tick(color=C["ink"], thickness=3, size=26).encode(x="target:Q")
        st.markdown("**Speed against target**")
        st.altair_chart((bars + ticks).properties(height=alt.Step(30)), use_container_width=True)
        st.caption("Bars: how long open complaints have typically waited. Dark tick: the department's target. Red: past target.")
        d = open_.assign(bucket=pd.cut(open_["age_days"], [-1, 3, 7, 14, 30, 10_000], labels=BUCKETS))
        agg2 = d.groupby(["department", "bucket"], observed=False).size().reset_index(name="Complaints")
        st.markdown("**How long open complaints have been waiting**")
        st.altair_chart(alt.Chart(agg2).mark_bar().encode(
            y=alt.Y("department:N", title=None, sort="-x", axis=alt.Axis(labelLimit=240)), x=alt.X("Complaints:Q", title="Open complaints"),
            color=alt.Color("bucket:N", sort=BUCKETS, scale=alt.Scale(domain=BUCKETS, range=[C["pale"], C["light"], C["action"], C["amber"], C["red"]]),
                            legend=alt.Legend(orient="top", title="Waiting for")),
            order=alt.Order("bucket:N"), tooltip=["department", alt.Tooltip("bucket:N", title="Waiting for"), "Complaints"]).properties(height=alt.Step(30)),
            use_container_width=True)


def status_map(df: pd.DataFrame):
    import folium
    from core.config import CENTER
    show_fixed = st.toggle("Also show verified fixes", key="mon_fixed")
    from folium.plugins import MarkerCluster
    m = ui.base_map(CENTER, 15)
    pts = df[(~df["closed"]) | (show_fixed & (df["status"] == "resolved"))].dropna(subset=["lat", "lng"])
    layer = MarkerCluster(options={"maxClusterRadius": 38, "disableClusteringAtZoom": 17}).add_to(m) if len(pts) > 40 else m
    for r in pts.itertuples():
        folium.CircleMarker([r.lat, r.lng], radius=5 + 2.5 * (r.backers ** 0.5), color="#FFFFFF", weight=1.5, fill=True,
                            fill_color=STATUS_COLOR.get(r.stamp_class, C["ink"]), fill_opacity=0.85,
                            tooltip=f"{r.issue_id} · {r.summary} · {r.stamp} · {int(r.backers)} residents").add_to(layer)
    st_folium(m, height=520, use_container_width=True, returned_objects=[], key=f"monmap-{show_fixed}")
    legend = [("Past due or escalated", C["red"]), ("Filed", C["ink"]), ("Acknowledged or work started", C["blue"])] + ([("Verified fixed", C["action"])] if show_fixed else [])
    st.markdown(" ".join(f'<span class="cat" style="margin-right:14px"><i style="background:{c}"></i>{n}</span>' for n, c in legend), unsafe_allow_html=True)


def report_html(df, ev, p, gran) -> str:
    m = metrics(df, ev, p)
    lab = label(p, gran)
    rows = ""
    for dept, g in df.groupby("department"):
        dm = metrics(g, ev, p)
        gr, sc = grade(dm, g["target_days"].iloc[0])
        wt = "–" if math.isnan(dm["Fixed within target"]) else f"{dm['Fixed within target']:.0f}%"
        md = "–" if math.isnan(dm["Median days to fix"]) else f"{dm['Median days to fix']:.1f}"
        rows += (f"<tr><td><b>{gr}</b></td><td>{_html.escape(dept)}</td><td>{dm['New complaints']}</td><td>{dm['Verified fixes']}</td>"
                 f"<td>{wt}</td><td>{md}</td><td>{dm['Backlog at period end']}</td><td>{dm['Bounce-backs']}</td></tr>")
    sim = int(df["simulated"].sum())
    fmt = lambda v, f: "–" if isinstance(v, float) and math.isnan(v) else f.format(v)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Awaaz report card: {lab}</title>
<style>body{{font-family:Arial,sans-serif;color:#14261B;max-width:900px;margin:32px auto;padding:0 16px}}h1{{color:#01411C;margin-bottom:4px}}
.k{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}}.k div{{border:1px solid #D3DED6;border-radius:6px;padding:10px}}
.k b{{display:block;font-size:22px;color:#01411C}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{border-bottom:1px solid #D3DED6;padding:7px;text-align:left}}
th{{color:#526157}}.n{{color:#526157;font-size:12px;margin-top:18px}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>Awaaz accountability report card</h1><div>Johar Town, Lahore · {lab} ({gran.lower()})</div>
<div class="k"><div><b>{m['New complaints']}</b>new complaints</div><div><b>{m['Verified fixes']}</b>verified fixes</div>
<div><b>{fmt(m['Fixed within target'], '{:.0f}%')}</b>fixed within target</div><div><b>{fmt(m['Median days to fix'], '{:.1f}')}</b>median days to fix</div>
<div><b>{m['Backlog at period end']}</b>backlog at period end</div><div><b>{m['Bounce-backs']}</b>bounce-backs</div>
<div><b>{fmt(m['First response (hours)'], '{:.0f} h')}</b>first response</div><div><b>{m['People-days waiting']:,}</b>people-days waiting</div></div>
<table><tr><th>Grade</th><th>Department</th><th>New</th><th>Verified fixes</th><th>Within target</th><th>Median days</th><th>Backlog</th><th>Bounce-backs</th></tr>{rows}</table>
<p class="n">A fix only counts when a resident confirms it. Grades need at least 3 closed complaints in the period. Generated by Awaaz on
{pd.Timestamp.now(tz=PKT):%d %b %Y %H:%M} PKT.{f' Includes {sim} simulated complaints (references starting AWZ-LHR-S) for demonstration.' if sim else ''}</p></body></html>"""


def simulated_admin():
    with st.expander("Demonstration data"):
        st.write("A new deployment has only days of history. You can add about 18 months of simulated complaints so the daily, weekly, "
                 "monthly and yearly views have something to show. They get references starting AWZ-LHR-S and are labelled “Simulated”.")
        pw = secret("DASHBOARD_PASSWORD")
        entered = st.text_input("Department password", type="password", key="sim_pw")
        if not pw or entered != pw:
            st.caption("Enter the department password to change demonstration data.")
            return
        a, b = st.columns(2)
        if a.button("Add simulated history", use_container_width=True, disabled=db.simulated_count() > 0):
            with st.spinner("Adding 18 months of simulated complaints…"):
                n = simulate.add_history()
            load.clear(); st.toast(f"Added {n} simulated complaints."); st.rerun()
        if b.button("Remove simulated history", use_container_width=True, disabled=db.simulated_count() == 0):
            n = simulate.remove_history()
            load.clear(); st.toast(f"Removed {n} simulated complaints."); st.rerun()


def page():
    db.sweep_unverified()
    st.title("Live monitor")
    st.markdown('<p class="sub">Every complaint in Johar Town and how each department is handling it, day by day, week by week, month by month '
                'and year by year. Open to residents, journalists and the departments themselves. A fix only counts once a resident confirms it.</p>',
                unsafe_allow_html=True)
    df_all, _ = load()
    if df_all.empty:
        st.info("No complaints yet.")
        simulated_admin()
        return
    if sim := int(df_all["simulated"].sum()):
        st.info(f"Includes {sim} simulated complaints (references starting AWZ-LHR-S) so the trends have history. "
                "They're marked “Simulated” in the table and can be removed under Demonstration data.", icon="ℹ️")
    f0, f1, f2, f3 = st.columns([1.6, 1.3, 1.3, 0.6])
    gran = f0.segmented_control("View by", list(GRAN), default="Monthly", key="mon_gran") or "Monthly"
    depts = f1.multiselect("Departments", sorted(df_all["department"].unique()), placeholder="All departments")
    cats = f2.multiselect("Problem types", sorted(df_all["type"].dropna().unique()), placeholder="All types")
    with f3:
        st.write("")
        live = st.toggle("Live", help="Refresh the figures every 30 seconds.")

    @st.fragment(run_every=30 if live else None)
    def body():
        if live:
            load.clear()
        df, ev = load()
        if depts:
            df = df[df["department"].isin(depts)]
        if cats:
            df = df[df["type"].isin(cats)]
        if not ev.empty:
            ev = ev[ev["issue_id"].isin(df["issue_id"])]
        if df.empty:
            st.info("Nothing matches these filters.")
            return
        ps = periods(gran, df)
        kpi_tiles(df, ev, ps, gran)
        if live:
            st.caption(f"Live. Updated {pd.Timestamp.now(tz=PKT):%H:%M:%S} Pakistan time.")
        tabs = st.tabs(["Trends", "Report cards", "Early warnings", "Every complaint", "Departments", "Map", "Reports & data"])
        with tabs[0]:
            trends(df, ev, ps, gran)
        with tabs[1]:
            report_cards(df, ev, ps, gran)
        with tabs[2]:
            early_warnings(df, ev)
        with tabs[3]:
            complaints_table(df)
        with tabs[4]:
            departments(df, ev, ps, gran)
        with tabs[5]:
            status_map(df)
        with tabs[6]:
            labels = [label(p, gran) for p in ps][::-1]
            pick = st.selectbox(f"Report card for", labels, key="rep_period")
            p = next(x for x in ps if label(x, gran) == pick)
            st.download_button(f"Download printable report card ({pick})", report_html(df, ev, p, gran).encode("utf-8"),
                               file_name=f"awaaz-report-{pick.replace(' ', '-').lower()}.html", mime="text/html", type="primary")
            st.caption("Opens in any browser; use Print to save it as a PDF to share with councilors or the press.")
            export = df[["issue_id", "summary", "category", "sector", "department", "status", "escalation_tier", "backers", "first_reported_at",
                         "expected_by", "resolved_at", "age_days", "overdue", "silent_days", "first_response_h", "lat", "lng", "simulated"]].rename(columns={"backers": "residents"})
            st.download_button("Download all complaints (CSV)", export.to_csv(index=False).encode("utf-8"), file_name="awaaz-complaints.csv", mime="text/csv")
            st.caption("Open data: no names or phone numbers; locations rounded to about 100 m.")

    body()
    simulated_admin()
