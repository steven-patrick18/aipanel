# dev/start.ps1 — bring up the full local backend stack on Windows.
#
# What it does:
#   1. docker compose up -d  (Postgres + Redis + MinIO)
#   2. waits for Postgres health
#   3. creates / activates the panel backend venv
#   4. installs panel backend deps (first run only)
#   5. bootstraps an admin user if none exists
#   6. launches the FastAPI backend (uvicorn) on http://127.0.0.1:8000
#
# Then start the frontend in another terminal:
#   cd panel/frontend; npm run dev
#
# To tear down:
#   docker compose -f dev/docker-compose.yml down
#   (add -v to also drop the Postgres + MinIO data volumes)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $Repo

Write-Host "[dev] starting docker-compose services..." -ForegroundColor Cyan
docker compose -f dev/docker-compose.yml up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

Write-Host "[dev] waiting for Postgres to accept connections..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    docker exec aipanel-dev-postgres pg_isready -U aipanel -d aipanel 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 750
}
if (-not $ready) { throw "Postgres did not come up" }

# ---- Panel backend venv ----
$VenvDir   = Join-Path $Repo "panel\backend\.venv"
$VenvPy    = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip   = Join-Path $VenvDir "Scripts\pip.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "[dev] creating panel backend venv at $VenvDir" -ForegroundColor Cyan
    python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    Write-Host "[dev] installing panel backend deps (one-time, may take a minute)..." -ForegroundColor Cyan
    & $VenvPy -m pip install --upgrade pip wheel
    & $VenvPip install -e (Join-Path $Repo "panel\backend")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

# ---- Env for everything below ----
$env:AIPANEL_CONF    = Join-Path $Repo "dev\aipanel.dev.conf"
$env:AIPANEL_SECRETS = Join-Path $Repo "dev\secrets.dev.env"
$env:PYTHONUTF8      = "1"

# ---- Bootstrap admin if no users exist yet ----
Write-Host "[dev] checking for existing admin..." -ForegroundColor Cyan
$count = docker exec aipanel-dev-postgres psql -U aipanel -d aipanel -tAc "SELECT count(*) FROM users" 2>$null
if ([string]::IsNullOrWhiteSpace($count)) { $count = "0" }
$count = $count.Trim()
if ($count -eq "0") {
    Write-Host "[dev] no users yet — running dev/bootstrap_admin.py" -ForegroundColor Yellow
    Write-Host "       default: tenant=Default, email=admin@local, password=changeme" -ForegroundColor Yellow
    & $VenvPy (Join-Path $Repo "dev\bootstrap_admin.py") `
        --tenant "Default" --email "admin@local" --password "changeme"
} else {
    Write-Host "[dev] users table already populated ($count rows) — skipping bootstrap" -ForegroundColor DarkGray
}

# ---- Run uvicorn ----
Write-Host "[dev] starting backend on http://127.0.0.1:8000 (Ctrl+C to stop)" -ForegroundColor Green
Set-Location (Join-Path $Repo "panel\backend")
& $VenvPy -m uvicorn aipanel.main:app --host 127.0.0.1 --port 8000 --reload
