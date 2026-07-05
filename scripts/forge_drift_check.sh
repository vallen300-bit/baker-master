#!/usr/bin/env bash
# forge_drift_check.sh — daily drift sentinel for the forge-agent liveness layer.
#
# Runs `install_forge_agent.sh --check` from a self-contained check bundle and:
#   - ALWAYS appends a timestamped one-line result to a grep-able log
#     (~/.brisen-lab/forge-drift.log): "<ts> forge-drift <host> <RESULT> ...".
#   - On DRIFT (non-zero --check), ALSO posts a bus message to `lead` so the
#     drift surfaces without anyone reading the log.
#
# Invoked by the launchd job com.brisen.forge-drift-check (daily). Kept separate
# from the checkout so it survives on a TCC-protected host where launchd cannot
# read the repo (bundle lives under ~/Library/Application Support/baker/, which
# launchd CAN read — same TCC-safe pattern as forge-snapshot-push).
#
# CONTRACT: exit 0 on every path (a sentinel that fails is invisible; the drift
# signal is the log line + bus post, never the exit code). Never blocks.

set -uo pipefail

BUNDLE_DIR="${FORGE_CHECK_DIR:-$HOME/Library/Application Support/baker/forge-check}"
INSTALLER="${BUNDLE_DIR}/install_forge_agent.sh"
LOG="${FORGE_DRIFT_LOG:-$HOME/.brisen-lab/forge-drift.log}"
LAB_URL="${LAB_URL:-https://brisen-lab.onrender.com}"
SENDER="${FORGE_DRIFT_BUS_ROLE:-daemon}"    # bus sender slug for the alert
TS="$(date -u +%FT%TZ)"
HOST="$(hostname 2>/dev/null || echo unknown)"

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

if [[ ! -f "$INSTALLER" ]]; then
  printf '%s forge-drift %s ERROR bundle-missing (%s)\n' "$TS" "$HOST" "$INSTALLER" >> "$LOG" 2>/dev/null || true
  exit 0
fi

# Run the check; capture output + exit code (never let it abort the sentinel).
OUT="$(bash "$INSTALLER" --check 2>&1)"; RC=$?

if [[ "$RC" -eq 0 ]]; then
  printf '%s forge-drift %s CLEAN\n' "$TS" "$HOST" >> "$LOG" 2>/dev/null || true
  exit 0
fi

# DRIFT. Log the failing lines (compact, grep-able) then bus-post to lead.
FAILS="$(printf '%s\n' "$OUT" | grep -E '\[FAIL\]|missing-wire|director-hook|RESULT: DRIFT' | tr '\n' ';' | sed 's/;$//')"
printf '%s forge-drift %s DRIFT %s\n' "$TS" "$HOST" "${FAILS:-see-bundle}" >> "$LOG" 2>/dev/null || true

# Best-effort bus post to lead. Key from ~/.brisen-lab/keys/<sender>; skip
# quietly if unavailable (the log line already recorded the drift).
KEY_FILE="$HOME/.brisen-lab/keys/${SENDER}"
if [[ -r "$KEY_FILE" ]]; then
  KEY="$(tr -d '\r\n' < "$KEY_FILE" 2>/dev/null || true)"
  BODY="forge-agent DRIFT on ${HOST} (${TS}): ${FAILS:-see log}. Re-run install_forge_agent.sh on that host to converge; log: ${LOG}."
  # Sender is inferred from the X-Terminal-Key (daemon key) — NOT sent in-body.
  # Endpoint is /msg/{recipient}; body uses `to` (list). Mirrors bus_post.py and
  # the daemon's own daemon->lead alert path (app.py from_slug="daemon").
  curl -fsS --max-time 6 -X POST "${LAB_URL}/msg/lead" \
    -H "X-Terminal-Key: ${KEY}" -H "Content-Type: application/json" \
    -d "$(FORGE_BODY="$BODY" HOST="$HOST" python3 -c '
import json, os
print(json.dumps({
    "kind": "alert",
    "body": os.environ["FORGE_BODY"],
    "to": ["lead"],
    "tier_required": "A",
    "topic": "drift/forge-agent-" + os.environ["HOST"],
}))')" >/dev/null 2>&1 || true
fi
exit 0
