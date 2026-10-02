"""LLM calls with JSON validation and one corrective retry.

Add one or more keys to Secrets. The first available provider (or LLM_PROVIDER) answers; if it's busy or out of quota,
the next provider with a key takes over automatically:
  ANTHROPIC_API_KEY (Claude) · GEMINI_API_KEY (free tier) · MISTRAL_API_KEY (free tier) · GROQ_API_KEY (free tier)
  OPENROUTER_API_KEY (free models) · XAI_API_KEY (Grok)
All except Claude are called through OpenAI-compatible endpoints, so no extra packages are needed."""
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
    "mistral": {"label": "Mistral", "key": "MISTRAL_API_KEY", "base": "https://api.mistral.ai/v1",
                "model": "mistral-small-latest", "vision": False},
    "groq": {"label": "Groq", "key": "GROQ_API_KEY", "base": "https://api.groq.com/openai/v1",
             "model": "llama-3.3-70b-versatile", "vision": False},
    "openrouter": {"label": "OpenRouter", "key": "OPENROUTER_API_KEY", "base": "https://openrouter.ai/api/v1",
                   "model": "meta-llama/llama-3.3-70b-instruct:free", "vision": False},
    "xai": {"label": "Grok", "key": "XAI_API_KEY", "base": "https://api.x.ai/v1",
            "model": "grok-3-mini", "vision": False},  # if this name is retired, the app picks a current Grok model itself
}


def provider() -> str | None:
    forced = (secret("LLM_PROVIDER") or "").lower()
    if forced in PROVIDERS and secret(PROVIDERS[forced]["key"]):
        return forced
    return next((p for p, cfg in PROVIDERS.items() if secret(cfg["key"])), None)


def chain(vision: bool = False) -> list[str]:
    """Primary provider first, then every other provider that has a key: the automatic fallback order."""
    p = provider()
    if not p:
        return []
    rest = [q for q, cfg in PROVIDERS.items() if q != p and secret(cfg["key"])]
    out = [p] + rest
    return [q for q in out if q == "anthropic" or PROVIDERS[q].get("vision")] if vision else out


def enabled() -> bool:
    return provider() is not None


def used_label() -> str:
    """Name of the provider that answered the last call (may be a backup)."""
    return PROVIDERS[_last_used["provider"]]["label"] if _last_used.get("provider") in PROVIDERS else label()


def label() -> str:
    p = provider()
    return PROVIDERS[p]["label"] if p else "off"


_discovered: dict[str, str] = {}  # provider -> model picked automatically after a "model not found" error
_busy_until: dict[str, float] = {}  # model -> time until which we skip it after an overload (503) error
GEMINI_BACKUPS = ["gemini-2.5-flash-lite", "gemini-3-flash-preview", "gemini-3.1-flash-lite"]


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


def available_models(p: str | None = None) -> list[str]:
    """Models this key can use (OpenAI-compatible providers only)."""
    p = p or provider()
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
    if p == "openrouter":
        free = [i for i in ids if i.endswith(":free")]
        return next((i for i in free if "llama-3.3-70b" in i), next((i for i in free if "70b" in i or "gemma" in i), free[0] if free else None))
    if p == "mistral":
        return next((i for i in ids if i.startswith("mistral-small")), next((i for i in ids if i.startswith("mistral-")), None))
    if p == "groq":
        chat = [i for i in ids if not any(b in i for b in ("whisper", "guard", "tts", "embed"))]
        return next((i for i in chat if "70b" in i), chat[0] if chat else None)
    return None


# ---------------- transport ----------------
@st.cache_resource(show_spinner=False)
def _anthropic(key: str):
    import anthropic
    return anthropic.Anthropic(api_key=key, timeout=60, max_retries=2)


def _model_for(p: str, smart: bool) -> str:
    if p == provider():
        return smart_model() if smart else fast_model()
    if p == "anthropic":
        return secret("CLAUDE_MODEL_SMART", "claude-sonnet-5") if smart else secret("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")
    return _discovered.get(p) or PROVIDERS[p]["model"]


def _complete(system: str | None, content, model: str, max_tokens: int) -> str:
    """Try the primary provider, then each backup provider with a key, until one answers."""
    smart = model == smart_model() and smart_model() != fast_model()
    needs_vision = not isinstance(content, str) and any("image" in x for x in content)
    errors = []
    for k, p in enumerate(chain(vision=needs_vision)):
        m = model if k == 0 else _model_for(p, smart)
        try:
            text = _complete_gemini(system, content, m, max_tokens) if p == "gemini" else _complete_one(system, content, m, max_tokens, p)
            _last_used["provider"] = p
            return text
        except Exception as e:  # busy, out of quota, bad key or network: try the next provider
            errors.append(f"{PROVIDERS[p]['label']}: {str(e)[:160]}")
    raise RuntimeError(" | ".join(errors) or "no AI provider configured")


def _complete_gemini(system: str | None, content, model: str, max_tokens: int) -> str:
    """Gemini: if a model is overloaded, try backup Gemini models the key can use, and remember for 5 minutes."""
    p = "gemini"
    chain = [m for m in [model] + GEMINI_BACKUPS if _busy_until.get(m, 0) < time.time()] or [model]
    chain = list(dict.fromkeys(chain))
    last = None
    for m in chain:
        try:
            text = _complete_one(system, content, m, max_tokens, "gemini")
            _last_used["model"] = m
            return text
        except RuntimeError as e:
            last = e
            msg = str(e)
            if " 503" in msg or " 500" in msg or "high demand" in msg or "overloaded" in msg.lower() or "rate limit" in msg:
                _busy_until[m] = time.time() + 300  # skip this model for 5 minutes
                continue
            if " 404" in msg or "not found" in msg.lower():
                continue  # backup name not available on this key: try the next
            raise
    raise last


_last_used: dict[str, str] = {}


def _complete_one(system: str | None, content, model: str, max_tokens: int, p: str | None = None) -> str:
    """One call to one provider. content is a string, or a list of parts: {"text": ...} / {"image": bytes, "media_type": ...}."""
    p = p or provider()
    parts = [{"text": content}] if isinstance(content, str) else content
    if p == "anthropic":
        blocks = [{"type": "image", "source": {"type": "base64", "media_type": x["media_type"], "data": base64.b64encode(x["image"]).decode()}}
                  if "image" in x else {"type": "text", "text": x["text"]} for x in parts]
        kwargs = {"system": system} if system else {}
        msg = _anthropic(secret("ANTHROPIC_API_KEY")).messages.create(model=model, max_tokens=max_tokens,
                                                                      messages=[{"role": "user", "content": blocks}], **kwargs)
        _last_used["model"] = model
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
        if r.status_code in (429, 503) and attempt < 2:
            time.sleep(1.5 * (attempt + 1))  # short back-off; overloads are often momentary
            continue
        msg = "" if r.ok else _error_message(r)
        not_found = r.status_code == 404 or "not found" in msg.lower() or "not supported" in msg.lower()
        if not r.ok and not_found and p not in _discovered and (p != provider() or (not secret("LLM_MODEL") and model == fast_model())):
            try:  # the default model was retired or isn't on this tier: switch to a current one once
                picked = _pick_model(p, available_models(p))
            except Exception:
                picked = None
            if picked and picked != model:
                _discovered[p] = picked
                return _complete_one(system, content, picked, max_tokens, p)
        if not r.ok:
            raise RuntimeError(f"{cfg['label']} {r.status_code}: {msg}")
        choice = (r.json().get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content")
        if not text:  # e.g. the whole budget went on reasoning
            raise RuntimeError(f"{cfg['label']} returned no text (finish reason: {choice.get('finish_reason', 'unknown')})")
        _last_used["model"] = model  # the model that actually answered
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
    """One tiny round trip for the status page, reporting which provider and model answered."""
    try:
        _last_used.clear()
        ask_json('Reply with ONLY this JSON: {"ok": true}', {"ping": 1}, lambda d: None if d.get("ok") is True else "no ok", max_tokens=200)
    except Exception as e:
        return False, str(e)[:500]
    used_p, used_m = _last_used.get("provider"), _last_used.get("model") or fast_model()
    backups = [PROVIDERS[q]["label"] for q in chain()[1:]]
    missing = next((PROVIDERS[q]["key"] for q in ("mistral", "groq", "gemini") if not secret(PROVIDERS[q]["key"])), None)
    tail = (f" Backups ready: {', '.join(backups)}." if backups else
            f" Tip: add a second free key (e.g. {missing}) as an automatic backup." if missing else "")
    if used_p and used_p != provider():
        return True, f"{label()} is busy, so the backup {PROVIDERS[used_p]['label']} answered (model {used_m}).{tail}"
    note = "" if used_m == fast_model() else f" (backup model; {fast_model()} is busy right now)"
    return True, f"{label()} answered using {used_m}{note}.{tail}"


def vision_enabled() -> bool:
    return bool(chain(vision=True))


def describe_image(data: bytes, media_type: str) -> str:
    prompt = ("A citizen sent this photo as a civic complaint. In one factual English sentence, describe the visible civic problem "
              "(e.g. pothole, sewage overflow, exposed wires, garbage pile). Do not guess location or cause. If no civic problem is visible, say so.")
    return _complete(None, [{"image": data, "media_type": media_type}, {"text": prompt}], fast_model(), 200).strip()
