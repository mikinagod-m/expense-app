$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot ".runtime\uvicorn.pid"

function Stop-ExpenseProcessById {
    param(
        [int]$TargetPid
    )

    if ($TargetPid -le 0) {
        return $false
    }

    $proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if (-not $proc) {
        return $false
    }

    Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue
    return $true
}

function Stop-ExpenseUvicornFallback {
    param(
        [string]$RootPath
    )

    $stopped = 0
    $pattern = "*$RootPath*uvicorn*app.main:app*"
    $candidates = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq "python.exe" -and
            $_.CommandLine -like $pattern
        }

    foreach ($candidate in $candidates) {
        if (Stop-ExpenseProcessById -TargetPid ([int]$candidate.ProcessId)) {
            $stopped++
        }
    }

    return $stopped
}

$stoppedByPidFile = 0
if (Test-Path $pidFile) {
    $pidRaw = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $processId = 0
    if ([int]::TryParse($pidRaw, [ref]$processId)) {
        if (Stop-ExpenseProcessById -TargetPid $processId) {
            $stoppedByPidFile = 1
        }
    } else {
        Write-Host "PID file was invalid and has been cleaned."
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$stoppedByFallback = Stop-ExpenseUvicornFallback -RootPath $projectRoot
$totalStopped = $stoppedByPidFile + $stoppedByFallback

if ($totalStopped -gt 0) {
    Write-Host "Stopped expense app process(es): $totalStopped"
} else {
    Write-Host "No running expense app process found."
}
