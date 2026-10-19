-- Voice platform v1 schema. Multi-tenant; isolation enforced by row-level security (RLS).
-- Run once in the Supabase SQL editor of the NEW project (see docs/decision.md D-013).

create extension if not exists pgcrypto;

-- ---------- tenants and membership ----------
create table tenants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

create table tenant_members (
  tenant_id uuid not null references tenants(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'owner' check (role in ('owner','admin','editor','viewer')),
  created_at timestamptz not null default now(),
  primary key (tenant_id, user_id)
);
create index on tenant_members (user_id);

-- Is the signed-in user a member of this tenant (optionally with one of the roles)?
create or replace function is_member(t uuid, roles text[] default null)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from tenant_members m
    where m.tenant_id = t and m.user_id = auth.uid() and (roles is null or m.role = any(roles))
  );
$$;

-- ---------- agents and immutable versions ----------
create table agents (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  phone_number text,                       -- E.164, assigned later (SIP)
  published_version int,                   -- pointer; publish/rollback = change this
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on agents (tenant_id);

create table agent_versions (
  agent_id uuid not null references agents(id) on delete cascade,
  tenant_id uuid not null references tenants(id) on delete cascade,
  version int not null,
  status text not null default 'draft' check (status in ('draft','published','archived')),
  config jsonb not null,                   -- same shape as agents/*.yaml
  note text,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  published_at timestamptz,
  primary key (agent_id, version)
);
create index on agent_versions (tenant_id);

-- ---------- calls and transcripts ----------
create table calls (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  agent_id uuid not null references agents(id),
  agent_version int not null,              -- config this call ran on
  channel text not null default 'web',     -- web | phone
  caller_number text,                      -- E.164 when phone
  livekit_room text,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  duration_s numeric,
  outcome text check (outcome in ('resolved','handed_off','dropped','callback')),
  language text,
  avg_reply_ms int,
  cost_usd numeric,
  cost_breakdown jsonb,                    -- {stt_sec, tts_chars, llm_in, llm_out}
  summary text
);
create index on calls (tenant_id, started_at desc);

create table call_turns (
  id bigserial primary key,
  call_id uuid not null references calls(id) on delete cascade,
  tenant_id uuid not null references tenants(id) on delete cascade,
  seq int not null,
  speaker text not null check (speaker in ('caller','agent')),
  text text not null,
  at_ms int,
  latency_ms int,
  interrupted boolean not null default false
);
create index on call_turns (call_id, seq);

-- ---------- append-only audit log ----------
create table audit_log (
  id bigserial primary key,
  tenant_id uuid not null references tenants(id) on delete cascade,
  actor uuid,
  action text not null,                    -- e.g. agent.publish
  target text,
  detail jsonb,
  at timestamptz not null default now()
);

-- ---------- signup: create a workspace and make the user its owner ----------
create or replace function handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
declare t uuid;
begin
  insert into tenants(name) values (split_part(new.email, '@', 1) || ' workspace')
    returning id into t;
  insert into tenant_members(tenant_id, user_id, role) values (t, new.id, 'owner');
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function handle_new_user();

-- ---------- row-level security ----------
alter table tenants enable row level security;
alter table tenant_members enable row level security;
alter table agents enable row level security;
alter table agent_versions enable row level security;
alter table calls enable row level security;
alter table call_turns enable row level security;
alter table audit_log enable row level security;

create policy tenants_read on tenants for select using (is_member(id));
create policy members_read on tenant_members for select using (user_id = auth.uid() or is_member(tenant_id));

create policy agents_read on agents for select using (is_member(tenant_id));
create policy agents_write on agents for all
  using (is_member(tenant_id, array['owner','admin','editor']))
  with check (is_member(tenant_id, array['owner','admin','editor']));

create policy versions_read on agent_versions for select using (is_member(tenant_id));
create policy versions_write on agent_versions for all
  using (is_member(tenant_id, array['owner','admin','editor']))
  with check (is_member(tenant_id, array['owner','admin','editor']));

create policy calls_read on calls for select using (is_member(tenant_id));
create policy turns_read on call_turns for select using (is_member(tenant_id));
create policy audit_read on audit_log for select using (is_member(tenant_id, array['owner','admin']));
-- Writes to calls / call_turns / audit_log come from the agent worker with the service-role key (bypasses RLS).
-- Audit log is append-only: no update/delete policies exist for any client role.
