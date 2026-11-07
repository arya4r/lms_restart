#!/usr/bin/env bash
# Mac/Linux: set up and start Loan Ledger with Docker.
#   ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null 2>&1 || { echo "Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is installed but not running. Start it and run this again."; exit 1; }

secret() { python3 -c "import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))" "$1"; }
if [ ! -f .env ]; then
  sed -e "s/^MYSQL_PASSWORD=.*/MYSQL_PASSWORD=$(secret 16)/" \
      -e "s/^MYSQL_ROOT_PASSWORD=.*/MYSQL_ROOT_PASSWORD=$(secret 16)/" \
      -e "s/^JWT_SECRET=.*/JWT_SECRET=$(secret 32)/" \
      -e "s/^ADMIN_PASSWORD=.*/ADMIN_PASSWORD=$(secret 12)/" .env.example > .env
  echo "Created .env with generated passwords. The admin password is ADMIN_PASSWORD in .env."
else
  echo "Using the existing .env"
fi

docker compose up --build -d
echo "Waiting for the app..."
for _ in $(seq 1 60); do
  curl -fsS http://localhost:8000/api/health >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS http://localhost:8000/api/health >/dev/null || { echo "The app did not start. Run: docker compose logs app"; exit 1; }
echo "Loan Ledger is running: http://localhost:8000 (sign in as admin; password in .env)"
