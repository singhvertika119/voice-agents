# Voice Agent Platform

Docs: `docs/` (PRD, architecture, implementation plan, `DESIGN.md` for the UI, `decision.md` for why things are as they are).

## Setup
```
cp .env.example .env     # fill in keys (LiveKit, Sarvam, Groq, Deepgram, Cartesia, Gemini)
uv sync
```

## Run (PowerShell, from the project folder)
```
powershell -ExecutionPolicy Bypass -File scripts\start-all.ps1
```
Opens three windows (voice agent, document reader, website). Open http://localhost:3000 after ~15 seconds.
One at a time: `scripts\run-agent.ps1`, `scripts\run-ingestion.ps1`, `scripts\run-dashboard.ps1`.
Tests: `uv run pytest`. Per-call latency/cost logs: `logs/*.jsonl`.

## Benchmarks
```
cd benchmark; uv run python stt.py; uv run python llm.py; uv run python tts.py
```

## Platform mode (database + dashboard)
1. Create a NEW Supabase project (region: Mumbai) and put its URL and keys in `.env`.
2. In its SQL editor run `db/migrations/0001_init.sql`, then `0002_publish_functions.sql`.
3. `uv run python db/tests/test_rls.py` should print only PASS lines.
4. Dashboard: `cd apps/dashboard; npm run dev`, open http://localhost:3000, create an account, create an agent, publish v1.
5. Worker: `uv run python -m agent_worker.agent dev` (keep it running). In the dashboard open an agent and use "Test the agent" on the right; it picks the agent by room name, no AGENT_ID needed. Calls appear under Calls.

## Knowledge pipeline
Run `db/migrations/0001` to `0004` once in the Supabase SQL editor. Check everything with
`uv run python db/tests/test_rls.py` and `uv run python db/tests/e2e_knowledge.py` (all PASS).
Use: Knowledge page > add > wait for Ready > agent's Knowledge tab > tick, Save draft, Publish.
