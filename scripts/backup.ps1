param(
    [string]$BackupDir = "",
    [int]$RetentionDays = 0
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot "venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "No virtual environment found. Run .\scripts\setup-dev.ps1 first."
}

$argsList = @("-m", "app.backup")
if ($BackupDir) {
    $env:BACKUP_DIR = $BackupDir
}
if ($RetentionDays -gt 0) {
    $env:BACKUP_RETENTION_DAYS = "$RetentionDays"
}

Push-Location $projectRoot
try {
    & $pythonExe @argsList
    if ($LASTEXITCODE -ne 0) {
        throw "Backup command failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
