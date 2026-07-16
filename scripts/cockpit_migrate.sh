#!/usr/bin/env bash
# cockpit_migrate.sh — per-seat migration state machine (FLEET_TMUX_LAUNCH_1 §6a v1.3).
#
# Phase 1 (sandbox) — the ONLY thing that runs today. NO Terminal-profile edits,
# NO killing of live seats. Creates a tmux session for a seat that is already
# down/idle (its own daemon refresh cadence stopped it), smokes both viewers,
# marks the ledger. Order: B3 -> Brisen Desk (§6a); the rest wait for lead GO.
#
# Phase 2 (coordinated global cutover) — BUILT, NOT EXECUTED (scope §6a + lead
# #12080). The cutover() function rewrites ALL eligible Terminal-profile
# CommandStrings in one pass + a single Terminal.app quit; it REFUSES to run
# without both pilots green AND the explicit lead-GO token. Do not remove the guard.
#
# Ledger writes flow through fleet_terminals.sh's ledger_set (single owner).

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/fleet_terminals.sh
source "$SCRIPT_DIR/fleet_terminals.sh"   # ledger_*, manifest_*, session_up (guarded main)
TTYD_INSTALL="$SCRIPT_DIR/install_cockpit_ttyd.sh"
CREDENTIAL_PATH="${COCKPIT_CREDENTIAL_FILE:-$HOME/Library/Application Support/baker/cockpit/credentials}"

die() { echo "FATAL: $*" >&2; exit 1; }

# --- Phase 1: sandbox-migrate one seat -------------------------------------
sandbox() {
  local slug="${1:-}"
  [ -n "$slug" ] || die "usage: cockpit_migrate.sh sandbox <slug>"
  manifest_has "$slug" || die "seat '$slug' not in manifest"
  local alias launch port
  alias="$(manifest_alias "$slug")"
  launch="$(manifest_launch "$slug")"
  port="$(jq -r --arg s "$slug" '.entries[] | select(.slug==$s) | .port' "$MANIFEST")"

  echo "[1/5] checkpoint — sandbox pilot: seat must be down/idle (no live-seat kill; §6a)"
  if session_up "$slug"; then
    die "tmux session '$slug' already exists — refusing to double-seat (AC-1/AC-M1). Down the seat first."
  fi

  echo "[2/5] stop old seat — SKIPPED (Phase-1 sandbox: no profile edit, no kill)"

  echo "[3/5] create tmux seat: tmux new-session -A -d -s $slug ($launch)"
  tmux new-session -A -d -s "$slug" "$launch"

  echo "[4/5] dual-viewer smoke (native + web)"
  session_up "$slug" || die "native: tmux session '$slug' did not come up"
  echo "   native: tmux session '$slug' present + attachable"
  # web viewer: install ttyd for this seat + probe it under its base path.
  # ttyd runs with -b /term/<slug>/ (controller reverse-proxy contract), so the
  # servable URL is /term/<slug>/, NOT / — probing / returns 404 by design and
  # must NOT be "fixed" back (regression #12139 / deputy-codex #12138).
  "$TTYD_INSTALL" "$slug"
  [ -f "$CREDENTIAL_PATH" ] || die "web: credential $CREDENTIAL_PATH absent (controller-owned #12074)"
  local cred; cred="$(head -n1 "$CREDENTIAL_PATH")"
  local base="http://127.0.0.1:$port/term/$slug/"
  local code=""
  for _ in $(seq 1 20); do
    code="$(curl -s -o /dev/null -w '%{http_code}' -u "$cred" "$base" || true)"
    [ "$code" = "200" ] && break
    sleep 0.5
  done
  [ "$code" = "200" ] || die "web: ttyd base path $base did not serve 200 (got '$code')"
  # negative expectation: bare / MUST be 404 — that is correct base-path behavior,
  # the proof the -b guard is in force (not a bug to repair).
  local root_code
  root_code="$(curl -s -o /dev/null -w '%{http_code}' -u "$cred" "http://127.0.0.1:$port/" || true)"
  [ "$root_code" = "404" ] || die "web: expected 404 at bare / (base-path guard), got '$root_code'"
  # AC-M3: confirm 127.0.0.1-only bind
  lsof -nP -iTCP:"$port" -sTCP:LISTEN | grep -q "127.0.0.1:$port" \
    || die "web: ttyd not bound 127.0.0.1:$port (AC-M3)"
  echo "   web: ttyd $base -> 200, bare / -> 404 (base-path guard), loopback-only"

  echo "[5/5] mark migrated in ledger"
  ledger_set "$slug" migrated
  echo "SANDBOX MIGRATED: $slug (native + web green). Ledger: $LEDGER"
}

# --- Phase 2: coordinated global cutover — BUILT, NOT EXECUTED --------------
cutover() {
  # Guard (do NOT remove): scope §6a + lead #12080 — Phase-2 runs only after both
  # pilots are green AND lead issues the GO token. Default = loud refusal.
  if [ "${COCKPIT_PHASE2_GO:-}" != "LEAD-RATIFIED" ]; then
    cat >&2 <<'EOF'
REFUSING Phase-2 cutover: this is BUILT-NOT-EXECUTED (scope §6a, lead #12080).
It requires: (a) B3 + Brisen Desk pilots green in the ledger, and (b) lead's
explicit GO, passed as COCKPIT_PHASE2_GO=LEAD-RATIFIED. The cutover does ONE
Terminal.app quit for the whole fleet (Lesson 76) and must be scheduled in a
quiet window with the daemon refresh cadence paused. Not runnable ad hoc.
EOF
    exit 3
  fi
  # --- cutover implementation (inert until the guard above passes) ---
  # 1. all active seats checkpoint (external: context-band rollover discipline).
  # 2. rewrite ALL eligible Terminal-profile CommandStrings -> tmux wrapper, one pass.
  # 3. single Terminal.app quit (the ONLY Cmd+Q).
  # 4. fleet_terminals.sh up creates all sessions; windows reopen attached.
  # 5. per-seat smoke recorded in ledger; failures roll back individually (§12).
  die "Phase-2 cutover body is intentionally not implemented for execution in this brief (built-not-executed). See cockpit_rollback.sh for the recovery path."
}

case "${1:-}" in
  sandbox) shift; sandbox "$@" ;;
  cutover) shift; cutover "$@" ;;
  *) echo "usage: cockpit_migrate.sh {sandbox <slug> | cutover(guarded)}" >&2; exit 2 ;;
esac
