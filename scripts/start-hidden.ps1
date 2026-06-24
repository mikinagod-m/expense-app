param(
    [int]$Port = 8000,
    [switch]$Lan
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot "venv\Scripts\python.exe"
$runtimeDir = Join-Path $projectRoot ".runtime"
$pidFile = Join-Path $runtimeDir "uvicorn.pid"
$outLog = Join-Path $runtimeDir "uvicorn.out.log"
$errLog = Join-Path $runtimeDir "uvicorn.err.log"
$hostAddress = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }

if (-not (Test-Path $pythonExe)) {
    throw "No virtual environment found. Run .\scripts\setup-dev.ps1 first."
}

if (-not (Test-Path $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
}

# If a prior pid file points to a live process, do not start duplicates.
if (Test-Path $pidFile) {
    $existingPidRaw = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    $existingPid = 0
    if ([int]::TryParse($existingPidRaw, [ref]$existingPid)) {
        $existingProc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProc) {
            Write-Host "Expense app is already running (PID $existingPid) on port $Port."
            exit 0
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# Seed safely on each launch (idempotent for this project).
& $pythonExe -m app.seed | Out-Null

$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", $hostAddress, "--port", "$Port") `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru

Set-Content -Path $pidFile -Value $proc.Id
if ($Lan) {
    $lanIp = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
        Select-Object -First 1 -ExpandProperty IPAddress
    if ($lanIp) {
        Write-Host "Expense app started in background (PID $($proc.Id)). Open http://localhost:$Port or http://${lanIp}:$Port from same network."
    } else {
        Write-Host "Expense app started in background (PID $($proc.Id)). Open http://localhost:$Port"
    }
} else {
    Write-Host "Expense app started in background (PID $($proc.Id)). Open http://localhost:$Port"
}
