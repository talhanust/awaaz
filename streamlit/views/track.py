import re

import streamlit as st

from core import db, lifecycle, ui


def actions(i: dict, citizen: str | None):
    st.subheader("Your response")
    if lifecycle.is_closed(i):
        st.success("This issue is closed." if i["status"] == "resolved" else "Closed without a resident confirming the fix.")
        return
    if not citizen:
        st.caption("Enter the mobile number you reported with to respond to check-ins and approve escalations.")
        return
    if not db.is_reporter(i["issue_id"], citizen):
        st.caption("Only residents who reported this issue can respond. To join it, report the same problem at the same spot; "
                   "Awaaz will offer to add your voice.")
        return
    d = i["pending_escalation"]
    if d:
        titles = {1: "Tier 1 · Formal re-complaint", 2: "Tier 2 · Copy to local representative", 3: "Tier 3 · Public post you can share"}
        st.warning(f"**{titles[d['tier']]}** is drafted and waiting for your approval. Nothing is sent until you approve.", icon="✋")
        if d.get("short_post"):
            st.code(d["short_post"], language=None, wrap_lines=True)
        with st.expander("Read the full draft", expanded=not d.get("short_post")):
            if not d["body"].lstrip().startswith("To:"):
                st.write(f"**To:** {', '.join(d.get('recipients') or [])}")
            if d.get("missing_contacts"):
                st.caption("Missing contact: " + ", ".join(d["missing_contacts"]))
            st.text(d["body"])
        if d.get("citizen_tip"):
            ui.local_text(d["citizen_tip"])
        a, b = st.columns(2)
        if a.button("Copy post is ready — mark as shared" if d["tier"] == 3 else "Approve and send", type="primary", use_container_width=True):
            how = lifecycle.approve(i, citizen)
            st.session_state.notice = {"email": "Sent to the department by email.", "handed_to_citizen":
                                       "Recorded. Awaaz never posts for you; share the post wherever you choose.",
                                       "assisted": "Approved. This department has no email on file, so submit the draft above in person or by post."}[how]
            st.rerun()
        if b.button("Not now", use_container_width=True):
            lifecycle.decline(i, citizen); st.rerun()
        return
    if i["verification_requested_at"]:
        st.info("Someone says this is fixed. Can you confirm?", icon="🔍")
        a, b = st.columns(2)
        if a.button("Yes, it's fixed", type="primary", use_container_width=True):
            lifecycle.confirm(i, citizen, True); st.rerun()
        if b.button("No, it's still there", use_container_width=True):
            lifecycle.confirm(i, citizen, False); st.rerun()
        return
    if lifecycle.checkin_due(i):
        st.info(f"**Is it fixed yet?** {i['issue_id']} was due by {i['expected_by']:%d %b}.", icon="⏰")
        a, b = st.columns(2)
        if a.button("Yes, it's fixed", type="primary", use_container_width=True):
            res = lifecycle.claim_fixed(i, citizen)
            st.session_state.notice = "Resolved. Thank you for raising your voice." if res == "resolved" else "Thanks. Another resident will be asked to confirm."
            st.rerun()
        if b.button("No, still not fixed", use_container_width=True):
            with st.spinner("Drafting the next escalation…"):
                d = lifecycle.not_fixed(i, citizen, st.session_state.get("lang", "ur-Latn"))
            if d is None:
                st.session_state.notice = "All three escalation steps are on record. Awaaz keeps tracking it and includes it in Neighborhood Reports."
            st.rerun()
        return
    st.write(f"Awaaz will ask you on **{i['expected_by']:%d %b %Y}** whether it's fixed.")
    if st.button("It's already fixed"):
        res = lifecycle.claim_fixed(i, citizen)
        st.session_state.notice = "Resolved. Thank you for raising your voice." if res == "resolved" else "Thanks. Another resident will be asked to confirm."
        st.rerun()


def page():
    ui.css()
    st.title("Track an issue")
    ui.show_warnings()
    c1, c2 = st.columns([1, 1])
    ref = c1.text_input("Reference number", value=st.session_state.get("track_ref") or st.session_state.get("last_ref") or "", placeholder="AWZ-LHR-01301")
    phone = c2.text_input("Your mobile number (to respond)", value=st.session_state.get("phone", ""), placeholder="03xx xxxxxxx")
    if phone:
        st.session_state.phone = phone
    if not ref.strip():
        st.info("Enter a reference number, e.g. **AWZ-LHR-00231**, a pothole that 12 residents reported.")
        return
    i = db.get_issue(ref)
    if not i:
        st.error("No issue with that reference number.")
        return
    st.session_state.track_ref = i["issue_id"]
    if n := st.session_state.pop("notice", None):
        st.success(n)
    citizen = db.citizen_hash(re.sub(r"[^\d+]", "", phone)) if len(re.sub(r"\D", "", phone)) >= 10 else None
    if citizen and not db.one("select 1 from citizens where citizen_hash = %s", (citizen,)):
        row = db.one("select citizen_hash from citizens where phone = %s", (re.sub(r"[^\d+]", "", phone),))
        citizen = row["citizen_hash"] if row else None
    auth = db.authority(i["authority_id"])

    st.markdown(f'<div class="ref">{i["issue_id"]}</div>{ui.pill(i)}', unsafe_allow_html=True)
    st.markdown(f"#### {i['summary']}")
    st.caption(f"{i['category'].title()} · {i['sector']} · {auth['name']} · {auth['filing_channel'].replace('_', ' ')}")
    days = max(1, (db.now() - i["first_reported_at"]).days)
    late = (db.now() - i["expected_by"]).days
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Residents", i["report_count"])
    m2.metric("Days open", days)
    m3.metric("Escalation tier", i["escalation_tier"])
    m4.metric("Due", f"{i['expected_by']:%d %b}", f"{late} days overdue" if late > 0 and not lifecycle.is_closed(i) else None, delta_color="inverse")

    stage = lifecycle.STAGE.get(i["status"], 0)
    cols = st.columns(4)
    for k, (col, name) in enumerate(zip(cols, ["Filed", "Acknowledged", "In progress", "Fixed & verified"])):
        col.markdown(("✅ **" + name + "**") if k <= stage else ("⚪ " + name))

    rb = i.get("routing_basis")
    if rb:
        with st.container(border=True):
            st.markdown(f"**Why {auth['name']}?** {rb.get('explanation', '')}")
            if rb.get("sources"):
                st.caption("Based on: " + " · ".join(f"{s['title']} › {s.get('heading', '')}{'' if s.get('verified') else ' (unverified demo guidance)'}" for s in rb["sources"]))
    actions(i, citizen)
    if i["formatted_complaint"]:
        with st.expander("The filed complaint"):
            st.text(i["formatted_complaint"])
            st.download_button("Download (.txt)", i["formatted_complaint"], file_name=f"{i['issue_id']}.txt")
    st.subheader("Timeline")
    for e in db.timeline(i["issue_id"]):
        extra = f" (Tier {e['payload'].get('tier')})" if e["payload"].get("tier") else ""
        st.markdown(f"`{e['created_at']:%d %b %Y, %H:%M}` {ui.EVENT_TEXT.get(e['type'], e['type'])}{extra}")
