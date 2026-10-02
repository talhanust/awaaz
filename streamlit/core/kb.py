"""Knowledge base: parse kb/<city>/*.md, embed (optional, Voyage AI), load into Postgres, and search."""
import re
from pathlib import Path

import requests
import streamlit as st

from . import db
from .config import secret

KB_DIR = Path(__file__).resolve().parents[2] / "kb"
STOP = {"the", "a", "an", "is", "are", "in", "on", "at", "of", "to", "and", "or", "for", "with", "hai", "hain", "ka", "ki", "ke",
        "mein", "se", "pe", "par", "ko", "yeh", "woh"}
SYN = {"bijli": "electricity", "batti": "light", "batian": "light", "lights": "light", "gutter": "sewerage sewer drain", "naali": "drain",
       "nali": "drain", "kachra": "garbage", "kachre": "garbage", "koora": "garbage", "gaddha": "pothole", "sadak": "road", "pani": "water",
       "nalka": "tap water", "cantt": "cantonment", "darakht": "tree", "taar": "wire", "chingari": "sparking", "بجلی": "electricity",
       "بتی": "light", "گٹر": "sewerage drain", "نالی": "drain", "کچرا": "garbage", "سڑک": "road", "پانی": "water", "درخت": "tree",
       "گیس": "gas"}


def parse(doc_id: str, raw: str) -> tuple[dict, list[dict]]:
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
    if not m:
        raise ValueError(f"{doc_id}: missing front matter")
    meta = {k.strip(): v.strip() for k, _, v in (l.partition(":") for l in m.group(1).splitlines()) if v}
    doc = {"doc_id": doc_id, "city": meta["city"], "title": meta["title"], "source": meta.get("source", ""),
           "source_type": meta.get("source_type", "demo"), "verified": meta.get("verified") == "true",
           "authority_ids": [a.strip() for a in meta.get("authorities", "").split(",") if a.strip()]}
    chunks = []
    for sec in (s.strip() for s in re.split(r"^## +", m.group(2), flags=re.M) if s.strip()):
        heading, _, body = sec.partition("\n")
        chunks.append({"chunk_id": f"{doc_id}#{len(chunks) + 1}", "heading": heading.strip(), "content": body.strip()})
    return doc, chunks


def keyword_query(text: str) -> str:
    words = []
    for w in re.findall(r"\w{3,}", text.lower()):
        if w in STOP:
            continue
        words.append(w)
        words += SYN.get(w, "").split()
    return " or ".join(dict.fromkeys(words))[:600]


def embeddings_enabled() -> bool:
    return bool(secret("VOYAGE_API_KEY"))


def embed(texts: list[str], input_type: str) -> list[list[float]] | None:
    key = secret("VOYAGE_API_KEY")
    if not key or not texts:
        return None
    try:
        r = requests.post("https://api.voyageai.com/v1/embeddings", timeout=20,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"input": texts, "model": secret("VOYAGE_MODEL", "voyage-4"), "input_type": input_type, "output_dimension": 1024})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
    except Exception as e:  # retrieval still works keyword-only
        st.session_state.setdefault("warnings", []).append(f"Embeddings unavailable ({e}); using keyword search.")
        return None


def embed_one(text: str, input_type: str) -> list[float] | None:
    out = embed([text], input_type)
    return out[0] if out else None


def ingest() -> int:
    total = 0
    for md in sorted(KB_DIR.glob("*/*.md")):
        doc, chunks = parse(f"{md.parent.name}/{md.stem}", md.read_text(encoding="utf-8"))
        vectors = embed([f"{doc['title']}. {c['heading']}. {c['content']}" for c in chunks], "document")
        db.kb_upsert(doc, chunks, vectors)
        total += len(chunks)
    return total


def _repo_docs() -> list[tuple[dict, list[dict]]]:
    return [parse(f"{md.parent.name}/{md.stem}", md.read_text(encoding="utf-8")) for md in sorted(KB_DIR.glob("*/*.md"))]


def _fingerprint() -> str:
    import hashlib
    h = hashlib.sha256()
    for f in sorted(KB_DIR.glob("*/*")):
        h.update(f.name.encode()); h.update(f.read_bytes())
    return h.hexdigest()


def sync() -> dict:
    """Bring the database in line with the repo: departments from departments.toml, and only the KB documents that changed."""
    import tomllib
    stats = {"departments": 0, "updated": 0, "removed": 0}
    for toml_file in KB_DIR.glob("*/departments.toml"):
        stats["departments"] += db.sync_authorities(tomllib.loads(toml_file.read_text(encoding="utf-8"))["department"])
    current = db.kb_snapshot()
    repo = _repo_docs()
    repo_ids = {d["doc_id"] for d, _ in repo}
    for doc, chunks in repo:
        same = len([c for c in current.values() if c[0] == doc["doc_id"]]) == len(chunks) and all(
            current.get(c["chunk_id"]) == (doc["doc_id"], c["heading"], c["content"]) for c in chunks)
        if not same:
            vectors = embed([f"{doc['title']}. {c['heading']}. {c['content']}" for c in chunks], "document")
            db.kb_upsert(doc, chunks, vectors)
            stats["updated"] += 1
    stale = sorted({v[0] for v in current.values()} - repo_ids)
    db.kb_delete_docs(stale)
    stats["removed"] = len(stale)
    return stats


@st.cache_resource(show_spinner="Updating the knowledge base…")
def _sync_once(fingerprint: str) -> dict:  # reruns only when the KB files in the repo change
    return sync()


def ensure_loaded() -> dict:
    return _sync_once(_fingerprint())


def documents() -> list[dict]:
    """All passages grouped for browsing."""
    return db.q("""select c.chunk_id, d.doc_id, d.title, c.heading, c.content, d.verified from kb_chunks c join kb_documents d using (doc_id)
                   where c.city = %s order by d.doc_id, c.chunk_id""", ("Lahore",))


def retrieve(text: str, k: int = 6, authority_ids: list[str] | None = None) -> list[dict]:
    return db.match_kb(text, keyword_query(text), embed_one(text, "query"), k, authority_ids)
