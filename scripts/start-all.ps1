# Opens all three in separate windows.
$here = $PSScriptRoot
foreach ($s in "run-agent.ps1", "run-ingestion.ps1", "run-dashboard.ps1") {
  Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "`"$here\$s`""
}
Write-Host "Started. Open http://localhost:3000 in your browser in about 15 seconds."
