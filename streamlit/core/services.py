"""Outside services: reverse geocoding (OpenStreetMap Nominatim), speech-to-text (OpenAI Whisper), email (Resend)."""
import time

import requests
import streamlit as st

from .config import secret

_last_call = [0.0]


@st.cache_data(ttl=86400, show_spinner=False)
def reverse_geocode(lat: float, lng: float) -> dict:
    """Free Nominatim lookup (max 1 request/second). Returns city, sector and a readable landmark."""
    wait = 1.1 - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()
    fallback = {"city": None, "sector": f"near {lat:.4f}, {lng:.4f}", "landmark": f"near {lat:.4f}, {lng:.4f}"}
    try:
        r = requests.get("https://nominatim.openstreetmap.org/reverse", timeout=8,
                         params={"format": "jsonv2", "lat": lat, "lon": lng, "zoom": 17, "accept-language": "en"},
                         headers={"User-Agent": "Awaaz/0.2 (civic complaints pilot)"})
        a = r.json().get("address", {})
    except Exception:
        return fallback
    sector = a.get("neighbourhood") or a.get("quarter") or a.get("suburb") or a.get("residential") or fallback["sector"]
    landmark = ", ".join(x for x in [a.get("road"), a.get("neighbourhood") or a.get("suburb")] if x) or fallback["landmark"]
    return {"city": a.get("city") or a.get("town") or a.get("county") or a.get("state_district"), "sector": sector, "landmark": landmark}


def stt_enabled() -> bool:
    return bool(secret("OPENAI_API_KEY"))


def transcribe(audio: bytes) -> str | None:
    key = secret("OPENAI_API_KEY")
    if not key:
        return None
    r = requests.post("https://api.openai.com/v1/audio/transcriptions", timeout=60, headers={"Authorization": f"Bearer {key}"},
                      files={"file": ("voice.wav", audio, "audio/wav")},
                      data={"model": "whisper-1", "prompt": "Civic complaint from Pakistan, may mix Urdu, Punjabi and English."})
    if not r.ok:
        return None
    text = r.json().get("text", "").strip()
    return text if len(text.split()) >= 3 else None


def email_enabled() -> bool:
    return bool(secret("RESEND_API_KEY") and secret("FILING_FROM_EMAIL"))


def send_email(to: list[str], subject: str, text: str, cc: list[str] | None = None) -> bool:
    if not email_enabled() or not to:
        return False
    r = requests.post("https://api.resend.com/emails", timeout=15, headers={"Authorization": f"Bearer {secret('RESEND_API_KEY')}"},
                      json={"from": secret("FILING_FROM_EMAIL"), "to": to, "cc": cc or None, "subject": subject, "text": text})
    return r.ok
