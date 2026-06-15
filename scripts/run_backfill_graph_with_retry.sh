#!/bin/bash
# Retry wrapper for scripts/backfill_graph.py — mirror of bluewin wrapper.
# Serialized after bluewin run: Neon pooler threw "Too many connections attempts"
# when both historical runs + prod service hit it concurrently (2026-06-10 20:30 local).
set -u
cd "$(dirname "$0")/.."
export DATABASE_URL="$(op read 'op://Baker API Keys/DATABASE_URL/credential')"
export BAKER_USE_GRAPH=true
# Item name contains "/" — must reference by item ID (op:// cannot escape slashes).
export M365_TENANT_ID="$(op read 'op://Baker API Keys/wyeoa7ymygvfp5vmuqnjd5xkry/tenant_id')"
export M365_CLIENT_ID="$(op read 'op://Baker API Keys/wyeoa7ymygvfp5vmuqnjd5xkry/client_id')"
export M365_CERT_THUMBPRINT="$(op read 'op://Baker API Keys/wyeoa7ymygvfp5vmuqnjd5xkry/cert_thumbprint')"
KEYFILE="$(mktemp /tmp/graph-key.XXXXXX.pem)"
chmod 600 "$KEYFILE"
op document get "M365 Graph cert PRIVATE KEY (PEM, unlocked 2026-06-03)" --vault "Baker API Keys" --output "$KEYFILE" --force
export M365_CERT_PATH="$KEYFILE"
trap 'rm -f "$KEYFILE"' EXIT
MAX_ATTEMPTS=30
attempt=0
while [ $attempt -lt $MAX_ATTEMPTS ]; do
  attempt=$((attempt + 1))
  echo "=== graph wrapper attempt $attempt/$MAX_ATTEMPTS @ $(date -u +%FT%TZ) ==="
  python3 scripts/backfill_graph.py
  rc=$?
  [ $rc -eq 0 ] && echo "=== graph backfill COMPLETE @ $(date -u +%FT%TZ) ===" && exit 0
  echo "=== exit $rc — resuming from cursor after 90s ==="
  sleep 90
done
echo "=== graph wrapper EXHAUSTED ==="
exit 1
