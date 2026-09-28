-- Awaaz v3 schema. Run in the Supabase SQL editor or with `supabase db push`.
create extension if not exists postgis;

-- ---------- Reference data ----------
create table authorities (
  authority_id        text primary key,                 -- 'LESCO', 'WASA-LHR', ...
  city                text not null,
  name                text not null,
  categories          text[] not null,
  filing_channel      text not null check (filing_channel in ('api','portal','email','written_application','whatsapp')),
  filing_target       text,                             -- URL / email / office name
  helpline            text,
  benchmark_days      int  not null default 7,          -- seeded, later learned from data
  escalation_contacts jsonb not null default '{}'::jsonb -- { "<sector>": {"title": "...", "email": "..."} }
);

-- ---------- Citizens (phone is needed to message them back; restrict to service role) ----------
create table citizens (
  citizen_hash text primary key,                        -- sha256(phone + salt)
  phone        text not null unique,                    -- consider pgsodium column encryption in production
  language     text not null default 'ur-Latn',
  created_at   timestamptz not null default now()
);

-- ---------- Issues: one physical problem ----------
create sequence issue_seq start 1000;

create table issues (
  issue_id              text primary key,
  city                  text not null,
  sector                text not null,
  category              text not null check (category in ('electrical','water','sanitation','roads','gas','encroachment','other')),
  severity              text not null check (severity in ('low','medium','high','urgent')),
  authority_id          text not null references authorities(authority_id),
  summary               text not null,
  geo_private           geography(point, 4326) not null, -- exact, never exposed publicly
  geo_public            geography(point, 4326),          -- ~100 m grid, set by trigger
  status                text not null default 'open' check (status in
                          ('open','acknowledged','in_progress','escalated_t1','escalated_t2','escalated_t3','resolved','closed_unverified')),
  escalation_tier       int  not null default 0,
  report_count          int  not null default 1,
  confirmations         int  not null default 0,
  tracker_hash          text references citizens(citizen_hash), -- earliest active reporter: gets check-ins, gives consent
  filing_channel        text,
  formatted_complaint   text,
  pending_escalation    jsonb,                           -- draft awaiting consent
  checkin_sent_at       timestamptz,
  reminder_sent         boolean not null default false,
  verification_requested_at timestamptz,
  first_reported_at     timestamptz not null default now(),
  expected_by           timestamptz not null,
  resolved_at           timestamptz,
  resolution_proof      text
);
create index issues_geo_idx on issues using gist (geo_private);
create index issues_open_idx on issues (city, category) where status not in ('resolved','closed_unverified');

-- ---------- Reports: one citizen's voice on an Issue ----------
create table reports (
  report_id    text primary key,
  issue_id     text not null references issues(issue_id) on delete cascade,
  citizen_hash text not null references citizens(citizen_hash),
  language     text,
  input_type   text check (input_type in ('voice','photo','text')),
  raw_text     text,
  photo_url    text,
  geo_private  geography(point, 4326) not null,
  created_at   timestamptz not null default now(),
  unique (issue_id, citizen_hash)                        -- one voice per citizen per Issue
);

-- ---------- Timeline ----------
create table events (
  event_id   bigserial primary key,
  issue_id   text not null references issues(issue_id) on delete cascade,
  type       text not null,
  actor      text not null,                              -- citizen_hash | 'system' | authority_id
  payload    jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index events_issue_idx on events (issue_id, created_at);

-- ---------- WhatsApp conversation state ----------
create table sessions (
  citizen_hash text primary key references citizens(citizen_hash),
  state        text not null default 'idle',
  payload      jsonb not null default '{}'::jsonb,
  updated_at   timestamptz not null default now()
);

-- ---------- Generated Neighborhood Reports ----------
create table neighborhood_reports (
  cluster_key text primary key,                          -- city|sector|category
  headline    text not null,
  report_en   text not null,
  report_ur   text not null,
  created_at  timestamptz not null default now()
);

-- ---------- Triggers ----------
create or replace function snap_geo_public() returns trigger language plpgsql as $$
begin
  -- ~100 m grid at Lahore's latitude (0.00105° lng × 0.0009° lat)
  new.geo_public := st_snaptogrid(new.geo_private::geometry, 0.00105, 0.0009)::geography;
  return new;
end $$;
create trigger issues_snap before insert or update of geo_private on issues
  for each row execute function snap_geo_public();

-- ---------- RPCs ----------
create or replace function city_code(p_city text) returns text language sql immutable as $$
  select case lower(p_city)
    when 'lahore' then 'LHR' when 'karachi' then 'KHI' when 'islamabad' then 'ISB'
    when 'rawalpindi' then 'RWP' when 'faisalabad' then 'FSD' when 'multan' then 'MUX'
    when 'peshawar' then 'PEW' when 'quetta' then 'UET' else upper(left(p_city, 3)) end
$$;

create or replace function match_candidates(p_city text, p_category text, p_lat double precision, p_lng double precision)
returns table (issue_id text, summary text, sector text, report_count int, status text, distance_m double precision)
language sql stable as $$
  with pt as (select st_setsrid(st_makepoint(p_lng, p_lat), 4326)::geography as g),
       r  as (select case p_category
                when 'roads' then 50 when 'encroachment' then 50
                when 'sanitation' then 100 when 'electrical' then 100
                when 'water' then 250 when 'gas' then 250 else 50 end as m)
  select i.issue_id, i.summary, i.sector, i.report_count, i.status, st_distance(i.geo_private, pt.g)
  from issues i, pt, r
  where i.city = p_city and i.category = p_category
    and i.status not in ('resolved','closed_unverified')
    and i.first_reported_at > now() - interval '30 days'
    and st_dwithin(i.geo_private, pt.g, r.m)
  order by 6
  limit 5;
$$;

create or replace function create_issue(
  p_city text, p_sector text, p_category text, p_severity text, p_authority_id text, p_summary text,
  p_lat double precision, p_lng double precision, p_citizen_hash text, p_language text,
  p_input_type text, p_raw_text text, p_photo_url text
) returns text language plpgsql as $$
declare
  v_id text := 'AWZ-' || city_code(p_city) || '-' || lpad(nextval('issue_seq')::text, 5, '0');
  v_pt geography := st_setsrid(st_makepoint(p_lng, p_lat), 4326)::geography;
  v_bench int;
begin
  select benchmark_days into v_bench from authorities where authority_id = p_authority_id;
  insert into issues (issue_id, city, sector, category, severity, authority_id, summary, geo_private,
                      tracker_hash, expected_by)
  values (v_id, p_city, p_sector, p_category, p_severity, p_authority_id, p_summary, v_pt,
          p_citizen_hash, now() + make_interval(days => coalesce(v_bench, 7)));
  insert into reports (report_id, issue_id, citizen_hash, language, input_type, raw_text, photo_url, geo_private)
  values ('R-' || v_id || '-1', v_id, p_citizen_hash, p_language, p_input_type, p_raw_text, p_photo_url, v_pt);
  insert into events (issue_id, type, actor, payload) values (v_id, 'filed', p_citizen_hash, '{}'::jsonb);
  return v_id;
end $$;

-- Adds a citizen's voice atomically; returns the new report_count (or -1 if they already reported it).
create or replace function add_voice(
  p_issue_id text, p_citizen_hash text, p_language text, p_input_type text, p_raw_text text,
  p_photo_url text, p_lat double precision, p_lng double precision
) returns int language plpgsql as $$
declare v_count int;
begin
  if exists (select 1 from reports where issue_id = p_issue_id and citizen_hash = p_citizen_hash) then
    return -1;
  end if;
  update issues set report_count = report_count + 1 where issue_id = p_issue_id returning report_count into v_count;
  insert into reports (report_id, issue_id, citizen_hash, language, input_type, raw_text, photo_url, geo_private)
  values ('R-' || p_issue_id || '-' || v_count, p_issue_id, p_citizen_hash, p_language, p_input_type, p_raw_text,
          p_photo_url, st_setsrid(st_makepoint(p_lng, p_lat), 4326)::geography);
  insert into events (issue_id, type, actor, payload)
  values (p_issue_id, 'report_added', p_citizen_hash, jsonb_build_object('report_count', v_count));
  return v_count;
end $$;

-- ---------- Views (read server-side with the service role) ----------
create or replace view issue_queue as
select issue_id, city, sector, category, severity, authority_id, status, escalation_tier, report_count,
       confirmations, summary, first_reported_at, expected_by,
       greatest(1, floor(extract(epoch from now() - first_reported_at) / 86400))::int as days_open,
       report_count
         * (case severity when 'low' then 1 when 'medium' then 2 when 'high' then 3 else 5 end)
         * greatest(1, floor(extract(epoch from now() - first_reported_at) / 86400)) as priority,
       st_y(geo_public::geometry) as lat, st_x(geo_public::geometry) as lng
from issues
where status not in ('resolved','closed_unverified');

create or replace view authority_scorecards as
select a.authority_id, a.city, a.name, a.benchmark_days,
       count(i.*) filter (where i.status = 'resolved' and i.resolved_at > now() - interval '90 days') as resolved_90d,
       percentile_cont(0.5) within group (order by extract(epoch from i.resolved_at - i.first_reported_at) / 86400)
         filter (where i.status = 'resolved' and i.resolved_at > now() - interval '90 days') as median_days,
       avg(((i.resolved_at - i.first_reported_at) <= make_interval(days => a.benchmark_days))::int)
         filter (where i.status = 'resolved' and i.resolved_at > now() - interval '90 days') as within_benchmark,
       count(i.*) filter (where i.status not in ('resolved','closed_unverified')) as open_now,
       count(i.*) filter (where i.status like 'escalated_%') as escalated_now,
       count(i.*) filter (where i.status = 'closed_unverified' and i.resolved_at > now() - interval '90 days') as unverified_90d
from authorities a
left join issues i on i.authority_id = a.authority_id
group by a.authority_id, a.city, a.name, a.benchmark_days;

create or replace view clusters_30d as
with cur as (
  select city, sector, category,
         count(*) as issues, sum(report_count)::int as reports,
         count(*) filter (where status = 'resolved') as resolved,
         coalesce(round(avg(extract(epoch from now() - first_reported_at) / 86400)
                        filter (where status not in ('resolved','closed_unverified'))), 0)::int as avg_days_open,
         min(authority_id) as authority_id
  from issues
  where first_reported_at > now() - interval '30 days'
  group by city, sector, category
),
prev as (
  select i.city, i.sector, i.category, count(*)::int as prev_reports
  from reports r join issues i using (issue_id)
  where r.created_at between now() - interval '60 days' and now() - interval '30 days'
  group by i.city, i.sector, i.category
)
select cur.city || '|' || cur.sector || '|' || cur.category as cluster_key, cur.*,
       coalesce(prev.prev_reports, 0) as prev_reports
from cur left join prev using (city, sector, category)
where cur.issues >= 3 or cur.reports >= 10;

-- ---------- Row-level security: nothing is readable with the anon key ----------
alter table authorities enable row level security;
alter table citizens enable row level security;
alter table issues enable row level security;
alter table reports enable row level security;
alter table events enable row level security;
alter table sessions enable row level security;
alter table neighborhood_reports enable row level security;
revoke all on issue_queue, authority_scorecards, clusters_30d from anon, authenticated;
