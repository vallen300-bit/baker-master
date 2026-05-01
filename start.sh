#!/bin/bash
# Baker start script
set -e

# Pre-flight: verify migration files match migrations/applied_migrations.lock
# BEFORE uvicorn boots dashboard (which invokes config.migration_runner).
# A drift here means an applied migration file was edited after the lock was
# refreshed — the migration runner will also abort, but pre-flight gives a
# louder, earlier signal that does not depend on DB connectivity.
if [ -x scripts/check_applied_migrations.sh ]; then
  # Strip the dev-only bypass env var so runtime divergence is always loud.
  if ! env -u BAKER_MIGRATION_EDIT_AUTHORIZED scripts/check_applied_migrations.sh; then
    echo "[start.sh] migration immutability check failed — refusing to boot." >&2
    exit 1
  fi
fi

exec uvicorn outputs.dashboard:app --host 0.0.0.0 --port $PORT
