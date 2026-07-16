#!/usr/bin/env bash
# cockpit_rollback.sh — Cockpit substrate rollback (FLEET_TMUX_LAUNCH_1 §12,
# codex-arch nit N3 #12047, Lesson 76).
#
# Lesson 76 (HARD): restoring a Terminal profile on disk does NOT refresh
# Terminal.app's in-memory cache — a per-seat instant profile-cache rollback is
# IMPOSSIBLE. This script therefore does NOT promise one. Failed-seat recovery is:
#   1. tear down the seat's cockpit substrate (ttyd plist + tmux session), and
#   2. (optional, --relaunch) immediately re-seat via the DIRECT ALIAS in a plain
#      new Terminal window — /bin/zsh -lic '<alias>', no profile dependency — so
#      the seat is working again NOW.
# The Terminal-profile CommandString cache is restored only at the next
# coordinated Terminal.app restart (Phase-2 concern; not done here).
#
# Phase-1 sandbox never edits profiles, so `seat`/`full` just remove the sandbox
# substrate; --relaunch is for the failed-cutover case.
#
#   seat <slug> [--relaunch]   roll back one seat
#   full [--relaunch]          roll back every seat in the manifest

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/fleet_terminals.sh"   # ledger_set, manifest_*, session_up
LAUNCHD_DIR="${COCKPIT_LAUNCHD_DIR:-$HOME/Library/LaunchAgents}"

die() { echo "FATAL: $*" >&2; exit 1; }

rollback_one() {
  local slug="$1" relaunch="$2"
  manifest_has "$slug" || die "seat '$slug' not in manifest"
  local alias; alias="$(manifest_alias "$slug")"

  # 1. unload + remove the ttyd plist (per-seat isolation)
  local plist="$LAUNCHD_DIR/com.baker.cockpit-ttyd-$slug.plist"
  if [ -f "$plist" ]; then
    launchctl unload "$plist" 2>/dev/null || true
    rm -f "$plist"
    echo "  removed ttyd plist: $plist"
  fi

  # 2. kill the tmux session
  if session_up "$slug"; then
    tmux kill-session -t "=$slug"
    echo "  killed tmux session: $slug"
  fi

  # 3. ledger -> pending (so fleet up will not recreate it)
  ledger_set "$slug" pending
  echo "  ledger: $slug -> pending"

  # 4. optional direct-alias re-seat (Lesson 76 recovery — NOT a profile restore)
  if [ "$relaunch" = "1" ]; then
    osascript -e "tell application \"Terminal\" to do script \"/bin/zsh -lic '$alias'\"" \
              -e "tell application \"Terminal\" to activate" >/dev/null
    echo "  re-seated '$slug' via direct alias '$alias' in a new Terminal window"
    echo "  NOTE (Lesson 76): Terminal-profile CommandString cache restore happens at the"
    echo "        next coordinated Terminal.app restart — NOT instantly, by design."
  fi
  echo "rolled back: $slug"
}

RELAUNCH=0
case "${1:-}" in
  seat)
    slug="${2:-}"; [ -n "$slug" ] || die "usage: cockpit_rollback.sh seat <slug> [--relaunch]"
    [ "${3:-}" = "--relaunch" ] && RELAUNCH=1
    rollback_one "$slug" "$RELAUNCH"
    ;;
  full)
    [ "${2:-}" = "--relaunch" ] && RELAUNCH=1
    while IFS= read -r slug; do
      [ -n "$slug" ] && rollback_one "$slug" "$RELAUNCH"
    done < <(manifest_slugs)
    echo "full rollback complete."
    ;;
  *)
    echo "usage: cockpit_rollback.sh {seat <slug> [--relaunch] | full [--relaunch]}" >&2; exit 2 ;;
esac
