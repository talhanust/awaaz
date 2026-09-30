"""Postgres access (Supabase in production). Uses the same schema, RPCs and views as the WhatsApp app."""
import hashlib
from datetime import datetime, timezone

import psycopg
import streamlit as st
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import CITY, secret

ISSUE_COLUMNS = {
    "status", "escalation_tier", "filing_channel", "formatted_complaint", "pending_escalation", "checkin_sent_at",
    "reminder_sent", "verification_requested_at", "expected_by", "resolved_at", "resolution_proof", "routing_basis",
}


@st.cache_resource(show_spinner=False)
def _connect(url: str):
    # prepare_threshold=None keeps it compatible with Supabase's connection pooler.
    return psycopg.connect(url, autocommit=True, prepare_threshold=None, row_factory=dict_row, connect_timeout=10)


def _conn():
    url = secret("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Add it in the app's Secrets (see the README).")
    c = _connect(url)
    if c.closed or c.broken:
        _connect.clear()
        c = _connect(url)
    return c


def q(sql: str, params=None) -> list[dict]:
    for attempt in range(2):
        try:
            with _conn().cursor() as cur:
                cur.execute(sql, params or ())
                return cur.fetchall() if cur.description else []
        except psycopg.OperationalError:
            _connect.clear()
            if attempt:
                raise
    return []


def one(sql: str, params=None) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def vec(v: list[float] | None) -> str | None:
    return None if v is None else "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- citizens ----------------
def citizen_hash(phone: str) -> str:
    salt = secret("CITIZEN_HASH_SALT", "awaaz-demo-salt")
    return hashlib.sha256((phone.strip() + salt).encode()).hexdigest()


def get_or_create_citizen(phone: str, language: str = "ur-Latn") -> str:
    phone = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    h = citizen_hash(phone)
    q("insert into citizens (citizen_hash, phone, language) values (%s, %s, %s) on conflict do nothing", (h, phone, language))
    row = one("select citizen_hash from citizens where citizen_hash = %s or phone = %s", (h, phone))
    return row["citizen_hash"]


def reports_today(h: str) -> int:
    return one("select count(*) n from reports where citizen_hash = %s and created_at > now() - interval '1 day'", (h,))["n"]


def is_reporter(issue_id: str, h: str) -> bool:
    return one("select 1 from reports where issue_id = %s and citizen_hash = %s", (issue_id, h)) is not None


def reporter_count(issue_id: str) -> int:
    return one("select count(*) n from reports where issue_id = %s", (issue_id,))["n"]


# ---------------- reference data ----------------
@st.cache_data(ttl=600, show_spinner=False)
def authorities(city: str = CITY) -> list[dict]:
    return q("select * from authorities where city = %s order by name", (city,))


def authority(aid: str) -> dict | None:
    return next((a for a in authorities() if a["authority_id"] == aid), None)


# ---------------- issues ----------------
def match_candidates(category: str, lat: float, lng: float) -> list[dict]:
    return q("select * from match_candidates(%s, %s, %s, %s)", (CITY, category, lat, lng))


def semantic_candidates(embedding: list[float], lat: float, lng: float) -> list[dict]:
    return q("select * from semantic_candidates(%s, %s::vector, %s, %s)", (CITY, vec(embedding), lat, lng))


def create_issue(*, sector, category, severity, authority_id, summary, lat, lng, citizen, language, input_type, raw_text) -> str:
    return one("select create_issue(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) as id",
               (CITY, sector, category, severity, authority_id, summary, lat, lng, citizen, language, input_type, raw_text, None))["id"]


def add_voice(issue_id, citizen, language, input_type, raw_text, lat, lng) -> int:
    return one("select add_voice(%s,%s,%s,%s,%s,%s,%s,%s) as n", (issue_id, citizen, language, input_type, raw_text, None, lat, lng))["n"]


def get_issue(issue_id: str) -> dict | None:
    return one("select *, st_y(geo_public::geometry) lat, st_x(geo_public::geometry) lng from issues where upper(issue_id) = upper(%s)",
               (issue_id.strip(),))


def update_issue(issue_id: str, **fields):
    bad = set(fields) - ISSUE_COLUMNS
    if bad:
        raise ValueError(f"Not updatable: {bad}")
    cols = ", ".join(f"{k} = %s" for k in fields)
    vals = [Jsonb(v) if k in ("pending_escalation", "routing_basis") and v is not None else v for k, v in fields.items()]
    q(f"update issues set {cols} where issue_id = %s", (*vals, issue_id))


def set_embedding(issue_id: str, embedding: list[float] | None):
    if embedding is not None:
        q("update issues set summary_embedding = %s::vector where issue_id = %s", (vec(embedding), issue_id))


def add_event(issue_id: str, type_: str, actor: str, payload: dict | None = None):
    q("insert into events (issue_id, type, actor, payload) values (%s, %s, %s, %s)", (issue_id, type_, actor, Jsonb(payload or {})))


def timeline(issue_id: str) -> list[dict]:
    return q("select type, payload, created_at from events where issue_id = %s order by created_at desc, event_id desc", (issue_id,))


def queue() -> list[dict]:
    return q("select * from issue_queue where city = %s order by priority desc", (CITY,))


def open_issues_for_map() -> list[dict]:
    return q("select issue_id, summary, category, report_count, lat, lng from issue_queue where city = %s", (CITY,))


def scorecards() -> list[dict]:
    return q("select * from authority_scorecards where city = %s order by name", (CITY,))


def clusters() -> list[dict]:
    return q("select * from clusters_30d where city = %s order by reports desc", (CITY,))


def saved_reports() -> dict[str, dict]:
    return {r["cluster_key"]: r for r in q("select * from neighborhood_reports")}


def save_report(key: str, headline: str, en: str, ur: str):
    q("""insert into neighborhood_reports (cluster_key, headline, report_en, report_ur, created_at) values (%s,%s,%s,%s,now())
         on conflict (cluster_key) do update set headline = excluded.headline, report_en = excluded.report_en,
         report_ur = excluded.report_ur, created_at = now()""", (key, headline, en, ur))


def sweep_unverified():
    """Lazy version of the daily job: fixes nobody confirmed within 5 days close as unverified."""
    for r in q("""update issues set status = 'closed_unverified', resolved_at = now(), verification_requested_at = null
                  where verification_requested_at < now() - interval '5 days' and status not in ('resolved','closed_unverified')
                  returning issue_id"""):
        add_event(r["issue_id"], "closed_unverified", "system")


# ---------------- knowledge base ----------------
def kb_count() -> int:
    return one("select count(*) n from kb_chunks where city = %s", (CITY,))["n"]


def kb_upsert(doc: dict, chunks: list[dict], embeddings: list[list[float]] | None):
    q("""insert into kb_documents (doc_id, city, title, source, source_type, verified, updated_at) values (%s,%s,%s,%s,%s,%s,now())
         on conflict (doc_id) do update set title = excluded.title, source = excluded.source, source_type = excluded.source_type,
         verified = excluded.verified, updated_at = now()""",
      (doc["doc_id"], doc["city"], doc["title"], doc["source"], doc["source_type"], doc["verified"]))
    q("delete from kb_chunks where doc_id = %s", (doc["doc_id"],))
    for i, c in enumerate(chunks):
        q("insert into kb_chunks (chunk_id, doc_id, city, authority_ids, heading, content, embedding) values (%s,%s,%s,%s,%s,%s,%s::vector)",
          (c["chunk_id"], doc["doc_id"], doc["city"], doc["authority_ids"], c["heading"], c["content"], vec(embeddings[i]) if embeddings else None))


def match_kb(query_text: str, keyword_query: str, embedding: list[float] | None, k: int = 6, authority_ids: list[str] | None = None):
    return q("select * from match_kb(%s, %s, %s::vector, %s, %s)", (CITY, keyword_query, vec(embedding), k, authority_ids))
