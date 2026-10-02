"""Awaaz: civic accountability copilot. Streamlit web channel (real database, real AI agents)."""
import streamlit as st

from pathlib import Path  # noqa: E402

from PIL import Image  # noqa: E402

ASSETS = Path(__file__).parent / "assets"
st.set_page_config(page_title="Awaaz: report it once, follow it until it's fixed", page_icon=Image.open(ASSETS / "awaaz-favicon-64.png"), layout="wide")

from core import db, kb, ui  # noqa: E402  (after set_page_config)
from views import about, dashboard, knowledge, monitor, pulse, report, reports, track  # noqa: E402

ui.theme()
pages = {
    "pulse": st.Page(pulse.page, title="City pulse", icon=":material/monitor_heart:", default=True),
    "report": st.Page(report.page, title="Report a problem", icon=":material/campaign:", url_path="report"),
    "track": st.Page(track.page, title="Track an issue", icon=":material/package_2:", url_path="track"),
    "monitor": st.Page(monitor.page, title="Live monitor", icon=":material/query_stats:", url_path="monitor"),
    "dashboard": st.Page(dashboard.page, title="Authority dashboard", icon=":material/account_balance:", url_path="dashboard"),
    "reports": st.Page(reports.page, title="Neighborhood reports", icon=":material/description:", url_path="reports"),
    "kb": st.Page(knowledge.page, title="Who handles what", icon=":material/menu_book:", url_path="knowledge"),
    "about": st.Page(about.page, title="About and status", icon=":material/info:", url_path="about"),
}
st.session_state.pages = pages

with st.sidebar:
    mark = (ASSETS / "awaaz-mark-on-green.svg").read_text().replace('width="100" height="100"', 'width="58" height="58"')
    st.markdown('<div style="display:flex;align-items:center;gap:8px">' + mark +
                '<div><div style="font-family:Archivo,sans-serif;font-stretch:112%;font-weight:800;font-size:1.65rem;letter-spacing:.035em;color:#fff;line-height:1">AWAAZ</div>'
                '<div dir="rtl" style="font-family:\'Noto Nastaliq Urdu\',serif;font-weight:700;color:#F47B20;font-size:1.05rem;line-height:1.7;text-align:right">آواز</div></div></div>'
                '<p style="color:#C9DCCF;font-size:.9rem;margin-top:10px">Report it once. Follow it until a resident confirms it\'s fixed.</p>',
                unsafe_allow_html=True)

try:
    if "kb_checked" not in st.session_state:
        kb.ensure_loaded()  # syncs departments and any changed knowledge-base rules from the repo
        st.session_state.kb_checked = True
except Exception as e:
    st.error(f"Awaaz can't reach its database ({type(e).__name__}: {e}). Check DATABASE_URL in the app's Secrets; see the README.")
    st.stop()

st.navigation(list(pages.values())).run()
