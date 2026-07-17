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
# Phase-1 sandbox never edits profiles: with no Phase-2 backup present, `seat`/
# `full` just remove the sandbox substrate. After a Phase-2 cutover (a
# profile_backup.json exists), they ALSO restore each seat's original
# Terminal-profile CommandString from that backup (§12) — durable at the next
# coordinated Terminal restart, never instantly (Lesson 76). --relaunch re-seats
# the failed seat NOW via the direct alias.
#
#   seat <slug> [--relaunch]   roll back one seat
#   full [--relaunch]          roll back every seat in the manifest

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/fleet_terminals.sh"   # ledger_set, manifest_*, session_up
LAUNCHD_DIR="${COCKPIT_LAUNCHD_DIR:-$HOME/Library/LaunchAgents}"
PROFILE_REWRITE="$SCRIPT_DIR/cockpit_profile_rewrite.py"
TERMINAL_PLIST="${COCKPIT_TERMINAL_PLIST:-$HOME/Library/Preferences/com.apple.Terminal.plist}"
PROFILE_BACKUP="${COCKPIT_PROFILE_BACKUP:-$LEDGER_DIR/profile_backup.json}"

die() { echo "FATAL: $*" >&2; exit 1; }

# Restore one profile's original CommandString from the Phase-2 backup (§12).
# Lesson 76: the restored value is durable at the next coordinated Terminal
# restart, NOT instantly — this function makes NO instant-rollback promise.
# No-op (not an error) when there is no backup (Phase-1 sandbox never edits profiles).
restore_profile_cmd() {
  local slug="$1" profile
  [ -f "$PROFILE_BACKUP" ] || { echo "  (no profile backup — Phase-1 sandbox path, nothing to restore)"; return 0; }
  [ -f "$PROFILE_REWRITE" ] || { echo "  (profile-rewrite helper missing — skipping profile restore)"; return 0; }
  profile="$(manifest_profile "$slug" 2>/dev/null || true)"
  [ -n "$profile" ] && [ "$profile" != "null" ] || { echo "  (no profile for '$slug' in manifest — skipping profile restore)"; return 0; }
  if python3 "$PROFILE_REWRITE" restore --plist "$TERMINAL_PLIST" --backup "$PROFILE_BACKUP" \
       --profile "$profile" --allow-running >/dev/null 2>&1; then
    echo "  restored profile CommandString for '$profile' (durable at next Terminal restart — Lesson 76)"
  else
    echo "  profile restore for '$profile' failed (non-fatal) — check $PROFILE_BACKUP"
  fi
}

rollback_one() {
  local slug="$1" relaunch="$2"
  manifest_has "$slug" || die "seat '$slug' not in manifest"
  local alias; alias="$(manifest_alias "$slug")"

  # 0. restore the seat's original Terminal-profile command (§12; no-op in Phase-1)
  restore_profile_cmd "$slug"

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
