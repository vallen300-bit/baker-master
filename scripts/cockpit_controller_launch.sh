#!/usr/bin/env bash
# Launchd entrypoint: restore tmux substrate before the controller starts.
set -euo pipefail

: "${COCKPIT_CONTROLLER_SCRIPT:?COCKPIT_CONTROLLER_SCRIPT is required}"
: "${COCKPIT_FLEET_SCRIPT:?COCKPIT_FLEET_SCRIPT is required}"

if [[ ! -x "$COCKPIT_FLEET_SCRIPT" ]]; then
  echo "FATAL: fleet launcher missing or not executable: $COCKPIT_FLEET_SCRIPT" >&2
  exit 2
fi

"$COCKPIT_FLEET_SCRIPT" up
exec /usr/bin/python3 "$COCKPIT_CONTROLLER_SCRIPT" \
  --host "${COCKPIT_HOST:-127.0.0.1}" \
  --port "${COCKPIT_PORT:-7800}"
