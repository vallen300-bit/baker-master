#!/usr/bin/env bash
# CASE_ONE_P5_DELIVERY_CONFIRMATION_1 (P5.3) — dispatcher/lead one-liner over the
# fleet-visible, METADATA-ONLY GET /delivery/status. Answers "does seat X know about
# dispatch N" (acked? started? or silently un-delivered) in ONE call — the exact
# question the dispatcher could not answer on E21 without a human round-trip.
#
# STANDING DISPATCHER AUTHORITY (structural, per brief §P5.3 + #10164): a delivery-
# status check is the dispatcher's OWN call. It NEVER routes as a Director permission
# ask — no `🟢 GO?` / `👉 YOU` cue. Just run it. The daemon authz already scopes an
# orchestration role (deputy=dispatcher, lead) to cross-seat reads; a plain seat is
# scoped to itself. Bodies are never returned (delivery telemetry is fleet-visible,
# content is not).
set -euo pipefail

DAEMON_URL="${BRISEN_LAB_DAEMON_URL:-https://brisen-lab.onrender.com}"
# The querying role — an orchestration role (lead/deputy/deputy-codex) for cross-seat,
# else the seat's own slug. Override with BAKER_ROLE (matches the fleet convention).
SLUG="${BAKER_ROLE:-lead}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

usage() {
    cat >&2 <<'EOF'
Usage: delivery_status.sh [seat <slug>] [msg <id>] [job <id>] [since <RFC3339>] [limit N]
  seat <slug>     per-seat delivery state (cross-seat needs lead/deputy via BAKER_ROLE)
  msg  <id>       one dispatch's delivery record across its recipients
  job  <id>       records for the linked P2 job (agent_jobs id)
  since <RFC3339>  only records posted after this timezone-aware timestamp
  limit N         1..500 (default 200)
Examples:
  BAKER_ROLE=deputy delivery_status.sh seat b2
  BAKER_ROLE=lead   delivery_status.sh msg 10172
EOF
    exit 2
}

KEY="$(brisen_lab_read_terminal_key "$SLUG" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"
[ -n "$KEY" ] || { echo "ERROR: terminal key for '${SLUG}' unavailable (set BAKER_ROLE)" >&2; exit 1; }

CURL_ARGS=(-fsS --max-time 20 -G -H "X-Terminal-Key: ${KEY}")
while [ "$#" -gt 0 ]; do
    case "$1" in
        seat) [ "${2:-}" ] || usage; CURL_ARGS+=(--data-urlencode "seat=$2"); shift 2 ;;
        msg)  [ "${2:-}" ] || usage; case "$2" in *[!0-9]*|'') usage ;; esac
              CURL_ARGS+=(--data-urlencode "message_id=$2"); shift 2 ;;
        job)  [ "${2:-}" ] || usage; case "$2" in *[!0-9]*|'') usage ;; esac
              CURL_ARGS+=(--data-urlencode "job_ref=$2"); shift 2 ;;
        since) [ "${2:-}" ] || usage
              printf '%s' "$2" | grep -Eq \
                '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$' \
                || { echo "ERROR: since must be timezone-aware RFC3339" >&2; exit 2; }
              CURL_ARGS+=(--data-urlencode "since=$2"); shift 2 ;;
        limit) [ "${2:-}" ] || usage; case "$2" in *[!0-9]*|'') usage ;; esac
              [ "$2" -ge 1 ] && [ "$2" -le 500 ] || usage
              CURL_ARGS+=(--data-urlencode "limit=$2"); shift 2 ;;
        -h|--help) usage ;;
        *) usage ;;
    esac
done

curl "${CURL_ARGS[@]}" "${DAEMON_URL}/delivery/status"
