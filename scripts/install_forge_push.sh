#!/usr/bin/env bash
# install_forge_push.sh — install or reinstall the forge-snapshot-push launchd agent.
# Idempotent: unloads existing, regenerates plist with current FORGE_KEY, reloads.

set -euo pipefail

if [[ -z "${FORGE_KEY:-}" ]]; then
  echo "FATAL: FORGE_KEY env var must be set in the calling shell" >&2
  exit 2
fi

LABEL="com.baker.forge-snapshot-push"
TEMPLATE="$(dirname "$0")/launchd/${LABEL}.plist"
INSTALLED="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "FATAL: template missing at $TEMPLATE" >&2
  exit 2
fi

# Unload existing if present (ignore errors — may not be loaded).
launchctl unload "$INSTALLED" 2>/dev/null || true

# Generate plist with FORGE_KEY substituted. Pipe delimiter avoids collision
# with slashes that may appear in a key.
sed "s|__FORGE_KEY__|${FORGE_KEY}|" "$TEMPLATE" > "$INSTALLED"
chmod 600 "$INSTALLED"   # protect the embedded secret

launchctl load -w "$INSTALLED"

echo "Installed: $INSTALLED"
echo "Verify: launchctl list | grep $LABEL"
echo "Log: ~/Library/Logs/forge-snapshot-push.log"
