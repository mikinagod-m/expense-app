# Expense App Operations Runbook (Windows)

This runbook is for day-to-day support, debugging, and recovery of `expense-app` on a Windows laptop/server.

## 1) Quick Start / Stop

### Hidden background mode (recommended for daily use)

- Start: double-click `Start Expense App.vbs`
- Stop: double-click `Stop Expense App.vbs`

Equivalent PowerShell commands:

```powershell
.\scripts\start-hidden.ps1 -Lan
.\scripts\stop-hidden.ps1
```

### Foreground dev mode (interactive logs)

```powershell
.\scripts\run-dev.ps1 -Lan
```

## 2) Access URLs

- Same machine: `http://localhost:8000`
- Same LAN: `http://<this-pc-local-ip>:8000`

Get local IPv4:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
  Select-Object -First 1 -ExpandProperty IPAddress
```

If LAN access fails, allow inbound TCP `8000` in Windows Firewall.

## 3) Health Checks

### Process and port

```powershell
Get-Process python | Select-Object Id,ProcessName,StartTime
netstat -ano | rg "8000"
```

Expected: `LISTENING` on `0.0.0.0:8000` (LAN mode) or `127.0.0.1:8000` (local-only mode).

### App response

```powershell
(Invoke-WebRequest -UseBasicParsing http://localhost:8000).StatusCode
```

Expected: `200`.

### Smoke suite

```powershell
.\scripts\run-smoke-tests.ps1
```

Expected: all tests `OK`.

## 4) Logs and Runtime Files

Runtime folder: `.runtime`

- PID file: `.runtime\uvicorn.pid`
- stdout log: `.runtime\uvicorn.out.log`
- stderr log: `.runtime\uvicorn.err.log`

Quick read:

```powershell
Get-Content .\.runtime\uvicorn.out.log -Tail 100
Get-Content .\.runtime\uvicorn.err.log -Tail 100
```

## 5) Common Incidents and Fixes

### A) App does not start

1. Ensure venv exists:
   ```powershell
   Test-Path .\venv\Scripts\python.exe
   ```
2. If missing, recreate:
   ```powershell
   .\scripts\setup-dev.ps1
   ```
3. Retry startup.

### B) Port 8000 already in use

1. Find PID:
   ```powershell
   netstat -ano | rg "8000"
   ```
2. Stop process:
   ```powershell
   Stop-Process -Id <PID> -Force
   ```
3. Start app again.

### C) Cannot log in / auth issues

- For local/dev mode, use `DEV_LOGIN=1` in `.env`.
- For Azure mode (`DEV_LOGIN=0`), verify:
  - `AAD_TENANT_ID`
  - `AAD_CLIENT_ID`
  - `AAD_CLIENT_SECRET`
  - `AAD_REDIRECT_URI`

### D) OCR not populating fields

- Upload still succeeds by design; users can enter values manually.
- Verify Tesseract installation and `.env` path:
  - `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`

### E) Unexpected validation errors on line save

- Required fields:
  - date (valid `YYYY-MM-DD`)
  - category (valid option)
  - amount (`> 0`)

## 6) Data and Recovery

### Backup (SQLite default)

Database file: `data\expenses.db`  
Receipt files: `receipts\`

Automated backup (recommended):

```powershell
.\scripts\backup.ps1
```

This creates a timestamped folder under `backups\` with:

- SQLite database copy (when `DATABASE_URL` uses SQLite)
- Full `receipts\` folder copy
- `manifest.json` metadata

Configure in `.env`:

```env
BACKUP_DIR=./backups
BACKUP_RETENTION_DAYS=14
```

Schedule daily on the Windows server (Task Scheduler):

1. Action: `powershell.exe`
2. Arguments: `-NoProfile -ExecutionPolicy Bypass -File "C:\path\to\expense-app\scripts\backup.ps1"`
3. Start in: `C:\path\to\expense-app`

Manual one-off backup:

```powershell
Copy-Item .\data\expenses.db ".\data\expenses-backup-$(Get-Date -Format yyyyMMdd-HHmmss).db"
```

### Reset demo data (destructive)

```powershell
Stop-Process -Name python -Force -ErrorAction SilentlyContinue
Remove-Item .\data\expenses.db -Force
.\scripts\run-dev.ps1 -Lan
```

## 7) Operational Checklist

Daily:

- Start app (hidden mode)
- Verify `http://localhost:8000` returns `200`
- Check `.runtime\uvicorn.err.log` is quiet

Before release/demo:

- Run smoke suite
- Confirm LAN access from a second machine
- Confirm auth mode (`DEV_LOGIN`) is intentionally set

After incidents:

- Capture log snippets from `.runtime`
- Record incident time, symptom, and fix in your tracker

## 8) Escalation Notes

When escalating a production-like issue, include:

- current mode (`DEV_LOGIN` and `-Lan` usage)
- startup method (`start-hidden` vs `run-dev`)
- relevant log excerpt from `.runtime\uvicorn.err.log`
- failing endpoint and HTTP status
- smoke test output
