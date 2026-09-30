"""Shared UI pieces."""
import re

import folium
import streamlit as st

from .config import CENTER

CAT_HEX = {"roads": "#9A6324", "sanitation": "#7A5AA6", "water": "#1F7FB8", "electrical": "#C28E00", "gas": "#D1495B",
           "encroachment": "#4F7A4F", "other": "#6B7280"}
EVENT_TEXT = {
    "filed": "Filed", "drafted": "Complaint drafted for the department", "filed_email": "Sent to the department by email",
    "filed_assisted": "Complaint prepared for the resident to submit", "report_added": "Another resident added their voice",
    "checkin_sent": "Resident asked whether it is fixed", "citizen_no": "Resident reports it is still unresolved",
    "escalation_drafted": "Escalation drafted, waiting for resident approval", "escalation_approved": "Escalation approved by resident",
    "escalation_declined": "Resident chose not to escalate yet", "acknowledged": "Acknowledged by the department",
    "in_progress": "Department marked work in progress", "authority_marked_fixed": "Department marked it fixed; waiting for a resident to confirm",
    "fix_claimed": "A resident says it is fixed", "fix_disputed": "A resident says it is still there",
    "resolved": "Resolved and confirmed by a resident", "closed_unverified": "Closed without resident confirmation",
}
STATUS_LABEL = {"open": "Filed", "acknowledged": "Acknowledged", "in_progress": "In progress", "resolved": "Resolved",
                "closed_unverified": "Closed (unverified)"}


def css():
    st.markdown("""<style>
      .block-container{padding-top:1.4rem;max-width:1250px}
      .ref{font-size:2rem;font-weight:700;letter-spacing:.01em}
      .ur{direction:rtl;text-align:right;font-family:'Noto Nastaliq Urdu','Jameel Noori Nastaleeq',serif;font-size:1.15rem;line-height:2.1}
      .pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.8rem;font-weight:600;margin-right:6px;background:#E9EEF6;color:#121D33}
      .pill.esc{background:#FBEBCB;color:#7A4F00}.pill.ok{background:#DDF0E4;color:#2F7D4F}.pill.urgent{background:#F9DEDC;color:#B3261E}
      .trace{font-size:.92rem;line-height:1.6}
      button[kind="primary"],button[data-testid="stBaseButton-primary"]{background:#D98E04!important;border-color:#D98E04!important;color:#1b1200!important}
      button[kind="primary"]:hover,button[data-testid="stBaseButton-primary"]:hover{background:#C07D03!important;border-color:#C07D03!important}
    </style>""", unsafe_allow_html=True)


def status_label(i: dict) -> str:
    if i["status"].startswith("escalated_t"):
        return f"Escalated · Tier {i['escalation_tier']}"
    return STATUS_LABEL.get(i["status"], i["status"])


def pill(i: dict) -> str:
    cls = "ok" if i["status"] == "resolved" else "esc" if i["escalation_tier"] else "urgent" if i["severity"] == "urgent" else ""
    return f'<span class="pill {cls}">{status_label(i)}</span>'


def local_text(s: str):
    if re.search(r"[\u0600-\u06FF]", s or ""):
        st.markdown(f'<div class="ur">{s}</div>', unsafe_allow_html=True)
    else:
        st.write(s)


def issues_map(issues: list[dict], pin: tuple[float, float] | None = None, zoom: int = 15) -> folium.Map:
    m = folium.Map(location=pin or CENTER, zoom_start=zoom, control_scale=True, tiles="OpenStreetMap")
    for i in issues:
        if i.get("lat") is None:
            continue
        folium.CircleMarker([i["lat"], i["lng"]], radius=6 + 3 * (i["report_count"] ** 0.5), color="#ffffff", weight=2,
                            fill=True, fill_color=CAT_HEX.get(i["category"], "#6B7280"), fill_opacity=0.85,
                            tooltip=f"{i['issue_id']} · {i['summary']} · {i['report_count']} residents").add_to(m)
    if pin:
        folium.Marker(pin, tooltip="Problem location", icon=folium.Icon(color="orange", icon="map-marker", prefix="fa")).add_to(m)
    return m


def show_warnings():
    for w in st.session_state.pop("warnings", []):
        st.warning(w, icon="⚠️")
