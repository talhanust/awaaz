import streamlit as st

from core import db, kb, ui
from core.config import secret


def page():
    ui.css()
    st.title("Knowledge base")
    st.caption("The Jurisdiction Router searches these rules to decide which department is responsible, and cites what it used. "
               f"Search mode: **{'hybrid (embeddings + keywords)' if kb.embeddings_enabled() else 'keywords (add a Voyage key for hybrid search)'}**.")
    examples = ["street lights band hain", "kachra naali band", "cantt mein gaddha", "gas ki bu"]
    cols = st.columns(len(examples))
    for col, ex in zip(cols, examples):
        if col.button(ex, use_container_width=True):
            st.session_state.kbq = ex
    query = st.text_input("Search in Urdu, Roman Urdu or English", key="kbq", placeholder="e.g. street lights band hain")
    rows = kb.retrieve(query, k=6) if query.strip() else db.q(
        "select c.chunk_id, d.title, c.heading, c.content, d.verified, c.authority_ids, null::float score from kb_chunks c join kb_documents d using (doc_id) order by c.chunk_id")
    if query.strip() and not rows:
        st.warning('No passages match. Try "street lights", "cantt" or "kachra naali".')
    for r in rows:
        with st.container(border=True):
            tag = "" if r["verified"] else ' <span class="pill esc">unverified demo</span>'
            score = f" `score {r['score']:.4f}`" if r.get("score") is not None else ""
            st.markdown(f"**{r['title']}** · {r['heading']}{score}{tag}", unsafe_allow_html=True)
            st.write(r["content"])
            st.caption(r["chunk_id"])
    st.caption("These passages were written for the prototype and aren't yet checked against official sources.")
    pw = secret("DASHBOARD_PASSWORD")
    if pw and st.session_state.get("dash_ok"):
        if st.button("Reload knowledge base from the repository"):
            with st.spinner("Loading…"):
                n = kb.ingest()
            st.success(f"Loaded {n} passages.")
