# Windows: run the automated tests (backend pytest + frontend build).
#   powershell -ExecutionPolicy Bypass -File scripts\test.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Find a Python 3.10+ (the py launcher first, then python on PATH)
$py = $null
foreach ($cand in @("py -3.12", "py -3.13", "py -3", "python")) {
    $exe, $args0 = $cand.Split(" ", 2)
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        & $exe $args0 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $py = $cand; break }
    }
}
if (-not $py) { throw "Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'." }

if (-not (Test-Path "backend\.venv\Scripts\python.exe")) {
    $exe, $args0 = $py.Split(" ", 2)
    & $exe $args0 -m venv backend\.venv
}
$venv = "backend\.venv\Scripts\python.exe"
& $venv -m pip install -q --upgrade pip
& $venv -m pip install -q -r backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Installing Python packages failed." }

Push-Location backend
& .\.venv\Scripts\python.exe -m pytest
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw "Backend tests failed." }

if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location frontend
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -eq 0) { npm run build }
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { throw "Frontend build failed." }
} else {
    Write-Host "npm not found: skipped the frontend build. Install Node.js 22 LTS to include it." -ForegroundColor Yellow
}
Write-Host "All checks passed." -ForegroundColor Green
