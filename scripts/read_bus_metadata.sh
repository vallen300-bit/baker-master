#!/usr/bin/env bash
# Vetted READ-ONLY Researcher client for metadata-only Brisen Lab inspection.
set -euo pipefail

DAEMON_URL="https://brisen-lab.onrender.com"
SLUG="researcher"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
. "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

usage() {
    echo "Usage: read_bus_metadata.sh schema | events <RFC3339-since> [limit 1..200]" >&2
    exit 2
}

KEY="$(brisen_lab_read_terminal_key "$SLUG" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"
[ -n "$KEY" ] || { echo "ERROR: researcher terminal key unavailable" >&2; exit 1; }

case "${1:-}" in
    schema)
        [ "$#" -eq 1 ] || usage
        curl -fsS --max-time 20 -H "X-Terminal-Key: ${KEY}" \
            "${DAEMON_URL}/research/bus/schema"
        ;;
    events)
        [ "$#" -ge 2 ] && [ "$#" -le 3 ] || usage
        SINCE="$2"; LIMIT="${3:-100}"
        case "$LIMIT" in *[!0-9]*|'') usage ;; esac
        [ "$LIMIT" -ge 1 ] && [ "$LIMIT" -le 200 ] || usage
        printf '%s' "$SINCE" | grep -Eq \
            '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$' \
            || { echo "ERROR: since must be timezone-aware RFC3339" >&2; exit 2; }
        curl -fsS --max-time 20 -G -H "X-Terminal-Key: ${KEY}" \
            --data-urlencode "since=${SINCE}" --data-urlencode "limit=${LIMIT}" \
            "${DAEMON_URL}/research/bus/events"
        ;;
    *) usage ;;
esac
