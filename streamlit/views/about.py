import streamlit as st

from core import db, kb, llm, services, ui

GITHUB = "https://github.com/talhanust/awaaz"


def page():

    st.title("About Awaaz")
    st.markdown("*Your complaint doesn't end when you file it. It ends when it's fixed.*")
    st.graphviz_chart("""digraph { rankdir=LR; bgcolor="transparent";
      node [shape=box, style="rounded,filled", fillcolor="#121D33", fontcolor="white", fontname="Helvetica", fontsize=11, color="#121D33"];
      edge [color="#8894A8"];
      in [label="Resident\\nweb or WhatsApp", fillcolor="#E9EEF6", fontcolor="#121D33"];
      a1 [label="1 · Classifier"]; a1b [label="1b · Router (RAG)", fillcolor="#D98E04", color="#D98E04", fontcolor="#1b1200"];
      a2 [label="2 · Matcher"]; a3 [label="3 · Drafter & Filer"]; a4 [label="4 · Tracker & Escalator"]; a5 [label="5 · Pattern Analyst"];
      kb [label="Knowledge base\\npgvector", shape=cylinder, fillcolor="#FBEBCB", fontcolor="#7A4F00", color="#D98E04"];
      out [label="Department queue\\n& public reports", fillcolor="#E9EEF6", fontcolor="#121D33"];
      in -> a1 -> a1b -> a2 -> a3 -> a4 -> a5 -> out; kb -> a1b [style=dashed]; kb -> a3 [style=dashed]; }""", use_container_width=True)
    st.subheader("Live system status")
    try:
        n = db.one("select count(*) n from issues")["n"]
        db_ok = f"connected · {n} issues · {db.kb_count()} knowledge passages"
    except Exception as e:
        db_ok = f"not connected ({type(e).__name__})"
    rows = [("Database (Postgres + PostGIS + pgvector)", db_ok),
            ("AI agents", (f"on · {llm.label()} · {llm.fast_model()}" + (f" / {llm.smart_model()}" if llm.smart_model() != llm.fast_model() else "")
                           + (f" · backups: {', '.join(llm.PROVIDERS[q]['label'] for q in llm.chain()[1:])}" if len(llm.chain()) > 1 else " · no backup provider"))
             if llm.enabled() else "off: using labelled fallback rules"),
            ("Embeddings for RAG (Voyage AI)", "on · hybrid search" if kb.embeddings_enabled() else "off · keyword search"),
            ("Voice notes (Whisper)", "on" if services.stt_enabled() else "off · text and photos only"),
            ("Email filing (Resend)", "on" if services.email_enabled() else "off · residents get ready-to-submit complaints")]
    st.dataframe([{"Component": a, "Status": b} for a, b in rows], hide_index=True, use_container_width=True)
    if llm.enabled() and st.button("Test AI connection"):
        with st.spinner(f"Asking {llm.label()}…"):
            ok, msg = llm.test_connection()
        (st.success if ok else st.error)(msg)
        if not ok and llm.provider() != "anthropic":
            try:
                models = [m for m in llm.available_models() if any(t in m for t in ("flash", "llama", "grok", "mistral", ":free"))][:15]
                if models:
                    st.info("Models your key can use: " + ", ".join(models) +
                            ". To force one, add a line like LLM_MODEL = \"" + models[0] + "\" to Secrets.")
            except Exception as e:
                st.caption(f"Couldn't list models: {str(e)[:200]}")
    st.subheader("Honest limits")
    st.markdown("""
- Knowledge-base rules and department contacts are **demo placeholders**, to be verified with departments before a pilot.
- Most departments have no filing API: Awaaz emails where possible and otherwise hands the resident a ready-to-submit complaint.
- This web app is one channel. The WhatsApp channel (same database and agents) is in the repository's Next.js app.
""")
    st.link_button("Source code and README on GitHub", GITHUB)
