-- Knowledge pipeline: sources -> parsed text -> chunks (+ embeddings) -> hybrid search; spreadsheets -> lookup tables.
-- Run once in the Supabase SQL editor (after 0001-0003).

create extension if not exists vector;

create table knowledge_sources (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  source_type text not null check (source_type in ('text','faq','file','url')),
  file_kind text,                          -- pdf | docx | txt | md | csv | xlsx (for source_type = file)
  url text,
  storage_path text,                       -- Supabase Storage object path (bucket: knowledge)
  raw_text text,                           -- pasted text / FAQ
  content_hash text,
  status text not null default 'queued'
    check (status in ('queued','parsing','indexing','testing','ready','needs_review','failed')),
  error text,                              -- readable message shown in the dashboard
  parsed_md text,                          -- what the parser produced (preview before use)
  stats jsonb not null default '{}'::jsonb, -- {chunks, tokens, tables, quality:{hit_rate, tested, failed:[...]}}
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on knowledge_sources (tenant_id, created_at desc);
create index on knowledge_sources (status) where status = 'queued';

create table kb_chunks (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  source_id uuid not null references knowledge_sources(id) on delete cascade,
  idx int not null,
  section text,                            -- heading path, e.g. "Refund policy > Timelines"
  content text not null,                   -- spoken-friendly text, prefixed with the section path
  tokens int not null default 0,
  embedding vector(1536),
  fts tsvector generated always as (to_tsvector('simple', content)) stored
);
create index on kb_chunks (source_id, idx);
create index on kb_chunks using gin (fts);
create index on kb_chunks using hnsw (embedding vector_cosine_ops);

-- Spreadsheets are not embedded: exact lookups (prices, fees) go through a lookup tool.
create table kb_tables (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  source_id uuid not null references knowledge_sources(id) on delete cascade,
  name text not null,
  columns jsonb not null,                  -- ["Service","Price"]
  rows jsonb not null                      -- [{"Service":"ECG","Price":"400"}, ...]
);
create index on kb_tables (source_id);

alter table knowledge_sources enable row level security;
alter table kb_chunks enable row level security;
alter table kb_tables enable row level security;

create policy ks_read on knowledge_sources for select using (is_member(tenant_id));
create policy ks_write on knowledge_sources for all
  using (is_member(tenant_id, array['owner','admin','editor']))
  with check (is_member(tenant_id, array['owner','admin','editor']));
create policy chunks_read on kb_chunks for select using (is_member(tenant_id));
create policy tables_read on kb_tables for select using (is_member(tenant_id));
-- kb_chunks / kb_tables are written only by the ingestion worker (service role).

-- Hybrid search: vector similarity + keyword rank, merged by reciprocal rank fusion.
-- security invoker: row-level security still limits results to the caller's workspace.
create or replace function match_chunks(
  p_sources uuid[], p_embedding vector(1536), p_query text, p_k int default 4, p_tenant uuid default null
) returns table (id uuid, source_id uuid, section text, content text, score float)
language sql stable security invoker set search_path = public as $$
  with vec as (
    select c.id, row_number() over (order by c.embedding <=> p_embedding) as r
    from kb_chunks c where c.source_id = any(p_sources) and c.embedding is not null
      and (p_tenant is null or c.tenant_id = p_tenant)
    order by c.embedding <=> p_embedding limit 20
  ), kw as (
    select c.id, row_number() over (order by ts_rank(c.fts, websearch_to_tsquery('simple', p_query)) desc) as r
    from kb_chunks c
    where c.source_id = any(p_sources) and (p_tenant is null or c.tenant_id = p_tenant)
      and c.fts @@ websearch_to_tsquery('simple', p_query)
    order by ts_rank(c.fts, websearch_to_tsquery('simple', p_query)) desc limit 20
  ), fused as (
    select coalesce(vec.id, kw.id) as id,
           coalesce(1.0 / (60 + vec.r), 0) + coalesce(1.0 / (60 + kw.r), 0) as score
    from vec full join kw on vec.id = kw.id
  )
  select c.id, c.source_id, c.section, c.content, f.score::float
  from fused f join kb_chunks c on c.id = f.id
  order by f.score desc limit p_k;
$$;

-- Storage bucket for uploaded originals (private). Objects are written by the dashboard server after it
-- checks workspace membership, and read by the ingestion worker, both with the service-role key.
insert into storage.buckets (id, name, public) values ('knowledge', 'knowledge', false)
on conflict (id) do nothing;
