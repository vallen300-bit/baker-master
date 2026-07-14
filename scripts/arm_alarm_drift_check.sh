#!/usr/bin/env bash
# arm_alarm_drift_check.sh — drift sentinel for the ARM out-of-band alarm job.
#
# Runs `install_arm_alarm_job.sh --check` and:
#   - ALWAYS appends a timestamped one-line result to a grep-able log
#     (~/.brisen-lab/arm-alarm-drift.log): "<ts> arm-alarm-drift <host> <RESULT> ...".
#   - On DRIFT (non-zero --check), ALSO posts a bus message to `lead` so the
#     drift surfaces without anyone reading the log.
#
# NOTE ON THE BUS: this sentinel checks that the alarm JOB is installed/healthy
# — an install-health meta-check — and it is fine for THAT to travel over the
# bus (normal channel). It is distinct from the alarm's own out-of-band send
# path, which never uses the bus. If the bus itself is down, the alarm job's own
# out-of-band email is the primary signal; this drift-post is the secondary,
# "is the alarm job even installed" check.
#
# Mirrors forge_drift_check.sh / arm_cadence_drift_check.sh: same TCC-safe bundle
# probe, same fail-open contract (exit 0 on every path — a sentinel that fails is
# invisible; the signal is the log line + bus post, never the exit code).

set -uo pipefail

BUNDLE_DIR="${ARM_ALARM_CHECK_DIR:-$HOME/Library/Application Support/baker/arm-alarm-check}"
# Probe scripts/-first then bundle root (both invocation modes) so a manual run
# never false-reports "bundle-missing" — the forge_drift_check.sh anchor lesson.
INSTALLER="${BUNDLE_DIR}/scripts/install_arm_alarm_job.sh"
[[ -f "$INSTALLER" ]] || INSTALLER="${BUNDLE_DIR}/install_arm_alarm_job.sh"
# Fall back to a sibling in THIS checkout (dev / CI runs without a deployed bundle).
[[ -f "$INSTALLER" ]] || INSTALLER="$(cd "$(dirname "$0")" && pwd)/install_arm_alarm_job.sh"
FLEET_PARITY="${BUNDLE_DIR}/scripts/arm_fleet_parity.sh"
[[ -f "$FLEET_PARITY" ]] || FLEET_PARITY="${BUNDLE_DIR}/arm_fleet_parity.sh"
[[ -f "$FLEET_PARITY" ]] || FLEET_PARITY="$(cd "$(dirname "$0")" && pwd)/arm_fleet_parity.sh"

LOG="${ARM_ALARM_DRIFT_LOG:-$HOME/.brisen-lab/arm-alarm-drift.log}"
LAB_URL="${LAB_URL:-https://brisen-lab.onrender.com}"
SENDER="${ARM_ALARM_DRIFT_BUS_ROLE:-daemon}"    # bus sender slug for the alert
TS="$(date -u +%FT%TZ)"
HOST="$(hostname 2>/dev/null || echo unknown)"

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

if [[ ! -f "$INSTALLER" ]]; then
  printf '%s arm-alarm-drift %s ERROR bundle-missing (%s)\n' "$TS" "$HOST" "$INSTALLER" >> "$LOG" 2>/dev/null || true
  exit 0
fi

# Run the check; capture output + exit code (never let it abort the sentinel).
OUT="$(bash "$INSTALLER" --check 2>&1)"; RC=$?
FLEET_OUT=""; FLEET_RC=0
if [[ -f "$FLEET_PARITY" ]]; then
  FLEET_OUT="$(bash "$FLEET_PARITY" 2>&1)"; FLEET_RC=$?
fi

if [[ "$RC" -eq 0 && "$FLEET_RC" -eq 0 ]]; then
  printf '%s arm-alarm-drift %s CLEAN\n' "$TS" "$HOST" >> "$LOG" 2>/dev/null || true
  exit 0
fi

# DRIFT. Log the failing lines (compact, grep-able) then bus-post to lead.
FAILS="$(printf '%s\n%s\n' "$OUT" "$FLEET_OUT" \
  | grep -E '\[FAIL\]|RESULT: DRIFT|^(RED|DRIFT) ' \
  | tr '\n' ';' | sed 's/;$//')"
printf '%s arm-alarm-drift %s DRIFT %s\n' "$TS" "$HOST" "${FAILS:-see-bundle}" >> "$LOG" 2>/dev/null || true

# Best-effort bus post to lead. Key from ~/.brisen-lab/keys/<sender>; skip
# quietly if unavailable (the log line already recorded the drift).
KEY_FILE="$HOME/.brisen-lab/keys/${SENDER}"
if [[ -r "$KEY_FILE" ]]; then
  KEY="$(tr -d '\r\n' < "$KEY_FILE" 2>/dev/null || true)"
  BODY="arm-alarm watchdog DRIFT on ${HOST} (${TS}): ${FAILS:-see log}. ARM's OUT-OF-BAND alarm job may not be installed/loaded — re-run install_arm_alarm_job.sh on that host to converge; log: ${LOG}."
  # kind MUST be a VALID_KIND (dispatch); mint a per-post envelope id so a future
  # BRISEN_LAB_REQUIRE_ENVELOPE_ID flip does not silently 400 the alert.
  curl -fsS --max-time 6 -X POST "${LAB_URL}/msg/lead" \
    -H "X-Terminal-Key: ${KEY}" -H "Content-Type: application/json" \
    -d "$(ARM_BODY="$BODY" HOST="$HOST" python3 -c '
import json, os, uuid
print(json.dumps({
    "kind": "dispatch",
    "body": os.environ["ARM_BODY"],
    "to": ["lead"],
    "tier_required": "A",
    "topic": "drift/arm-alarm-" + os.environ["HOST"],
    "idempotency_key": str(uuid.uuid4()),
}))')" >/dev/null 2>&1 || true
fi
exit 0
