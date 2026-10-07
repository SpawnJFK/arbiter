#!/bin/sh
# Runs migrations before the main process when ARBITER_MIGRATE_ON_START=1.
# Set it on exactly one service (the api) so two containers never race on alembic.
set -eu

if [ "${ARBITER_MIGRATE_ON_START:-0}" = "1" ]; then
  echo "[entrypoint] alembic upgrade head"
  cd /app
  alembic upgrade head
fi

exec "$@"
