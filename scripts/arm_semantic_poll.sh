#!/usr/bin/env bash
# arm_semantic_poll.sh — SEMANTIC_DELIVERY_EVALUATOR_1 producer poller (Option 2,
# lead ruling #10915).
#
# The ARM custodian's SEMANTIC delivery poll. Fetches the server-side evaluator
# verdict from the Render app (which holds DATABASE_URL) and writes it as the
# local semantic.json marker that arm_alarm_check.sh consumes. This keeps the
# prod DB DSN server-side — a DSN in a local plist was declined on principle
# (#10915). curl-only, ZERO LLM tokens per poll (charter §5).
#
# WHY a producer poller and not a cron of the CLI evaluator: the evaluator needs
# the DB; the custodian is deliberately public-endpoint + bus-key only. So the
# eval runs server-side (GET /api/semantic_delivery, terminal-key gated) and this
# poller just fetches + writes the marker (mirrors arm_cadence_poll.sh, which
# fetches /api/bus_health).
#
# FAIL-SAFE POSTURE (lead #10915): on ANY fetch failure (non-200 / unparseable /
# missing load-bearing field) this poller does NOT overwrite semantic.json. A
# stale marker then ages out and pages under ARM_ALARM_SEMANTIC_ENFORCE=1 — the
# correct posture (a broken producer must not silently mask delivery health).
# Exits 0 on every completed run (even a skipped write) so the crash-only
# KeepAlive does NOT hot-loop; a non-zero exit means a genuine crash.
#
# Env:
#   LAB_URL                    optional. Default https://brisen-lab.onrender.com
#   ARM_ALARM_MARKER_DIR       optional. Marker dir. Default ~/.brisen-lab/arm-alarm/markers
#   ARM_SEMANTIC_KEY           optional. Terminal key (injected by the plist). Falls
#                              back to the key cache / 1Password via the key helper.
#   ARM_SEMANTIC_SEAT          optional. Seat slug whose key authenticates the fetch.
#                              Default 'daemon'. (Endpoint accepts any valid seat key.)
#   ARM_SEMANTIC_LOG           optional. Log file. Default ~/.brisen-lab/arm-semantic.log

set -u
set -o pipefail

LAB_URL="${LAB_URL:-https://brisen-lab.onrender.com}"
MARKER_DIR="${ARM_ALARM_MARKER_DIR:-$HOME/.brisen-lab/arm-alarm/markers}"
MARKER="${MARKER_DIR}/semantic.json"
SEAT="${ARM_SEMANTIC_SEAT:-daemon}"
LOG="${ARM_SEMANTIC_LOG:-$HOME/.brisen-lab/arm-semantic.log}"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/brisen_lab_terminal_key.sh
[ -f "$SCRIPT_DIR/brisen_lab_terminal_key.sh" ] && . "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

log_line() {
  mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$LOG" 2>/dev/null || true
}

# Resolve the terminal key: env → key cache → 1Password (via the helper).
KEY="${ARM_SEMANTIC_KEY:-}"
if [ -z "$KEY" ] && command -v brisen_lab_read_terminal_key >/dev/null 2>&1; then
  KEY="$(brisen_lab_read_terminal_key "$SEAT" "" 2>/dev/null || true)"
fi
if [ -z "$KEY" ]; then
  log_line "SKIP no terminal key for seat=${SEAT} (marker left untouched; ages out -> pages)"
  exit 0
fi

mkdir -p "$MARKER_DIR" 2>/dev/null || true

# Fetch the server-side verdict. --max-time bounds a cold-start; a slow/failed
# fetch must not hang the launchd slot.
TMP_BODY="$(mktemp "${MARKER_DIR}/.semantic-fetch.XXXXXX" 2>/dev/null || echo "")"
if [ -z "$TMP_BODY" ]; then
  log_line "SKIP mktemp failed in ${MARKER_DIR} (marker left untouched)"
  exit 0
fi
trap 'rm -f "$TMP_BODY" 2>/dev/null || true' EXIT

HTTP="$(curl -sS --connect-timeout 5 --max-time 45 \
  -H "X-Terminal-Key: ${KEY}" \
  -o "$TMP_BODY" -w "%{http_code}" \
  "${LAB_URL}/api/semantic_delivery" 2>/dev/null)" || HTTP="000"

if [ "$HTTP" != "200" ]; then
  log_line "SKIP fetch HTTP ${HTTP} (marker left untouched; stale ages out -> pages)"
  exit 0
fi

# Validate: parseable JSON carrying the load-bearing marker fields (b4 #10634
# contract: schema startswith semantic_delivery_verdict_v1, evaluated_at, semantic_ok).
# A 200-empty / malformed body must NOT overwrite a good marker.
if ! VALID="$(MK_BODY="$TMP_BODY" python3 - <<'PY' 2>/dev/null
import json, os, sys
try:
    d = json.load(open(os.environ["MK_BODY"]))
except Exception:
    sys.exit(1)
if not isinstance(d, dict):
    sys.exit(1)
schema = d.get("schema")
if not (isinstance(schema, str) and schema.startswith("semantic_delivery_verdict_v1")):
    sys.exit(1)
if not isinstance(d.get("evaluated_at"), str):
    sys.exit(1)
if not isinstance(d.get("semantic_ok"), bool):
    sys.exit(1)
print("ok")
PY
)"; then
  log_line "SKIP body failed validation (HTTP 200 but not a valid verdict; marker left untouched)"
  exit 0
fi

# Atomic write: rename within the same dir so arm_alarm_check.sh never reads a
# half-written marker.
if mv -f "$TMP_BODY" "$MARKER" 2>/dev/null; then
  OK="$(python3 -c "import json;print(json.load(open('$MARKER')).get('semantic_ok'))" 2>/dev/null || echo '?')"
  log_line "OK wrote semantic.json (semantic_ok=${OK})"
else
  log_line "SKIP atomic rename failed (marker left untouched)"
fi
exit 0
