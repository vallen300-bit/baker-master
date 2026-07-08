#!/usr/bin/env bash
# bus_post.sh — AI Head outbound auto-post to Brisen Lab bus.
# Director ratified 2026-05-06 OPTION A + policy (ii): op-fetch sender key on demand.
#
# Usage:
#   bus_post.sh <recipient_slug_or_id> <body> [topic]
#
# Env:
#   BAKER_ROLE              — required. Maps to sender slug.
#                             Resolved via generated agent identity registry map.
#   BRISEN_LAB_DAEMON_URL   — optional. Default: https://brisen-lab.onrender.com
#
# Exits non-zero on any failure with descriptive stderr.

set -euo pipefail

DAEMON_URL="${BRISEN_LAB_DAEMON_URL:-https://brisen-lab.onrender.com}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/agent_identity_generated.sh
. "$SCRIPT_DIR/agent_identity_generated.sh"
# shellcheck source=scripts/brisen_lab_terminal_key.sh
. "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

# --- arg parsing ---
# Positional: <recipient> <body> [topic]. Optional threading flags (BUS_POST_
# THREADING_ARG_1) may appear in any position, conventionally after the positionals:
#   --parent <msg-id>  -> payload parent_id (threads a reply onto that message; the
#                         airport check-in reader matches disposes on parent_id).
#   --thread <uuid>    -> payload thread_id. The daemon does NOT auto-inherit the
#                         parent's thread on parent_id alone (verified: a --parent-only
#                         reply gets a fresh thread), so pass --thread to keep a reply in
#                         the parent's thread. Mirrors bus_post.py --parent-id/--thread-id.
# Un-flagged invocations stay byte-identical on the wire (no parent_id/thread_id keys).

PARENT_ID=""
THREAD_ID=""
POSITIONAL=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --parent)
            # An EMPTY value (flag as last arg, or an empty-expanded next arg) must fail
            # loud, never silently post unthreaded. `&&` short-circuits so $2 is only read
            # when it exists (safe under set -u).
            [ "$#" -ge 2 ] && [ -n "$2" ] || { echo "ERROR: --parent requires a non-empty message id" >&2; exit 2; }
            PARENT_ID="$2"; shift 2 ;;
        --parent=*)
            PARENT_ID="${1#*=}"
            [ -n "$PARENT_ID" ] || { echo "ERROR: --parent requires a non-empty message id" >&2; exit 2; }
            shift ;;
        --thread)
            [ "$#" -ge 2 ] && [ -n "$2" ] || { echo "ERROR: --thread requires a non-empty thread uuid" >&2; exit 2; }
            THREAD_ID="$2"; shift 2 ;;
        --thread=*)
            THREAD_ID="${1#*=}"
            [ -n "$THREAD_ID" ] || { echo "ERROR: --thread requires a non-empty thread uuid" >&2; exit 2; }
            shift ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done
set -- "${POSITIONAL[@]:-}"

if [ "${1:-}" = "" ] || [ "${2:-}" = "" ]; then
    echo "Usage: bus_post.sh <recipient_slug> <body> [topic] [--parent <msg-id>] [--thread <uuid>]" >&2
    exit 2
fi

RECIPIENT_INPUT="$1"
BODY="$2"
TOPIC="${3:-}"

# --parent must be an integer message id if provided (fail-loud; matches the daemon's
# int parent_id + bus_post.py's --parent-id type=int).
if [ -n "$PARENT_ID" ] && ! printf '%s' "$PARENT_ID" | grep -qE '^[0-9]+$'; then
    echo "ERROR: --parent must be an integer message id, got: $PARENT_ID" >&2
    exit 2
fi

# --- recipient validation ---

# F2-FU-1 (Stage 2 BRISEN_LAB_APP_AUTOPOLL_INBOX_1): director-recipient is no
# longer hard-rejected client-side. Daemon enforces the env-gated block via
# BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED. Single control point — flipping the
# daemon flag is now the only kill-switch (no script-layer drift).

# Resolve agent IDs / aliases to canonical slugs; system endpoints pass through.
if agent_identity_is_valid_slug "$RECIPIENT_INPUT"; then
    RECIPIENT="$RECIPIENT_INPUT"
elif RESOLVED_RECIPIENT="$(agent_identity_resolve_role "$RECIPIENT_INPUT" 2>/dev/null)"; then
    RECIPIENT="$RESOLVED_RECIPIENT"
else
    echo "ERROR: unknown slug, alias, or agent id: $RECIPIENT_INPUT" >&2
    echo "  Valid slugs: ${AGENT_IDENTITY_VALID_SLUGS[*]}" >&2
    exit 1
fi

# --- sender slug from BAKER_ROLE ---

if ! SENDER="$(agent_identity_resolve_role "${BAKER_ROLE:-}")"; then
    echo "ERROR: BAKER_ROLE not set or unrecognized: '${BAKER_ROLE:-}'" >&2
    echo "  Valid registry roles: ${AGENT_IDENTITY_BUS_AGENT_SLUGS[*]} plus aliases" >&2
    exit 1
fi

# --- credential fetch ---
# Precedence: literal env → ~/.brisen-lab/keys/<slug> cache → op fallback.

KEY="$(brisen_lab_read_terminal_key "$SENDER" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"

if [ -z "$KEY" ]; then
    echo "ERROR: terminal key empty for sender=${SENDER} (no env, no cache, no 1P)" >&2
    exit 1
fi

# --- payload construction (Python json.dumps for safe escaping) ---

PAYLOAD="$(python3 -c '
import json, sys
recipient, body, topic = sys.argv[1], sys.argv[2], sys.argv[3]
parent_id, thread_id = sys.argv[4], sys.argv[5]
out = {"kind": "dispatch", "body": body, "to": [recipient], "tier_required": "B"}
if topic:
    out["topic"] = topic
# Appended last + only when provided, so an un-flagged post is byte-identical to before.
if parent_id:
    out["parent_id"] = int(parent_id)
if thread_id:
    out["thread_id"] = thread_id
print(json.dumps(out))
' "$RECIPIENT" "$BODY" "$TOPIC" "$PARENT_ID" "$THREAD_ID")"

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
