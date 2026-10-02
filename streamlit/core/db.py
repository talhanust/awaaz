"""Postgres access (Supabase in production). Uses the same schema, RPCs and views as the WhatsApp app."""
import hashlib
import re
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


def normalize_phone(raw: str) -> str | None:
    """One person = one identity: 0300 1234567, 3001234567, +92 300 1234567 and 0092... all become +923001234567."""
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("0092"):
        d = d[2:]
    if len(d) == 12 and d.startswith("92"):
        return "+" + d
    if len(d) == 11 and d.startswith("0"):
        return "+92" + d[1:]
    if len(d) == 10 and d.startswith("3"):
        return "+92" + d
    return "+" + d if 10 <= len(d) <= 15 else None


def _legacy(raw: str) -> str:  # how numbers were stored before normalization
    return "".join(ch for ch in raw if ch.isdigit() or ch == "+")


def find_citizen(raw: str) -> str | None:
    norm = normalize_phone(raw)
    if not norm:
        return None
    row = one("select citizen_hash from citizens where phone = any(%s) or citizen_hash = %s order by created_at limit 1",
              ([norm, _legacy(raw), "0" + norm[3:] if norm.startswith("+92") else norm], citizen_hash(norm)))
    return row["citizen_hash"] if row else None


def get_or_create_citizen(phone: str, language: str = "ur-Latn") -> str:
    existing = find_citizen(phone)
    if existing:
        return existing
    norm = normalize_phone(phone) or _legacy(phone)
    h = citizen_hash(norm)
    q("insert into citizens (citizen_hash, phone, language) values (%s, %s, %s) on conflict do nothing", (h, norm, language))
    return one("select citizen_hash from citizens where citizen_hash = %s or phone = %s", (h, norm))["citizen_hash"]


def actions_today(h: str) -> int:
    """Reports plus 'I see this too' in the last 24 h, for abuse limits."""
    return one("""select (select count(*) from reports where citizen_hash = %(h)s and created_at > now() - interval '1 day')
                       + (select count(*) from events where actor = %(h)s and type = 'confirmed' and created_at > now() - interval '1 day') n""",
               {"h": h})["n"]


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


# ---------------- engagement (pulse page, "I see this too", my reports) ----------------
def pulse_stats() -> dict:
    return one("""select
        (select count(*) from issues where city = %(c)s and status not in ('resolved','closed_unverified')) as open,
        (select coalesce(sum(report_count), 0) from issues where city = %(c)s and status not in ('resolved','closed_unverified')) as waiting,
        (select count(*) from issues where city = %(c)s and status not in ('resolved','closed_unverified') and expected_by < now()) as overdue,
        (select count(*) from issues where city = %(c)s and status = 'resolved' and resolved_at > now() - interval '30 days') as fixed_30d,
        (select count(*) from reports r join issues i using (issue_id) where i.city = %(c)s and r.created_at > now() - interval '7 days') as reports_7d,
        (select percentile_cont(0.5) within group (order by extract(epoch from resolved_at - first_reported_at) / 86400)
           from issues where city = %(c)s and status = 'resolved') as median_fix_days""", {"c": CITY})


def activity(limit: int = 12) -> list[dict]:
    return q("""select e.type, e.payload, e.created_at, i.issue_id, i.summary, i.category, i.sector, i.report_count
                from events e join issues i using (issue_id) where i.city = %s
                order by e.created_at desc, e.event_id desc limit %s""", (CITY, limit))


def most_backed(limit: int = 3) -> list[dict]:
    return q("""select *, greatest(1, floor(extract(epoch from now() - first_reported_at) / 86400))::int as days_open
                from issues where city = %s and status not in ('resolved','closed_unverified')
                order by report_count + confirmations desc, first_reported_at limit %s""", (CITY, limit))


def recent_issues(limit: int = 6) -> list[dict]:
    return q("select * from issues where city = %s order by first_reported_at desc limit %s", (CITY, limit))


def nearby_open(lat: float, lng: float, meters: int = 150) -> list[dict]:
    return q("""select issue_id, summary, category, report_count, confirmations, status, escalation_tier, severity, expected_by,
                       round(st_distance(geo_private, st_setsrid(st_makepoint(%(lng)s, %(lat)s), 4326)::geography)) as distance_m
                from issues where city = %(c)s and status not in ('resolved','closed_unverified')
                  and st_dwithin(geo_private, st_setsrid(st_makepoint(%(lng)s, %(lat)s), 4326)::geography, %(m)s)
                order by distance_m limit 5""", {"lat": lat, "lng": lng, "m": meters, "c": CITY})


def my_reports(citizen: str) -> list[dict]:
    return q("""select i.*, r.created_at as reported_at from reports r join issues i using (issue_id)
                where r.citizen_hash = %s order by r.created_at desc""", (citizen,))


def see_too(issue_id: str, citizen: str) -> bool:
    """One-tap 'I see this too' (Waze-style confirmation). False if closed, already backed, or over the daily limit."""
    i = one("select status from issues where issue_id = %s", (issue_id,))
    if not i or i["status"] in ("resolved", "closed_unverified") or actions_today(citizen) >= 20:
        return False
    if is_reporter(issue_id, citizen) or one("select 1 from events where issue_id = %s and type = 'confirmed' and actor = %s", (issue_id, citizen)):
        return False
    q("update issues set confirmations = confirmations + 1 where issue_id = %s", (issue_id,))
    add_event(issue_id, "confirmed", citizen)
    return True


def response_board() -> list[dict]:
    """Departments ranked by how they're doing on open issues right now (works before any history exists)."""
    return q("""select a.authority_id, a.name, a.benchmark_days,
                       count(i.*) filter (where i.status not in ('resolved','closed_unverified')) as open,
                       count(i.*) filter (where i.status not in ('resolved','closed_unverified') and i.expected_by < now()) as overdue,
                       count(i.*) filter (where i.status like 'escalated_%%') as escalated,
                       count(i.*) filter (where i.status = 'resolved') as fixed,
                       coalesce(round(avg(extract(epoch from now() - i.first_reported_at) / 86400)
                                filter (where i.status not in ('resolved','closed_unverified'))), 0)::int as avg_days_open
                from authorities a left join issues i on i.authority_id = a.authority_id
                where a.city = %s group by a.authority_id, a.name, a.benchmark_days
                having count(i.*) > 0 order by overdue desc, avg_days_open desc""", (CITY,))


def category_breakdown() -> list[dict]:
    return q("""select category, count(*) as issues, sum(report_count)::int as residents from issues
                where city = %s and status not in ('resolved','closed_unverified') group by category order by issues desc""", (CITY,))


def executemany(sql: str, rows: list) -> None:
    with _conn().cursor() as cur:
        cur.executemany(sql, rows)


# ---------------- departments file → authorities table ----------------
def sync_authorities(departments: list[dict]) -> int:
    rows = [(d["id"], CITY, d["name"], d["categories"], d["channel"], d.get("target"), d.get("helpline"), int(d.get("benchmark_days", 7)))
            for d in departments]
    executemany("""insert into authorities (authority_id, city, name, categories, filing_channel, filing_target, helpline, benchmark_days)
                   values (%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (authority_id) do update set name = excluded.name, categories = excluded.categories,
                     filing_channel = excluded.filing_channel, filing_target = excluded.filing_target,
                     helpline = excluded.helpline, benchmark_days = excluded.benchmark_days""", rows)
    authorities.clear()
    return len(rows)


def kb_snapshot() -> dict[str, tuple]:
    return {r["chunk_id"]: (r["doc_id"], r["heading"], r["content"])
            for r in q("select chunk_id, doc_id, heading, content from kb_chunks where city = %s", (CITY,))}


def kb_delete_docs(doc_ids: list[str]):
    if doc_ids:
        q("delete from kb_documents where doc_id = any(%s)", (doc_ids,))


# ---------------- live monitor ----------------
def monitor_issues() -> list[dict]:
    return q("""select issue_id, summary, category, sector, authority_id, status, escalation_tier, report_count, confirmations, severity,
                       first_reported_at, expected_by, resolved_at, verification_requested_at,
                       st_y(geo_public::geometry) lat, st_x(geo_public::geometry) lng,
                       coalesce(tracker_hash like 'seed-hist%%', false) as simulated
                from issues where city = %s""", (CITY,))


def monitor_events(days: int) -> list[dict]:
    return q("""select e.type, e.created_at, e.issue_id, i.authority_id, i.category from events e join issues i using (issue_id)
                where i.city = %s and e.created_at > now() - make_interval(days => %s)""", (CITY, days))


def monitor_reports(days: int) -> list[dict]:
    return q("""select r.created_at, i.authority_id, i.category from reports r join issues i using (issue_id)
                where i.city = %s and r.created_at > now() - make_interval(days => %s)""", (CITY, days))


def simulated_count() -> int:
    return one("select count(*) n from issues where tracker_hash like 'seed-hist%%'")["n"]


def typical_fix_days(authority_id: str) -> tuple[float, int] | None:
    """Median days to a resident-verified fix for this department (needs 5+ fixes)."""
    r = one("""select percentile_cont(0.5) within group (order by extract(epoch from resolved_at - first_reported_at) / 86400) d, count(*) n
               from issues where authority_id = %s and status = 'resolved'""", (authority_id,))
    return (round(r["d"], 1), r["n"]) if r and r["n"] >= 5 else None
