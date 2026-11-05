-- Vectors from our own embedding model, multilingual-e5-base, 768 numbers (docs/decision.md D-122).
-- Added next to the old OpenAI column, so the running agent keeps working until it is redeployed; the old column
-- and match_chunks are removed later by 0010 once the switch is verified.
-- Run once in the Supabase SQL editor (after 0001-0008). Then fill the column: scripts/reembed_local.py.

alter table kb_chunks add column if not exists embedding_local vector(768);
create index if not exists kb_chunks_embedding_local_idx on kb_chunks using hnsw (embedding_local vector_cosine_ops);

-- Same hybrid search as match_chunks (vector similarity + keyword rank, reciprocal rank fusion), on the new column.
-- p_embedding may be null: then only the keyword half runs (used when the model is unavailable).
-- security invoker: row-level security still limits results to the caller's workspace.
create or replace function match_chunks_local(
  p_sources uuid[], p_embedding vector(768), p_query text, p_k int default 4, p_tenant uuid default null
) returns table (id uuid, source_id uuid, section text, content text, score float)
language sql stable security invoker set search_path = public as $$
  with vec as (
    select c.id, row_number() over (order by c.embedding_local <=> p_embedding) as r
    from kb_chunks c where p_embedding is not null and c.source_id = any(p_sources) and c.embedding_local is not null
      and (p_tenant is null or c.tenant_id = p_tenant)
    order by c.embedding_local <=> p_embedding limit 20
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
