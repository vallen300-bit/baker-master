#!/usr/bin/env bash
# brisen_lab_ack.sh — idempotent bus-ack with retry-and-exponential-backoff.
#
# WHY (deputy F2, lead #12428 GO 2026-07-17, ops/bus-health-wake-503):
# POST /msg/<id>/ack intermittently 503s when the brisen-lab Render instance
# flaps (restart / cold-start window — starter plan is always-on, so the flap
# is a restart, most likely a 512MB OOM under fleet load, NOT idle spin-down).
# A single-shot ack that hits that window fails hard and needs a human retry
# (~6x manual retries observed 2026-07-17). The ack endpoint is IDEMPOTENT —
# acking an already-acked message still returns 200 — so retrying a transient
# failure is always safe. This helper self-heals acks through any restart
# window, removing the manual-retry toil.
#
# Sourceable API:
#   . scripts/brisen_lab_ack.sh
#   brisen_lab_ack_post "<terminal_key>" "<msg_id>"   # -> 0 on 200, 1 otherwise
#                                                      # echoes final HTTP code
# CLI:
#   BAKER_ROLE=deputy scripts/brisen_lab_ack.sh <msg_id>      # resolves key
#   scripts/brisen_lab_ack.sh --key <key> <msg_id>            # explicit key
#
# Tunables (env, all optional):
#   BRISEN_LAB_ACK_MAX_ATTEMPTS  total attempts incl. first (default 5)
#   BRISEN_LAB_ACK_BASE_DELAY    seconds, first backoff (default 0.5)
#   BRISEN_LAB_ACK_MAX_DELAY     seconds, backoff ceiling (default 8)
#   BRISEN_LAB_ACK_NO_SLEEP      =1 skips the sleeps (fast tests)
#   BRISEN_LAB_DAEMON_URL        daemon base (default the pinned prod URL)
#
# Retry policy: retry on transient/infra codes (000 network/timeout, 408, 425,
# 429, 500, 502, 503, 504). Do NOT retry a permanent client error
# (400/401/403/404/409/410/422) — that is a real fault to surface, not flap.

# HARD-PINNED daemon URL default (defense-in-depth, mirrors check_inbox.sh):
# an attacker-controlled BRISEN_LAB_DAEMON_URL prefix must never redirect the
# terminal key. The env override exists only for the test harness + staging.
_BRISEN_LAB_ACK_DEFAULT_URL="https://brisen-lab.onrender.com"

# Return 0 if the HTTP code is worth retrying, 1 if terminal (success or a
# permanent client error).
_brisen_lab_ack_is_retryable() {
    case "$1" in
        000|408|425|429|500|502|503|504) return 0 ;;
        *) return 1 ;;
    esac
}

# brisen_lab_ack_post <key> <msg_id>
# Echoes the final HTTP code; returns 0 iff a 200 was seen.
brisen_lab_ack_post() {
    local key="$1" msg_id="$2"
    local base_url="${BRISEN_LAB_DAEMON_URL:-$_BRISEN_LAB_ACK_DEFAULT_URL}"
    local max_attempts="${BRISEN_LAB_ACK_MAX_ATTEMPTS:-5}"
    local base_delay="${BRISEN_LAB_ACK_BASE_DELAY:-0.5}"
    local max_delay="${BRISEN_LAB_ACK_MAX_DELAY:-8}"

    local attempt=1 http delay
    while :; do
        # No -f: -f collapses 4xx to exit 22 and hides the body/code. We want
        # the real code to drive the retry decision. `|| http=000` catches a
        # hard network failure (connect refused / DNS / timeout).
        http="$(curl -sS --connect-timeout 5 --max-time 15 \
            -o /dev/null -w '%{http_code}' -X POST \
            -H "X-Terminal-Key: ${key}" \
            "${base_url}/msg/${msg_id}/ack" 2>/dev/null)" || http="000"

        if [[ "$http" == "200" ]]; then
            printf '%s' "$http"
            return 0
        fi

        if ! _brisen_lab_ack_is_retryable "$http"; then
            # Permanent client error — surface it, do not spin.
            printf '%s' "$http"
            return 1
        fi

        if (( attempt >= max_attempts )); then
            printf '%s' "$http"
            return 1
        fi

        if [[ "${BRISEN_LAB_ACK_NO_SLEEP:-}" != "1" ]]; then
            # delay = min(base * 2^(attempt-1), max_delay), float-safe via awk.
            delay="$(awk -v b="$base_delay" -v a="$attempt" -v m="$max_delay" \
                'BEGIN{ d=b*(2^(a-1)); if(d>m)d=m; printf "%.3f", d }')"
            sleep "$delay"
        fi
        attempt=$(( attempt + 1 ))
    done
}

# --- CLI entrypoint (only when executed directly, not when sourced) ---
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -u
    set -o pipefail
    _SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

    _EXPLICIT_KEY=""
    _MSG_ID=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --key) _EXPLICIT_KEY="${2:-}"; shift 2 ;;
            -h|--help)
                echo "Usage: BAKER_ROLE=<role> $0 <msg_id>   |   $0 --key <key> <msg_id>"
                exit 0 ;;
            *)
                if [[ -z "$_MSG_ID" ]]; then _MSG_ID="$1"; shift
                else echo "ERROR: unexpected arg '$1'" >&2; exit 2; fi ;;
        esac
    done

    if ! [[ "$_MSG_ID" =~ ^[0-9]+$ ]]; then
        echo "ERROR: message-id must be numeric, got '${_MSG_ID:-}'." >&2
        exit 2
    fi

    if [[ -n "$_EXPLICIT_KEY" ]]; then
        _KEY="$_EXPLICIT_KEY"
    else
        # shellcheck source=scripts/agent_identity_generated.sh
        . "$_SCRIPT_DIR/agent_identity_generated.sh"
        # shellcheck source=scripts/brisen_lab_terminal_key.sh
        . "$_SCRIPT_DIR/brisen_lab_terminal_key.sh"
        if ! _SLUG="$(agent_identity_resolve_role "${BAKER_ROLE:-}")"; then
            echo "ERROR: BAKER_ROLE not set or unrecognized: '${BAKER_ROLE:-}'." >&2
            exit 2
        fi
        _KEY="$(brisen_lab_read_terminal_key "$_SLUG" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"
        if [[ -z "$_KEY" ]]; then
            echo "ERROR: terminal key empty for slug=${_SLUG} (no env, no cache, no 1P)." >&2
            exit 2
        fi
    fi

    if _CODE="$(brisen_lab_ack_post "$_KEY" "$_MSG_ID")"; then
        echo "ack #${_MSG_ID} → ${_CODE}"
        exit 0
    else
        echo "ack #${_MSG_ID} FAILED → HTTP ${_CODE} (after retries)" >&2
        exit 3
    fi
fi
