# Windows: set up and start Loan Ledger with Docker Desktop.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Creates .env with generated passwords (first run only), builds the app and starts MySQL + the app.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd not found. $hint" }
}
Need docker "Install Docker Desktop from https://www.docker.com/products/docker-desktop and start it."
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker is installed but not running. Start Docker Desktop, wait until it says it is running, then run this again." }

function New-Secret([int]$bytes) {
    $b = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return -join ($b | ForEach-Object { $_.ToString("x2") })
}

if (-not (Test-Path ".env")) {
    $lines = Get-Content ".env.example" | ForEach-Object {
        if ($_ -match '^MYSQL_PASSWORD=') { "MYSQL_PASSWORD=$(New-Secret 16)" }
        elseif ($_ -match '^MYSQL_ROOT_PASSWORD=') { "MYSQL_ROOT_PASSWORD=$(New-Secret 16)" }
        elseif ($_ -match '^JWT_SECRET=') { "JWT_SECRET=$(New-Secret 32)" }
        elseif ($_ -match '^ADMIN_PASSWORD=') { "ADMIN_PASSWORD=$(New-Secret 12)" }
        else { $_ }
    }
    Set-Content -Path ".env" -Value $lines -Encoding ASCII
    Write-Host "Created .env with generated passwords. The admin password is in .env (ADMIN_PASSWORD)." -ForegroundColor Yellow
} else {
    Write-Host "Using the existing .env" -ForegroundColor Cyan
}

docker compose up --build -d
if ($LASTEXITCODE -ne 0) { throw "docker compose failed. See the messages above." }

Write-Host "Waiting for the app..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 60 -and -not $ok; $i++) {
    Start-Sleep -Seconds 2
    try { Invoke-RestMethod "http://localhost:8000/api/health" -TimeoutSec 3 | Out-Null; $ok = $true } catch {}
}
if (-not $ok) { throw "The app did not start. Run 'docker compose logs app' to see why." }
Write-Host ""
Write-Host "Loan Ledger is running: http://localhost:8000" -ForegroundColor Green
Write-Host "Sign in as admin. The password is ADMIN_PASSWORD in .env."
