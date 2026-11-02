-- Keep the live speech-to-text alongside the re-transcribed text (docs/decision.md D-097).
-- Optional: without it the worker still replaces call_turns.text, it just does not keep the live version.
-- Run once in the Supabase SQL editor (after 0001-0007).
alter table call_turns add column if not exists text_live text;   -- what streaming STT heard during the call
