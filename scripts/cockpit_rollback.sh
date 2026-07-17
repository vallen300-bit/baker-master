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
  # NO --allow-running: the helper refuses (Lesson 76) if Terminal.app is live, so a
  # restore is never silently clobbered on Terminal's next quit (codex 267d4477
  # finding 3). For a durable profile restore, Terminal must be down — run this
  # rollback inside the coordinated cutover window, or quit Terminal first.
  local err
  if err="$(python3 "$PROFILE_REWRITE" restore --plist "$TERMINAL_PLIST" --backup "$PROFILE_BACKUP" \
       --profile "$profile" 2>&1 >/dev/null)"; then
    echo "  restored profile CommandString for '$profile' (Terminal down -> durable)"
  else
    echo "  profile restore for '$profile' NOT written: ${err#FATAL: }"
    echo "  -> the seat works now via --relaunch direct alias; restore the profile in a Terminal-down window."
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

# Quit Terminal.app if it is up, so `full`'s profile restores are DURABLE
# (Lesson 76 — a restore written while Terminal is live is clobbered on its next
# quit; codex 019f713a finding 5). Sets QUIT_DONE=1 if it quit.
QUIT_DONE=0
quit_terminal_if_up() {
  pgrep -x Terminal >/dev/null 2>&1 || return 0
  echo "  quitting Terminal.app for a durable profile restore (Lesson 76 — run this detached, not from a live seat)..."
  osascript -e 'tell application "Terminal" to quit' >/dev/null 2>&1 || true
  local w=0
  while pgrep -x Terminal >/dev/null 2>&1; do sleep 0.5; w=$((w+1)); [ "$w" -ge 40 ] && break; done
  killall cfprefsd 2>/dev/null || true
  QUIT_DONE=1
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
    # Coordinated abort: restore every profile DURABLY, so quit Terminal first,
    # restore all seats (no per-seat relaunch mid-loop), then one relaunch at end.
    quit_terminal_if_up
    while IFS= read -r slug; do
      [ -n "$slug" ] && rollback_one "$slug" 0
    done < <(manifest_slugs)
    if [ "$RELAUNCH" = "1" ] || [ "$QUIT_DONE" = "1" ]; then
      osascript -e 'tell application "Terminal" to activate' >/dev/null 2>&1 || true
      echo "  Terminal relaunched; seats reopen via the restored direct-alias profiles."
    fi
    if [ "$QUIT_DONE" = "1" ]; then
      echo "full rollback complete (profiles restored while Terminal was down -> durable)."
    else
      echo "full rollback complete (Terminal was not running; profiles restored on disk, effective at next launch)."
    fi
    ;;
  *)
    echo "usage: cockpit_rollback.sh {seat <slug> [--relaunch] | full [--relaunch]}" >&2; exit 2 ;;
esac
