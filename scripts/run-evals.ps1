# Terminal 4: runs the automatic test conversations started from the website. Leave it running.
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONPATH = "apps/agent-worker;packages/core;."
$env:PYTHONIOENCODING = "utf-8"
uv run python -m evals.worker
