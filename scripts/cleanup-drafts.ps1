$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "Stopping app if running..."
& "$PSScriptRoot\stop-hidden.ps1" 2>$null | Out-Null

Write-Host "Removing draft claims..."
& ".\venv\Scripts\python.exe" -m app.cleanup_drafts

Write-Host "Done."
