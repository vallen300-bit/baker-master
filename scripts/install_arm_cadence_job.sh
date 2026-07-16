#!/usr/bin/env bash
# install_arm_cadence_job.sh — ARM_CADENCE_LAUNCHD_JOB_1 (charter D2 + §4).
#
# Install / reinstall the ARM custodian machine-cadence launchd job. Idempotent:
# unloads existing, redeploys the worker to the TCC-safe dir, regenerates the
# plist, reloads. SINGLE job per host (the ARM custodian is one seat, unlike the
# per-seat lease emitter) — one Label, no seat fan-out.
#
# Mirrors install_lease_heartbeat_emitter.sh / install_arm_semantic_job.sh
# (TCC-safe deploy dir + Python str.replace substitution + crash-only KeepAlive)
# with two deltas:
#   - EMBEDDED secret: GET /api/bus_health went authed (bare=401, X-Terminal-Key=200
#     — BUS_HEALTH_401_POLLER_KEY_1, supersedes the 2026-07-13 http=200-unauth note).
#     The terminal key is resolved at install time (env → cache → 1Password, via
#     brisen_lab_terminal_key.sh) and EMBEDDED in the plist, so it is chmod 600
#     (was 0644). The key helper is deployed alongside the worker so the deployed
#     poller can fall back to the cache if the plist env is ever cleared.
#   - A `--check` subcommand (forge_drift_check.sh contract) so the drift
#     sentinel can assert convergence without re-running the install.
#
# Usage:
#   bash scripts/install_arm_cadence_job.sh              # install / reinstall
#   bash scripts/install_arm_cadence_job.sh --check      # drift check (exit!=0 on drift)
#   ARM_CADENCE_DRYRUN=1 bash scripts/install_arm_cadence_job.sh   # deploy files only
#
# Env:
#   ARM_CADENCE_INTERVAL_S   optional. StartInterval seconds. Default 1800 (30 min).
#   ARM_CADENCE_DEPLOY_DIR   optional (tests). Worker deploy dir override.
#   ARM_CADENCE_SNAPSHOT_DIR optional. Snapshot dir (also injected into plist env).
#   ARM_CADENCE_SEAT         optional. Seat slug whose key authenticates. Default 'arm'.
#   ARM_CADENCE_KEY / BRISEN_LAB_TERMINAL_KEY  optional. Key override (else cache/1P).
#   ARM_CADENCE_DRYRUN       optional (tests). Deploy files only; skip launchctl + key.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/lib/parity.sh
. "${SCRIPT_DIR}/lib/parity.sh"

LABEL="com.baker.arm-cadence"
WORKER_SRC="${SCRIPT_DIR}/arm_cadence_poll.sh"
KEYHELPER_SRC="${SCRIPT_DIR}/brisen_lab_terminal_key.sh"
TEMPLATE="${SCRIPT_DIR}/launchd/com.baker.arm-cadence.plist"

DEPLOY_DIR="${ARM_CADENCE_DEPLOY_DIR:-$HOME/Library/Application Support/baker}"
WORKER_DEPLOY="${DEPLOY_DIR}/arm_cadence_poll.sh"
KEYHELPER_DEPLOY="${DEPLOY_DIR}/brisen_lab_terminal_key.sh"
SEAT="${ARM_CADENCE_SEAT:-arm}"
INSTALLED_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG="$HOME/Library/Logs/arm-cadence.log"
ERRLOG="$HOME/Library/Logs/arm-cadence.err.log"
SNAP_DIR="${ARM_CADENCE_SNAPSHOT_DIR:-$HOME/.brisen-lab/arm-cadence}"
CADENCE_LOG="${ARM_CADENCE_LOG:-$HOME/.brisen-lab/arm-cadence.log}"

# Cadence: config, not a constant. Clamp to a sane floor (>=60s).
CADENCE="${ARM_CADENCE_INTERVAL_S:-1800}"
if ! [[ "$CADENCE" =~ ^[0-9]+$ ]] || [[ "$CADENCE" -lt 60 ]]; then CADENCE=1800; fi

# --------------------------------------------------------------------------
# --check: assert the installed job has NOT drifted. Exit non-zero on drift so
# arm_cadence_drift_check.sh (and any CI wrapper) can alarm. Prints [FAIL] lines
# the sentinel greps. No side effects.
# --------------------------------------------------------------------------
if [[ "${1:-}" == "--check" ]]; then
  rc=0
  emit() { echo "$1"; }
  [[ -f "$WORKER_DEPLOY" ]] || { emit "[FAIL] worker not deployed at $WORKER_DEPLOY"; rc=1; }
  [[ -x "$WORKER_DEPLOY" ]] || { emit "[FAIL] worker not executable at $WORKER_DEPLOY"; rc=1; }
  [[ -f "$INSTALLED_PLIST" ]] || { emit "[FAIL] plist missing at $INSTALLED_PLIST"; rc=1; }
  if command -v launchctl >/dev/null 2>&1; then
    # SIGPIPE-safe under `set -o pipefail`: `launchctl list | grep -q` lets grep
    # short-circuit on the first match, launchctl then dies on SIGPIPE (rc141) and
    # pipefail trips the whole pipeline -> a false "not loaded" (match-position
    # lottery). Capture first, then grep pipe-free.
    _ll="$(launchctl list 2>/dev/null || true)"
    if ! grep -q "$LABEL" <<<"$_ll"; then
      emit "[FAIL] launchd job $LABEL not loaded"; rc=1
    fi
  fi
  # Worker + plist should still bash-parse (lost-exec-bit / truncation guard —
  # the E23 blocker #2 lesson: existence != healthy).
  if [[ -f "$WORKER_DEPLOY" ]] && ! bash -n "$WORKER_DEPLOY" 2>/dev/null; then
    emit "[FAIL] deployed worker fails syntax probe"; rc=1
  fi
  if [[ -f "$WORKER_SRC" && -f "$WORKER_DEPLOY" ]]; then
    repo_sha="$(_sha256 "$WORKER_SRC" 2>/dev/null || true)"
    deploy_sha="$(_sha256 "$WORKER_DEPLOY" 2>/dev/null || true)"
    if [[ -z "$repo_sha" || -z "$deploy_sha" ]]; then
      emit "[FAIL] unable to hash repo/deployed worker for parity"; rc=1
    elif [[ "$repo_sha" != "$deploy_sha" ]]; then
      emit "[FAIL] deployed worker drifted from repo source (deployed ${deploy_sha:0:8} != repo ${repo_sha:0:8} - re-run install)"
      rc=1
    fi
  fi
  if [[ -f "$INSTALLED_PLIST" ]]; then
    ival="$(python3 -c "
import plistlib,sys
try:
    d=plistlib.load(open(sys.argv[1],'rb')); print(int(d.get('StartInterval',0)))
except Exception: print(-1)
" "$INSTALLED_PLIST" 2>/dev/null || echo -1)"
    plist_worker="$(python3 -c "
import plistlib,sys
try:
    d=plistlib.load(open(sys.argv[1],'rb')); a=d.get('ProgramArguments',[]); print(a[1] if len(a)>1 else '')
except Exception: print('')
" "$INSTALLED_PLIST" 2>/dev/null || echo '')"
    if [[ "$ival" -le 0 ]]; then
      emit "[FAIL] installed StartInterval=${ival}s is invalid"; rc=1
    elif [[ "$ival" -ne "$CADENCE" ]]; then
      emit "[FAIL] installed StartInterval=${ival}s differs from expected ${CADENCE}s"; rc=1
    fi
    if [[ "$plist_worker" != "$WORKER_DEPLOY" ]]; then
      emit "[FAIL] installed plist worker path differs (installed ${plist_worker:-<missing>} != expected $WORKER_DEPLOY)"; rc=1
    fi
    # BUS_HEALTH_401_POLLER_KEY_1: the plist MUST carry a non-empty terminal key
    # (embedded env), else every poll 401s and the snapshot is silently degraded.
    # Print only present/empty — never the key itself.
    key_present="$(python3 -c "
import plistlib,sys
try:
    d=plistlib.load(open(sys.argv[1],'rb')); k=d.get('EnvironmentVariables',{}).get('ARM_CADENCE_KEY','')
    print('yes' if (k and k != '__KEY__') else 'no')
except Exception: print('no')
" "$INSTALLED_PLIST" 2>/dev/null || echo 'no')"
    if [[ "$key_present" != "yes" ]]; then
      emit "[FAIL] installed plist has no embedded ARM_CADENCE_KEY (bus_health polls will 401 — re-run install)"; rc=1
    fi
  fi
  # Snapshot freshness: latest.json should be younger than 3x the cadence. A
  # stale snapshot means the poller silently stopped producing (the exact
  # snapshot-pusher-outage failure mode this job hardens against).
  LATEST="${SNAP_DIR}/latest.json"
  if [[ -f "$LATEST" ]]; then
    now="$(date +%s)"; mtime="$(stat -f %m "$LATEST" 2>/dev/null || stat -c %Y "$LATEST" 2>/dev/null || echo 0)"
    age=$(( now - mtime ))
    if [[ "$age" -gt $(( CADENCE * 3 )) ]]; then
      emit "[FAIL] snapshot stale: latest.json ${age}s old (> 3x cadence ${CADENCE}s)"; rc=1
    fi
  else
    emit "[FAIL] no snapshot yet at $LATEST"; rc=1
  fi
  if [[ "$rc" -eq 0 ]]; then echo "RESULT: CLEAN ($LABEL loaded, worker healthy, snapshot fresh)"; else echo "RESULT: DRIFT"; fi
  exit "$rc"
fi

# --------------------------------------------------------------------------
# install / reinstall
# --------------------------------------------------------------------------
[[ -f "$WORKER_SRC" ]] || { echo "FATAL: worker missing at $WORKER_SRC" >&2; exit 2; }
[[ -f "$KEYHELPER_SRC" ]] || { echo "FATAL: key helper missing at $KEYHELPER_SRC" >&2; exit 2; }
[[ -f "$TEMPLATE"   ]] || { echo "FATAL: plist template missing at $TEMPLATE" >&2; exit 2; }

# 1. Deploy worker + key helper to the TCC-safe dir; ensure snapshot dir exists.
mkdir -p "$DEPLOY_DIR" "$SNAP_DIR"
cp "$WORKER_SRC" "$WORKER_DEPLOY"; chmod +x "$WORKER_DEPLOY"
cp "$KEYHELPER_SRC" "$KEYHELPER_DEPLOY"; chmod +x "$KEYHELPER_DEPLOY"

# Dry-run (tests): deploy files only; never touch launchd, never resolve the key.
if [[ -n "${ARM_CADENCE_DRYRUN:-}" ]]; then
  echo "Dry-run: deployed ARM cadence poller (interval=${CADENCE}s) to ${DEPLOY_DIR}"
  echo "  Worker:   $WORKER_DEPLOY"
  echo "  Label:    $LABEL"
  echo "  Snapshot: $SNAP_DIR"
  exit 0
fi

# 2. Resolve the terminal key (env → cache → 1Password). Fail loud if unresolved —
#    an authed poller with no key would only ever record 401/degraded snapshots.
# shellcheck source=scripts/brisen_lab_terminal_key.sh
. "$KEYHELPER_SRC"
KEY="$(brisen_lab_read_terminal_key "$SEAT" "${ARM_CADENCE_KEY:-${BRISEN_LAB_TERMINAL_KEY:-}}" 2>/dev/null || true)"
if [[ -z "$KEY" ]]; then
  echo "FATAL: could not resolve terminal key for seat '$SEAT' (env → cache → 1Password all empty)" >&2
  exit 3
fi

# 3. Unload existing job if present.
launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true

# 4. Generate the plist. The key goes via env (ARM_CADENCE_KEY), NOT argv, so it
#    never appears in the process list. All other tokens are argv (non-secret paths).
ARM_CADENCE_KEY="$KEY" python3 -c "
import os, sys
tpl, worker, label, cadence, log, errlog, snap_dir, cadence_log, seat = sys.argv[1:10]
body = open(tpl).read()
for a, b in (('__WORKER_PATH__', worker), ('__LABEL__', label),
             ('__CADENCE__', cadence), ('__LOG__', log), ('__ERRLOG__', errlog),
             ('__SNAP_DIR__', snap_dir), ('__CADENCE_LOG__', cadence_log),
             ('__SEAT__', seat), ('__KEY__', os.environ['ARM_CADENCE_KEY'])):
    body = body.replace(a, b)
sys.stdout.write(body)
" "$TEMPLATE" "$WORKER_DEPLOY" "$LABEL" "$CADENCE" "$LOG" "$ERRLOG" "$SNAP_DIR" "$CADENCE_LOG" "$SEAT" \
  > "$INSTALLED_PLIST"
chmod 600 "$INSTALLED_PLIST"   # protect the embedded terminal key

# 5. Load the job.
launchctl load -w "$INSTALLED_PLIST"

echo "Installed ARM cadence watchdog:"
echo "  Interval: ${CADENCE}s   Seat: ${SEAT}"
echo "  Worker:   $WORKER_DEPLOY"
echo "  Plist:    $INSTALLED_PLIST  (chmod 600 — embeds terminal key)"
echo "  Snapshot: ${SNAP_DIR}/latest.json  (ARM report synthesis reads this)"
echo "Verify:   launchctl list | grep $LABEL"
echo "Kill:     launchctl unload $INSTALLED_PLIST   # reverts ARM to v1 scope (charter §7)"
echo "Log:      $LOG"
