#!/usr/bin/env bash
# fleet_terminals.sh — Cockpit tmux fleet launcher (FLEET_TMUX_LAUNCH_1, scope §6).
#
# Consumes ONLY the generated launch manifest (scripts/cockpit_launch_manifest.json,
# from generate_cockpit_manifest.py) + the migration ledger. No hand-kept lists.
#
#   up            create tmux sessions for LEDGER-MIGRATED seats only, in manifest
#                 (registry) order; idempotent (re-run is a no-op); an unmigrated
#                 seat is NEVER launched, so old windows are never double-seated.
#   open <slug>   open a native Terminal window attached to that seat's tmux session.
#   status        per-seat: ledger state (migrated/pending) + session (up/down).
#
# Ledger writes are owned by cockpit_migrate.sh; this script only READS the ledger
# for `up`/`status` (plus the internal mark helpers the migrator sources).
#
# Launch form is taken verbatim from the manifest: /bin/zsh -lic '<alias>' (scope §6b).

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# Manifest resolution: explicit override wins, else the deployed name
# (launch_manifest.json, what the controller expects in DEPLOY_DIR), else the
# in-repo generated name (cockpit_launch_manifest.json). Lets the SAME script
# work in scripts/ and when deployed alongside launch_manifest.json.
if [ -n "${COCKPIT_MANIFEST:-}" ]; then
  MANIFEST="$COCKPIT_MANIFEST"
elif [ -f "$SCRIPT_DIR/launch_manifest.json" ]; then
  MANIFEST="$SCRIPT_DIR/launch_manifest.json"
else
  MANIFEST="$SCRIPT_DIR/cockpit_launch_manifest.json"
fi
LEDGER_DIR="${COCKPIT_STATE_DIR:-$HOME/Library/Application Support/baker/cockpit}"
LEDGER="$LEDGER_DIR/migration_ledger.json"

die() { echo "FATAL: $*" >&2; exit 1; }

[ -f "$MANIFEST" ] || die "manifest missing at $MANIFEST — run generate_cockpit_manifest.py --write"
command -v jq >/dev/null 2>&1 || die "jq required but not found"
command -v tmux >/dev/null 2>&1 || die "tmux required but not found (brew install tmux)"

ledger_init() {
  mkdir -p "$LEDGER_DIR"
  [ -f "$LEDGER" ] || echo '{}' > "$LEDGER"
}

# state of a seat in the ledger: "migrated" | "pending" (default when absent)
ledger_state() {
  ledger_init
  jq -r --arg s "$1" '.[$s].state // "pending"' "$LEDGER"
}

# mark helpers (sourced by cockpit_migrate.sh; safe atomic write)
ledger_set() {
  local slug="$1" state="$2"
  ledger_init
  local tmp; tmp="$(mktemp)"
  jq --arg s "$slug" --arg st "$state" \
     '.[$s] = ((.[$s] // {}) + {state:$st})' "$LEDGER" > "$tmp"
  mv "$tmp" "$LEDGER"
}

manifest_slugs()  { jq -r '.entries[].slug' "$MANIFEST"; }
manifest_alias()  { jq -r --arg s "$1" '.entries[] | select(.slug==$s) | .alias'  "$MANIFEST"; }
manifest_launch() { jq -r --arg s "$1" '.entries[] | select(.slug==$s) | .launch' "$MANIFEST"; }
manifest_has()    { jq -e --arg s "$1" '.entries[] | select(.slug==$s)' "$MANIFEST" >/dev/null 2>&1; }

session_up() { tmux has-session -t "=$1" 2>/dev/null; }

cmd_up() {
  ledger_init
  local created=0 skipped=0 pending=0
  while IFS= read -r slug; do
    [ -n "$slug" ] || continue
    if [ "$(ledger_state "$slug")" != "migrated" ]; then
      pending=$((pending+1)); continue          # never launch an unmigrated seat
    fi
    if session_up "$slug"; then
      skipped=$((skipped+1)); continue           # idempotent
    fi
    local launch; launch="$(manifest_launch "$slug")"
    tmux new-session -d -s "$slug" "$launch"
    echo "up: $slug  ($launch)"
    created=$((created+1))
  done < <(manifest_slugs)
  echo "fleet up: $created created, $skipped already-up, $pending pending(unmigrated)."
}

cmd_open() {
  local slug="${1:-}"
  [ -n "$slug" ] || die "usage: fleet_terminals.sh open <slug>"
  manifest_has "$slug" || die "unknown seat '$slug' (not in manifest)"
  session_up "$slug" || die "no tmux session for '$slug' — run 'fleet_terminals.sh up' (seat must be ledger-migrated) first"
  # native Terminal window attached to the session
  osascript -e "tell application \"Terminal\" to do script \"tmux attach -t $slug\"" \
            -e "tell application \"Terminal\" to activate" >/dev/null
  echo "opened native Terminal attached to '$slug'"
}

cmd_status() {
  ledger_init
  printf '%-20s %-10s %-8s %-6s\n' SEAT LEDGER SESSION PORT
  printf '%-20s %-10s %-8s %-6s\n' ==== ====== ======= ====
  while IFS= read -r slug; do
    [ -n "$slug" ] || continue
    local st sess port
    st="$(ledger_state "$slug")"
    if session_up "$slug"; then sess=up; else sess=down; fi
    port="$(jq -r --arg s "$slug" '.entries[] | select(.slug==$s) | .port' "$MANIFEST")"
    printf '%-20s %-10s %-8s %-6s\n' "$slug" "$st" "$sess" "$port"
  done < <(manifest_slugs)
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    up)     cmd_up ;;
    open)   cmd_open "$@" ;;
    status) cmd_status ;;
    *) echo "usage: fleet_terminals.sh {up | open <slug> | status}" >&2; exit 2 ;;
  esac
}

# allow sourcing (cockpit_migrate.sh) without running main
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
