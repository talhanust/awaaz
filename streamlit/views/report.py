import re

import streamlit as st
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

from core import agents, db, kb, llm, services, ui
from core.config import CENTER

PRESETS = {  # places in Johar Town used by the seeded data, for quick testing
    "J Block market, main road": (31.47008, 74.27280),
    "K Block park gate": (31.47232, 74.27890),
    "L Block, street 14": (31.46866, 74.26700),
    "H Block, street 6": (31.47145, 74.27260),
    "G Block, street 2": (31.47170, 74.26680),
}
EXAMPLES = {
    "Pothole (Roman Urdu)": ("J Block market ke saamne main road pe bohat bara gaddha hai, kal raat ek motorcycle wala gir gaya", "J Block market, main road"),
    "Sparking wires (English)": ("Wires on the electricity pole near the park gate are sparking at night", "K Block park gate"),
    "Street lights (Roman Urdu)": ("Street 6 mein street lights 2 hafte se band hain, raat ko bohat andhera hota hai", "H Block, street 6"),
    "Sewage (Urdu)": ("گلی نمبر 14 میں گٹر ابل رہا ہے، ہر طرف گندا پانی ہے", "L Block, street 14"),
}


def _trace(flow, agent, text, mode=None):
    tag = " · fallback rules" if mode == "rules" else f" · {mode}" if mode else ""
    flow["trace"].append(f"**{agent}**{tag}: {text}")


def location_picker():
    st.subheader("Where is it?")
    loc = st.session_state.get("loc")
    tab_map, tab_gps, tab_place = st.tabs(["Pick on map", "Use my current location", "Choose a place"])
    with tab_map:
        st.caption("Click the spot on the map. Circles are problems already reported (bigger = more residents).")
        m = ui.issues_map(db.open_issues_for_map(), (loc["lat"], loc["lng"]) if loc else None)
        out = st_folium(m, height=380, use_container_width=True, returned_objects=["last_clicked"], key="pickmap")
        click = (out or {}).get("last_clicked")
        if click and (not loc or abs(click["lat"] - loc["lat"]) > 1e-7 or abs(click["lng"] - loc["lng"]) > 1e-7):
            st.session_state.loc = {"lat": click["lat"], "lng": click["lng"], "source": "map"}
            st.rerun()
    with tab_gps:
        if st.button("Share my current location"):
            st.session_state.want_gps = True
        if st.session_state.get("want_gps"):
            g = get_geolocation()
            if g and g.get("coords"):
                c = g["coords"]
                st.session_state.loc = {"lat": c["latitude"], "lng": c["longitude"], "source": f"GPS (±{round(c.get('accuracy', 0))} m)"}
                st.session_state.want_gps = False
                st.rerun()
            elif g and g.get("error"):
                st.warning("Your browser didn't share a location. Pick the spot on the map instead.")
                st.session_state.want_gps = False
            else:
                st.caption("Waiting for your browser… allow location access if it asks.")
    with tab_place:
        name = st.selectbox("Places in Johar Town, Lahore", ["—"] + list(PRESETS))
        if name != "—" and st.button("Use this place"):
            lat, lng = PRESETS[name]
            st.session_state.loc = {"lat": lat, "lng": lng, "source": name}
            st.rerun()
    if loc:
        st.success(f"Location set ({loc['source']}): {loc['lat']:.5f}, {loc['lng']:.5f}", icon="📍")
    return st.session_state.get("loc")


def run_pipeline(phone: str, text: str, photo, audio, loc: dict, prior: dict | None = None):
    flow = {"stage": "running", "trace": [], "phone": phone, "loc": loc}
    with st.status("Awaaz agents are handling your report…", expanded=True) as status:
        citizen = db.get_or_create_citizen(phone)
        if db.actions_today(citizen) >= 5:
            st.session_state.setdefault("warnings", []).append("This number has filed 5 reports in the last 24 hours. Please try again tomorrow.")
            return
        input_type = "text"
        if audio is not None:
            tr = services.transcribe(audio.getvalue())
            if not tr:
                st.session_state.setdefault("warnings", []).append("I couldn't understand the voice note. Please type one line about the problem.")
                return
            text = f"{text} {tr}".strip(); input_type = "voice"
            _trace(flow, "Speech-to-text", f"“{tr}”"); st.write(flow["trace"][-1])
        photo_desc = None
        if photo is not None and llm.vision_enabled():
            photo_desc = llm.describe_image(photo.getvalue(), photo.type)
            input_type = "photo" if not text else input_type
            _trace(flow, "Vision", photo_desc, llm.label()); st.write(flow["trace"][-1])
        answer = text
        if prior:
            text = f"{prior['text']}. {text}"
        place = services.reverse_geocode(round(loc["lat"], 5), round(loc["lng"], 5))
        if place["city"] and "lahore" not in place["city"].lower():
            st.session_state.setdefault("warnings", []).append(
                f"That location looks like {place['city']}. Awaaz is piloting in Lahore; please pick a location in Lahore.")
            return
        if place["city"] is None and loc["source"] in PRESETS:  # map lookup unavailable: use the chosen place's name
            place = {"city": "Lahore", "sector": "Johar Town " + loc["source"].split(",")[0], "landmark": loc["source"]}
        area = place["landmark"] if place["landmark"] == place["sector"] else f"{place['landmark']}, {place['sector']}"
        area += ", Lahore"
        _trace(flow, "Location", area); st.write(flow["trace"][-1])

        c, mode = agents.classify(text, photo_desc, area)
        _trace(flow, "1 · Classifier", f"{c['category']} · {c['severity']} · language {c['language']} · confidence {c['confidence']:.2f}", mode)
        st.write(flow["trace"][-1])
        if agents.needs_clarification(c) and not (prior and prior.get("asked_by") == "classifier"):
            flow.update(stage="clarify", question=c.get("needs_clarification") or "Can you tell me a little more about the problem?",
                        text=text, asked_by="classifier", citizen=citizen)
            status.update(label="One question before filing", state="complete")
            st.session_state.flow = flow
            return
        if c["authority_id"] == "unknown":
            c["authority_id"] = {"roads": "MCL-ROADS", "water": "WASA-LHR", "sanitation": "WASA-LHR", "electrical": "LESCO",
                                 "gas": "SNGPL", "encroachment": "MCL-ENC"}.get(c["category"], "MCL-ROADS")

        routing, rmode, passages = agents.route(c, text, area)
        src = "; ".join(f"{s['title']} › {s['heading']}" for s in routing["source_meta"]) or "no specific rule"
        name = (db.authority(routing["authority_id"]) or {}).get("name", routing["authority_id"])
        _trace(flow, "1b · Jurisdiction Router (RAG)", f"{len(passages)} passages retrieved → **{name}**"
               f"{' (changed from ' + db.authority(c['authority_id'])['name'] + ')' if routing['changed'] else ''}. Based on: {src}", rmode)
        st.write(flow["trace"][-1])
        if (routing.get("needs_clarification") and prior and prior.get("asked_by") == "router"
                and "society" in routing["needs_clarification"].lower() and not re.search(r"\bcity|shehr|sheher|شہر|\bno\b|nahi|نہیں", answer, re.I)):
            # the resident confirmed it's inside a private society: a city department won't act, so don't file there
            st.session_state.setdefault("warnings", []).append(
                "Inside private housing societies, the society administration maintains roads, streetlights, sewerage and waste, so a city "
                "department won't act on this. Please contact your society office. If it's actually a city area, report it again and answer "
                "“city area”. Gas and electricity supply problems are different: SNGPL and LESCO handle those everywhere.")
            status.update(label="Not filed: this is a housing-society matter", state="complete")
            st.session_state.flow = None
            return
        if routing.get("needs_clarification") and not (prior and prior.get("asked_by") == "router"):
            flow.update(stage="clarify", question=routing["needs_clarification"], text=text, asked_by="router", citizen=citizen)
            status.update(label="One question before filing", state="complete")
            st.session_state.flow = flow
            return
        c["authority_id"] = routing["authority_id"]

        emb = kb.embed_one(f"{c['category']}: {c['summary_en']}", "document")
        m, mmode, cands = agents.match(c, loc["lat"], loc["lng"], emb)
        if m["decision"] == "match":
            _trace(flow, "2 · Matcher", f"same problem as **{m['issue']['issue_id']}** ({m['issue']['report_count']} residents, "
                   f"{round(m['issue']['distance_m'])} m away). {m['reason']}", mmode)
        else:
            _trace(flow, "2 · Matcher", f"{len(cands)} nearby open issues checked; this is a new problem.", mmode)
        st.write(flow["trace"][-1])
        flow.update(citizen=citizen, c=c, routing=routing, emb=emb, place=place, text=text, input_type=input_type)
        if m["decision"] == "match":
            flow.update(stage="match", match=m["issue"])
            status.update(label="Neighbors already reported this", state="complete")
        else:
            file_new(flow, status)
    st.session_state.flow = flow


def queue_rank(issue_id: str) -> tuple[int | None, int]:
    rows = db.queue()
    ids = [r["issue_id"] for r in rows]
    return (ids.index(issue_id) + 1 if issue_id in ids else None), len(ids)


def file_new(flow: dict, status=None):
    c, loc, place, routing = flow["c"], flow["loc"], flow["place"], flow["routing"]
    issue_id = db.create_issue(sector=place["sector"], category=c["category"], severity=c["severity"], authority_id=c["authority_id"],
                               summary=c["summary_en"], lat=loc["lat"], lng=loc["lng"], citizen=flow["citizen"], language=c["language"],
                               input_type=flow["input_type"], raw_text=flow["text"])
    db.set_embedding(issue_id, flow.get("emb"))
    issue = db.get_issue(issue_id)
    auth = db.authority(c["authority_id"])
    d, dmode = agents.draft(issue, auth, place["landmark"], c["language"])
    subject = d.get("email_subject") or f"Complaint {issue_id}"
    sent = auth["filing_channel"] == "email" and "@" in (auth["filing_target"] or "") and services.send_email([auth["filing_target"]], subject, d["formatted_complaint"])
    db.update_issue(issue_id, formatted_complaint=d["formatted_complaint"], filing_channel=d.get("filing_channel") or auth["filing_channel"],
                    routing_basis={"authority_id": routing["authority_id"], "changed": routing["changed"], "explanation": routing["explanation"],
                                   "explanation_local": routing.get("explanation_local", ""), "sources": routing["source_meta"]})
    db.add_event(issue_id, "drafted", "system", {"mode": dmode, "missing_fields": d.get("missing_fields", [])})
    db.add_event(issue_id, "filed_email" if sent else "filed_assisted", "system", {"channel": auth["filing_channel"]})
    _trace(flow, "3 · Drafter & Filer", f"{auth['filing_channel'].replace('_', ' ')} for {auth['name']} · "
           f"{'sent by email' if sent else 'ready for the resident to submit'}", dmode)
    if status:
        st.write(flow["trace"][-1])
        status.update(label=f"Filed as {issue_id}", state="complete")
    rank, total = queue_rank(issue_id)
    flow.update(stage="done", issue_id=issue_id, confirmation=d["citizen_confirmation"], doc=d["formatted_complaint"], sent=sent,
                auth=auth, rank=rank, total=total, new=True)
    st.session_state.last_ref = issue_id


def add_voice(flow: dict):
    c, loc, i = flow["c"], flow["loc"], flow["match"]
    before, _ = queue_rank(i["issue_id"])
    n = db.add_voice(i["issue_id"], flow["citizen"], c["language"], flow["input_type"], flow["text"], loc["lat"], loc["lng"])
    after, total = queue_rank(i["issue_id"])
    issue = db.get_issue(i["issue_id"])
    flow.update(stage="done", issue_id=i["issue_id"], new=False, already=(n == -1), residents=issue["report_count"], before=before,
                rank=after, total=total, auth=db.authority(issue["authority_id"]))
    _trace(flow, "2 · Matcher", "you were already a reporter of this issue" if n == -1 else f"voice added: now {issue['report_count']} residents")
    st.session_state.last_ref = i["issue_id"]


def show_trace(flow):
    with st.expander("How the agents handled this", expanded=False):
        for line in flow["trace"]:
            st.markdown(line)


CATEGORIES = {  # quick-pick chips: label shown → hint sent to the classifier
    "Pothole or road": "Road problem", "Sewage or drain": "Sewage or blocked drain", "Garbage": "Garbage not collected",
    "No water": "No tap water", "Street lights": "Street lights not working", "Power or wires": "Electricity problem",
    "Gas smell": "Gas smell", "Encroachment": "Encroachment",
}


def join_existing(issue: dict, phone: str, loc: dict):
    """Fast path from 'Already reported near here': add the resident's voice without running the AI agents."""
    citizen = db.get_or_create_citizen(phone)
    if db.actions_today(citizen) >= 5:
        st.session_state.setdefault("warnings", []).append("This number has reached today's limit of 5 reports. Please try again tomorrow.")
        return
    before, _ = queue_rank(issue["issue_id"])
    n = db.add_voice(issue["issue_id"], citizen, st.session_state.get("lang", "ur-Latn"), "text", "Joined from the map", loc["lat"], loc["lng"])
    after, total = queue_rank(issue["issue_id"])
    fresh = db.get_issue(issue["issue_id"])
    st.session_state.flow = {"stage": "done", "issue_id": issue["issue_id"], "new": False, "already": n == -1, "residents": fresh["report_count"],
                             "before": before, "rank": after, "total": total, "auth": db.authority(fresh["authority_id"]),
                             "trace": ["**2 · Matcher** · you picked an existing report on the map, so no new complaint was needed."], "phone": phone}
    st.session_state.last_ref = issue["issue_id"]


def nearby_panel(loc: dict):
    near = db.nearby_open(loc["lat"], loc["lng"], 150)
    if not near:
        st.caption("No open reports within 150 m of this spot. Yours will be the first.")
        return
    with st.container(border=True):
        st.markdown(f"**Already reported near here** ({len(near)} within 150 m). If one of these is your problem, join it instead of filing again.")
        for i in near:
            full = db.get_issue(i["issue_id"])
            st.markdown(ui.issue_row(full), unsafe_allow_html=True)
            st.caption(f"{int(i['distance_m'])} m from your pin")
            if st.button("This is my problem, add my voice", key=f"join-{i['issue_id']}"):
                st.session_state.join_target = i["issue_id"]
            if st.session_state.get("join_target") == i["issue_id"]:
                ph = st.text_input("Your mobile number", value=st.session_state.get("phone", ""), key=f"jph-{i['issue_id']}",
                                   placeholder="03xx xxxxxxx", help="So you can respond to check-ins. Never shown.")
                if st.button("Add my voice", key=f"jgo-{i['issue_id']}", type="primary") and db.normalize_phone(ph):
                    st.session_state.phone = ph
                    join_existing(full, ph, loc)
                    st.session_state.join_target = None
                    st.rerun()


def render_flow(flow: dict):
    if flow["stage"] == "clarify":
        st.markdown("#### One quick question before filing")
        ui.local_text(flow["question"])
        with st.form("clarify"):
            answer = st.text_input("Your answer")
            go = st.form_submit_button("Continue", type="primary")
        if go and answer.strip():
            prior = {"text": flow["text"], "asked_by": flow["asked_by"]}
            st.session_state.flow = None
            run_pipeline(flow["phone"], answer.strip(), None, None, flow["loc"], prior)
            st.rerun()
        show_trace(flow)
    elif flow["stage"] == "match":
        i = flow["match"]
        issue = db.get_issue(i["issue_id"])
        st.markdown(f"#### {i['report_count']} neighbors already reported this")
        st.caption("Joining keeps it as one strong complaint instead of several weak ones, and moves it up the department's queue.")
        with st.container(border=True):
            st.markdown(ui.issue_row(issue), unsafe_allow_html=True)
        a, b = st.columns(2)
        if a.button("Add my voice to it", type="primary", use_container_width=True):
            add_voice(flow); st.rerun()
        if b.button("It's a different problem", use_container_width=True):
            with st.status("Filing a new report…", expanded=False) as s:
                file_new(flow, s)
            st.rerun()
        show_trace(flow)
    elif flow["stage"] == "done":
        auth = flow["auth"]
        issue = db.get_issue(flow["issue_id"])
        if flow["new"]:
            st.markdown(f'<div style="margin:6px 0 14px">{ui.stamp(issue, big=True, land=True)}</div>', unsafe_allow_html=True)
            st.markdown(f"#### Filed with {auth['name']}")
            ui.local_text(flow["confirmation"])
            routing = flow.get("routing") or {}
            if routing.get("changed"):
                st.info(f"**Why {auth['name']}?** {routing['explanation']}", icon="🧭")
        else:
            if flow.get("already"):
                st.markdown("#### You're already backing this issue")
            else:
                st.markdown(f"#### You're resident number {flow['residents']} behind this issue")
            if flow.get("before") and flow.get("rank"):
                moved = (f"It moved from #{flow['before']} to **#{flow['rank']}** of {flow['total']} in the department's queue."
                         if flow["before"] != flow["rank"] else f"It's **#{flow['rank']}** of {flow['total']} in the department's queue.")
                st.markdown(moved)
        line = f"{issue['summary']}. {ui.plural(issue['report_count'] + (issue['confirmations'] or 0), 'resident')} backing it, {auth['name']}, due {issue['expected_by']:%d %b}."
        st.html(ui.receipt(flow["issue_id"], line))
        if typical := db.typical_fix_days(auth["authority_id"]):
            st.caption(f"Based on {typical[1]} verified fixes, {auth['name']} usually takes about {typical[0]:.0f} days. Awaaz will check in on {issue['expected_by']:%d %b}.")
        if flow["new"]:
            with st.expander("The complaint Awaaz prepared" + ("" if flow["sent"] else ": ready to submit"), expanded=not flow["sent"]):
                st.write(ui.filing_instruction(auth, flow["sent"]))
                st.code(flow["doc"], language=None, wrap_lines=True)
                st.download_button("Download complaint (.txt)", flow["doc"], file_name=f"{flow['issue_id']}.txt")
        show_trace(flow)
        a, b = st.columns(2)
        if a.button("Track this issue", type="primary", use_container_width=True):
            st.session_state.track_ref = flow["issue_id"]
            st.switch_page(st.session_state.pages["track"])
        if b.button("Report another problem", use_container_width=True):
            st.session_state.flow = None; st.session_state.loc = None; st.rerun()


def page():
    st.title("Report a problem")
    st.markdown('<p class="sub">Drop a pin, say what\'s wrong in Urdu, Roman Urdu or English, and Awaaz takes it from there.</p>', unsafe_allow_html=True)
    flow = st.session_state.get("flow")
    if flow and flow.get("stage") in ("clarify", "match", "done"):
        if flow["stage"] == "done":
            issue = db.get_issue(flow["issue_id"])
            ui.emergency_card(issue, flow["auth"])  # safety advice before anything else
        ui.show_warnings()
        render_flow(flow)
        return
    ui.show_warnings()

    with st.expander("Trying it out? Load an example", expanded=False):
        cols = st.columns(len(EXAMPLES))
        for col, (label, (txt, place)) in zip(cols, EXAMPLES.items()):
            if col.button(label, use_container_width=True):
                st.session_state.desc = txt
                lat, lng = PRESETS[place]
                st.session_state.loc = {"lat": lat, "lng": lng, "source": place}
                st.rerun()

    loc = location_picker()
    if loc:
        nearby_panel(loc)
    st.subheader("What's wrong?")
    pick = st.pills("Pick a type (optional)", list(CATEGORIES), key="cat_pick")
    text = st.text_area("Describe it in your own words", key="desc", height=90,
                        placeholder="e.g. Gali mein gutter 3 din se ubal raha hai")
    c1, c2 = st.columns(2)
    photo = c1.file_uploader("Photo (optional)", type=["jpg", "jpeg", "png", "webp"])
    audio = c2.audio_input("Voice note (optional)") if services.stt_enabled() else None
    if not services.stt_enabled():
        c2.caption("Voice notes need a speech-to-text key; typing works everywhere.")
    st.subheader("Your mobile number")
    phone = st.text_input("Only used to recognise your reports and ask whether it got fixed. Never shown publicly.",
                          value=st.session_state.get("phone", ""), placeholder="03xx xxxxxxx")
    described = text.strip() or photo is not None or audio is not None or pick
    phone_ok = db.normalize_phone(phone) is not None
    ready = bool(loc) and described and phone_ok
    if st.button("Send report", type="primary", disabled=not ready, use_container_width=True):
        st.session_state.phone = phone
        body = text.strip()
        if pick and CATEGORIES[pick].lower() not in body.lower():
            body = f"{CATEGORIES[pick]}. {body}".strip()
        run_pipeline(phone, body, photo, audio, loc)
        st.rerun()
    if not ready:
        missing = [n for n, ok in (("a location", bool(loc)), ("what's wrong", described), ("your mobile number (like 0300 1234567)", phone_ok)) if not ok]
        st.caption("To send, add " + ", ".join(missing[:-1]) + (" and " if len(missing) > 1 else "") + missing[-1] + ".")
