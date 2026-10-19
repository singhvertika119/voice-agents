# Terminal 1: the voice agent (answers calls). Leave it running.
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONPATH = "apps/agent-worker;packages/core"
$env:PYTHONIOENCODING = "utf-8"
uv run python -m agent_worker.agent dev
