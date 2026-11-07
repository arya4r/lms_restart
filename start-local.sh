#!/usr/bin/env bash
# Run Loan Ledger on this computer.
#   ./start-local.sh            uses local MySQL if it's installed, otherwise SQLite
#   ./start-local.sh --sqlite   always use SQLite (no database install needed)
#   ./start-local.sh --reset    wipe the local data and start fresh
# Then open http://localhost:8000 and sign in as admin / Admin@12345
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
PORT="${PORT:-8000}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin@12345}"
USE_SQLITE=0; RESET=0
for a in "$@"; do
  case "$a" in --sqlite) USE_SQLITE=1 ;; --reset) RESET=1 ;; esac
done

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31m%s\033[0m\n' "$*"; exit 1; }

# ---- prerequisites -----------------------------------------------------------
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
[ -n "$PY" ] || die "Python 3.10 or newer is needed. On a Mac: brew install python@3.12   (Homebrew: https://brew.sh)"
command -v npm >/dev/null 2>&1 || die "Node.js is needed. On a Mac: brew install node"

# ---- database ----------------------------------------------------------------
mkdir -p "$ROOT/.local"
# A DATABASE_URL already set in the environment (for example an AWS RDS database reached through a
# tunnel) is used as it is. Demo data is never loaded into it, and --reset is refused.
EXTERNAL_DB=0
if [ -n "${DATABASE_URL:-}" ]; then
  EXTERNAL_DB=1
  [ "$RESET" = 1 ] && die "--reset is not allowed with a DATABASE_URL set. Remove DATABASE_URL to use the local database."
  say "Using DATABASE_URL from the environment"
elif [ "$USE_SQLITE" = 0 ] && command -v mysql >/dev/null 2>&1; then
  say "Using local MySQL"
  if command -v brew >/dev/null 2>&1 && ! mysqladmin ping >/dev/null 2>&1; then
    brew services start mysql >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do mysqladmin ping >/dev/null 2>&1 && break; sleep 1; done
  fi
  MYSQL_ROOT=(mysql -u root)
  [ -n "${MYSQL_ROOT_PASSWORD:-}" ] && MYSQL_ROOT=(mysql -u root "-p$MYSQL_ROOT_PASSWORD")
  if "${MYSQL_ROOT[@]}" -e "SELECT 1" >/dev/null 2>&1; then
    [ "$RESET" = 1 ] && "${MYSQL_ROOT[@]}" -e "DROP DATABASE IF EXISTS lms;"
    "${MYSQL_ROOT[@]}" -e "CREATE DATABASE IF NOT EXISTS lms CHARACTER SET utf8mb4;
      CREATE USER IF NOT EXISTS 'lms'@'localhost' IDENTIFIED BY 'lms';
      GRANT ALL ON lms.* TO 'lms'@'localhost'; FLUSH PRIVILEGES;"
    export DATABASE_URL="mysql+pymysql://lms:lms@127.0.0.1:3306/lms"
  else
    say "MySQL is installed but root login failed. Re-run with MYSQL_ROOT_PASSWORD=yourpassword ./start-local.sh, or use --sqlite."
    exit 1
  fi
else
  say "Using SQLite (file .local/lms.db). Install MySQL with 'brew install mysql' to run on MySQL."
  [ "$RESET" = 1 ] && rm -f "$ROOT/.local/lms.db"
  export DATABASE_URL="sqlite:///$ROOT/.local/lms.db"
fi

# ---- backend -----------------------------------------------------------------
say "Setting up Python packages (first run takes a minute)"
[ -d "$ROOT/.local/venv" ] || "$PY" -m venv "$ROOT/.local/venv"
# shellcheck disable=SC1091
source "$ROOT/.local/venv/bin/activate"
pip install -q --upgrade pip >/dev/null
pip install -q -r backend/requirements.txt

# ---- frontend ----------------------------------------------------------------
say "Building the admin screens"
( cd frontend && { [ -d node_modules ] || npm install --silent --no-audit --no-fund; } && npm run -s build )
rm -rf backend/static && cp -R frontend/dist backend/static

# ---- start -------------------------------------------------------------------
export ADMIN_PASSWORD JWT_SECRET="local-dev-secret-$(whoami)-0123456789abcdef" CORS_ORIGINS="http://localhost:$PORT" TZ="Asia/Kolkata"
FIRST_RUN=0; [ -f "$ROOT/.local/seeded" ] && [ "$RESET" = 0 ] || FIRST_RUN=1
[ "$EXTERNAL_DB" = 1 ] && FIRST_RUN=0  # never load demo data into an external database

cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT INT TERM
for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break; sleep 1; done
curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null || die "The server didn't start. See the messages above."

if [ "$FIRST_RUN" = 1 ]; then
  say "Loading demo data (sample M2P book and three new loans)"
  python scripts/seed_demo.py "http://127.0.0.1:$PORT" admin "$ADMIN_PASSWORD" && touch "$ROOT/.local/seeded"
fi

say "Loan Ledger is running at http://localhost:$PORT  (sign in: admin / $ADMIN_PASSWORD). Press Ctrl+C to stop."
[ "$(uname)" = "Darwin" ] && open "http://localhost:$PORT" || true
wait $SERVER
