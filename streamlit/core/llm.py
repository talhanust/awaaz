"""LLM calls with JSON validation and one corrective retry.

Provider is chosen by which key is present in Secrets (or forced with LLM_PROVIDER):
  ANTHROPIC_API_KEY → Claude    GEMINI_API_KEY → Google Gemini (free tier)    GROQ_API_KEY → Groq (free tier)    XAI_API_KEY → xAI Grok
Gemini, Groq and Grok are called through their OpenAI-compatible endpoints, so no extra packages are needed."""
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
    "xai": {"label": "Grok", "key": "XAI_API_KEY", "base": "https://api.x.ai/v1",
            "model": "grok-3-mini", "vision": False},  # if this name is retired, the app picks a current Grok model itself
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


_discovered: dict[str, str] = {}  # provider -> model picked automatically after a "model not found" error


def fast_model() -> str:
    p = provider()
    if p == "anthropic":
        return secret("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")
    if not p:
        return ""
    return secret("LLM_MODEL") or _discovered.get(p) or PROVIDERS[p]["model"]


def smart_model() -> str:
    p = provider()
    if p == "anthropic":
        return secret("CLAUDE_MODEL_SMART", "claude-sonnet-5")
    return secret("LLM_MODEL_SMART") or fast_model() if p else ""


def _error_message(r) -> str:
    try:
        j = r.json()
        j = j[0] if isinstance(j, list) and j else j
        return str((j.get("error") or {}).get("message") or j)[:220]
    except Exception:
        return (r.text or "")[:220]


def available_models() -> list[str]:
    """Models this key can use (OpenAI-compatible providers only)."""
    p = provider()
    if not p or p == "anthropic":
        return []
    cfg = PROVIDERS[p]
    r = requests.get(f"{cfg['base']}/models", timeout=20, headers={"Authorization": f"Bearer {secret(cfg['key'])}"})
    if not r.ok:
        raise RuntimeError(f"{cfg['label']} {r.status_code}: {_error_message(r)}")
    return sorted({(m.get("id") or "").removeprefix("models/") for m in r.json().get("data", []) if m.get("id")})


def _pick_model(p: str, ids: list[str]) -> str | None:
    if p == "gemini":
        bad = ("image", "tts", "audio", "live", "embed", "vision", "thinking", "exp", "learnlm", "gemma")
        flash = [i for i in ids if "flash" in i and not any(b in i for b in bad)]
        def rank(i):  # prefer full Flash over Flash-Lite (better Urdu), then newest version, then stable over preview
            nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", i)] or [0]
            return ("lite" not in i, nums[0], "preview" not in i, -len(i))
        return max(flash, key=rank) if flash else None
    if p == "xai":
        grok = [i for i in ids if i.startswith("grok") and not any(b in i for b in ("image", "vision", "imagine", "code"))]
        def rank(i):  # prefer fast/mini variants (cheaper, quick), then newest version
            nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", i)] or [0]
            return (any(t in i for t in ("fast", "mini")), nums[0], -len(i))
        return max(grok, key=rank) if grok else None
    if p == "groq":
        chat = [i for i in ids if not any(b in i for b in ("whisper", "guard", "tts", "embed"))]
        return next((i for i in chat if "70b" in i), chat[0] if chat else None)
    return None


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
    body = {"model": model, "messages": messages, "temperature": 0.2,
            # thinking models spend tokens reasoning before answering; leave room so the answer isn't cut off
            "max_tokens": max(max_tokens, 1024) if p == "gemini" else max_tokens}
    if p == "gemini":  # classification and drafting don't need long reasoning: turn it off (2.5) or keep it minimal (newer)
        body["reasoning_effort"] = "none" if "2.5" in model else "low"
    for attempt in range(3):  # free tiers rate-limit: back off briefly on 429
        r = requests.post(f"{cfg['base']}/chat/completions", timeout=60,
                          headers={"Authorization": f"Bearer {secret(cfg['key'])}", "Content-Type": "application/json"}, json=body)
        if r.status_code == 400 and "reasoning" in (r.text or "").lower() and "reasoning_effort" in body:
            body.pop("reasoning_effort")  # this model doesn't accept the setting: retry without it
            continue
        if r.status_code == 429 and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        msg = "" if r.ok else _error_message(r)
        not_found = r.status_code == 404 or "not found" in msg.lower() or "not supported" in msg.lower()
        if not r.ok and not_found and not secret("LLM_MODEL") and p not in _discovered:
            try:  # the default model was retired or isn't on this tier: switch to a current one once
                picked = _pick_model(p, available_models())
            except Exception:
                picked = None
            if picked and picked != model:
                _discovered[p] = picked
                return _complete(system, content, picked, max_tokens)
        if not r.ok:
            raise RuntimeError(f"{cfg['label']} {r.status_code}: {msg}")
        choice = (r.json().get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content")
        if not text:  # e.g. the whole budget went on reasoning
            raise RuntimeError(f"{cfg['label']} returned no text (finish reason: {choice.get('finish_reason', 'unknown')})")
        return text
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


def test_connection() -> tuple[bool, str]:
    """Tiny round trip for the status page."""
    try:
        d = ask_json('Reply with ONLY this JSON: {"ok": true}', {"ping": 1}, lambda d: None if d.get("ok") is True else "no ok", max_tokens=200)
        return True, f"{label()} answered using {fast_model()}"
    except Exception as e:
        return False, str(e)[:300]


def vision_enabled() -> bool:
    p = provider()
    return p == "anthropic" or bool(p and PROVIDERS[p].get("vision"))


def describe_image(data: bytes, media_type: str) -> str:
    prompt = ("A citizen sent this photo as a civic complaint. In one factual English sentence, describe the visible civic problem "
              "(e.g. pothole, sewage overflow, exposed wires, garbage pile). Do not guess location or cause. If no civic problem is visible, say so.")
    return _complete(None, [{"image": data, "media_type": media_type}, {"text": prompt}], fast_model(), 200).strip()
