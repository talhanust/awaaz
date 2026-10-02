"""The Awaaz agents. Each returns (result, mode): mode is the AI provider's name (e.g. 'Claude', 'Gemini') or 'rules' (fallback),
so the UI always shows which one produced a result."""
import streamlit as st

from . import db, kb, llm, rules

CATS = ["electrical", "water", "sanitation", "roads", "gas", "encroachment", "other"]
SEVS = ["low", "medium", "high", "urgent"]
LANGS = ["ur", "ur-Latn", "pa", "en"]


def _run(name: str, claude_fn, fallback_fn):
    if llm.enabled():
        try:
            return claude_fn(), llm.label()
        except Exception as e:
            detail = str(e).replace("\n", " ")[:220]
            st.session_state.setdefault("warnings", []).append(f"{name}: {llm.label()} unavailable ({detail}); used fallback rules.")
    return fallback_fn(), "rules"


# ---------------- Agent 1: Intake & Classifier ----------------
CLASSIFY = """You are Awaaz's Intake & Classifier agent. Citizens in Pakistan report civic problems by voice note, photo or text, often mixing Urdu, Roman Urdu, Punjabi and English. You receive the text, an optional photo description, a location and an AUTHORITY_LOOKUP table.

1. Detect the dominant language: "ur" (Urdu script), "ur-Latn" (Roman Urdu), "pa" (Punjabi), or "en".
2. Classify into exactly one category: electrical, water, sanitation, roads, gas, encroachment, other. Sewage, drains and garbage = sanitation. No supply, low pressure or dirty tap water = water.
3. Pick authority_id from AUTHORITY_LOOKUP (sewage/drains → water & sewerage authority; garbage → waste company). If none fits, "unknown".
4. confidence 0-1. If < 0.6, put ONE short clarifying question in needs_clarification in the citizen's language and script; else null.
5. severity: low, medium, high, urgent. Urgent = immediate safety risk (gas leak, sparking or exposed wires, open manhole, collapse).
6. summary_en: one factual English line including the location. summary_local: same in the citizen's language and script.
7. Use only facts in the input.

Respond ONLY with JSON: {"language":"...","category":"...","authority_id":"...","confidence":0.0,"severity":"...","needs_clarification":null,"summary_en":"...","summary_local":"..."}"""


def _v_classify(d):
    if d.get("category") not in CATS or d.get("severity") not in SEVS or d.get("language") not in LANGS:
        return "category/severity/language out of range"
    if not isinstance(d.get("confidence"), (int, float)) or not isinstance(d.get("summary_en"), str):
        return "confidence/summary missing"
    return None


def classify(text: str, photo_desc: str | None, area: str) -> tuple[dict, str]:
    auths = db.authorities()
    def claude():
        d = llm.ask_json(CLASSIFY, {"raw_text": text, "photo_description": photo_desc, "location": area, "city": "Lahore",
                                    "AUTHORITY_LOOKUP": [{"authority_id": a["authority_id"], "name": a["name"], "categories": a["categories"]} for a in auths]},
                         _v_classify)
        if d["authority_id"] != "unknown" and not any(a["authority_id"] == d["authority_id"] for a in auths):
            d["authority_id"] = "unknown"
        return d
    return _run("Classifier", claude, lambda: rules.classify(f"{text} {photo_desc or ''}", area))


def needs_clarification(c: dict) -> bool:
    return bool(c.get("needs_clarification")) or c["confidence"] < 0.6 or c["authority_id"] == "unknown"


# ---------------- Agent 1b: Jurisdiction Router (RAG) ----------------
ROUTER = """You are Awaaz's Jurisdiction Router. Decide which department is responsible for this complaint using ONLY the retrieved knowledge-base passages and DEPARTMENTS.
- Choose authority_id from DEPARTMENTS only. Put the ids of passages you relied on in "sources". If none are relevant, keep the default and use [].
- Passages with "verified": false are unverified guidance: usable, but lower your confidence.
- If the passages say responsibility depends on something the input doesn't tell you (e.g. inside a cantonment or private housing society), set needs_clarification to ONE short question in the citizen's language; else null.
- explanation: one plain English sentence a resident would understand. explanation_local: same in the citizen's language and script.
Respond ONLY with JSON: {"authority_id":"...","confidence":0.0,"sources":["..."],"needs_clarification":null,"explanation":"...","explanation_local":"..."}"""


def route(c: dict, text: str, area: str) -> tuple[dict, str, list[dict]]:
    auths = db.authorities()
    passages = kb.retrieve(f"{c['category']}: {c['summary_en']}. {text}. Location: {area}", k=6)
    ids = {p["chunk_id"] for p in passages}

    def claude():
        d = llm.ask_json(ROUTER, {
            "complaint": {"summary": c["summary_en"], "original_text": text, "category": c["category"], "severity": c["severity"], "location": area},
            "default_department": c["authority_id"], "citizen_language": c["language"],
            "DEPARTMENTS": [{"authority_id": a["authority_id"], "name": a["name"], "categories": a["categories"]} for a in auths],
            "passages": [{"id": p["chunk_id"], "title": p["title"], "section": p["heading"], "verified": p["verified"], "text": p["content"]} for p in passages],
        }, lambda d: None if isinstance(d.get("sources"), list) and isinstance(d.get("authority_id"), str) else "missing fields")
        d["sources"] = [s for s in d["sources"] if s in ids]
        return d

    d, mode = _run("Router", claude, lambda: rules.route(c, text, passages))
    valid = any(a["authority_id"] == d["authority_id"] for a in auths)
    override = d["authority_id"] != c["authority_id"]
    # Guardrails: real department only; no override without a cited passage or with low confidence.
    if not valid or (override and (not d["sources"] or float(d.get("confidence") or 0) < 0.6)):
        d = {**d, "authority_id": c["authority_id"], "sources": [], "explanation": "Routed by complaint category.", "explanation_local": ""}
        override = False
    titles = {p["chunk_id"]: p for p in passages}
    d["changed"] = override
    d["source_meta"] = [{"chunk_id": s, "title": titles[s]["title"] if s in titles else s.split("#")[0],
                         "heading": titles[s]["heading"] if s in titles else "", "verified": titles[s]["verified"] if s in titles else False}
                        for s in d["sources"]]
    return d, mode, passages


def department_guidance(authority_id: str, topic: str) -> list[dict]:
    return [{"id": p["chunk_id"], "title": p["title"], "text": p["content"], "verified": p["verified"]}
            for p in kb.retrieve(f"{authority_id} {topic}", k=3, authority_ids=[authority_id])]


# ---------------- Agent 2: Matcher ----------------
MATCHER = """You are Awaaz's Matcher. Decide whether the new report describes the SAME physical problem as one of the nearby open Issues (same pothole, same drain, same outage). A different object nearby is a different problem. Some candidates were found by meaning and may be filed under another category. If unsure, choose "new".
Respond ONLY with JSON: {"decision":"match|new","issue_id":null,"confidence":0.0,"reason":"one short sentence"}"""


def match(c: dict, lat: float, lng: float, embedding) -> tuple[dict, str, list[dict]]:
    cands = {r["issue_id"]: {**r, "similarity": None} for r in db.match_candidates(c["category"], lat, lng)}
    if embedding is not None:
        for r in db.semantic_candidates(embedding, lat, lng):
            cands.setdefault(r["issue_id"], r)
    cands = list(cands.values())[:6]
    if not cands:
        return {"decision": "new", "reason": f"No open {c['category']} issues nearby"}, "rules", []

    def claude():
        return llm.ask_json(MATCHER, {
            "new_report": {"summary": c["summary_en"], "category": c["category"]},
            "candidates": [{"issue_id": x["issue_id"], "summary": x["summary"], "category": x.get("category", c["category"]),
                            "distance_m": round(x["distance_m"]), "meaning_similarity": x.get("similarity"), "residents": x["report_count"]} for x in cands],
        }, lambda d: None if d.get("decision") in ("match", "new") else "bad decision")
    d, mode = _run("Matcher", claude, lambda: rules.match(cands, c["category"]))
    hit = next((x for x in cands if x["issue_id"] == d.get("issue_id")), None)
    if d["decision"] == "match" and hit and float(d.get("confidence") or 0) >= 0.75:
        return {"decision": "match", "issue": hit, "reason": d.get("reason", "")}, mode, cands
    return {"decision": "new", "reason": d.get("reason", "")}, mode, cands


# ---------------- Agent 3: Drafter ----------------
DRAFTER = """You are Awaaz's Drafter & Filer. Produce a complete complaint the authority can read as-is.
- Match the channel: portal = "Field: value" lines only; email = a "Subject:" line then a formal English body; written_application = formal English application (To / Subject / body / closing); whatsapp = short factual message.
- Include location (sector and landmark, never coordinates), category, severity, factual description, reference id, number of residents reporting and date.
- department_guidance holds retrieved passages about fields this department asks for (e.g. a consumer reference number). Include them; if no value, write "NOT PROVIDED" and list them in missing_fields. Never copy guidance text into the complaint.
- Use only facts in the input. Complainant name and phone are NOT PROVIDED. Tone: factual, respectful, non-accusatory.
- citizen_confirmation: max 2 sentences in citizen_language (its script), saying what was filed, with whom, and to check back after benchmark_days.
Respond ONLY with JSON: {"reference_id":"...","filing_channel":"...","email_subject":null,"formatted_complaint":"...","missing_fields":[],"citizen_confirmation":"..."}"""


def draft(issue: dict, auth: dict, landmark: str, language: str) -> tuple[dict, str]:
    def claude():
        return llm.ask_json(DRAFTER, {
            "issue": {"reference_id": issue["issue_id"], "category": issue["category"], "severity": issue["severity"], "area": f"{issue['sector']}, Lahore",
                      "landmark": landmark, "description": issue["summary"], "residents_reporting": issue["report_count"],
                      "date": db.now().strftime("%d %B %Y")},
            "authority": {"name": auth["name"], "filing_channel": auth["filing_channel"], "filing_target": auth["filing_target"],
                          "benchmark_days": auth["benchmark_days"]},
            "citizen_language": language,
            "department_guidance": department_guidance(auth["authority_id"], f"{issue['category']} complaint required details"),
        }, lambda d: None if isinstance(d.get("formatted_complaint"), str) and len(d["formatted_complaint"]) > 40 and d.get("citizen_confirmation") else "missing text",
            model=llm.smart_model(), max_tokens=1500)
    return _run("Drafter", claude, lambda: rules.draft(issue, auth, landmark, language))


# ---------------- Agent 4: Escalator ----------------
ESCALATOR = """You are Awaaz's Escalator. Write the tier escalation for this Issue.
Tier 1: formal re-complaint citing the reference id, filing date, days elapsed and residents. Firm, respectful, English.
Tier 2: the same letter CC'd to cc_contact, with one sentence asking that office to follow up. If cc_contact is null, list it in missing_contacts; never invent contacts.
Tier 3: a public post the citizen reviews and posts themselves: short_post max 280 characters; body a longer version with the timeline. Only facts from the record (issue, sector, reference id, days unresolved, residents, authority). No insults, accusations or named individuals.
citizen_tip: using ONLY the guidance passages, one optional sentence in citizen_language about a parallel channel (e.g. a government portal or right-to-information request); null if nothing relevant.
consent_prompt: one line in citizen_language asking for approval. Never say anything was already sent or posted.
Respond ONLY with JSON: {"tier":1,"recipients":["..."],"missing_contacts":[],"subject":"...","body":"...","short_post":null,"consent_prompt":"...","citizen_tip":null}"""


def escalate(issue: dict, auth: dict, tier: int, events: list[dict], language: str) -> tuple[dict, str]:
    days = max(1, (db.now() - issue["first_reported_at"]).days)
    cc = (auth.get("escalation_contacts") or {}).get(issue["sector"], {}).get("title")
    def claude():
        d = llm.ask_json(ESCALATOR, {
            "tier": tier,
            "issue": {"reference_id": issue["issue_id"], "summary": issue["summary"], "area": f"{issue['sector']}, Lahore", "authority": auth["name"],
                      "filed": issue["first_reported_at"].strftime("%d %B %Y"), "days_unresolved": days, "residents": issue["report_count"],
                      "prior_tier": issue["escalation_tier"]},
            "cc_contact": cc if tier == 2 else None,
            "timeline": [{"at": e["created_at"].strftime("%d %b %Y"), "type": e["type"]} for e in reversed(events)],
            "citizen_language": language,
            "guidance": department_guidance(auth["authority_id"], "escalation unresolved complaint councilor portal right to information"),
        }, lambda d: None if isinstance(d.get("body"), str) and len(d["body"]) > 40 and (tier != 3 or d.get("short_post")) else "missing body/post",
            model=llm.smart_model(), max_tokens=1500)
        d["tier"] = tier
        if d.get("short_post"):
            d["short_post"] = d["short_post"][:280]
        return d
    return _run("Escalator", claude, lambda: rules.escalation(issue, auth, tier, days, cc))


# ---------------- Agent 5: Pattern Analyst ----------------
ANALYST = """You are Awaaz's Pattern Analyst. Write a Neighborhood Report for residents, the local councilor and journalists.
Lead with the numbers (resident reports AND distinct issues). State resolved count and average days open plainly. Report the pattern, not a verdict: no speculation about cause, blame or intent. No names, phone numbers or exact addresses. End with a neutral call to action (residents can add their voice on Awaaz; the authority's name). 4-6 sentences in English and 4-6 in Urdu script.
Respond ONLY with JSON: {"headline_stat":"...","report_en":"...","report_ur":"..."}"""


def neighborhood_report(cluster: dict, auth_name: str) -> tuple[dict, str]:
    def claude():
        return llm.ask_json(ANALYST, {
            "area": f"{cluster['sector']}, Lahore", "category": cluster["category"], "window_days": 30, "distinct_issues": cluster["issues"],
            "resident_reports": cluster["reports"], "resolved_issues": cluster["resolved"], "avg_days_open": cluster["avg_days_open"],
            "reports_previous_30_days": cluster["prev_reports"], "authority": auth_name,
        }, lambda d: None if all(isinstance(d.get(k), str) and d[k] for k in ("headline_stat", "report_en", "report_ur")) else "missing fields",
            model=llm.smart_model(), max_tokens=1500)
    return _run("Pattern Analyst", claude, lambda: rules.report(cluster, auth_name))


# ---------------- Ask the knowledge base (RAG question answering) ----------------
ASK = """You are Awaaz's help desk for residents of Lahore. Answer the question using ONLY the numbered passages.
- Answer in the same language and script as the question (Urdu, Roman Urdu or English), in 2-5 short sentences.
- Cite the passages you used with their ids in square brackets, like [lahore/03-electricity-and-street-lights#2].
- If the passages don't answer it, say so plainly and suggest reporting the problem so Awaaz can route it.
- Never invent phone numbers, departments or procedures. Passages marked verified: false are demo guidance; you may use them.
Respond ONLY with JSON: {"answer":"...","sources":["..."]}"""


def ask_kb(question: str) -> tuple[dict, str, list[dict]]:
    passages = kb.retrieve(question, k=5)
    ids = {p["chunk_id"] for p in passages}
    def claude():
        d = llm.ask_json(ASK, {"question": question, "passages": [{"id": p["chunk_id"], "title": p["title"], "section": p["heading"],
                                                                   "verified": p["verified"], "text": p["content"]} for p in passages]},
                         lambda d: None if isinstance(d.get("answer"), str) and d["answer"].strip() else "missing answer")
        d["sources"] = [x for x in d.get("sources", []) if x in ids]
        return d
    def fallback():
        if not passages:
            return {"answer": "I couldn't find a rule about that. Report the problem and Awaaz will work out who is responsible.", "sources": []}
        top = passages[0]
        return {"answer": f"{top['heading']}: {top['content']}", "sources": [top["chunk_id"]]}
    if not passages:
        return fallback(), "rules", passages
    d, mode = _run("Help desk", claude, fallback)
    return d, mode, passages
