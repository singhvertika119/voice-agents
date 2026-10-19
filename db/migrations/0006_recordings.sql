-- Call recordings: where each call's audio is stored, and a per-workspace switch.
-- The private storage bucket "recordings" is created by the app (or in Storage > New bucket, private).
-- Run once in the Supabase SQL editor (after 0001-0005).

alter table calls add column if not exists recording_path text;       -- object path inside the "recordings" bucket
alter table calls add column if not exists recording_seconds numeric;

alter table tenant_settings add column if not exists record_calls boolean not null default true;
