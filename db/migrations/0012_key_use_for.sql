-- What the workspace's own OpenAI key is used for (docs/decision.md D-125). 'calls' (the default, cheapest): only
-- live-call replies and the agent's replies in test conversations, where answer quality shows. Summaries, the test
-- caller and reviewer, the knowledge quality check and the knowledge chat use the free model. 'everything': all of
-- them use the key.
alter table tenant_api_keys add column if not exists use_for text not null default 'calls'
  check (use_for in ('calls', 'everything'));
