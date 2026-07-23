# start-api.ps1 — launch the ArenaRank read-API on http://127.0.0.1:8000
# Uses the broken-venv bypass: local Python 3.12 + the venv's intact site-packages.
# Run from a normal PowerShell window:  .\start-api.ps1
# Leave the window open — closing it stops the API.

$ErrorActionPreference = "Stop"
$BK  = "C:\Users\João\Downloads\arenarank-realoficial-main\arenarank-realoficial-main\backend"
$py  = "C:\Users\João\AppData\Local\Programs\Python\Python312\python.exe"

Set-Location $BK
$env:PYTHONPATH   = "$BK;$BK\.venv\Lib\site-packages"
$env:DATABASE_URL = "postgresql+asyncpg://arena:arena@localhost:5432/arena"  # compose postgres (has the data)
$env:REDIS_URL    = "redis://localhost:6379/0"

Write-Host "Starting API on http://127.0.0.1:8000 (Ctrl+C to stop)..." -ForegroundColor Cyan
& $py -m uvicorn arena.api.app:app --host 127.0.0.1 --port 8000
