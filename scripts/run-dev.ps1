param(
    [switch]$Lan,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    throw "No virtual environment found. Run .\scripts\setup-dev.ps1 first."
}

& ".\venv\Scripts\python.exe" -m app.seed
$hostAddress = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }

Write-Host "Starting expense app on http://localhost:$Port"
if ($Lan) {
    $lanIp = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
        Select-Object -First 1 -ExpandProperty IPAddress
    if ($lanIp) {
        Write-Host "LAN access (same network): http://${lanIp}:$Port"
    }
}

& ".\venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host $hostAddress --port $Port
