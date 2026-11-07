#!/usr/bin/env bash
# Mac/Linux: run the automated tests (backend pytest + frontend build).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
[ -d backend/.venv ] || "$PY" -m venv backend/.venv
backend/.venv/bin/python -m pip install -q --upgrade pip
backend/.venv/bin/python -m pip install -q -r backend/requirements.txt
( cd backend && .venv/bin/python -m pytest )
if command -v npm >/dev/null 2>&1; then
  ( cd frontend && npm ci --no-audit --no-fund && npm run build )
else
  echo "npm not found: skipped the frontend build"
fi
echo "All checks passed."
