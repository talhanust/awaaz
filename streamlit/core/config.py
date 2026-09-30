"""Settings come from Streamlit secrets (Streamlit Cloud) or environment variables (local runs)."""
import os
import streamlit as st


def secret(name: str, default: str | None = None) -> str | None:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file locally
        pass
    return os.environ.get(name, default)


CITY = "Lahore"
CENTER = (31.4697, 74.2728)  # Johar Town, Lahore
