-- Fix 1.1: Ensure agent_id belongs to the same tenant_id on eval_runs, eval_scenarios, and agent_versions.

-- 1. eval_runs
drop policy if exists er_queue on eval_runs;
create policy er_queue on eval_runs for insert
  with check (
    is_member(tenant_id, array['owner','admin','editor'])
    and status = 'queued'
    and agent_id in (select id from agents where tenant_id = eval_runs.tenant_id)
  );

-- 2. eval_scenarios
drop policy if exists es_write on eval_scenarios;
create policy es_write on eval_scenarios for all
  using (is_member(tenant_id, array['owner','admin','editor']))
  with check (
    is_member(tenant_id, array['owner','admin','editor'])
    and (agent_id is null or agent_id in (select id from agents where tenant_id = eval_scenarios.tenant_id))
  );

-- 3. agent_versions
drop policy if exists versions_write on agent_versions;
create policy versions_write on agent_versions for all
  using (is_member(tenant_id, array['owner','admin','editor']))
  with check (
    is_member(tenant_id, array['owner','admin','editor'])
    and agent_id in (select id from agents where tenant_id = agent_versions.tenant_id)
  );
