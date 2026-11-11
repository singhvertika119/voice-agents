-- Bring your own OpenAI key (docs/decision.md D-124). Each workspace stores its own key; the platform no longer
-- pays for OpenAI. The key is encrypted by the dashboard server (AES-256-GCM, TOOL_SECRET_KEY, the same scheme as
-- tool_secrets) and decrypted only by server code. Row-level security with no policies: only the service key can
-- read or write this table, so the browser never sees the key, not even encrypted.
-- Without a key, everything still works on the free Groq model.

create table if not exists tenant_api_keys (
  tenant_id uuid not null references tenants(id) on delete cascade,
  provider text not null check (provider in ('openai')),
  secret_enc text not null,
  last4 text not null,                       -- shown in Settings so people can tell which key is saved
  status text not null default 'unchecked' check (status in ('ok', 'no_credits', 'invalid', 'unchecked')),
  checked_at timestamptz,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id) on delete set null,
  primary key (tenant_id, provider)
);
alter table tenant_api_keys enable row level security;   -- no policies: service key only
