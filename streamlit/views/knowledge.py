import streamlit as st

from core import agents, db, kb, ui
from core.config import secret

EXAMPLES = ["Street lights band hain, kisko complain karun?", "Gas ki bu aa rahi hai, kya karun?", "Who fixes potholes in a housing society?",
            "Can I find out why my complaint is delayed?"]


def page():
    st.title("Who handles what")
    st.markdown('<p class="sub">The rules Awaaz uses to send each complaint to the right place. Ask a question in Urdu, Roman Urdu or '
                'English, or browse by topic.</p>', unsafe_allow_html=True)
    ui.show_warnings()
    st.markdown('<div class="emerg"><b>In danger right now?</b> Call Rescue 1122 first. Gas leak: SNGPL 1199. Sparking or fallen wires: '
                'LESCO 118. Police: 15. Then report it here so there is a record.</div>', unsafe_allow_html=True)

    st.subheader("Ask a question")
    cols = st.columns(2)
    for k, ex in enumerate(EXAMPLES):
        col = cols[k % 2]
        if col.button(ex, use_container_width=True, key=f"ex-{ex}"):
            st.session_state.kb_question = ex
            st.session_state.kb_autorun = True
    with st.form("ask", clear_on_submit=False, border=False):
        question = st.text_input("Your question", key="kb_question", placeholder="e.g. Gutter ubal raha hai, kahan shikayat karun?",
                                 label_visibility="collapsed")
        asked = st.form_submit_button("Ask", type="primary")
    if (asked or st.session_state.get("kb_autorun")) and question.strip():
        with st.spinner("Looking through the rules…"):
            answer, mode, passages = agents.ask_kb(question.strip())
        st.session_state.kb_answer = (question.strip(), answer, mode, passages)
        st.session_state.kb_autorun = False
    if st.session_state.get("kb_answer"):
        q_, answer, mode, passages = st.session_state.kb_answer
        cited = [p for p in passages if p["chunk_id"] in answer.get("sources", [])]
        by = "fallback: closest rule" if mode == "rules" else mode
        st.markdown(f'<div class="answer">{ui.esc(answer["answer"]).replace(chr(10), "<br>")}<div style="margin-top:8px">'
                    + "".join(f'<span class="cite">{ui.esc(p["title"])}: {ui.esc(p["heading"])}</span>' for p in cited)
                    + f'</div><div style="color:#56606E;font-size:.8rem;margin-top:6px">Answered by {ui.esc(by)} from {len(passages)} matching rules.</div></div>',
                    unsafe_allow_html=True)
        with st.expander("The rules it read"):
            for p in passages:
                st.markdown(f"**{p['title']}: {p['heading']}**" + ("" if p["verified"] else " · unverified demo guidance"))
                st.write(p["content"])
        if st.button("Report this problem"):
            st.switch_page(st.session_state.pages["report"])

    st.subheader("Browse by topic")
    rows = kb.documents()
    st.caption(f"{len(rows)} rules in {len({r['doc_id'] for r in rows})} topics. All are demonstration guidance until checked with each department.")
    for doc_id in dict.fromkeys(r["doc_id"] for r in rows):
        group = [r for r in rows if r["doc_id"] == doc_id]
        with st.expander(group[0]["title"]):
            for r in group:
                st.markdown(f"**{r['heading']}**")
                st.write(r["content"])

    st.subheader("Departments")
    st.dataframe([{"Department": a["name"], "Handles": ", ".join(ui.CAT_LABEL.get(c, c) for c in a["categories"]),
                   "How Awaaz files": a["filing_channel"].replace("_", " "), "Helpline": a["helpline"] or "", "Target days": a["benchmark_days"]}
                  for a in db.authorities()], hide_index=True, use_container_width=True)
    if secret("DASHBOARD_PASSWORD") and st.session_state.get("dash_ok"):
        if st.button("Reload rules and departments from the repository"):
            kb._sync_once.clear()
            st.success(f"Updated: {kb.ensure_loaded()}")
