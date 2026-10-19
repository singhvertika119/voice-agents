-- Drafting and publishing are done atomically in the database. Both run as the caller (security invoker),
-- so row-level security decides whether the user may touch the agent.

create or replace function create_draft(p_agent uuid, p_config jsonb, p_note text default null)
returns int language plpgsql security invoker set search_path = public as $$
declare t uuid; v int;
begin
  select tenant_id into t from agents where id = p_agent;   -- invisible (null) if not a member
  if t is null then raise exception 'agent not found'; end if;
  select coalesce(max(version), 0) + 1 into v from agent_versions where agent_id = p_agent;
  insert into agent_versions(agent_id, tenant_id, version, status, config, note, created_by)
    values (p_agent, t, v, 'draft', p_config, p_note, auth.uid());
  return v;
end $$;

-- Publish and rollback are the same operation: move the pointer. Old versions stay immutable.
create or replace function publish_version(p_agent uuid, p_version int)
returns void language plpgsql security invoker set search_path = public as $$
declare t uuid;
begin
  select tenant_id into t from agents where id = p_agent;
  if t is null then raise exception 'agent not found'; end if;
  if not exists (select 1 from agent_versions where agent_id = p_agent and version = p_version) then
    raise exception 'version not found';
  end if;
  update agent_versions set status = 'archived' where agent_id = p_agent and status = 'published';
  update agent_versions set status = 'published', published_at = now()
    where agent_id = p_agent and version = p_version;
  update agents set published_version = p_version, updated_at = now() where id = p_agent;
  -- audit_log has no client insert policy; write it via a definer helper
  perform write_audit(t, 'agent.publish', p_agent::text, jsonb_build_object('version', p_version));
end $$;

create or replace function write_audit(p_tenant uuid, p_action text, p_target text, p_detail jsonb)
returns void language sql security definer set search_path = public as $$
  insert into audit_log(tenant_id, actor, action, target, detail)
  select p_tenant, auth.uid(), p_action, p_target, p_detail
  where is_member(p_tenant);
$$;
