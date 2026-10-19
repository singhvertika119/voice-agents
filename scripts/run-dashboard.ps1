# Terminal 3: the website. Then open http://localhost:3000
Set-Location (Join-Path (Split-Path $PSScriptRoot -Parent) "apps/dashboard")
npm run dev
