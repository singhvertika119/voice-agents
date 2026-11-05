-- Clean-up after the switch to local embeddings (docs/decision.md D-122). Run ONLY after 0009, the re-embedding
-- (scripts/reembed_local.py) and the new agent, background worker and dashboard are all live and verified:
-- the old agent version searches with these, and would lose its vector search.
drop function if exists match_chunks(uuid[], vector, text, int, uuid);
alter table kb_chunks drop column if exists embedding;   -- the old OpenAI vectors (1536 numbers); drops its index too
