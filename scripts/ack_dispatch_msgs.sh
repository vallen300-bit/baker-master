#!/usr/bin/env bash
# ack_dispatch_msgs.sh — sweep-ack inbox messages tied to a shipped brief.
#
# Usage:
#   BAKER_ROLE=b3 scripts/ack_dispatch_msgs.sh --brief-slug DEADLINE_MATTER_SLUG_BACKFILL_1
#
# Topic prefixes acked (lowercase slug; hyphens preserved):
#   dispatch/<slug>             — original wake-ping
#   dispatch/<slug>-*           — corrections (stale-checkout, branch reset)
#   request-changes/<slug>      — review REQUEST_CHANGES wake-pings
#   scope-amendment/<slug>      — Director-ratified mid-flight scope adds
#   ship/<slug>-v*-rerun        — gate-chain re-trigger pings
#
# Director-ratified 2026-05-13 (BRISEN_LAB_CARD_STATE_FIX_2 Fix 1).
#
# Behaviour:
#   - Non-fatal on every network/HTTP failure path. A bus-ack failure cannot
#     block a ship-merge. Per-message HTTP error logs + continues.
#   - Exits 0 always when config is valid (even if zero messages matched OR
#     individual acks 4xx). Exits 2 on invalid config (missing role / slug /
#     1Password fetch fail / empty key).
#   - Single-ack per message (one log line per id) — bulk-ack signature exists
#     but the documented per-id path is the audit-friendly default.

# `set -u + pipefail` without `-e` is deliberate (BRISEN_LAB_CARD_STATE_FIX_2-v0-2 LOW):
# the script must NEVER abort a ship — every network/HTTP failure path falls
# through to a logged non-fatal continuation. `-u` still catches typos in
# variable names; `pipefail` still surfaces a failing left-of-pipe to the
# command-substitution exit code so the `|| { ... }` guards downstream can
# detect it; `-e` would short-circuit those guards and break the contract.
set -u
set -o pipefail

DAEMON_URL="${BRISEN_LAB_DAEMON_URL:-https://brisen-lab.onrender.com}"
BRIEF_SLUG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --brief-slug)
            if [[ $# -lt 2 ]]; then
                echo "[ack] --brief-slug requires a value" >&2
                exit 2
            fi
            BRIEF_SLUG="$2"
            shift 2
            ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *)
            echo "[ack] unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

if [[ -z "$BRIEF_SLUG" ]]; then
    echo "[ack] --brief-slug required" >&2
    exit 2
fi

# Resolve sender slug from BAKER_ROLE — same map as bus_post.sh.
ROLE="${BAKER_ROLE:-}"
case "$ROLE" in
    b1|B1)                              SENDER="b1" ;;
    b2|B2)                              SENDER="b2" ;;
    b3|B3)                              SENDER="b3" ;;
    b4|B4)                              SENDER="b4" ;;
    b5|B5)                              SENDER="b5" ;;
    AH1|aihead1|lead|LEAD)              SENDER="lead" ;;
    AH2|aihead2|deputy|DEPUTY)          SENDER="deputy" ;;
    architect|ARCHITECT)                SENDER="architect" ;;
    cortex|CORTEX)                      SENDER="cortex" ;;
    aid|AID)                            SENDER="aid" ;;
    *)
        echo "[ack] BAKER_ROLE unset or unrecognized: '${ROLE}'" >&2
        echo "[ack]   Valid: b1-b5, AH1/lead, AH2/deputy, architect, cortex, aid" >&2
        exit 2
        ;;
esac

# Allow tests to inject the key directly (skips the 1Password round-trip).
KEY="${BRISEN_LAB_TERMINAL_KEY_OVERRIDE:-}"
if [[ -z "$KEY" ]]; then
    KEY="$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${SENDER}/credential" 2>/dev/null)" || {
        echo "[ack] 1Password fetch failed for sender=${SENDER}" >&2
        exit 2
    }
fi
if [[ -z "$KEY" ]]; then
    echo "[ack] empty terminal key for sender=${SENDER}" >&2
    exit 2
fi

# Drain own inbox (limit 50 — well above per-brief topic count of ~5).
# No `-f`: parity with per-ack POST below. `-f` swallows 4xx and emits exit-22,
# which would collapse the response body and lose the HTTP code we'd want for
# diagnosis. Without `-f`, curl returns 0 on 4xx and writes the body to stdout;
# the python parser then sees a non-`messages` JSON (e.g. `{"detail": "..."}`)
# and yields zero matches, which routes through the "no unacked messages" exit.
INBOX="$(curl -sS --connect-timeout 5 --max-time 15 \
    -H "X-Terminal-Key: ${KEY}" \
    "${DAEMON_URL}/msg/${SENDER}?limit=50" 2>/dev/null)" || {
    echo "[ack] inbox fetch failed (network/HTTP) — non-fatal, continuing as zero-match" >&2
    INBOX=""
}

if [[ -z "$INBOX" ]]; then
    echo "[ack] empty/unparsable response from daemon for ${SENDER}; nothing to ack"
    exit 0
fi

# Lowercase slug for topic matching.
SLUG_LC="$(echo "$BRIEF_SLUG" | tr '[:upper:]' '[:lower:]')"

# Select unacked message IDs whose topic matches one of the brief-tied prefixes.
# Constraint: NEVER auto-ack messages whose topic doesn't match a known
# brief-slug prefix — Director-relayed messages, cross-agent dispatches, and
# ratify-decision threads stay unacked for human review.
MATCHING_IDS="$(echo "$INBOX" | BRIEF_SLUG_LC="$SLUG_LC" python3 -c '
import json, os, re, sys

slug = os.environ.get("BRIEF_SLUG_LC", "")
patterns = [
    re.compile(rf"^dispatch/{re.escape(slug)}(-|$)"),
    re.compile(rf"^request-changes/{re.escape(slug)}(-|$)"),
    re.compile(rf"^scope-amendment/{re.escape(slug)}(-|$)"),
    re.compile(rf"^ship/{re.escape(slug)}-v.*-rerun$"),
]

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)

messages = payload.get("messages") or payload.get("items") or []
ids = []
for m in messages:
    if not isinstance(m, dict):
        continue
    if m.get("acknowledged_at"):  # already acked — skip
        continue
    if m.get("acked"):            # tolerate alternate field name
        continue
    topic = (m.get("topic") or "").lower()
    if any(p.match(topic) for p in patterns):
        mid = m.get("id") or m.get("message_id")
        if mid is not None:
            ids.append(int(mid))
print(" ".join(str(i) for i in ids))
')"

if [[ -z "$MATCHING_IDS" ]]; then
    echo "[ack] no unacked messages for slug ${BRIEF_SLUG} on ${SENDER}'s inbox"
    exit 0
fi

# Split into an array to avoid relying on unquoted word-splitting (BRISEN_LAB_CARD_STATE_FIX_2-v0-2 LOW).
# `read -ra` is IFS-defensive and gives an explicit iteration count without `wc -w`.
declare -a ACK_IDS=()
read -ra ACK_IDS <<< "$MATCHING_IDS"

ACKED=0
TOTAL=${#ACK_IDS[@]}
for id in "${ACK_IDS[@]}"; do
    # No -f here: -f turns 4xx into exit 22 + suppresses the body, which
    # would mask the real HTTP code via the `|| HTTP="000"` fallback. We want
    # to log the actual HTTP code for diagnosis on 4xx.
    HTTP="$(curl -sS --connect-timeout 5 --max-time 15 \
        -o /dev/null -w '%{http_code}' -X POST \
        -H "X-Terminal-Key: ${KEY}" \
        "${DAEMON_URL}/msg/${id}/ack" 2>/dev/null)" || HTTP="000"
    if [[ "$HTTP" == "200" ]]; then
        ACKED=$((ACKED + 1))
        echo "[ack] ${SENDER}/${id}: OK"
    else
        echo "[ack] ${SENDER}/${id}: HTTP ${HTTP} (continuing)" >&2
    fi
done

echo "[ack] acked ${ACKED} of ${TOTAL} messages for ${BRIEF_SLUG} on ${SENDER}'s inbox"
exit 0
