#!/usr/bin/env bash
# Launch the BetPredictor local dashboard.
# Ensures the project's Postgres (with the existing data volume) is running
# on host port 5433, then serves the dashboard on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")/.."

DB_PORT="${DB_PORT:-5433}"
PORT="${PORT:-8000}"
CONTAINER="betpredictor_db"

# Start the DB container from the existing data volume if not already up.
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "Starting existing ${CONTAINER}…"; docker start "${CONTAINER}" >/dev/null
  else
    echo "Creating ${CONTAINER} on port ${DB_PORT} from volume betpredictor_pgdata…"
    docker run -d --name "${CONTAINER}" \
      -e POSTGRES_USER=user -e POSTGRES_PASSWORD=pwd -e POSTGRES_DB=betting_historical_data \
      -p "${DB_PORT}:5432" -v betpredictor_pgdata:/var/lib/postgresql/data postgres:16 >/dev/null
  fi
  for i in $(seq 1 30); do
    docker exec "${CONTAINER}" pg_isready -U user -d betting_historical_data >/dev/null 2>&1 && break
    sleep 1
  done
fi

export DB_URL="${DB_URL:-postgresql://user:pwd@localhost:${DB_PORT}/betting_historical_data}"
export PORT
echo "Dashboard → http://localhost:${PORT}"
exec ./venv/bin/python dashboard/app.py
