param(
    [string]$PythonVersion = "3.13"
)

$ErrorActionPreference = "Stop"

Write-Host "Setting up expense-app with Python $PythonVersion..."

if (Test-Path "venv") {
    Write-Host "Removing existing venv..."
    Remove-Item -Recurse -Force "venv"
}

py -$PythonVersion -m venv "venv"

& ".\venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\venv\Scripts\python.exe" -m pip install -r "requirements.txt"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example (set DEV_LOGIN=1 for local login)."
}

Write-Host "Setup complete."
Write-Host "Next: .\scripts\run-dev.ps1"
