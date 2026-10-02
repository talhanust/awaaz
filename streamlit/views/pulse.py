import streamlit as st

from core import db, ui


def page():
    db.sweep_unverified()
    s = db.pulse_stats()
    fixed = s["fixed_30d"]
    st.markdown(
        f'<p class="hero"><b>{s["waiting"]}</b> {"resident is" if s["waiting"] == 1 else "residents are"} waiting on <b>{s["open"]}</b> '
        f'open {"problem" if s["open"] == 1 else "problems"} in Johar Town, Lahore. '
        f'<b>{s["overdue"]}</b> {"is past its" if s["overdue"] == 1 else "are past their"} due date, and <b class="ok">{fixed}</b> '
        f'{"was" if fixed == 1 else "were"} fixed and verified by residents this month.</p>',
        unsafe_allow_html=True)
    if sim := db.simulated_count():
        st.caption(f"These figures include {sim} simulated complaints added for demonstration (references starting AWZ-LHR-S). "
                   "They're labelled on the Live monitor and can be removed there.")
    st.markdown('<p class="sub">Report a problem once. Awaaz files it with the right department, joins you with neighbors who '
                'reported the same thing, and keeps asking until a resident confirms it\'s fixed.</p>', unsafe_allow_html=True)
    a, b, _ = st.columns([1.1, 1, 2.2])
    if a.button("Report a problem", type="primary", use_container_width=True):
        st.switch_page(st.session_state.pages["report"])
    if b.button("Track my report", use_container_width=True):
        st.switch_page(st.session_state.pages["track"])

    st.write("")
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.subheader("Most-backed problems")
        st.caption("Tap “I see this too” if you've seen it. Every resident behind an issue moves it up the department's queue.")
        phone = st.session_state.get("phone", "")
        for i in db.most_backed(3):
            with st.container(border=True):
                st.markdown(ui.issue_row(i), unsafe_allow_html=True)
                c1, c2 = st.columns([1, 1])
                if c1.button("I see this too", key=f"see-{i['issue_id']}", use_container_width=True):
                    st.session_state.see_target = i["issue_id"]
                if c2.button("Open", key=f"open-{i['issue_id']}", use_container_width=True):
                    st.session_state.track_ref = i["issue_id"]
                    st.switch_page(st.session_state.pages["track"])
                if st.session_state.get("see_target") == i["issue_id"]:
                    num = st.text_input("Your mobile number", value=phone, key=f"ph-{i['issue_id']}", placeholder="03xx xxxxxxx",
                                        help="Used only so each person counts once. Never shown.")
                    if st.button("Confirm", key=f"conf-{i['issue_id']}", type="primary") and db.normalize_phone(num):
                        st.session_state.phone = num
                        added = db.see_too(i["issue_id"], db.get_or_create_citizen(num))
                        st.session_state.see_target = None
                        st.toast("Thanks. You're now backing this issue." if added else "You're already backing this issue.")
                        st.rerun()
        if st.button("See every complaint and department grade on the Live monitor", type="tertiary"):
            st.switch_page(st.session_state.pages["monitor"])
        st.subheader("How departments are responding")
        rows = db.response_board()
        if rows:
            st.dataframe([{"Department": r["name"], "Open": r["open"], "Overdue": r["overdue"], "Escalated": r["escalated"],
                           "Avg days open": r["avg_days_open"], "Verified fixes": r["fixed"]} for r in rows],
                         hide_index=True, use_container_width=True)
            st.caption("Ordered by overdue issues. Updates live as residents report, escalate and verify fixes.")
    with right:
        st.subheader("Happening now")
        items = db.activity(14)
        if not items:
            st.caption("No activity yet. Be the first to report a problem.")
        else:
            lis = "".join(
                f'<li><time>{ui.rel_time(e["created_at"])}</time><div><b>{ui.esc(ui.FEED_TEXT.get(e["type"], ui.EVENT_TEXT.get(e["type"], e["type"])))}</b> '
                f'{ui.esc(e["summary"])} <span style="color:#5B6475">({ui.esc(e["issue_id"])})</span></div></li>'
                for e in items if e["type"] in ui.FEED_TEXT)
            st.markdown(f'<ul class="feed">{lis}</ul>', unsafe_allow_html=True)
