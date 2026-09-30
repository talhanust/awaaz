"""Deterministic fallbacks, used only when Claude is unavailable (no key, outage, or invalid output).
Every result produced here is labelled 'rules' in the UI so it's never mistaken for an AI decision."""
import re
from datetime import datetime

KW = {
    "roads": r"gadd?ha|gadda|pothole|sadak|sarak|road|speed ?breaker|سڑک|گڑھا",
    "sanitation": r"gutter|sewer|sewage|naali|nali|kachr|koora|kooda|garbage|trash|badbu|manhole|گٹر|کچر|نالی|سیوریج|گندا پانی",
    "water": r"nalk|tap|supply|pressure|pani nahi|water not|no water|پانی نہیں|نلک",
    "electrical": r"bijli|light|wire|taar|spark|chingari|transformer|pole|current|بجلی|تار|چنگاری|بتی",
    "gas": r"\bgas\b|گیس",
    "encroachment": r"thela|stall|qabza|encroach|footpath|تجاوز|قبضہ",
}
DEFAULT_AUTH = {"roads": "MCL-ROADS", "water": "WASA-LHR", "electrical": "LESCO", "gas": "SNGPL", "encroachment": "MCL-ENC", "other": "unknown"}


def detect_language(s: str) -> str:
    if re.search(r"[\u0600-\u06FF]", s):
        return "ur"
    if re.search(r"\b(hai|hain|ka|ki|ke|mein|nahi|bohat|gaya|raha|se|pe|par)\b", s, re.I):
        return "ur-Latn"
    return "en"


def classify(text: str, area: str) -> dict:
    lang = detect_language(text)
    hits = [c for c, rx in KW.items() if re.search(rx, text, re.I)]
    cat = "gas" if "gas" in hits else (hits[0] if hits else "other")
    if "sanitation" in hits and "water" in hits:
        cat = "sanitation" if re.search(r"gutter|sewer|گٹر|گندا", text, re.I) else "water"
    clar = None
    if not hits:
        clar = {"en": "Can you tell me a little more? For example: road, water, sewage, electricity or gas?",
                "ur-Latn": "Thoda aur batayein? Jaise sadak, pani, gutter, bijli ya gas?",
                "ur": "تھوڑا اور بتائیں؟ جیسے سڑک، پانی، گٹر، بجلی یا گیس؟"}[lang]
    sev = "medium"
    if re.search(r"spark|chingari|چنگاری|gas|گیس|leak|manhole|dhakkan|naked wire|nangi taar|live wire", text, re.I):
        sev = "urgent"
    elif re.search(r"gir gay|fell|accident|injur|zakhmi|ubal|overflow|ابل|badbu|din se|days|hafte", text, re.I):
        sev = "high"
    if cat == "encroachment":
        sev = "low"
    auth = DEFAULT_AUTH[cat]
    if cat == "sanitation":
        auth = "LWMC" if re.search(r"kachr|koora|kooda|garbage|trash|کچر", text, re.I) else "WASA-LHR"
    summary = {
        "roads": "Damaged speed breaker on the road" if re.search(r"speed ?breaker", text, re.I) else "Pothole or damaged road surface",
        "sanitation": "Garbage not collected" if auth == "LWMC" else "Sewage overflow or blocked drain",
        "water": "No tap water or low pressure in the supply",
        "electrical": "Sparking or exposed electrical wires" if re.search(r"spark|chingari|چنگاری|wire|taar", text, re.I)
        else ("Street lights not working" if re.search(r"street ?lights?|batti|بتی", text, re.I) else "Electrical fault or outage"),
        "gas": "Smell of gas, suspected leak", "encroachment": "Encroachment blocking public space", "other": "Civic issue",
    }[cat]
    return {"language": lang, "category": cat, "authority_id": auth, "confidence": 0.9 if hits else 0.3, "severity": sev,
            "needs_clarification": clar, "summary_en": f"{summary} at {area.split(',')[0]}", "summary_local": text}


ROUTE_RULES = [
    (lambda c, x: re.search(r"cantt|cantonment|کینٹ", x, re.I), "LCB", "lahore/area-types#1",
     {"en": "Inside cantonment limits, municipal services are handled by the cantonment board.",
      "ur-Latn": "Cantonment ki hudood mein yeh kaam cantonment board karta hai.", "ur": "کنٹونمنٹ کی حدود میں یہ کام کنٹونمنٹ بورڈ کرتا ہے۔"}),
    (lambda c, x: c["category"] == "electrical" and re.search(r"street ?lights?|batti|بتی", x, re.I)
     and not re.search(r"spark|chingari|wire|taar|چنگاری|تار", x, re.I), "MCL-LIGHTS", "lahore/electricity-vs-streetlights#2",
     {"en": "Street lights in city areas are maintained by municipal street lighting, not LESCO.",
      "ur-Latn": "Shehri ilaqon mein street lights ki dekh bhaal municipal street lighting karti hai, LESCO nahi.",
      "ur": "شہری علاقوں میں اسٹریٹ لائٹس کی دیکھ بھال میونسپل اسٹریٹ لائٹنگ کرتی ہے، لیسکو نہیں۔"}),
    (lambda c, x: c["category"] == "sanitation" and re.search(r"kachr|garbage|koora|کچر", x, re.I)
     and re.search(r"naal|nali|drain|gutter|نالی|گٹر", x, re.I), "WASA-LHR", "lahore/water-and-sewerage#3",
     {"en": "A blocked drain is WASA's job, even when garbage is blocking it.",
      "ur-Latn": "Band naali WASA ki zimmedari hai, chahe kachre ki wajah se band ho.", "ur": "بند نالی واسا کی ذمہ داری ہے، چاہے کچرے کی وجہ سے بند ہو۔"}),
    (lambda c, x: c["category"] == "roads" and re.search(r"signal|marking|speed ?breaker", x, re.I), "TEPA", "lahore/roads-and-traffic#2",
     {"en": "Traffic signals, road markings and speed breakers are handled by TEPA.",
      "ur-Latn": "Traffic signal, road markings aur speed breaker TEPA ke zimme hain.", "ur": "ٹریفک سگنل، روڈ مارکنگ اور اسپیڈ بریکر ٹیپا کے ذمے ہیں۔"}),
]


def route(c: dict, text: str, passages: list[dict]) -> dict:
    if re.search(r"\b(society|dha|bahria)\b|سوسائٹی", text, re.I) and not re.search(r"\bcity( area)?\b", text, re.I):
        return {"authority_id": c["authority_id"], "sources": ["lahore/area-types#2"], "confidence": 0.8,
                "needs_clarification": {"en": "Is this inside a private housing society or DHA? If yes, the society office maintains it. Reply 'city area' if it's a city area.",
                                        "ur-Latn": "Kya yeh kisi private housing society ya DHA ke andar hai? Agar haan, to society office zimmedar hai. Shehri ilaqa ho to 'city area' likhein.",
                                        "ur": "کیا یہ کسی نجی ہاؤسنگ سوسائٹی یا ڈی ایچ اے کے اندر ہے؟ اگر ہاں تو سوسائٹی آفس ذمہ دار ہے۔ شہری علاقہ ہو تو 'city area' لکھیں۔"}.get(c["language"], ""),
                "explanation": "Inside private societies, the society administration maintains this.", "explanation_local": ""}
    for test, to, src, ex in ROUTE_RULES:
        if test(c, text):
            return {"authority_id": to, "sources": [src], "confidence": 0.85, "needs_clarification": None,
                    "explanation": ex["en"], "explanation_local": ex.get(c["language"], ex["en"])}
    support = next((p for p in passages if c["authority_id"] in (p.get("authority_ids") or [])), None)
    return {"authority_id": c["authority_id"], "sources": [support["chunk_id"]] if support else [], "confidence": 0.7,
            "needs_clarification": None, "explanation": "Routed by complaint category.", "explanation_local": ""}


def match(candidates: list[dict], category: str) -> dict:
    radius = {"roads": 50, "encroachment": 50, "sanitation": 100, "electrical": 100, "water": 250, "gas": 250}.get(category, 50)
    geo = [c for c in candidates if c.get("similarity") is None]
    if geo and geo[0]["distance_m"] <= radius * 0.6:
        return {"decision": "match", "issue_id": geo[0]["issue_id"], "confidence": 0.86, "reason": f"Same category, {round(geo[0]['distance_m'])} m away"}
    return {"decision": "new", "issue_id": None, "confidence": 0.6, "reason": "No close candidate"}


FILED = {"en": "Filed as {id} with {auth}. Check back in {b} days, or track it any time with this reference.",
         "ur-Latn": "Aap ki shikayat {id} ke naam se {auth} ko bheji ja rahi hai. {b} din baad dekhein, ya is reference se kabhi bhi track karein.",
         "ur": "آپ کی شکایت {id} کے نام سے {auth} کو بھیجی جا رہی ہے۔ {b} دن بعد دیکھیں، یا اس حوالے سے کبھی بھی ٹریک کریں۔"}


def draft(issue: dict, auth: dict, landmark: str, language: str) -> dict:
    date = datetime.now().strftime("%d %B %Y")
    place = f"{landmark}, Lahore" if landmark == issue["sector"] or landmark.startswith("near ") else f"{landmark}, {issue['sector']}, Lahore"
    ch = auth["filing_channel"]
    if ch == "email":
        doc = (f"Subject: Complaint {issue['issue_id']}: {issue['category']} issue in {issue['sector']}\n\nDear Sir/Madam,\n\n"
               f"We would like to report: {issue['summary']}.\nLocation: {place}\nSeverity: {issue['severity']}\n"
               f"Residents reporting: {issue['report_count']}\nDate: {date}\n\nPlease inspect and resolve the issue, and quote reference "
               f"{issue['issue_id']} in any reply.\n\nRegards,\nResidents of {issue['sector']} (via Awaaz)")
    elif ch == "portal":
        consumer = "\nConsumer reference number (from the bill): NOT PROVIDED" if auth["authority_id"] in ("LESCO", "SNGPL") else ""
        doc = (f"Category: {issue['category']}\nSeverity: {issue['severity']}\nArea: {issue['sector']}\nLocation / landmark: {landmark}\n"
               f"Description: {issue['summary']}\nResidents reporting: {issue['report_count']}\nDate: {date}\nReference: {issue['issue_id']}"
               f"{consumer}\nComplainant name: NOT PROVIDED\nContact number: NOT PROVIDED")
    else:
        doc = (f"To\nThe {auth['filing_target'] or auth['name']}\n\nSubject: Complaint regarding {'an' if issue['category'][0] in 'aeiou' else 'a'} {issue['category']} issue in {issue['sector']} "
               f"(Ref {issue['issue_id']})\n\nRespected Sir/Madam,\n\nThis is to report the following issue: {issue['summary']}. Location: {place}. "
               f"Severity: {issue['severity']}. Reported by {issue['report_count']} resident(s) through Awaaz on {date}.\n\nWe request that the "
               f"issue be inspected and resolved, and that residents be informed of the action taken.\n\nReference: {issue['issue_id']}\n\n"
               f"Sincerely,\nResidents of {issue['sector']}\n(submitted via Awaaz)")
    return {"reference_id": issue["issue_id"], "filing_channel": ch, "email_subject": None, "formatted_complaint": doc, "missing_fields": [],
            "citizen_confirmation": FILED.get(language, FILED["en"]).format(id=issue["issue_id"], auth=auth["name"], b=auth["benchmark_days"])}


def escalation(issue: dict, auth: dict, tier: int, days: int, cc: str | None) -> dict:
    filed = issue["first_reported_at"].strftime("%d %B %Y")
    body = (f"To: {auth['name']}\n\nSubject: Follow-up on unresolved complaint {issue['issue_id']}\n\nRespected Sir/Madam,\n\n"
            f"This is a follow-up to complaint {issue['issue_id']}, filed on {filed}: {issue['summary']}, {issue['sector']}. "
            f"It remains unresolved after {days} days and has been reported by {issue['report_count']} residents.\n\n"
            f"We request that it be addressed and that residents be told the expected resolution date.\n\nReference: {issue['issue_id']}")
    if tier == 2:
        body = body.replace(f"To: {auth['name']}", f"To: {auth['name']}\nCC: {cc or 'NOT PROVIDED'}") + \
            f"\n\nWe also request the office of the local representative to follow up with {auth['name']}."
    short = None
    if tier == 3:
        short = (f"{issue['summary']} in {issue['sector']}, Lahore: unresolved for {days} days, reported by {issue['report_count']} "
                 f"residents. Ref {issue['issue_id']} with {auth['name']}.")[:280]
    return {"tier": tier, "recipients": [auth["name"]] + ([cc] if tier == 2 and cc else []), "missing_contacts": [] if cc or tier != 2 else ["local representative"],
            "subject": f"Follow-up on unresolved complaint {issue['issue_id']}", "body": short + "\n\n" + body if short else body,
            "short_post": short, "consent_prompt": "Approve to send?", "citizen_tip": None}


def report(c: dict, auth_name: str) -> dict:
    trend = f"up from {c['prev_reports']}" if c["prev_reports"] else "with none"
    return {
        "headline_stat": f"{c['reports']} residents reported {c['issues']} {c['category']} issues in {c['sector']} in 30 days",
        "report_en": (f"{c['reports']} residents have reported {c['issues']} {c['category']} issues in {c['sector']} in the last 30 days, "
                      f"{trend} in the previous 30 days. {c['resolved']} of these have been resolved, and open issues have been pending "
                      f"{c['avg_days_open']} days on average. Residents can add their own report on Awaaz. Authority: {auth_name}."),
        "report_ur": (f"{c['sector']} میں پچھلے 30 دنوں میں {c['reports']} رہائشیوں نے {c['issues']} مسائل رپورٹ کیے۔ ان میں سے {c['resolved']} حل ہوئے "
                      f"اور زیرِ التوا مسائل اوسطاً {c['avg_days_open']} دن سے حل طلب ہیں۔ رہائشی آواز پر اپنی شکایت شامل کر سکتے ہیں۔ متعلقہ ادارہ: {auth_name}۔"),
    }
