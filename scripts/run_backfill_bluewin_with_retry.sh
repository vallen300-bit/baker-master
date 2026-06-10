#!/bin/bash
# Retry wrapper for scripts/backfill_bluewin.py — the script is cursor-resumable,
# but a single IMAP socket EOF kills the process (seen 2026-06-10 14:12 local,
# uid 91256, 5794/23691 INBOX). Loop until clean exit, capped attempts.
# Launched by AH1-lead (Tier A recovery of Director-ratified BACKFILL_BLUEWIN_1 run).
set -u
cd "$(dirname "$0")/.."

export BLUEWIN_USER="$(op read 'op://Baker API Keys/Bluewin IMAP/username')"
export BLUEWIN_PASS="$(op read 'op://Baker API Keys/Bluewin IMAP/password')"
export DATABASE_URL="$(op read 'op://Baker API Keys/DATABASE_URL/credential')"

MAX_ATTEMPTS=30
SLEEP_BASE=60
attempt=0
while [ $attempt -lt $MAX_ATTEMPTS ]; do
  attempt=$((attempt + 1))
  echo "=== wrapper attempt $attempt/$MAX_ATTEMPTS @ $(date -u +%FT%TZ) ==="
  python3 scripts/backfill_bluewin.py
  rc=$?
  if [ $rc -eq 0 ]; then
    echo "=== backfill COMPLETE (exit 0) @ $(date -u +%FT%TZ) after $attempt attempt(s) ==="
    exit 0
  fi
  echo "=== exit $rc — resuming from cursor after ${SLEEP_BASE}s ==="
  sleep $SLEEP_BASE
done
echo "=== wrapper EXHAUSTED $MAX_ATTEMPTS attempts — manual attention needed ==="
exit 1
