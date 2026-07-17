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
  # No backup at all = Phase-1 (profiles were never rewritten): a genuine no-op.
  [ -f "$PROFILE_BACKUP" ] || { echo "  (no profile backup — Phase-1 sandbox path, nothing to restore)"; return 0; }
  # Backup EXISTS (post-cutover): a missing helper or an unresolved profile means we
  # CANNOT restore a seat whose profile was wrapped — that is a real failure, not a
  # skip (codex 019f7173 finding 3).
  [ -f "$PROFILE_REWRITE" ] || { echo "  ERROR: profile-rewrite helper missing but a backup exists — cannot restore '$slug'"; return 1; }
  profile="$(manifest_profile "$slug" 2>/dev/null || true)"
  [ -n "$profile" ] && [ "$profile" != "null" ] || { echo "  ERROR: no profile for '$slug' in manifest but a backup exists — cannot restore its wrapped profile"; return 1; }
  # NO --allow-running: the helper refuses (Lesson 76) if Terminal.app is live, so a
  # restore is never silently clobbered on Terminal's next quit (codex 267d4477
  # finding 3). For a durable profile restore, Terminal must be down — run this
  # rollback inside the coordinated cutover window, or quit Terminal first.
  # Returns non-zero on a genuine restore FAILURE so the caller can propagate it
  # (codex 019f7168 finding 4). The "no backup / no helper / no profile" cases are
  # legitimate no-ops (Phase-1) and return 0.
  local err
  if err="$(python3 "$PROFILE_REWRITE" restore --plist "$TERMINAL_PLIST" --backup "$PROFILE_BACKUP" \
       --profile "$profile" 2>&1 >/dev/null)"; then
    echo "  restored profile CommandString for '$profile' (Terminal down -> durable)"
    return 0
  fi
  echo "  profile restore for '$profile' NOT written: ${err#FATAL: }"
  echo "  -> the seat works now via --relaunch direct alias; restore the profile in a Terminal-down window."
  return 1
}

# Rolls one seat back. Every step propagates failure into rc; the final line is
# "rolled back" ONLY when rc==0 (codex 019f7168 findings 2/4). Returns rc.
rollback_one() {
  local slug="$1" relaunch="$2" rc=0
  manifest_has "$slug" || die "seat '$slug' not in manifest"
  local alias; alias="$(manifest_alias "$slug")"

  # 0. restore the seat's original Terminal-profile command (§12; no-op in Phase-1)
  restore_profile_cmd "$slug" || rc=1

  # 1. unload + remove the ttyd plist (per-seat isolation)
  local plist="$LAUNCHD_DIR/com.baker.cockpit-ttyd-$slug.plist"
  if [ -f "$plist" ]; then
    launchctl unload "$plist" 2>/dev/null || true   # unload-of-unloaded is fine
    rm -f "$plist" || rc=1
    echo "  removed ttyd plist: $plist"
  fi

  # 2. kill the tmux session
  if session_up "$slug"; then
    tmux kill-session -t "=$slug" 2>/dev/null || rc=1
    echo "  killed tmux session: $slug"
  fi

  # 3. ledger -> pending (so fleet up will not recreate it)
  ledger_set "$slug" pending || rc=1
  echo "  ledger: $slug -> pending"

  # 4. optional direct-alias re-seat (Lesson 76 recovery — NOT a profile restore)
  if [ "$relaunch" = "1" ]; then
    if osascript -e "tell application \"Terminal\" to do script \"/bin/zsh -lic '$alias'\"" \
                 -e "tell application \"Terminal\" to activate" >/dev/null 2>&1; then
      echo "  re-seated '$slug' via direct alias '$alias' in a new Terminal window"
    else
      rc=1
      echo "  WARNING: direct-alias re-seat of '$slug' failed — re-seat it by hand."
    fi
  fi

  if [ "$rc" = "0" ]; then
    echo "rolled back: $slug"
  else
    echo "ROLLBACK INCOMPLETE for '$slug' — one or more steps failed; inspect by hand." >&2
  fi
  return "$rc"
}

# Quit Terminal.app if it is up, so `full`'s profile restores are DURABLE
# (Lesson 76 — a restore written while Terminal is live is clobbered on its next
# quit). Sets QUIT_DONE=1 ONLY if Terminal is actually down afterward (codex
# 019f714a finding 2: a 20s-timeout must not claim a durable quit).
QUIT_DONE=0
quit_terminal_if_up() {
  pgrep -x Terminal >/dev/null 2>&1 || return 0
  echo "  quitting Terminal.app for a durable profile restore (Lesson 76 — run this detached, not from a live seat)..."
  osascript -e 'tell application "Terminal" to quit' >/dev/null 2>&1 || true
  local w=0
  while pgrep -x Terminal >/dev/null 2>&1; do sleep 0.5; w=$((w+1)); [ "$w" -ge 40 ] && break; done
  if pgrep -x Terminal >/dev/null 2>&1; then
    echo "  WARNING: Terminal did not quit within 20s — profile restores will NOT be durable until a manual restart."
    QUIT_DONE=0
  else
    killall cfprefsd 2>/dev/null || true
    QUIT_DONE=1
  fi
}

RELAUNCH=0
FULL_RC=0
case "${1:-}" in
  seat)
    slug="${2:-}"; [ -n "$slug" ] || die "usage: cockpit_rollback.sh seat <slug> [--relaunch]"
    [ "${3:-}" = "--relaunch" ] && RELAUNCH=1
    rollback_one "$slug" "$RELAUNCH" || exit 1     # surface a failed rollback loudly
    ;;
  full)
    [ "${2:-}" = "--relaunch" ] && RELAUNCH=1
    # Never run the rollback loop over an empty set (codex 019f7173 finding 2).
    ALL_SLUGS="$(manifest_slugs)"
    [ -n "$ALL_SLUGS" ] || die "manifest yielded no seats — nothing to roll back (refusing to report a clean rollback over zero seats)."
    if [ -f "$PROFILE_BACKUP" ]; then
      # POST-cutover abort: profile restores are durable only with Terminal DOWN.
      quit_terminal_if_up
      # Durability = Terminal is actually down NOW (we quit it, OR it was already
      # down — codex 019f7168 finding 5). Drop the prefs cache in the already-down
      # case too, so the on-disk restore is authoritative.
      DURABLE=0
      if pgrep -x Terminal >/dev/null 2>&1; then DURABLE=0; else DURABLE=1; killall cfprefsd 2>/dev/null || true; fi
      while IFS= read -r slug; do
        if [ -n "$slug" ]; then rollback_one "$slug" 0 || FULL_RC=1; fi
      done <<< "$ALL_SLUGS"
      if [ "$RELAUNCH" = "1" ] || [ "$QUIT_DONE" = "1" ]; then
        osascript -e 'tell application "Terminal" to activate' >/dev/null 2>&1 || true
        echo "  Terminal relaunched."
      fi
      if [ "$DURABLE" = "1" ]; then
        echo "full rollback finished (profiles restored while Terminal was down -> durable)."
      else
        echo "WARNING: full rollback restored profiles ON DISK but Terminal is still up -> NOT durable until a manual Terminal restart."
      fi
    else
      # Phase-1 cleanup (no profiles were ever rewritten): substrate teardown only,
      # do NOT quit the fleet. Honor --relaunch as a PER-SEAT direct-alias re-seat.
      while IFS= read -r slug; do
        if [ -n "$slug" ]; then rollback_one "$slug" "$RELAUNCH" || FULL_RC=1; fi
      done <<< "$ALL_SLUGS"
      if [ "$RELAUNCH" = "1" ]; then
        echo "full rollback finished (Phase-1: substrate torn down; each seat re-seated via its direct alias)."
      else
        echo "full rollback finished (Phase-1: substrate teardown only; no profiles to restore)."
      fi
    fi
    if [ "$FULL_RC" != "0" ]; then
      echo "WARNING: one or more seats did NOT roll back cleanly — see the ROLLBACK INCOMPLETE lines above; inspect by hand." >&2
      exit 1
    fi
    ;;
  *)
    echo "usage: cockpit_rollback.sh {seat <slug> [--relaunch] | full [--relaunch]}" >&2; exit 2 ;;
esac
