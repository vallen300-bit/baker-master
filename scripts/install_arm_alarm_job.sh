#!/usr/bin/env bash
# install_arm_alarm_job.sh — ARM_OUT_OF_BAND_ALARM_1 (Plan v3, bus #10404).
#
# Install / reinstall the ARM out-of-band alarm launchd job. Idempotent: unloads
# existing, redeploys the worker to the TCC-safe dir, regenerates the plist,
# reloads. SINGLE job per host (one ARM custodian seat).
#
# Mirrors install_arm_cadence_job.sh (TCC-safe deploy dir + Python str.replace
# substitution + crash-only KeepAlive + `--check` drift subcommand) with two
# deltas:
#   - NO embedded secret: the out-of-band email sends through Outlook.app's own
#     M365 auth (no key in the plist). The alarm path never touches the bus.
#   - Interval is clamped to <=300s (not just >=60s) so the <=5-min alarm SLO
#     cannot be misconfigured away. Default 180s.
#
# Usage:
#   bash scripts/install_arm_alarm_job.sh              # install / reinstall
#   bash scripts/install_arm_alarm_job.sh --check      # drift check (exit!=0 on drift)
#   ARM_ALARM_DRYRUN=1 bash scripts/install_arm_alarm_job.sh   # deploy files only
#
# Env:
#   ARM_ALARM_INTERVAL_S   optional. StartInterval seconds. Default 180. Clamped [60,300].
#   ARM_ALARM_EMAIL_TO     optional. Out-of-band recipient. Default dvallen@brisengroup.com.
#   ARM_ALARM_DEPLOY_DIR   optional (tests). Worker deploy dir override.
#   ARM_ALARM_DIR          optional. Alarm state/marker/log root (also injected into plist env).
#   ARM_ALARM_DRYRUN       optional (tests). Deploy files only; skip launchctl.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/lib/parity.sh
. "${SCRIPT_DIR}/lib/parity.sh"

LABEL="com.baker.arm-alarm"
WORKER_SRC="${SCRIPT_DIR}/arm_alarm_check.sh"
TEMPLATE="${SCRIPT_DIR}/launchd/com.baker.arm-alarm.plist"

DEPLOY_DIR="${ARM_ALARM_DEPLOY_DIR:-$HOME/Library/Application Support/baker}"
WORKER_DEPLOY="${DEPLOY_DIR}/arm_alarm_check.sh"
INSTALLED_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG="$HOME/Library/Logs/arm-alarm.log"
ERRLOG="$HOME/Library/Logs/arm-alarm.err.log"
ALARM_DIR="${ARM_ALARM_DIR:-$HOME/.brisen-lab/arm-alarm}"
ALARM_LOG="${ARM_ALARM_LOG:-$HOME/.brisen-lab/arm-alarm.log}"
EMAIL_TO="${ARM_ALARM_EMAIL_TO:-dvallen@brisengroup.com}"

# Cadence: config, not a constant. Clamp to [60,300] — the <=5-min SLO is the
# hard ceiling; a floor of 60s avoids a needless hot poll.
CADENCE="${ARM_ALARM_INTERVAL_S:-180}"
if ! [[ "$CADENCE" =~ ^[0-9]+$ ]]; then CADENCE=180; fi
if [[ "$CADENCE" -lt 60 ]]; then CADENCE=60; fi
if [[ "$CADENCE" -gt 300 ]]; then CADENCE=300; fi

# --------------------------------------------------------------------------
# --check: assert the installed job has NOT drifted. Exit non-zero on drift.
# Prints [FAIL] lines the sentinel greps. No side effects.
# NOTE: unlike arm-cadence, there is NO snapshot-freshness check here — this job
# produces no snapshot; a clean run is silent. Health = installed + loaded +
# worker parses. The alarm's OWN correctness is proven by its state file and the
# test suite, not by a freshness artifact.
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
  # Interval sanity: the installed plist must poll at <=300s or the SLO is void.
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
    if [[ "$ival" -le 0 || "$ival" -gt 300 ]]; then
      emit "[FAIL] installed StartInterval=${ival}s violates <=300s alarm SLO"; rc=1
    elif [[ "$ival" -ne "$CADENCE" ]]; then
      emit "[FAIL] installed StartInterval=${ival}s differs from expected ${CADENCE}s"; rc=1
    fi
    if [[ "$plist_worker" != "$WORKER_DEPLOY" ]]; then
      emit "[FAIL] installed plist worker path differs (installed ${plist_worker:-<missing>} != expected $WORKER_DEPLOY)"; rc=1
    fi
  fi
  if [[ "$rc" -eq 0 ]]; then echo "RESULT: CLEAN ($LABEL loaded, worker healthy, interval <=300s)"; else echo "RESULT: DRIFT"; fi
  exit "$rc"
fi

# --------------------------------------------------------------------------
# install / reinstall
# --------------------------------------------------------------------------
[[ -f "$WORKER_SRC" ]] || { echo "FATAL: worker missing at $WORKER_SRC" >&2; exit 2; }
[[ -f "$TEMPLATE"   ]] || { echo "FATAL: plist template missing at $TEMPLATE" >&2; exit 2; }

# 1. Deploy worker to the TCC-safe dir; ensure alarm dir exists.
mkdir -p "$DEPLOY_DIR" "$ALARM_DIR" "$ALARM_DIR/markers"
cp "$WORKER_SRC" "$WORKER_DEPLOY"; chmod +x "$WORKER_DEPLOY"

# Dry-run (tests): deploy files only; never touch launchd or the live agent.
if [[ -n "${ARM_ALARM_DRYRUN:-}" ]]; then
  echo "Dry-run: deployed ARM out-of-band alarm worker (interval=${CADENCE}s) to ${DEPLOY_DIR}"
  echo "  Worker:   $WORKER_DEPLOY"
  echo "  Label:    $LABEL"
  echo "  Alarm dir:$ALARM_DIR"
  exit 0
fi

# 2. Unload existing job if present.
launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true

# 3. Generate the plist via Python str.replace (safe regardless of path content).
# No secret token here (Outlook M365 auth) — all tokens are non-secret paths/addr.
python3 -c "
import sys
tpl, worker, label, cadence, log, errlog, alarm_dir, alarm_log, email_to = sys.argv[1:10]
body = open(tpl).read()
for a, b in (('__WORKER_PATH__', worker), ('__LABEL__', label),
             ('__CADENCE__', cadence), ('__LOG__', log), ('__ERRLOG__', errlog),
             ('__ALARM_DIR__', alarm_dir), ('__ALARM_LOG__', alarm_log),
             ('__EMAIL_TO__', email_to)):
    body = body.replace(a, b)
sys.stdout.write(body)
" "$TEMPLATE" "$WORKER_DEPLOY" "$LABEL" "$CADENCE" "$LOG" "$ERRLOG" "$ALARM_DIR" "$ALARM_LOG" "$EMAIL_TO" \
  > "$INSTALLED_PLIST"
chmod 644 "$INSTALLED_PLIST"

# 4. Load the job.
launchctl load -w "$INSTALLED_PLIST"

echo "Installed ARM out-of-band alarm watchdog:"
echo "  Interval: ${CADENCE}s  (<=300s guarantees the <=5-min alarm SLO)"
echo "  Worker:   $WORKER_DEPLOY"
echo "  Plist:    $INSTALLED_PLIST"
echo "  Alarm dir:$ALARM_DIR   (markers/ read by the watchdog; state.json = dedupe)"
echo "  Email to: $EMAIL_TO   (out-of-band recipient — override per host)"
echo "Verify:   launchctl list | grep $LABEL"
echo "Kill:     launchctl unload $INSTALLED_PLIST"
echo "Log:      $LOG"
