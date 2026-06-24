$ErrorActionPreference = "Stop"

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    throw "No virtual environment found. Run .\scripts\setup-dev.ps1 first."
}

& ".\venv\Scripts\python.exe" -m unittest discover -s "tests" -p "test_*.py" -v
