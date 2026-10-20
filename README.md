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

## Database updates, in order
Run these once, in this order, in the Supabase SQL editor: `db/migrations/0001` to `0006`.
Checks (all lines should say PASS): `uv run python db/tests/test_rls.py`, `db/tests/e2e_knowledge.py`, `db/tests/e2e_core.py`, `db/tests/e2e_recording.py`, `db/tests/check_livekit.py`, and with the dashboard running `db/tests/e2e_wizard.py`.

## Automatic test conversations
From a terminal: `$env:PYTHONPATH="apps/agent-worker;packages/core;."; uv run python -m evals.runner --agent sunrise-clinic`
From the website: Agent > Tests > Run tests (needs the test worker window, started by `start-all.ps1`).

## Using knowledge
Knowledge page > add > wait for Ready > agent's Knowledge tab > tick, Save draft, Publish.

## Deploying
See `docs/deployment.md`: website on Vercel, agent worker on LiveKit Cloud (root `Dockerfile`), document reader and test worker on Render (`render.yaml`, `deploy/background.Dockerfile`).
