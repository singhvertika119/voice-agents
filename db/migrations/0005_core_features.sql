-- Core features: test runs, handoff and callbacks, call outcome and summary, caller memory, consent,
-- retention and erasure, capacity limits and kill switches, custom tools.
-- Run once in the Supabase SQL editor (after 0001-0004).

-- ====================================================================== columns on existing tables
alter table agents add column if not exists enabled boolean not null default true;   -- kill switch per agent
alter table calls add column if not exists structured jsonb;        -- {intent, outcome, commitments, open_items, language}
alter table calls add column if not exists consent jsonb;           -- {notice, version, at, recording, memory}
alter table calls add column if not exists contact_id uuid;
alter table calls add column if not exists tool_calls jsonb not null default '[]'::jsonb;  -- redacted log of tool uses

-- ====================================================================== per-workspace settings
create table if not exists tenant_settings (
  tenant_id uuid primary key references tenants(id) on delete cascade,
  retention_days int not null default 90 check (retention_days between 1 and 3650),
  max_concurrent_calls int not null default 5 check (max_concurrent_calls between 1 and 500),
  business_hours jsonb not null default '{"days":[1,2,3,4,5,6],"start":"09:00","end":"19:00"}'::jsonb,  -- IST
  handoff_phone text,                       -- where a human handoff would ring (used once phone lines exist)
  require_tests_to_publish boolean not null default false,
  memory_enabled boolean not null default true,
  updated_at timestamptz not null default now()
);
alter table tenant_settings enable row level security;
create policy ts_read on tenant_settings for select using (is_member(tenant_id));
create policy ts_write on tenant_settings for all
  using (is_member(tenant_id, array['owner','admin'])) with check (is_member(tenant_id, array['owner','admin']));

-- Platform-wide switches (degraded mode). Readable only with the service key.
create table if not exists platform_flags (key text primary key, value jsonb not null, updated_at timestamptz not null default now());
alter table platform_flags enable row level security;
insert into platform_flags(key, value) values ('degraded_mode', 'false'::jsonb) on conflict do nothing;

-- ====================================================================== contacts and memory
create table if not exists contacts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  phone_e164 text not null,
  name text,
  preferred_language text,
  consent_memory boolean not null default true,
  created_at timestamptz not null default now(),
  unique (tenant_id, phone_e164)
);
create table if not exists contact_memory (
  contact_id uuid not null references contacts(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  tenant_id uuid not null references tenants(id) on delete cascade,
  rolling_summary text not null default '',     -- about 250 words, English
  facts jsonb not null default '{}'::jsonb,
  open_items jsonb not null default '[]'::jsonb,
  version int not null default 1,
  updated_at timestamptz not null default now(),
  primary key (contact_id, agent_id)
);
alter table contacts enable row level security;
alter table contact_memory enable row level security;
create policy contacts_read on contacts for select using (is_member(tenant_id));
create policy memory_read on contact_memory for select using (is_member(tenant_id));
-- written by the worker (service key) only

-- ====================================================================== handoff and callbacks
create table if not exists handoffs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  call_id uuid references calls(id) on delete cascade,
  agent_id uuid references agents(id) on delete set null,
  reason text not null,
  outcome text not null check (outcome in ('callback_requested','after_hours','no_target','transferred')),
  requested_at timestamptz not null default now()
);
create table if not exists callbacks (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  call_id uuid references calls(id) on delete set null,
  agent_id uuid references agents(id) on delete set null,
  phone_e164 text,
  preferred_time text,
  reason text,
  status text not null default 'open' check (status in ('open','done','cancelled')),
  created_at timestamptz not null default now()
);
create index if not exists callbacks_open on callbacks (tenant_id, status, created_at desc);
alter table handoffs enable row level security;
alter table callbacks enable row level security;
create policy handoffs_read on handoffs for select using (is_member(tenant_id));
create policy callbacks_read on callbacks for select using (is_member(tenant_id));
create policy callbacks_update on callbacks for update
  using (is_member(tenant_id, array['owner','admin','editor'])) with check (is_member(tenant_id, array['owner','admin','editor']));

-- ====================================================================== custom tools
create table if not exists tools (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null check (name ~ '^[a-z][a-z0-9_]{2,40}$'),
  description text not null,
  parameters jsonb not null default '{"type":"object","properties":{}}'::jsonb,   -- JSON Schema
  method text not null default 'POST' check (method in ('GET','POST')),
  endpoint text not null,
  auth_header text,                        -- header NAME, e.g. Authorization; the value lives in tool_secrets
  timeout_ms int not null default 4000 check (timeout_ms between 500 and 5000),
  requires_confirmation boolean not null default false,
  idempotent boolean not null default false,
  filler_phrase text,                      -- spoken while the tool runs, e.g. "ek second, check karti hoon"
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  unique (tenant_id, name)
);
create table if not exists tool_secrets (
  tool_id uuid primary key references tools(id) on delete cascade,
  tenant_id uuid not null references tenants(id) on delete cascade,
  secret_enc text not null                 -- encrypted by the dashboard server; decrypted only in the worker
);
alter table tools enable row level security;
alter table tool_secrets enable row level security;          -- no policies: service key only
create policy tools_read on tools for select using (is_member(tenant_id));
create policy tools_write on tools for all
  using (is_member(tenant_id, array['owner','admin','editor'])) with check (is_member(tenant_id, array['owner','admin','editor']));

-- ====================================================================== test conversations
create table if not exists eval_scenarios (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid references agents(id) on delete cascade,    -- null = every agent in the workspace
  name text not null,
  spec jsonb not null,                    -- {caller_goal, opening, must_say_any, must_not_say, language}
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);
create table if not exists eval_runs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid not null references agents(id) on delete cascade,
  agent_version int not null,
  status text not null default 'queued' check (status in ('queued','running','done','failed')),
  runs_per_scenario int not null default 3 check (runs_per_scenario between 1 and 10),
  passed boolean,
  pass_rate numeric,
  p95_reply_ms int,
  results jsonb,
  error text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);
create index if not exists eval_runs_agent on eval_runs (agent_id, agent_version, created_at desc);
alter table eval_scenarios enable row level security;
alter table eval_runs enable row level security;
create policy es_read on eval_scenarios for select using (is_member(tenant_id));
create policy es_write on eval_scenarios for all
  using (is_member(tenant_id, array['owner','admin','editor'])) with check (is_member(tenant_id, array['owner','admin','editor']));
create policy er_read on eval_runs for select using (is_member(tenant_id));
create policy er_queue on eval_runs for insert
  with check (is_member(tenant_id, array['owner','admin','editor']) and status = 'queued');
-- results are written by the test worker (service key)

-- ====================================================================== publish gate
create or replace function publish_version(p_agent uuid, p_version int, p_override boolean default false)
returns void language plpgsql security invoker set search_path = public as $$
declare t uuid; gate boolean; ok boolean;
begin
  select tenant_id into t from agents where id = p_agent;
  if t is null then raise exception 'agent not found'; end if;
  if not exists (select 1 from agent_versions where agent_id = p_agent and version = p_version) then
    raise exception 'version not found';
  end if;
  select coalesce((select require_tests_to_publish from tenant_settings where tenant_id = t), false) into gate;
  if gate and not p_override then
    select exists (select 1 from eval_runs where agent_id = p_agent and agent_version = p_version
                   and status = 'done' and passed) into ok;
    if not ok then raise exception 'tests_required: run the test conversations for this version and pass them first'; end if;
  end if;
  if p_override and not is_member(t, array['owner','admin']) then raise exception 'only an owner or admin can publish without passing tests'; end if;
  update agent_versions set status = 'archived' where agent_id = p_agent and status = 'published';
  update agent_versions set status = 'published', published_at = now() where agent_id = p_agent and version = p_version;
  update agents set published_version = p_version, updated_at = now() where id = p_agent;
  perform write_audit(t, case when gate and p_override then 'agent.publish_override' else 'agent.publish' end,
                      p_agent::text, jsonb_build_object('version', p_version));
end $$;
drop function if exists publish_version(uuid, int);

-- ====================================================================== privacy: erasure and retention
-- Delete everything held about one caller number in a workspace. Owner/admin only; leaves an audit row.
create or replace function erase_caller(p_tenant uuid, p_phone text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare n_calls int; n_contacts int; n_cb int;
begin
  if not is_member(p_tenant, array['owner','admin']) then raise exception 'not allowed'; end if;
  delete from callbacks where tenant_id = p_tenant and phone_e164 = p_phone;  get diagnostics n_cb = row_count;
  delete from calls where tenant_id = p_tenant and caller_number = p_phone;   get diagnostics n_calls = row_count;  -- turns, handoffs cascade
  delete from contacts where tenant_id = p_tenant and phone_e164 = p_phone;   get diagnostics n_contacts = row_count; -- memory cascades
  insert into audit_log(tenant_id, actor, action, target, detail)
    values (p_tenant, auth.uid(), 'privacy.erase_caller', right(p_phone, 4),
            jsonb_build_object('calls', n_calls, 'contacts', n_contacts, 'callbacks', n_cb));
  return jsonb_build_object('calls', n_calls, 'contacts', n_contacts, 'callbacks', n_cb);
end $$;

-- Scheduled by the background worker. Removes transcripts older than each workspace's retention window.
-- Summaries stay on the call row; memory stays only while the contact consents.
create or replace function purge_expired()
returns jsonb language plpgsql security definer set search_path = public as $$
declare n int;
begin
  delete from call_turns ct using calls c, tenant_settings s
   where ct.call_id = c.id and s.tenant_id = c.tenant_id and c.started_at < now() - make_interval(days => s.retention_days);
  get diagnostics n = row_count;
  delete from call_turns ct using calls c
   where ct.call_id = c.id and c.started_at < now() - interval '90 days'
     and not exists (select 1 from tenant_settings s where s.tenant_id = c.tenant_id);
  return jsonb_build_object('turns_deleted', n);
end $$;
revoke all on function purge_expired() from public, anon, authenticated;
