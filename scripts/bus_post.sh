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
IDEMPOTENCY_KEY=""
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
        --idempotency-key)
            # AGENT_BUS_IDEMPOTENT_POST_1: caller-supplied key so a retry loop that
            # spans MULTIPLE invocations reuses ONE key (the daemon dedupes on it).
            # Reject empty OR whitespace-only (codex #8385): the daemon strips the key
            # before insert (bus.py), so a blank key silently becomes keyless and never
            # dedupes — fail loud instead. Parity with bus_post.py's flag guard.
            [ "$#" -ge 2 ] || { echo "ERROR: --idempotency-key requires a non-empty value" >&2; exit 2; }
            case "$2" in
                *[![:space:]]*) IDEMPOTENCY_KEY="$2" ;;
                *) echo "ERROR: --idempotency-key requires a non-empty value" >&2; exit 2 ;;
            esac
            shift 2 ;;
        --idempotency-key=*)
            case "${1#*=}" in
                *[![:space:]]*) IDEMPOTENCY_KEY="${1#*=}" ;;
                *) echo "ERROR: --idempotency-key requires a non-empty value" >&2; exit 2 ;;
            esac
            shift ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done
set -- "${POSITIONAL[@]:-}"

if [ "${1:-}" = "" ] || [ "${2:-}" = "" ]; then
    echo "Usage: bus_post.sh <recipient_slug> <body> [topic] [--parent <msg-id>] [--thread <uuid>] [--idempotency-key <key>]" >&2
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

# --- CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1 (E3): worker-side GO-reroute gate ---
# STRUCTURAL enforcement of "route a GO/confirm on already-dispatched work to your
# superior, not the Director". Only invoked when the recipient is the Director, so
# every non-director post stays byte-identical. CONSERVATIVE (lead rider #10036): the
# gate reroutes ONLY a GO/confirm about referenced already-dispatched work, and NEVER a
# ratify_required / Tier-B/C / business message (protected veto inside the gate). Env
# kill switch BAKER_GO_REROUTE_DISABLED bypasses. The reroute target is the sender's
# reports_to superior — which is `lead` for every seat that can reroute today, so the
# rider's "cc lead" is inherent (target == lead); the gate also writes an audit line to
# ~/.brisen-lab/go-reroute.log on every reroute. If a future seat reports to a non-lead
# superior, add an explicit lead cc here.
if printf '%s' "$RECIPIENT" | grep -qiE '^director$'; then
    REROUTED_RECIPIENT="$(python3 "$SCRIPT_DIR/go_reroute_gate.py" "$RECIPIENT" "$BODY" "$SENDER" || printf '%s' "$RECIPIENT")"
    if [ -n "$REROUTED_RECIPIENT" ] && [ "$REROUTED_RECIPIENT" != "$RECIPIENT" ]; then
        echo "[bus_post] GO-reroute gate: director -> ${REROUTED_RECIPIENT} (sender=${SENDER}); logged to ~/.brisen-lab/go-reroute.log" >&2
        RECIPIENT="$REROUTED_RECIPIENT"
    fi
fi

# --- credential fetch ---
# Precedence: literal env → ~/.brisen-lab/keys/<slug> cache → op fallback.

KEY="$(brisen_lab_read_terminal_key "$SENDER" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"

if [ -z "$KEY" ]; then
    echo "ERROR: terminal key empty for sender=${SENDER} (no env, no cache, no 1P)" >&2
    exit 1
fi

# --- idempotency key (one per logical send, reused across retries) ---
# AGENT_BUS_IDEMPOTENT_POST_1: precedence --idempotency-key flag -> BUS_IDEMPOTENCY_KEY
# env -> minted here ONCE. Generated before the retry loop so every attempt of THIS
# send carries the SAME key; the daemon dedupes on (from_terminal, idempotency_key), so
# a retry-after-commit (503/timeout that actually landed) replays the original row
# instead of duplicating. A caller managing its own multi-invocation loop passes the key
# in so its retries dedupe too.
# BUS_IDEMPOTENCY_KEY env fallback (only when no flag). A whitespace-only env value is
# treated as UNSET -> mint below (parity with bus_post.py's .strip(); the daemon would
# strip a blank key to keyless anyway — codex #8385). Unlike the explicit flag, a blank
# env is not a caller error, so it mints rather than failing loud (matches bus_post.py).
if [ -z "$IDEMPOTENCY_KEY" ]; then
    case "${BUS_IDEMPOTENCY_KEY:-}" in
        *[![:space:]]*) IDEMPOTENCY_KEY="$BUS_IDEMPOTENCY_KEY" ;;
        *) : ;;   # empty or whitespace-only -> leave unset
    esac
fi
if [ -z "$IDEMPOTENCY_KEY" ]; then
    IDEMPOTENCY_KEY="$(uuidgen 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
    [ -n "$IDEMPOTENCY_KEY" ] || IDEMPOTENCY_KEY="$(python3 -c 'import uuid; print(uuid.uuid4())')"
fi

# --- payload construction (Python json.dumps for safe escaping) ---

PAYLOAD="$(python3 -c '
import json, sys
recipient, body, topic = sys.argv[1], sys.argv[2], sys.argv[3]
parent_id, thread_id, idempotency_key = sys.argv[4], sys.argv[5], sys.argv[6]
out = {"kind": "dispatch", "body": body, "to": [recipient], "tier_required": "B"}
# Always-present now (every send is idempotent-safe); placed right after the core
# fields, before the optional threading keys.
out["idempotency_key"] = idempotency_key
if topic:
    out["topic"] = topic
# Appended last + only when provided, so a threading-free post keeps a stable shape.
if parent_id:
    out["parent_id"] = int(parent_id)
if thread_id:
    out["thread_id"] = thread_id
print(json.dumps(out))
' "$RECIPIENT" "$BODY" "$TOPIC" "$PARENT_ID" "$THREAD_ID" "$IDEMPOTENCY_KEY")"

# --- POST (bounded retry-with-backoff) ---
# AGENT_BUS_IDEMPOTENT_POST_1 (lead #8366, ratified C+B): retry ONLY on HTTP 503
# (bus_busy_retry) or a network/timeout-class curl failure — every attempt reuses the
# single IDEMPOTENCY_KEY above, so a retry that follows a commit replays instead of
# duplicating. Any other HTTP (4xx / non-503 5xx) fails loud immediately (no retry).
# After MAX_ATTEMPTS the final failure exits non-zero (exit code unchanged: 1) — fail
# loud, do not swallow. Defaults 4 attempts / base 2s (~2/4/8s); both env-overridable
# (BUS_POST_MAX_ATTEMPTS / BUS_POST_BACKOFF_BASE) so the test suite runs with base 0.

MAX_ATTEMPTS="${BUS_POST_MAX_ATTEMPTS:-4}"
BACKOFF_BASE="${BUS_POST_BACKOFF_BASE:-2}"

RESP_FILE="$(mktemp)"
trap 'rm -f "$RESP_FILE"' EXIT

attempt=1
while :; do
    set +e
    HTTP="$(curl -s -o "$RESP_FILE" -w "%{http_code}" \
        --connect-timeout 5 --max-time 30 \
        -H "X-Terminal-Key: $KEY" \
        -H "Content-Type: application/json" \
        -X POST "$DAEMON_URL/msg/${RECIPIENT}" \
        --data "$PAYLOAD")"
    CURL_EXIT=$?
    set -e

    if [ "$CURL_EXIT" -eq 0 ] && [ "$HTTP" = "200" ]; then
        cat "$RESP_FILE"
        echo
        exit 0
    fi

    # Retryable = network/timeout (curl non-zero) OR HTTP 503. Everything else is
    # a hard failure that retrying cannot fix.
    retryable=0
    [ "$CURL_EXIT" -ne 0 ] && retryable=1
    [ "$HTTP" = "503" ] && retryable=1

    if [ "$retryable" -eq 0 ] || [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
        echo "ERROR: POST /msg/${RECIPIENT} failed (curl_exit=${CURL_EXIT}, HTTP ${HTTP}) after ${attempt} attempt(s)" >&2
        cat "$RESP_FILE" >&2
        echo >&2
        exit 1
    fi

    sleep_s=$(( BACKOFF_BASE * (1 << (attempt - 1)) ))   # base 2 -> 2, 4, 8
    [ "$sleep_s" -gt 0 ] && sleep "$sleep_s"
    attempt=$(( attempt + 1 ))
done
