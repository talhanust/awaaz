-- Awaaz RAG layer: jurisdiction knowledge base (hybrid vector + keyword search) and semantic duplicate matching.
create extension if not exists vector;

-- ---------- Knowledge base ----------
create table kb_documents (
  doc_id      text primary key,                         -- e.g. 'lahore/electricity-vs-streetlights'
  city        text not null,
  title       text not null,
  source      text,                                     -- URL or citation of the original
  source_type text not null default 'demo' check (source_type in ('official','ngo','community','demo')),
  verified    boolean not null default false,           -- a person checked it against the source
  updated_at  timestamptz not null default now()
);

create table kb_chunks (
  chunk_id      text primary key,                       -- '<doc_id>#<n>'
  doc_id        text not null references kb_documents(doc_id) on delete cascade,
  city          text not null,
  authority_ids text[] not null default '{}',           -- departments the passage is about (for filtered lookups)
  heading       text,
  content       text not null,
  embedding     vector(1024),                           -- null when ingested without an embedding key
  tsv           tsvector generated always as (to_tsvector('simple', coalesce(heading, '') || ' ' || content)) stored
);
create index kb_chunks_embedding_idx on kb_chunks using hnsw (embedding vector_cosine_ops);
create index kb_chunks_tsv_idx on kb_chunks using gin (tsv);
create index kb_chunks_city_idx on kb_chunks (city);

-- ---------- Issues: semantic embedding + why it was routed where it was ----------
alter table issues add column summary_embedding vector(1024);
alter table issues add column routing_basis jsonb;      -- { authority_id, explanation, sources: [{chunk_id, title, verified}] }
create index issues_summary_embedding_idx on issues using hnsw (summary_embedding vector_cosine_ops);

-- ---------- Hybrid retrieval: vector + keyword, fused with reciprocal rank fusion ----------
-- p_query should be an OR-query for websearch_to_tsquery (e.g. 'streetlight or light or band').
-- Works keyword-only when p_embedding is null.
create or replace function match_kb(
  p_city text, p_query text, p_embedding vector(1024) default null, p_k int default 6, p_authority_ids text[] default null
) returns table (chunk_id text, doc_id text, title text, heading text, content text, verified boolean, source text, score double precision)
language sql stable as $$
  with base as (
    select c.* from kb_chunks c
    where c.city = p_city and (p_authority_ids is null or c.authority_ids && p_authority_ids)
  ),
  sem as (
    select b.chunk_id, row_number() over (order by b.embedding <=> p_embedding) as r
    from base b
    where p_embedding is not null and b.embedding is not null
    order by b.embedding <=> p_embedding
    limit 20
  ),
  lex as (
    select b.chunk_id, row_number() over (order by ts_rank_cd(b.tsv, q) desc) as r
    from base b, websearch_to_tsquery('simple', coalesce(p_query, '')) q
    where b.tsv @@ q
    order by ts_rank_cd(b.tsv, q) desc
    limit 20
  ),
  fused as (
    select u.chunk_id, sum(1.0 / (60 + u.r)) as score
    from (select * from sem union all select * from lex) u
    group by u.chunk_id
  )
  select c.chunk_id, c.doc_id, d.title, c.heading, c.content, d.verified, d.source, f.score
  from fused f
  join kb_chunks c on c.chunk_id = f.chunk_id
  join kb_documents d on d.doc_id = c.doc_id
  order by f.score desc
  limit p_k;
$$;

-- ---------- Semantic duplicate candidates: any category, nearby, similar meaning ----------
create or replace function semantic_candidates(
  p_city text, p_embedding vector(1024), p_lat double precision, p_lng double precision,
  p_radius_m int default 300, p_min_similarity double precision default 0.75
) returns table (issue_id text, summary text, sector text, category text, report_count int, status text,
                 distance_m double precision, similarity double precision)
language sql stable as $$
  with pt as (select st_setsrid(st_makepoint(p_lng, p_lat), 4326)::geography as g)
  select i.issue_id, i.summary, i.sector, i.category, i.report_count, i.status,
         st_distance(i.geo_private, pt.g), 1 - (i.summary_embedding <=> p_embedding)
  from issues i, pt
  where i.city = p_city
    and i.summary_embedding is not null
    and i.status not in ('resolved','closed_unverified')
    and i.first_reported_at > now() - interval '30 days'
    and st_dwithin(i.geo_private, pt.g, p_radius_m)
    and 1 - (i.summary_embedding <=> p_embedding) >= p_min_similarity
  order by i.summary_embedding <=> p_embedding
  limit 5;
$$;

alter table kb_documents enable row level security;
alter table kb_chunks enable row level security;
