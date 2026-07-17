#!/usr/bin/env bash
# cockpit_migrate.sh — per-seat migration state machine (FLEET_TMUX_LAUNCH_1 §6a v1.3).
#
# Phase 1 (sandbox) — the ONLY thing that runs today. NO Terminal-profile edits,
# NO killing of live seats. Creates a tmux session for a seat that is already
# down/idle (its own daemon refresh cadence stopped it), smokes both viewers,
# marks the ledger. Order: B3 -> Brisen Desk (§6a); the rest wait for lead GO.
#
# Phase 2 (coordinated global cutover) — IMPLEMENTED, GO-GATED (scope §6a + lead
# #12330 Option-A ruling). The cutover() function rewrites ALL eligible
# Terminal-profile CommandStrings in one pass (via cockpit_profile_rewrite.py) +
# a single Terminal.app quit + fleet up + per-seat wave smoke with per-seat
# rollback. It REFUSES to run without both pilots green AND the explicit lead-GO
# token (COCKPIT_PHASE2_GO=LEAD-RATIFIED). `cutover --dry-run` previews safely.
# Do not remove the guard. Execution is coordinated by lead in a quiet window
# (runbook: .claude/how-to/cockpit-phase2-cutover.md).
#
# Ledger writes flow through fleet_terminals.sh's ledger_set (single owner).

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=scripts/fleet_terminals.sh
source "$SCRIPT_DIR/fleet_terminals.sh"   # ledger_*, manifest_*, session_up (guarded main)
TTYD_INSTALL="$SCRIPT_DIR/install_cockpit_ttyd.sh"
CREDENTIAL_PATH="${COCKPIT_CREDENTIAL_FILE:-$HOME/Library/Application Support/baker/cockpit/credentials}"
PROFILE_REWRITE="$SCRIPT_DIR/cockpit_profile_rewrite.py"
TERMINAL_PLIST="${COCKPIT_TERMINAL_PLIST:-$HOME/Library/Preferences/com.apple.Terminal.plist}"
PROFILE_BACKUP="${COCKPIT_PROFILE_BACKUP:-$LEDGER_DIR/profile_backup.json}"
WAVE_LOG="${COCKPIT_WAVE_LOG:-$LEDGER_DIR/cutover_wave_report.log}"
LAUNCHD_DIR="${COCKPIT_LAUNCHD_DIR:-$HOME/Library/LaunchAgents}"

die() { echo "FATAL: $*" >&2; exit 1; }

# read-only ledger peek: never creates the ledger file (dry-run safety, codex
# 267d4477 finding 8). Returns "pending" when the file or key is absent.
ledger_peek() {
  [ -f "$LEDGER" ] && jq -r --arg s "$1" '.[$s].state // "pending"' "$LEDGER" 2>/dev/null || echo "pending"
}

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

# --- Phase 2 helpers --------------------------------------------------------
# Crash-safety state (GLOBAL so the EXIT trap sees them after cutover() returns).
CUTOVER_DANGER=0   # 1 once Terminal is down + profiles are being rewritten
CUTOVER_DONE=0     # 1 once we have relaunched Terminal + reached steady state

# emergency_recover: fired by the EXIT/INT/TERM trap if the cutover aborts inside
# the danger window (Terminal down, profiles wrapped). Best-effort: restore every
# profile from the backup and bring Terminal back so the fleet is never left dark
# (codex 267d4477 finding 2). --allow-running is the last-ditch here (recovery, not
# normal flow); if Terminal is already up the file write lands at the next restart,
# so we also whole-plist-restore from the belt copy and tell the operator.
emergency_recover() {
  [ "$CUTOVER_DANGER" = "1" ] && [ "$CUTOVER_DONE" = "0" ] || return 0
  echo "!! CUTOVER ABORTED mid-flight — emergency recovery (restore profiles + relaunch Terminal)" >&2
  if [ -f "$PROFILE_BACKUP" ]; then
    python3 "$PROFILE_REWRITE" restore-all --plist "$TERMINAL_PLIST" --backup "$PROFILE_BACKUP" --allow-running >/dev/null 2>&1 \
      || cp -p "$PROFILE_BACKUP.plist.bak" "$TERMINAL_PLIST" 2>/dev/null || true
  elif [ -f "$PROFILE_BACKUP.plist.bak" ]; then
    cp -p "$PROFILE_BACKUP.plist.bak" "$TERMINAL_PLIST" 2>/dev/null || true
  fi
  killall cfprefsd 2>/dev/null || true
  osascript -e 'tell application "Terminal" to activate' >/dev/null 2>&1 || true
  echo "!! recovery done: profiles restored from backup, Terminal relaunched. If any" >&2
  echo "!! seat still shows the tmux wrapper, quit+reopen Terminal once to reload profiles." >&2
  echo "!! Inspect: $WAVE_LOG , ledger $LEDGER , backup $PROFILE_BACKUP" >&2
}

# smoke_seat <slug>: native tmux up AND web ttyd 200 on /term/<slug>/. Runs with
# Terminal.app DOWN (needs neither). The ttyd installer is pinned to the frozen
# cutover manifest (COCKPIT_MANIFEST_SRC) so it does NOT regenerate from the now-
# rewritten profiles — the generator would resolve 0/29 post-cutover (codex
# 267d4477 finding 1). Returns 0 green, non-zero on any failure.
smoke_seat() {
  local slug="$1" port cred base code root_code
  port="$(jq -r --arg s "$slug" '.entries[] | select(.slug==$s) | .port' "$MANIFEST")"
  [ -n "$port" ] && [ "$port" != "null" ] || { echo "   smoke $slug: no port in manifest" >&2; return 1; }
  session_up "$slug" || { echo "   smoke $slug: native tmux session DOWN" >&2; return 1; }
  COCKPIT_MANIFEST_SRC="$MANIFEST" "$TTYD_INSTALL" "$slug" >/dev/null 2>&1 \
    || { echo "   smoke $slug: ttyd install failed" >&2; return 1; }
  [ -f "$CREDENTIAL_PATH" ] || { echo "   smoke $slug: credential $CREDENTIAL_PATH absent" >&2; return 1; }
  cred="$(head -n1 "$CREDENTIAL_PATH")"
  base="http://127.0.0.1:$port/term/$slug/"
  code=""
  for _ in $(seq 1 20); do
    code="$(curl -s -o /dev/null -w '%{http_code}' -u "$cred" "$base" || true)"
    [ "$code" = "200" ] && break
    sleep 0.5
  done
  [ "$code" = "200" ] || { echo "   smoke $slug: web $base -> '$code' (want 200)" >&2; return 1; }
  # base-path guard proof (regression #12139): bare / must 404
  root_code="$(curl -s -o /dev/null -w '%{http_code}' -u "$cred" "http://127.0.0.1:$port/" || true)"
  [ "$root_code" = "404" ] || { echo "   smoke $slug: bare / -> '$root_code' (want 404 base-path guard)" >&2; return 1; }
  return 0
}

# cutover_fail_seat <slug>: roll ONE failed seat back while Terminal is DOWN — so
# the profile restore is DURABLE (no --allow-running, Lesson 76 honored; codex
# 267d4477 finding 3). Restores the profile CommandString, tears down the seat's
# ttyd plist + tmux session, ledger -> pending. Does NOT relaunch Terminal (the
# whole fleet's single relaunch happens once, in step [7]); the restored profile
# then launches the plain direct alias on that reopen. Returns non-zero if the
# profile restore itself failed, so the caller can report it LOUD (finding 4).
cutover_fail_seat() {
  local slug="$1" profile rc=0 tp
  profile="$(manifest_profile "$slug")"
  if [ -n "$profile" ] && [ "$profile" != "null" ] && [ -f "$PROFILE_BACKUP" ]; then
    python3 "$PROFILE_REWRITE" restore --plist "$TERMINAL_PLIST" --backup "$PROFILE_BACKUP" \
      --profile "$profile" >/dev/null 2>&1 || rc=1
  fi
  tp="$LAUNCHD_DIR/com.baker.cockpit-ttyd-$slug.plist"
  if [ -f "$tp" ]; then launchctl unload "$tp" 2>/dev/null || true; rm -f "$tp"; fi
  if session_up "$slug"; then tmux kill-session -t "=$slug" 2>/dev/null || rc=1; fi
  ledger_set "$slug" pending
  return "$rc"
}

# --- Phase 2: coordinated global cutover (§6a) ------------------------------
# Executable ONLY with the GO token (guard kept). §6a Phase-2, resequenced so
# EVERY profile write happens while Terminal is DOWN (durable — Lesson 76), then a
# SINGLE Terminal relaunch at the end:
#   gate -> backup -> ONE Terminal quit -> rewrite ALL -> fleet up -> per-seat wave
#   smoke (+durable per-seat rollback on fail) -> relaunch Terminal -> report.
# A trap restores + relaunches if anything aborts inside the danger window.
#   flags: --wave-size N (smoke/report batch, default 5)
#          --no-quit      (caller already quit Terminal; refuse if it is still up)
#          --dry-run      (plan only; writes nothing live; no GO token needed)
cutover() {
  local wave_size=5 do_quit=1 dry=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --wave-size) wave_size="${2:?--wave-size needs a value}"; shift 2 ;;
      --no-quit)   do_quit=0; shift ;;
      --dry-run)   dry=1; shift ;;
      *) die "cutover: unknown arg '$1'" ;;
    esac
  done
  case "$wave_size" in ''|*[!0-9]*) die "cutover: --wave-size must be a positive integer";; esac
  [ "$wave_size" -ge 1 ] || die "cutover: --wave-size must be >= 1"

  # --- dry-run: plan only, touch nothing (no GO token required; read-only) ---
  if [ "$dry" = "1" ]; then
    echo "== Phase-2 cutover DRY-RUN (plan only; nothing written) =="
    [ -f "$PROFILE_REWRITE" ] || die "profile-rewrite helper missing: $PROFILE_REWRITE"
    [ -f "$TERMINAL_PLIST" ] || die "Terminal plist missing: $TERMINAL_PLIST"
    python3 "$PROFILE_REWRITE" rewrite --manifest "$MANIFEST" --plist "$TERMINAL_PLIST" \
      --backup "$PROFILE_BACKUP" --plan-only
    # read-only ledger peek — never creates the ledger (finding 8)
    echo "(dry-run) pilots: b3=$(ledger_peek b3) brisen-desk=$(ledger_peek brisen-desk)"
    return 0
  fi

  # --- GO-token guard (do NOT remove): scope §6a + lead #12080/#12330 ---
  if [ "${COCKPIT_PHASE2_GO:-}" != "LEAD-RATIFIED" ]; then
    cat >&2 <<'EOF'
REFUSING Phase-2 cutover: requires lead's explicit GO, passed as
COCKPIT_PHASE2_GO=LEAD-RATIFIED, in a scheduled quiet window with the daemon
refresh cadence paused and all active seats checkpointed. It does ONE
Terminal.app quit for the whole fleet (Lesson 76). Not runnable ad hoc.
Use `cockpit_migrate.sh cutover --dry-run` to preview the plan safely.
EOF
    exit 3
  fi

  command -v python3 >/dev/null 2>&1 || die "python3 required"
  [ -f "$PROFILE_REWRITE" ] || die "profile-rewrite helper missing: $PROFILE_REWRITE"
  [ -f "$TERMINAL_PLIST" ]  || die "Terminal plist missing: $TERMINAL_PLIST"

  # Precondition 1 (scope §6a): both Phase-1 pilots green before Phase-2.
  local pilot
  for pilot in b3 brisen-desk; do
    [ "$(ledger_state "$pilot")" = "migrated" ] \
      || die "precondition: pilot '$pilot' not migrated in ledger — both Phase-1 pilots must be green before Phase-2 (scope §6a)."
  done

  # Precondition 2: manifest strict-clean (every eligible seat resolved). The
  # dispatch names generate_cockpit_manifest.py --write --strict; verify it.
  local mel mre
  mel="$(jq -r '.meta.eligible_count // .eligible_count // 0' "$MANIFEST")"
  mre="$(jq -r '.meta.resolved_count // .resolved_count // 0' "$MANIFEST")"
  { [ -n "$mel" ] && [ "$mel" != "0" ] && [ "$mel" = "$mre" ]; } \
    || die "precondition: manifest not strict-clean (eligible=$mel resolved=$mre). Run: generate_cockpit_manifest.py --write --strict"

  # Self-seat safety: refuse to run from a live Terminal seat the quit would kill.
  # The sanctioned detached invocation clears TERM_SESSION_ID (runbook: `env -u
  # TERM_SESSION_ID nohup ...`); nohup alone inherits it (finding 6).
  if [ "$do_quit" = "1" ] && [ -n "${TERM_SESSION_ID:-}" ]; then
    die "cutover invoked from inside a Terminal.app session (TERM_SESSION_ID set): the single Cmd+Q would kill THIS process mid-cutover. Launch it detached with the variable cleared, e.g. \`env -u TERM_SESSION_ID nohup ./cockpit_migrate.sh cutover ...\` (see the runbook)."
  fi

  local seats; seats="$(manifest_slugs)"
  echo "== Phase-2 coordinated global cutover (§6a) — wave-size $wave_size, quit=$do_quit =="

  # [1] checkpoint — NOT script-enforceable (each agent pins its own context;
  # runbook step 1). The GO token asserts the runbook preconditions are met.
  echo "[1/7] PRECONDITION (runbook, not script-enforced): all active seats checkpointed + daemon refresh cadence paused."

  # [2] belt backup of the whole plist before any edit.
  ledger_init
  cp -p "$TERMINAL_PLIST" "$PROFILE_BACKUP.plist.bak"
  echo "[2/7] plist backed up -> $PROFILE_BACKUP.plist.bak"

  # [3] single Terminal.app quit (the ONLY Cmd+Q; §6a step 3), then drop the prefs
  # cache so the file rewrite is authoritative (Lesson 76: the write MUST happen
  # while Terminal is down or Terminal clobbers it on its next quit).
  if [ "$do_quit" = "1" ]; then
    echo "[3/7] quitting Terminal.app (single coordinated Cmd+Q)"
    osascript -e 'tell application "Terminal" to quit' >/dev/null 2>&1 || true
    local waited=0
    while pgrep -x Terminal >/dev/null 2>&1; do
      sleep 0.5; waited=$((waited+1))
      [ "$waited" -ge 40 ] && die "Terminal.app did not quit within 20s — aborting BEFORE any plist edit (plist untouched; backup at $PROFILE_BACKUP.plist.bak)."
    done
    killall cfprefsd 2>/dev/null || true
    echo "   Terminal down; cfprefsd cache dropped."
  else
    echo "[3/7] --no-quit: caller asserts Terminal.app already down."
    pgrep -x Terminal >/dev/null 2>&1 && die "--no-quit given but Terminal.app is still running — refusing to rewrite (Lesson 76)."
  fi

  # DANGER WINDOW OPEN: Terminal is down + about to be rewritten. From here any
  # abort must restore profiles + relaunch Terminal, so arm the recovery trap
  # (finding 2). It self-clears once CUTOVER_DONE=1.
  CUTOVER_DANGER=1
  trap 'emergency_recover' EXIT INT TERM

  # [4] rewrite ALL eligible profiles in one pass (durable — Terminal down), then
  # mark them migrated.
  echo "[4/7] rewriting eligible Terminal profiles -> tmux wrapper"
  python3 "$PROFILE_REWRITE" rewrite --manifest "$MANIFEST" --plist "$TERMINAL_PLIST" --backup "$PROFILE_BACKUP" \
    || die "profile rewrite failed — see error above. Trap will restore from backup."
  while IFS= read -r slug; do
    [ -n "$slug" ] && ledger_set "$slug" migrated
  done <<< "$seats"
  echo "   all eligible seats marked migrated in ledger."

  # [5] fleet up (creates every migrated tmux session). Terminal still DOWN.
  echo "[5/7] fleet up (create tmux sessions)"
  cmd_up

  # [6] per-seat smoke in waves, Terminal still DOWN so failed-seat profile
  # rollback is durable. Failures are reported LOUD (finding 4) — a failed
  # rollback never prints green.
  echo "[6/7] per-seat smoke (waves of $wave_size, Terminal down) -> $WAVE_LOG"
  : > "$WAVE_LOG"
  local n=0 wave=1 pass=0 fail=0 rberr=0 failed_seats="" ts
  while IFS= read -r slug; do
    [ -n "$slug" ] || continue
    n=$((n+1))
    ts="$(date -u +%FT%TZ)"
    if smoke_seat "$slug"; then
      pass=$((pass+1))
      echo "$ts wave$wave PASS $slug" | tee -a "$WAVE_LOG"
    else
      fail=$((fail+1)); failed_seats="$failed_seats $slug"
      if cutover_fail_seat "$slug"; then
        echo "$ts wave$wave FAIL $slug -> rolled back (profile restored, substrate torn down)" | tee -a "$WAVE_LOG"
      else
        rberr=$((rberr+1))
        echo "$ts wave$wave FAIL $slug -> ROLLBACK INCOMPLETE (profile restore/teardown errored — manual check needed)" | tee -a "$WAVE_LOG"
      fi
    fi
    if [ $((n % wave_size)) -eq 0 ]; then
      echo "  --- wave $wave complete: $pass pass / $fail fail cumulative ---" | tee -a "$WAVE_LOG"
      wave=$((wave+1))
    fi
  done <<< "$seats"

  # [7] single Terminal relaunch (steady state). Passed seats' profiles attach to
  # tmux; rolled-back seats' restored profiles launch the direct alias. Verify the
  # app actually came up and report it (finding 5 — never silently claim success).
  echo "[7/7] relaunching Terminal.app"
  osascript -e 'tell application "Terminal" to activate' >/dev/null 2>&1 || true
  local tup=0 twait=0
  while [ "$twait" -lt 20 ]; do
    pgrep -x Terminal >/dev/null 2>&1 && { tup=1; break; }
    sleep 0.5; twait=$((twait+1))
  done

  # Steady state reached: disarm the recovery trap.
  CUTOVER_DONE=1
  trap - EXIT INT TERM

  echo "CUTOVER COMPLETE: $pass passed, $fail failed.${failed_seats:+ Rolled back:$failed_seats}"
  [ "$tup" = "1" ] && echo "Terminal.app relaunched (native windows reopen per Terminal's own restore; the cockpit surface is the :7800 web page + tmux, which do not depend on native windows)." \
                   || echo "WARNING: Terminal.app did NOT come back up within 10s — relaunch it manually; the tmux+ttyd substrate is unaffected."
  [ "$fail" -eq 0 ] || echo "NOTE: failed seats' profiles restored to direct alias (durable — written while Terminal was down)."
  [ "$rberr" -eq 0 ] || { echo "ERROR: $rberr seat rollback(s) INCOMPLETE — see $WAVE_LOG; do not consider the cutover clean."; }
  echo "Wave report: $WAVE_LOG"
  [ "$rberr" -eq 0 ] || return 1
}

case "${1:-}" in
  sandbox) shift; sandbox "$@" ;;
  cutover) shift; cutover "$@" ;;
  *) echo "usage: cockpit_migrate.sh {sandbox <slug> | cutover(guarded)}" >&2; exit 2 ;;
esac
