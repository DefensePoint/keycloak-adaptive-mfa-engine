#!/usr/bin/env bash

CUSTOM_MSG=$1

if [ -z "$CUSTOM_MSG" ]; then
  echo "Error: You must provide a migration message."
  echo "Usage: ./generate_migration.sh \"add new users table\""
  exit 1
fi

docker exec -it amfa alembic revision --autogenerate -m "$CUSTOM_MSG"
