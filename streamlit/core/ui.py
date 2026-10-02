"""Awaaz visual system: theme, the status stamp, the progress tracker, and shared helpers."""
import html
import re
from datetime import datetime, timezone

import folium
import streamlit as st

from .config import CENTER

CAT_HEX = {"roads": "#8A5A2B", "sanitation": "#6B4FA0", "water": "#1F6FA8", "electrical": "#C08A00", "gas": "#A8432A",
           "encroachment": "#3F6E46", "other": "#56606E"}
CAT_LABEL = {"roads": "Roads", "sanitation": "Sewage & garbage", "water": "Water supply", "electrical": "Electricity & lights",
             "gas": "Gas", "encroachment": "Encroachment", "other": "Other"}
EVENT_TEXT = {
    "filed": "Filed", "drafted": "Complaint drafted for the department", "filed_email": "Sent to the department by email",
    "filed_assisted": "Complaint prepared for the resident to submit", "report_added": "Another resident added their voice",
    "confirmed": "A resident confirmed it's still there", "checkin_sent": "Resident asked whether it is fixed",
    "citizen_no": "Resident reports it is still unresolved", "escalation_drafted": "Escalation drafted, waiting for resident approval",
    "escalation_approved": "Escalation approved by resident", "escalation_declined": "Resident chose not to escalate yet",
    "acknowledged": "Acknowledged by the department", "in_progress": "Department started work",
    "authority_marked_fixed": "Department marked it fixed; waiting for a resident to confirm", "fix_claimed": "A resident says it is fixed",
    "fix_disputed": "A resident says it is still there", "resolved": "Fixed and verified by a resident",
    "closed_unverified": "Closed without resident confirmation",
}
FEED_TEXT = {  # short, for the live activity feed
    "filed": "New report", "report_added": "Another resident joined", "confirmed": "“I see this too”", "escalation_approved": "Escalated",
    "acknowledged": "Department acknowledged", "in_progress": "Work started", "authority_marked_fixed": "Department says fixed",
    "resolved": "Verified fixed", "fix_disputed": "Resident says still broken", "closed_unverified": "Closed unverified",
}
STATUS_LABEL = {"open": "Filed", "acknowledged": "Acknowledged", "in_progress": "In progress", "resolved": "Verified fixed",
                "closed_unverified": "Closed (unverified)"}

THEME = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&family=Noto+Nastaliq+Urdu:wght@400;600&display=swap');
:root{--ink:#14261B;--flag:#01411C;--action:#0B6B35;--action-deep:#01411C;--action-tint:#E3F1E7;--saffron:#C98A00;--red:#B3261E;
      --green:#1E8E3E;--slate:#526157;--paper:#F5F8F6;--line:#D3DED6;--white:#FFFFFF;--font:'Archivo',system-ui,-apple-system,'Segoe UI',sans-serif}
html,body,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:var(--paper)}
[data-testid="stHeader"]{background:transparent}
.block-container{padding-top:2rem;max-width:1180px}
p,li,label,input,textarea,button,td,th,.stMarkdown,[data-testid="stMetricValue"],[data-testid="stMetricLabel"],
[data-testid="stCaptionContainer"],[data-testid="stExpander"] summary p,h1,h2,h3,h4{font-family:var(--font)}
h1{font-stretch:125%;font-weight:800;letter-spacing:-.015em;color:var(--ink);line-height:1.05}
h2,h3{font-stretch:112%;font-weight:750;color:var(--ink);letter-spacing:-.005em}
p,li{color:#24304A}
[data-testid="stCaptionContainer"] p{color:var(--slate)}
/* sidebar: ink panel */
[data-testid="stSidebar"]{background:linear-gradient(90deg,#FFFFFF 0 12px,var(--flag) 12px)}  /* the flag: white hoist band, green field */
[data-testid="stSidebar"] *{color:#DCEBE0}
[data-testid="stSidebarContent"]{display:flex;flex-direction:column}
[data-testid="stSidebarHeader"]{order:-2;margin-bottom:0}
[data-testid="stSidebarUserContent"]{order:-1;padding-top:.25rem;padding-bottom:.6rem}  /* brand above the page links */
[data-testid="stSidebarNav"] a{border-radius:6px}
[data-testid="stSidebarNav"] a[aria-current="page"]{background:rgba(255,255,255,.12)}
[data-testid="stSidebarNav"] a[aria-current="page"] span{color:#FFFFFF;font-weight:700}
[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,.12)}
/* actions */
button[data-testid="stBaseButton-primaryFormSubmit"],button[data-testid="stBaseButton-primary"]{background:var(--action)!important;border:1px solid var(--action)!important;color:#fff!important;font-weight:700!important}
button[data-testid="stBaseButton-primary"] *,button[data-testid="stBaseButton-primaryFormSubmit"] *{color:#fff!important}
button[data-testid="stBaseButton-primary"]:disabled *{color:#5E7464!important}
button[data-testid="stBaseButton-primary"]:disabled{background:#D4E6D9!important;border-color:#D4E6D9!important;color:#5E7464!important;cursor:not-allowed}
button[data-testid="stBaseButton-primary"]:not(:disabled):hover{background:var(--action-deep)!important;border-color:var(--action-deep)!important;color:#fff!important}
button[data-testid="stBaseButton-secondary"]{border-color:var(--line);background:var(--white)}
button[data-testid="stBaseButton-secondary"]:hover{border-color:var(--ink);color:var(--ink)}
:focus-visible{outline:2px solid var(--action)!important;outline-offset:2px}
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]){background:var(--white)}
[data-testid="stMetricValue"]{font-stretch:118%;font-weight:750;color:var(--ink)}
[data-testid="stMetricDelta"] svg{display:none}
.emerg{border-left:4px solid var(--red);background:var(--white);padding:12px 16px;border-radius:6px;margin:4px 0 14px}
.emerg b{color:var(--red)}
.answer{background:var(--white);border:1px solid var(--line);border-left:4px solid var(--action);border-radius:6px;padding:14px 16px;margin:8px 0}
.cite{display:inline-block;font-size:.78rem;background:var(--action-tint);color:var(--action-deep);border-radius:999px;padding:1px 9px;margin:2px 4px 2px 0}
[data-testid="stMetricLabel"] p{color:var(--slate)}
.stTabs [data-baseweb="tab-list"]{gap:4px}
.stTabs [aria-selected="true"]{color:var(--ink)!important}
.stTabs [data-baseweb="tab-highlight"]{background-color:var(--action)!important}
.stTabs [data-baseweb="tab"]:hover{color:var(--ink)!important}
[data-testid="stButtonGroup"] button[data-selected="true"]{background:var(--action-tint)!important;border-color:var(--action)!important;color:var(--action-deep)!important}
[data-testid="stButtonGroup"] button:hover{border-color:var(--ink)!important;color:var(--ink)!important}
[data-baseweb="input"]:focus-within,[data-baseweb="textarea"]:focus-within,[data-baseweb="select"]>div:focus-within{border-color:var(--action)!important}
/* the stamp: the one bold element */
.stamp{display:inline-block;font-family:var(--font);font-weight:800;font-stretch:118%;text-transform:uppercase;letter-spacing:.07em;
       font-size:.74rem;line-height:1;padding:5px 9px 4px;border:2px solid currentColor;border-radius:3px;transform:rotate(-2.5deg);
       box-shadow:inset 0 0 0 1.5px var(--white),inset 0 0 0 3px currentColor;white-space:nowrap;opacity:.92}
.stamp.filed{color:var(--ink)}.stamp.progress{color:#2F6E8F}.stamp.overdue,.stamp.escalated{color:var(--red)}
.stamp.verified{color:var(--green)}.stamp.unverified{color:var(--slate)}
.stamp.big{font-size:1.25rem;padding:9px 16px 8px;border-width:3px;transform:rotate(-5deg);box-shadow:inset 0 0 0 2px var(--white),inset 0 0 0 4.5px currentColor}
.stamp.big.land{animation:stampdown .45s cubic-bezier(.2,1.4,.4,1) both}
@keyframes stampdown{0%{transform:rotate(-5deg) scale(1.9);opacity:0}100%{transform:rotate(-5deg) scale(1);opacity:.92}}
@media (prefers-reduced-motion:reduce){.stamp.big.land{animation:none}}
/* hero sentence */
[data-testid="stMarkdownContainer"] p.hero{font-stretch:110%;font-size:clamp(1.6rem,3.6vw,2.6rem);font-weight:500;line-height:1.25;color:var(--ink);max-width:24em;margin:.2rem 0 1.2rem}
[data-testid="stMarkdownContainer"] p.hero b{font-weight:800;font-stretch:125%;box-shadow:inset 0 -.28em 0 rgba(11,107,53,.22)}
[data-testid="stMarkdownContainer"] p.hero .ok{box-shadow:inset 0 -.28em 0 rgba(30,142,62,.35)}
[data-testid="stMarkdownContainer"] p.sub,.sub{color:var(--slate);font-size:1.02rem;max-width:62ch}
/* issue rows */
.irow{display:grid;grid-template-columns:1fr auto;gap:6px 14px;align-items:start;padding:12px 2px;border-bottom:1px solid var(--line)}
.irow:last-child{border-bottom:0}
.irow .t{font-weight:650;color:var(--ink);font-size:1.02rem;line-height:1.3}
.irow .m{color:var(--slate);font-size:.86rem;margin-top:4px;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center}
.irow .n{text-align:right;font-stretch:120%;font-weight:800;font-size:1.5rem;color:var(--ink);line-height:1}
.irow .n small{display:block;font-size:.72rem;font-weight:500;font-stretch:100%;color:var(--slate)}
.cat{display:inline-flex;align-items:center;gap:6px}.cat i{width:9px;height:9px;border-radius:50%;display:inline-block}
.ref{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}
.late{color:var(--red);font-weight:650}
/* feed */
.feed{list-style:none;margin:0;padding:0}
.feed li{display:grid;grid-template-columns:76px 1fr;gap:10px;padding:9px 0;border-bottom:1px solid var(--line);font-size:.93rem}
.feed li:last-child{border-bottom:0}
.feed time{color:var(--slate);font-size:.8rem;padding-top:2px}
.feed b{color:var(--ink);font-weight:650}
/* tracker */
.track{display:grid;grid-template-columns:repeat(4,1fr);margin:18px 0 6px}
.track .s{position:relative;padding-top:26px;font-size:.9rem;color:var(--slate)}
.track .s::before{content:"";position:absolute;top:4px;left:0;width:16px;height:16px;border-radius:50%;background:var(--white);border:2px solid var(--line);z-index:1}
.track .s::after{content:"";position:absolute;top:11px;left:18px;right:2px;height:3px;background:var(--line)}
.track .s:last-child::after{display:none}
.track .s.done{color:var(--ink);font-weight:650}.track .s.done::before{background:var(--green);border-color:var(--green)}
.track .s.done::after{background:var(--green)}
.track .s.now::before{border-color:var(--action);background:var(--action-tint)}
.track .s small{display:block;font-weight:400;color:var(--slate);font-size:.78rem;margin-top:2px}
.due{height:8px;border-radius:4px;background:var(--line);overflow:hidden;margin:8px 0 4px}
.due span{display:block;height:100%;background:var(--green)}
.due.warn span{background:var(--saffron)}.due.over span{background:var(--red)}
.ur{direction:rtl;text-align:right;font-family:'Noto Nastaliq Urdu','Jameel Noori Nastaleeq',serif!important;font-size:1.12rem;line-height:2.15}
.receipt{background:var(--white);border:1px dashed #A9BBAE;border-radius:8px;padding:16px 18px;display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center}
.receipt .r1{font-stretch:125%;font-weight:800;font-size:1.5rem;color:var(--ink)}
.receipt .r2{color:var(--slate);font-size:.88rem;margin-top:4px}
.receipt img{width:104px;height:104px;image-rendering:pixelated}
@media (max-width:640px){.track{grid-template-columns:repeat(2,1fr);row-gap:14px}.feed li{grid-template-columns:62px 1fr}}
</style>
"""


def theme():
    st.markdown(THEME, unsafe_allow_html=True)


def css():  # pages used to inject styles themselves; the app now applies the theme once
    pass


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def now() -> datetime:
    return datetime.now(timezone.utc)


def rel_time(dt: datetime) -> str:
    s = (now() - dt).total_seconds()
    if s < 60: return "just now"
    if s < 3600: return f"{int(s // 60)} min ago"
    if s < 86400: return f"{int(s // 3600)} h ago"
    d = int(s // 86400)
    return "yesterday" if d == 1 else f"{d} days ago"


def stamp_for(i: dict) -> tuple[str, str]:
    s = i["status"]
    if s == "resolved": return "Verified fixed", "verified"
    if s == "closed_unverified": return "Closed unverified", "unverified"
    if s.startswith("escalated_t"): return f"Escalated tier {i['escalation_tier']}", "escalated"
    if i.get("expected_by") and i["expected_by"] < now(): return "Overdue", "overdue"
    if s == "in_progress": return "Work started", "progress"
    if s == "acknowledged": return "Acknowledged", "progress"
    return "Filed", "filed"


def stamp(i: dict, big: bool = False, land: bool = False) -> str:
    text, cls = stamp_for(i)
    return f'<span class="stamp {cls}{" big" if big else ""}{" land" if land else ""}">{esc(text)}</span>'


def status_label(i: dict) -> str:
    return stamp_for(i)[0]


def pill(i: dict) -> str:  # kept for older call sites
    return stamp(i)


def cat_chip(cat: str) -> str:
    return f'<span class="cat"><i style="background:{CAT_HEX.get(cat, "#5B6475")}"></i>{esc(CAT_LABEL.get(cat, cat.title()))}</span>'


def issue_row(i: dict, rank: int | None = None, show_dept: bool = True) -> str:
    days = max(1, (now() - i["first_reported_at"]).days) if i.get("first_reported_at") else i.get("days_open", 1)
    late = i.get("expected_by") and i["expected_by"] < now() and i["status"] not in ("resolved", "closed_unverified")
    meta = [stamp(i), cat_chip(i["category"]), f'<span class="ref">{esc(i["issue_id"])}</span>', esc(i["sector"])]
    if show_dept: meta.append(esc(i["authority_id"]))
    meta.append(f'<span class="late">{days} days open</span>' if late else f"{days} days open")
    backers = i["report_count"] + (i.get("confirmations") or 0)
    title = f"{rank}. {esc(i['summary'])}" if rank else esc(i["summary"])
    return (f'<div class="irow"><div><div class="t">{title}</div><div class="m">{"".join(f"<span>{m}</span>" for m in meta)}</div></div>'
            f'<div class="n">{backers}<small>residents</small></div></div>')


def tracker(i: dict, events: list[dict]) -> str:
    when = {}
    for e in reversed(events):  # events arrive newest first
        when.setdefault(e["type"], e["created_at"])
    stage = {"open": 0, "acknowledged": 1, "in_progress": 2, "resolved": 3}.get(i["status"], 1 if i["status"].startswith("escalated") else 0)
    steps = [("Filed", when.get("filed")), ("Acknowledged", when.get("acknowledged")), ("Work started", when.get("in_progress")),
             ("Fixed & verified", when.get("resolved"))]
    out = []
    for k, (name, at) in enumerate(steps):
        cls = "done" if k <= stage else ("now" if k == stage + 1 else "")
        date = f"<small>{at:%d %b}</small>" if at else ""
        out.append(f'<div class="s {cls}">{name}{date}</div>')
    return f'<div class="track">{"".join(out)}</div>'


def due_bar(i: dict) -> str:
    total = max(1, (i["expected_by"] - i["first_reported_at"]).total_seconds())
    used = (now() - i["first_reported_at"]).total_seconds()
    pct = min(100, max(3, used / total * 100))
    left = (i["expected_by"] - now()).days
    cls = "over" if left < 0 else "warn" if pct > 70 else ""
    label = f'<span class="late">{-left} days overdue</span>' if left < 0 else f"{left} days left"
    return f'<div class="due {cls}"><span style="width:{pct:.0f}%"></span></div><div class="sub" style="font-size:.85rem">{label}, due {i["expected_by"]:%d %b}</div>'


def local_text(s: str):
    if re.search(r"[\u0600-\u06FF]", s or ""):
        st.markdown(f'<div class="ur">{esc(s)}</div>', unsafe_allow_html=True)
    else:
        st.write(s)


def base_map(location, zoom: int) -> folium.Map:
    """Free OpenStreetMap tiles (no API key), toned down to grey so issue markers stand out."""
    m = folium.Map(location=location, zoom_start=zoom, control_scale=True, tiles="OpenStreetMap")
    m.get_root().header.add_child(folium.Element(
        "<style>.leaflet-tile-pane{filter:grayscale(.9) contrast(.92) brightness(1.06)}"
        ".marker-cluster-small,.marker-cluster-medium,.marker-cluster-large{background:rgba(1,65,28,.25)}"
        ".marker-cluster-small div,.marker-cluster-medium div,.marker-cluster-large div{background:#01411C;color:#fff;font-weight:700}</style>"))
    return m


def issues_map(issues: list[dict], pin: tuple[float, float] | None = None, zoom: int = 15) -> folium.Map:
    from folium.plugins import MarkerCluster
    m = base_map(pin or CENTER, zoom)
    layer = MarkerCluster(options={"maxClusterRadius": 38, "disableClusteringAtZoom": 17}).add_to(m) if len(issues) > 40 else m
    for i in issues:
        if i.get("lat") is None:
            continue
        folium.CircleMarker([i["lat"], i["lng"]], radius=6 + 3 * (i["report_count"] ** 0.5), color="#ffffff", weight=2,
                            fill=True, fill_color=CAT_HEX.get(i["category"], "#5B6475"), fill_opacity=0.88,
                            tooltip=f"{i['issue_id']} · {i['summary']} · {i['report_count']} residents").add_to(layer)
    if pin:
        folium.Marker(pin, tooltip="Problem location", icon=folium.Icon(color="darkgreen", icon="map-marker", prefix="fa")).add_to(m)
    return m


def show_warnings():
    for w in st.session_state.pop("warnings", []):
        st.warning(w, icon="⚠️")


def receipt(issue_id: str, line: str) -> str:
    """Shareable receipt with a QR code that opens the issue's tracking page."""
    import segno
    from .config import secret
    url = f"{(secret('APP_URL') or 'https://awaaz-pk.streamlit.app').rstrip('/')}/track?ref={issue_id}"
    qr = segno.make(url, error="m").svg_data_uri(scale=4, dark="#01411C", border=1)  # an <img>, since inline SVG is stripped
    return (f'<div class="receipt"><div><div class="r1">{esc(issue_id)}</div><div class="r2">{esc(line)}</div>'
            f'<div class="r2">Scan the code, or open <span class="ref">{esc(url)}</span>, to follow it.</div></div>'
            f'<img src="{qr}" alt="QR code linking to the tracking page for {esc(issue_id)}"></div>')


# chart palette shared by pages (flag green family + warning red)
CHART = {"ink": "#14261B", "flag": "#01411C", "action": "#0B6B35", "light": "#8CC6A0", "pale": "#CFE6D6", "red": "#B3261E",
         "amber": "#C98A00", "slate": "#526157", "line": "#D3DED6", "blue": "#2F6E8F"}
GRADE_COLORS = {"A": "#0B6B35", "B": "#4E9E67", "C": "#C9B458", "D": "#D9823B", "E": "#B3261E", "–": "#E6ECE8"}
