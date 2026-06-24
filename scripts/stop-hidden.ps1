$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot ".runtime\uvicorn.pid"

if (-not (Test-Path $pidFile)) {
    Write-Host "No PID file found. App may already be stopped."
    exit 0
}

$pidRaw = Get-Content $pidFile | Select-Object -First 1
$processId = 0
if (-not [int]::TryParse($pidRaw, [ref]$processId)) {
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    throw "PID file was invalid and has been removed."
}

$proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
if (-not $proc) {
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "Process $processId is not running. Cleaned stale PID file."
    exit 0
}

Stop-Process -Id $processId -Force
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "Stopped expense app process $processId."
