"""Awaaz: civic accountability copilot. Streamlit web channel (real database, real Claude agents)."""
import streamlit as st

st.set_page_config(page_title="Awaaz: civic accountability", page_icon="📣", layout="wide")

from core import db, kb  # noqa: E402  (after set_page_config)
from views import about, dashboard, knowledge, report, reports, track  # noqa: E402

pages = {
    "report": st.Page(report.page, title="Report a problem", icon="📣", default=True),
    "track": st.Page(track.page, title="Track an issue", icon="🔎", url_path="track"),
    "dashboard": st.Page(dashboard.page, title="Authority dashboard", icon="🏛️", url_path="dashboard"),
    "reports": st.Page(reports.page, title="Neighborhood reports", icon="📊", url_path="reports"),
    "kb": st.Page(knowledge.page, title="Knowledge base", icon="📚", url_path="knowledge"),
    "about": st.Page(about.page, title="About & status", icon="ℹ️", url_path="about"),
}
st.session_state.pages = pages

with st.sidebar:
    st.markdown("## 📣 Awaaz")
    st.caption("Your complaint doesn't end when you file it. It ends when it's fixed.")

try:
    if "kb_checked" not in st.session_state:
        kb.ensure_loaded()  # first run on a fresh database: load the knowledge base from the repo
        st.session_state.kb_checked = True
except Exception as e:
    st.error(f"Awaaz can't reach its database ({type(e).__name__}: {e}). Check DATABASE_URL in the app's Secrets; see the README.")
    st.stop()

st.navigation(list(pages.values())).run()
