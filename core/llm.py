"""LLM calls with JSON validation and one corrective retry.

Provider is chosen by which key is present in Secrets (or forced with LLM_PROVIDER):
  ANTHROPIC_API_KEY → Claude      GEMINI_API_KEY → Google Gemini (free tier)      GROQ_API_KEY → Groq (free tier)
Gemini and Groq are called through their OpenAI-compatible endpoints, so no extra packages are needed."""
import base64
import json
import re
import time

import requests
import streamlit as st

from .config import secret

PROVIDERS = {
    "anthropic": {"label": "Claude", "key": "ANTHROPIC_API_KEY"},
    "gemini": {"label": "Gemini", "key": "GEMINI_API_KEY", "base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-2.5-flash", "vision": True},
    "groq": {"label": "Groq", "key": "GROQ_API_KEY", "base": "https://api.groq.com/openai/v1",
             "model": "llama-3.3-70b-versatile", "vision": False},
}


def provider() -> str | None:
    forced = (secret("LLM_PROVIDER") or "").lower()
    if forced in PROVIDERS and secret(PROVIDERS[forced]["key"]):
        return forced
    return next((p for p, cfg in PROVIDERS.items() if secret(cfg["key"])), None)


def enabled() -> bool:
    return provider() is not None


def label() -> str:
    p = provider()
    return PROVIDERS[p]["label"] if p else "off"


def fast_model() -> str:
    p = provider()
    if p == "anthropic":
        return secret("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")
    return secret("LLM_MODEL", PROVIDERS[p]["model"]) if p else ""


def smart_model() -> str:
    p = provider()
    if p == "anthropic":
        return secret("CLAUDE_MODEL_SMART", "claude-sonnet-5")
    return secret("LLM_MODEL_SMART", fast_model()) if p else ""


# ---------------- transport ----------------
@st.cache_resource(show_spinner=False)
def _anthropic(key: str):
    import anthropic
    return anthropic.Anthropic(api_key=key, timeout=60, max_retries=2)


def _complete(system: str | None, content, model: str, max_tokens: int) -> str:
    """content is a string, or a list of parts: {"text": ...} / {"image": bytes, "media_type": ...}."""
    p = provider()
    parts = [{"text": content}] if isinstance(content, str) else content
    if p == "anthropic":
        blocks = [{"type": "image", "source": {"type": "base64", "media_type": x["media_type"], "data": base64.b64encode(x["image"]).decode()}}
                  if "image" in x else {"type": "text", "text": x["text"]} for x in parts]
        kwargs = {"system": system} if system else {}
        msg = _anthropic(secret("ANTHROPIC_API_KEY")).messages.create(model=model, max_tokens=max_tokens,
                                                                      messages=[{"role": "user", "content": blocks}], **kwargs)
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    cfg = PROVIDERS[p]
    user = [{"type": "image_url", "image_url": {"url": f"data:{x['media_type']};base64,{base64.b64encode(x['image']).decode()}"}}
            if "image" in x else {"type": "text", "text": x["text"]} for x in parts]
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": user if any("image" in x for x in parts) else parts[0]["text"] if len(parts) == 1 else user}]
    for attempt in range(3):  # free tiers rate-limit: back off briefly on 429
        r = requests.post(f"{cfg['base']}/chat/completions", timeout=60,
                          headers={"Authorization": f"Bearer {secret(cfg['key'])}", "Content-Type": "application/json"},
                          json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2})
        if r.status_code == 429 and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        if not r.ok:
            raise RuntimeError(f"{cfg['label']} API error {r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]["content"] or ""
    raise RuntimeError(f"{cfg['label']} rate limit reached")


def _strip(s: str) -> str:
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S).strip()  # some open models emit reasoning tags
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    m = re.search(r"\{.*\}", s, re.S)
    return m.group(0) if m else s


def ask_json(system: str, payload: dict, validate, model: str | None = None, max_tokens: int = 1024) -> dict:
    """validate(data) returns None when valid, else a short error string."""
    last = ""
    for attempt in range(2):
        content = "INPUT:\n" + json.dumps(payload, ensure_ascii=False, indent=1, default=str)
        if attempt:
            content += f"\n\nYour previous reply was invalid ({last}). Reply with ONLY the JSON object."
        text = _complete(system, content, model or fast_model(), max_tokens)
        try:
            data = json.loads(_strip(text))
            err = validate(data)
            if not err:
                return data
            last = err
        except json.JSONDecodeError:
            last = "not valid JSON"
    raise ValueError(f"model output failed validation: {last}")


def vision_enabled() -> bool:
    p = provider()
    return p == "anthropic" or bool(p and PROVIDERS[p].get("vision"))


def describe_image(data: bytes, media_type: str) -> str:
    prompt = ("A citizen sent this photo as a civic complaint. In one factual English sentence, describe the visible civic problem "
              "(e.g. pothole, sewage overflow, exposed wires, garbage pile). Do not guess location or cause. If no civic problem is visible, say so.")
    return _complete(None, [{"image": data, "media_type": media_type}, {"text": prompt}], fast_model(), 200).strip()
