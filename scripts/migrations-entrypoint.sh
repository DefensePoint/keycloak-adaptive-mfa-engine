#!/usr/bin/env bash
# This should run automatically when starting docker's image runtime,
# at build time there is no access to env variables set in docker-compose.

set -e

echo "Waiting for Postgres at host='${POSTGRES_HOST}' port='${POSTGRES_PORT}' user='${POSTGRES_USER}'"

until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-postgres}"; do
    echo "Postgres is unavailable - sleeping"
    sleep 2
done
echo "Postgres is up!"

if [ -d /app/migrations/versions ] && [ "$(ls -A /app/migrations/versions)" ]; then
    echo "Running Alembic migrations..."
    alembic upgrade head
else
    echo "No migrations to apply"
fi

exec "$@"
