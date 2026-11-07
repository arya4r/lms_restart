#!/bin/bash
# Double-click to start Loan Ledger on MySQL. Installs MySQL, Python and Node with Homebrew if missing.
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
LOG="$PWD/.local-run.log"; mkdir -p .local
exec > >(tee "$LOG") 2>&1
echo "== Loan Ledger local start $(date)"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed. Install it from https://brew.sh, then double-click this file again."
  read -r -p "Press Enter to close"; exit 1
fi
need=()
command -v mysql >/dev/null 2>&1 || need+=(mysql)
command -v node >/dev/null 2>&1 || need+=(node)
ok_py=0
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null && ok_py=1 && break
done
[ "$ok_py" = 1 ] || need+=(python@3.12)
if [ ${#need[@]} -gt 0 ]; then
  echo "== Installing with Homebrew: ${need[*]}"
  brew install "${need[@]}" || { echo "Homebrew install failed"; read -r -p "Press Enter to close"; exit 1; }
fi
echo "== Starting MySQL"
brew services start mysql || true
for _ in $(seq 1 30); do mysqladmin ping >/dev/null 2>&1 && break; sleep 1; done
mysqladmin ping || { echo "MySQL did not start"; read -r -p "Press Enter to close"; exit 1; }
./start-local.sh
