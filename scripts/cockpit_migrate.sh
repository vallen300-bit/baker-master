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

# --- Phase 2 helpers --------------------------------------------------------

# smoke_seat <slug>: native tmux up AND web ttyd 200 on /term/<slug>/. Installs
# the seat's ttyd if absent. Returns 0 green, non-zero on any failure.
smoke_seat() {
  local slug="$1" port cred base code root_code
  port="$(jq -r --arg s "$slug" '.entries[] | select(.slug==$s) | .port' "$MANIFEST")"
  [ -n "$port" ] && [ "$port" != "null" ] || { echo "   smoke $slug: no port in manifest" >&2; return 1; }
  session_up "$slug" || { echo "   smoke $slug: native tmux session DOWN" >&2; return 1; }
  "$TTYD_INSTALL" "$slug" >/dev/null 2>&1 || { echo "   smoke $slug: ttyd install failed" >&2; return 1; }
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

# rollback_seat_profile <slug>: restore this seat's profile CommandString from the
# backup (durable at next coordinated Terminal restart — Lesson 76), tear down its
# cockpit substrate, and re-seat it NOW via the direct alias. No instant
# profile-cache rollback is promised (brief §6 deliverable 6).
rollback_seat_profile() {
  local slug="$1" profile
  profile="$(jq -r --arg s "$slug" '.entries[] | select(.slug==$s) | .profile' "$MANIFEST")"
  if [ -n "$profile" ] && [ "$profile" != "null" ] && [ -f "$PROFILE_BACKUP" ]; then
    python3 "$PROFILE_REWRITE" restore --plist "$TERMINAL_PLIST" --backup "$PROFILE_BACKUP" \
      --profile "$profile" --allow-running >/dev/null 2>&1 || true
  fi
  "$SCRIPT_DIR/cockpit_rollback.sh" seat "$slug" --relaunch >/dev/null 2>&1 || true
}

# --- Phase 2: coordinated global cutover (§6a) ------------------------------
# Executable ONLY with the GO token (guard kept). Does the whole §6a Phase-2
# sequence: precondition-gate -> backup -> single Terminal.app quit -> rewrite ALL
# eligible profiles -> fleet up + relaunch -> per-seat wave smoke -> per-seat
# rollback on failure -> wave-report log.
#   flags: --wave-size N (smoke/report batch, default 5)
#          --no-quit      (caller already quit Terminal; refuse if it is still up)
#          --dry-run      (plan only; writes nothing live)
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

  # --- dry-run: plan only, touch nothing (no GO token required) ---
  if [ "$dry" = "1" ]; then
    echo "== Phase-2 cutover DRY-RUN (plan only; nothing written) =="
    [ -f "$PROFILE_REWRITE" ] || die "profile-rewrite helper missing: $PROFILE_REWRITE"
    [ -f "$TERMINAL_PLIST" ] || die "Terminal plist missing: $TERMINAL_PLIST"
    python3 "$PROFILE_REWRITE" rewrite --manifest "$MANIFEST" --plist "$TERMINAL_PLIST" \
      --backup "$PROFILE_BACKUP" --plan-only
    echo "(dry-run) pilots: b3=$(ledger_state b3) brisen-desk=$(ledger_state brisen-desk)"
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
  if [ "$do_quit" = "1" ] && [ -n "${TERM_SESSION_ID:-}" ]; then
    die "cutover invoked from inside a Terminal.app session (TERM_SESSION_ID set): the single Cmd+Q would kill THIS process mid-cutover. Run it detached (nohup/caffeinate, or the controller context) — see the runbook. If you are certain this process is detached, unset TERM_SESSION_ID."
  fi

  local seats; seats="$(manifest_slugs)"
  echo "== Phase-2 coordinated global cutover (§6a) — wave-size $wave_size, quit=$do_quit =="

  # [1] checkpoint — NOT script-enforceable (each agent pins its own context;
  # runbook step 1). The GO token asserts the runbook preconditions are met.
  echo "[1/6] PRECONDITION (runbook, not script-enforced): all active seats checkpointed + daemon refresh cadence paused."

  # [2] belt backup of the whole plist before any edit.
  ledger_init
  cp -p "$TERMINAL_PLIST" "$PROFILE_BACKUP.plist.bak"
  echo "[2/6] plist backed up -> $PROFILE_BACKUP.plist.bak"

  # [3] single Terminal.app quit (the ONLY Cmd+Q; §6a step 3), then drop the prefs
  # cache so the file rewrite is authoritative (Lesson 76 corollary: the write MUST
  # happen while Terminal is down or Terminal clobbers it on its next quit).
  if [ "$do_quit" = "1" ]; then
    echo "[3/6] quitting Terminal.app (single coordinated Cmd+Q)"
    osascript -e 'tell application "Terminal" to quit' >/dev/null 2>&1 || true
    local waited=0
    while pgrep -x Terminal >/dev/null 2>&1; do
      sleep 0.5; waited=$((waited+1))
      [ "$waited" -ge 40 ] && die "Terminal.app did not quit within 20s — aborting BEFORE any plist edit (plist untouched; backup at $PROFILE_BACKUP.plist.bak)."
    done
    killall cfprefsd 2>/dev/null || true
    echo "   Terminal down; cfprefsd cache dropped."
  else
    echo "[3/6] --no-quit: caller asserts Terminal.app already down."
    pgrep -x Terminal >/dev/null 2>&1 && die "--no-quit given but Terminal.app is still running — refusing to rewrite (Lesson 76)."
  fi

  # [4] rewrite ALL eligible profiles in one pass, then mark them migrated.
  echo "[4/6] rewriting eligible Terminal profiles -> tmux wrapper"
  python3 "$PROFILE_REWRITE" rewrite --manifest "$MANIFEST" --plist "$TERMINAL_PLIST" --backup "$PROFILE_BACKUP" \
    || die "profile rewrite failed — see error above. Plist backup at $PROFILE_BACKUP.plist.bak."
  while IFS= read -r slug; do
    [ -n "$slug" ] && ledger_set "$slug" migrated
  done <<< "$seats"
  echo "   all eligible seats marked migrated in ledger."

  # [5] fleet up (creates every migrated tmux session) + reopen native windows.
  echo "[5/6] fleet up + relaunch native windows"
  cmd_up
  osascript -e 'tell application "Terminal" to activate' >/dev/null 2>&1 || true

  # [6] per-seat smoke in waves; per-seat rollback on failure; wave-report log.
  echo "[6/6] per-seat smoke (waves of $wave_size) -> $WAVE_LOG"
  : > "$WAVE_LOG"
  local n=0 wave=1 pass=0 fail=0 failed_seats="" ts
  while IFS= read -r slug; do
    [ -n "$slug" ] || continue
    n=$((n+1))
    ts="$(date -u +%FT%TZ)"
    if smoke_seat "$slug"; then
      pass=$((pass+1))
      echo "$ts wave$wave PASS $slug" | tee -a "$WAVE_LOG"
    else
      fail=$((fail+1)); failed_seats="$failed_seats $slug"
      echo "$ts wave$wave FAIL $slug -> rolling back seat" | tee -a "$WAVE_LOG"
      rollback_seat_profile "$slug"
    fi
    if [ $((n % wave_size)) -eq 0 ]; then
      echo "  --- wave $wave complete: $pass pass / $fail fail cumulative ---" | tee -a "$WAVE_LOG"
      wave=$((wave+1))
    fi
  done <<< "$seats"
  echo "CUTOVER COMPLETE: $pass passed, $fail failed.${failed_seats:+ Rolled back:$failed_seats}"
  [ "$fail" -eq 0 ] || echo "NOTE: failed seats re-seated via direct alias now; profile-cache restore lands at the next coordinated Terminal restart (Lesson 76)."
  echo "Wave report: $WAVE_LOG"
}

case "${1:-}" in
  sandbox) shift; sandbox "$@" ;;
  cutover) shift; cutover "$@" ;;
  *) echo "usage: cockpit_migrate.sh {sandbox <slug> | cutover(guarded)}" >&2; exit 2 ;;
esac
