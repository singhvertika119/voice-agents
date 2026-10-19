# Terminal 2: reads uploaded knowledge (PDFs, web pages...). Leave it running.
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONPATH = "apps/ingestion-worker;packages/core"
$env:PYTHONIOENCODING = "utf-8"
uv run python -m ingestion.main
