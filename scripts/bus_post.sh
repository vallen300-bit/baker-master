#!/usr/bin/env bash
# bus_post.sh — AI Head outbound auto-post to Brisen Lab bus.
# Director ratified 2026-05-06 OPTION A + policy (ii): op-fetch sender key on demand.
#
# Usage:
#   bus_post.sh <recipient_slug> <body> [topic]
#
# Env:
#   BAKER_ROLE              — required. Maps to sender slug.
#                             AH1/aihead1/lead → lead
#                             AH2/aihead2/deputy → deputy
#                             B1-B5/b1-b5 → b1-b5
#                             architect → architect
#                             cortex → cortex
#                             aid/AID → aid
#                             codex/CODEX → codex
#   BRISEN_LAB_DAEMON_URL   — optional. Default: https://brisen-lab.onrender.com
#
# Exits non-zero on any failure with descriptive stderr.

set -euo pipefail

DAEMON_URL="${BRISEN_LAB_DAEMON_URL:-https://brisen-lab.onrender.com}"

# --- arg parsing ---

if [ "${1:-}" = "" ] || [ "${2:-}" = "" ]; then
    echo "Usage: bus_post.sh <recipient_slug> <body> [topic]" >&2
    exit 2
fi

RECIPIENT="$1"
BODY="$2"
TOPIC="${3:-}"

# --- recipient validation ---

# F2-FU-1 (Stage 2 BRISEN_LAB_APP_AUTOPOLL_INBOX_1): director-recipient is no
# longer hard-rejected client-side. Daemon enforces the env-gated block via
# BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED. Single control point — flipping the
# daemon flag is now the only kill-switch (no script-layer drift).

# Validate against canonical slug registry (Director ratified aid 2026-05-10;
# hag-desk added 2026-05-21 per HAGENAUER_DESK_ON_BUS_1 single-desk pilot;
# researcher added 2026-05-22 per RESEARCHER_ON_BUS_1 Cowork-App-only install;
# CM-1..4 + hag-filer added 2026-05-24 per HAG_WORKERS_PHASE_1 worker pool build;
# codex added 2026-05-29 per CODEX_ON_BUS_1 slim install — CLI-based, no dashboard card / SessionStart hook).
case "$RECIPIENT" in
    director|cowork-ah1|lead|deputy|architect|b1|b2|b3|b4|b5|cortex|daemon|aid|codex|hag-desk|researcher|CM-1|CM-2|CM-3|CM-4|hag-filer) ;;
    *)
        echo "ERROR: unknown slug: $RECIPIENT" >&2
        echo "  Valid: director cowork-ah1 lead deputy architect b1 b2 b3 b4 b5 cortex daemon aid codex hag-desk researcher CM-1 CM-2 CM-3 CM-4 hag-filer" >&2
        exit 1
        ;;
esac

# --- sender slug from BAKER_ROLE ---

case "${BAKER_ROLE:-}" in
    AH1|aihead1|lead|LEAD)              SENDER=lead ;;
    AH1-APP|cowork-ah1|COWORK-AH1)      SENDER=cowork-ah1 ;;
    AH2|aihead2|deputy|DEPUTY)          SENDER=deputy ;;
    B1|b1)                              SENDER=b1 ;;
    B2|b2)                              SENDER=b2 ;;
    B3|b3)                              SENDER=b3 ;;
    B4|b4)                              SENDER=b4 ;;
    B5|b5)                              SENDER=b5 ;;
    architect|ARCHITECT)                SENDER=architect ;;
    cortex|CORTEX)                      SENDER=cortex ;;
    aid|AID)                            SENDER=aid ;;
    codex|CODEX)                        SENDER=codex ;;
    hag-desk|HAG-DESK|hagenauer-desk)   SENDER=hag-desk ;;
    researcher|RESEARCHER)              SENDER=researcher ;;
    CM-1|cm-1|CM_1)                     SENDER=CM-1 ;;
    CM-2|cm-2|CM_2)                     SENDER=CM-2 ;;
    CM-3|cm-3|CM_3)                     SENDER=CM-3 ;;
    CM-4|cm-4|CM_4)                     SENDER=CM-4 ;;
    hag-filer|HAG-FILER|hag_filer)      SENDER=hag-filer ;;
    *)
        echo "ERROR: BAKER_ROLE not set or unrecognized: '${BAKER_ROLE:-}'" >&2
        echo "  Valid: AH1 (terminal=lead), AH1-APP (Cowork=cowork-ah1), AH2, B1-B5, architect, cortex, aid, codex, hag-desk, researcher, CM-1, CM-2, CM-3, CM-4, hag-filer" >&2
        exit 1
        ;;
esac

# --- credential fetch ---
# Prefer pre-fetched env var (set by picker functions like cdx() to avoid
# requiring 1P access inside sandboxed sub-agent shells); fall back to 1P.

KEY="${BRISEN_LAB_TERMINAL_KEY:-}"
if [ -z "$KEY" ]; then
    KEY="$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${SENDER}/credential" 2>/dev/null)" || {
        echo "ERROR: 1Password CLI fetch failed for sender=${SENDER}" >&2
        echo "  Check: op CLI authenticated (op whoami) OR pre-set BRISEN_LAB_TERMINAL_KEY env" >&2
        exit 1
    }
fi

if [ -z "$KEY" ]; then
    echo "ERROR: terminal key empty for sender=${SENDER} (no env, no 1P)" >&2
    exit 1
fi

# --- payload construction (Python json.dumps for safe escaping) ---

PAYLOAD="$(python3 -c '
import json, sys
recipient, body, topic = sys.argv[1], sys.argv[2], sys.argv[3]
out = {"kind": "dispatch", "body": body, "to": [recipient], "tier_required": "B"}
if topic:
    out["topic"] = topic
print(json.dumps(out))
' "$RECIPIENT" "$BODY" "$TOPIC")"

# --- POST ---

RESP_FILE="$(mktemp)"
trap 'rm -f "$RESP_FILE"' EXIT

# Don't let `set -e` kill us on curl failure — we want to surface a
# descriptive error with both the curl exit code and HTTP status.
set +e
HTTP="$(curl -s -o "$RESP_FILE" -w "%{http_code}" \
    --connect-timeout 5 --max-time 30 \
    -H "X-Terminal-Key: $KEY" \
    -H "Content-Type: application/json" \
    -X POST "$DAEMON_URL/msg/${RECIPIENT}" \
    --data "$PAYLOAD")"
CURL_EXIT=$?
set -e

if [ "$CURL_EXIT" -ne 0 ] || [ "$HTTP" != "200" ]; then
    echo "ERROR: POST /msg/${RECIPIENT} failed (curl_exit=${CURL_EXIT}, HTTP ${HTTP})" >&2
    cat "$RESP_FILE" >&2
    echo >&2
    exit 1
fi

cat "$RESP_FILE"
echo
