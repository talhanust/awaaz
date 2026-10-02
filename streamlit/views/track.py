import re

import streamlit as st

from core import db, lifecycle, ui


def actions(i: dict, citizen: str | None):
    st.subheader("Your part")
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


def _citizen_for(phone: str) -> str | None:
    return db.find_citizen(phone) if phone else None


def _open(ref: str):
    st.session_state.track_ref = ref
    st.rerun()


def empty_state(phone: str):
    citizen = _citizen_for(phone)
    mine = db.my_reports(citizen) if citizen else []
    if mine:
        st.subheader("Your reports")
        for i in mine:
            with st.container(border=True):
                st.markdown(ui.issue_row(i), unsafe_allow_html=True)
                if st.button("Open", key=f"mine-{i['issue_id']}"):
                    _open(i["issue_id"])
    elif phone:
        st.caption("No reports found for this number yet.")
    st.subheader("Recently reported in Johar Town")
    for i in db.recent_issues(6):
        with st.container(border=True):
            st.markdown(ui.issue_row(i), unsafe_allow_html=True)
            if st.button("Open", key=f"recent-{i['issue_id']}"):
                _open(i["issue_id"])


def page():
    db.sweep_unverified()
    st.title("Track an issue")
    ui.show_warnings()
    if ref_param := st.query_params.get("ref"):  # opened from a receipt QR code or shared link
        st.session_state.track_ref = ref_param
        st.query_params.clear()
    c1, c2 = st.columns([1, 1])
    ref = c1.text_input("Reference number", value=st.session_state.get("track_ref") or "", placeholder="e.g. AWZ-LHR-00231")
    phone = c2.text_input("Your mobile number", value=st.session_state.get("phone", ""), placeholder="03xx xxxxxxx",
                          help="Shows your reports, and lets you answer check-ins and approve escalations.")
    if phone:
        st.session_state.phone = phone
    if not ref.strip():
        empty_state(phone)
        return
    i = db.get_issue(ref)
    if not i:
        st.error(f"No issue has the reference {ref.strip()}. Check the number on your receipt, or pick one below.")
        empty_state(phone)
        return
    st.session_state.track_ref = i["issue_id"]
    if n := st.session_state.pop("notice", None):
        st.success(n)
    citizen = _citizen_for(phone)
    auth = db.authority(i["authority_id"])
    events = db.timeline(i["issue_id"])

    head, stamp_col = st.columns([3, 1])
    with head:
        st.markdown(f'<div class="ref" style="font-size:.95rem">{ui.esc(i["issue_id"])}</div>', unsafe_allow_html=True)
        st.markdown(f"## {i['summary']}")
        st.markdown(f'<div class="irow" style="border:0;padding:0"><div class="m">{ui.cat_chip(i["category"])}<span>{ui.esc(i["sector"])}</span>'
                    f'<span>{ui.esc(auth["name"])}</span></div></div>', unsafe_allow_html=True)
    stamp_col.markdown(f'<div style="padding-top:28px;text-align:right">{ui.stamp(i, big=True, land=True)}</div>', unsafe_allow_html=True)

    st.markdown(ui.tracker(i, events), unsafe_allow_html=True)
    m1, m2, m3 = st.columns([1, 1, 2])
    m1.metric("Residents backing it", i["report_count"] + (i["confirmations"] or 0))
    m2.metric("Escalation tier", f"{i['escalation_tier']} of 3")
    with m3:
        if not lifecycle.is_closed(i):
            st.markdown("**Due date**")
            st.markdown(ui.due_bar(i), unsafe_allow_html=True)
            if typical := db.typical_fix_days(i["authority_id"]):
                st.caption(f"{auth['name']} usually fixes problems in about {typical[0]:.0f} days (from {typical[1]} verified fixes).")
    if not lifecycle.is_closed(i) and not (citizen and db.is_reporter(i["issue_id"], citizen)):
        if st.button("I see this too", help="Back this issue without filing a new report"):
            if not citizen and not db.normalize_phone(phone):
                st.warning("Add your mobile number above first (like 0300 1234567), so each person counts once.")
            else:
                added = db.see_too(i["issue_id"], citizen or db.get_or_create_citizen(phone))
                st.toast("Thanks. You're now backing this issue." if added else "You're already backing this issue.")
                st.rerun()

    rb = i.get("routing_basis")
    if rb and rb.get("explanation"):
        with st.container(border=True):
            st.markdown(f"**Why {auth['name']}?** {rb['explanation']}")
            if rb.get("sources"):
                st.caption("Based on: " + "; ".join(f"{s['title']} ({s.get('heading', '')})" + ("" if s.get("verified") else ", unverified demo guidance")
                                                    for s in rb["sources"]))
    actions(i, citizen)

    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.subheader("Timeline")
        lis = "".join(f'<li><time>{e["created_at"]:%d %b}</time><div>{ui.esc(ui.EVENT_TEXT.get(e["type"], e["type"]))}'
                      f'{" (tier " + str(e["payload"]["tier"]) + ")" if e["payload"].get("tier") else ""}</div></li>' for e in events)
        st.markdown(f'<ul class="feed">{lis}</ul>', unsafe_allow_html=True)
    with right:
        st.subheader("Share")
        st.html(ui.receipt(i["issue_id"], f"{i['report_count'] + (i['confirmations'] or 0)} residents backing it, {auth['name']}"))
        if i["formatted_complaint"]:
            with st.expander("The filed complaint"):
                st.text(i["formatted_complaint"])
                st.download_button("Download (.txt)", i["formatted_complaint"], file_name=f"{i['issue_id']}.txt")
