-- Deleting an agent: keep its call history.
-- Run once in the Supabase SQL editor (after 0001-0006).
--
-- Until now calls.agent_id was required and pointed at the agent with no delete rule, so an agent that had taken
-- calls could not be deleted. Now deleting the agent leaves its calls (transcripts, recordings, summaries) in place
-- with no agent attached; the dashboard shows them as "Deleted agent". Versions, test runs, test scenarios and the
-- agent's caller memory are removed with the agent (they already cascaded); callbacks and handoffs already
-- kept their rows with the agent cleared. Knowledge sources and tools belong to the workspace and are not touched.
alter table calls alter column agent_id drop not null;
alter table calls drop constraint if exists calls_agent_id_fkey;
alter table calls add constraint calls_agent_id_fkey foreign key (agent_id) references agents(id) on delete set null;
