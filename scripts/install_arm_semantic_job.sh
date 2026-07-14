#!/usr/bin/env bash
# install_arm_semantic_job.sh — SEMANTIC_DELIVERY_EVALUATOR_1 producer poller
# install (Option 2, lead ruling #10915).
#
# Install / reinstall the custodian's SEMANTIC delivery poller launchd job.
# Idempotent: unloads existing, redeploys the worker to the TCC-safe dir,
# regenerates the plist, reloads. SINGLE job per host (one ARM custodian).
#
# Mirrors install_arm_cadence_job.sh (TCC-safe deploy dir + Python str.replace
# substitution + crash-only KeepAlive + --check drift path) with ONE delta: the
# authed endpoint requires a terminal key, so the key is resolved at install time
# (env → cache → 1Password, via brisen_lab_terminal_key.sh) and EMBEDDED in the
# plist — hence chmod 600 (mirrors install_lease_heartbeat_emitter.sh). The key is
# passed to the plist generator via env (never argv → never in the process list).
#
# Marker freshness stays server-truthful: the poller writes semantic.json only on
# a valid 200; a fetch failure leaves the marker to age out and page (lead #10915).
#
# Usage:
#   bash scripts/install_arm_semantic_job.sh            # install / reinstall
#   bash scripts/install_arm_semantic_job.sh --check    # drift check (exit!=0 on drift)
#   ARM_SEMANTIC_DRYRUN=1 bash scripts/install_arm_semantic_job.sh   # deploy files only
#
# Env:
#   ARM_SEMANTIC_INTERVAL_S  optional. StartInterval seconds. Default 1800 (30 min).
#   ARM_SEMANTIC_SEAT        optional. Seat slug whose key authenticates. Default 'daemon'.
#   ARM_SEMANTIC_KEY / BRISEN_LAB_TERMINAL_KEY  optional. Key override (else cache/1P).
#   ARM_SEMANTIC_DEPLOY_DIR  optional (tests). Worker deploy dir override.
#   ARM_SEMANTIC_MARKER_DIR  optional. Marker dir (also injected into plist env).
#   ARM_SEMANTIC_DRYRUN      optional (tests). Deploy files only; skip launchctl + key.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

LABEL="com.baker.arm-semantic"
WORKER_SRC="${SCRIPT_DIR}/arm_semantic_poll.sh"
KEYHELPER_SRC="${SCRIPT_DIR}/brisen_lab_terminal_key.sh"
TEMPLATE="${SCRIPT_DIR}/launchd/com.baker.arm-semantic.plist"

DEPLOY_DIR="${ARM_SEMANTIC_DEPLOY_DIR:-$HOME/Library/Application Support/baker}"
WORKER_DEPLOY="${DEPLOY_DIR}/arm_semantic_poll.sh"
KEYHELPER_DEPLOY="${DEPLOY_DIR}/brisen_lab_terminal_key.sh"
INSTALLED_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG="$HOME/Library/Logs/arm-semantic.log"
ERRLOG="$HOME/Library/Logs/arm-semantic.err.log"
MARKER_DIR="${ARM_SEMANTIC_MARKER_DIR:-$HOME/.brisen-lab/arm-alarm/markers}"
SEMANTIC_LOG="${ARM_SEMANTIC_LOG:-$HOME/.brisen-lab/arm-semantic.log}"
SEAT="${ARM_SEMANTIC_SEAT:-daemon}"

# Cadence: config, not a constant. Clamp to a sane floor (>=60s). Default 1800s —
# well under ARM_ALARM_SEMANTIC_MAX_AGE_S (93600) so the marker never goes stale
# from poll cadence alone.
CADENCE="${ARM_SEMANTIC_INTERVAL_S:-1800}"
if ! [[ "$CADENCE" =~ ^[0-9]+$ ]] || [[ "$CADENCE" -lt 60 ]]; then CADENCE=1800; fi

# --------------------------------------------------------------------------
# --check: assert the installed job has NOT drifted. Exit non-zero on drift.
# --------------------------------------------------------------------------
if [[ "${1:-}" == "--check" ]]; then
  rc=0
  emit() { echo "$1"; }
  [[ -f "$WORKER_DEPLOY" ]] || { emit "[FAIL] worker not deployed at $WORKER_DEPLOY"; rc=1; }
  [[ -x "$WORKER_DEPLOY" ]] || { emit "[FAIL] worker not executable at $WORKER_DEPLOY"; rc=1; }
  [[ -f "$INSTALLED_PLIST" ]] || { emit "[FAIL] plist missing at $INSTALLED_PLIST"; rc=1; }
  if command -v launchctl >/dev/null 2>&1; then
    if ! launchctl list 2>/dev/null | grep -q "$LABEL"; then
      emit "[FAIL] launchd job $LABEL not loaded"; rc=1
    fi
  fi
  if [[ -f "$WORKER_DEPLOY" ]] && ! bash -n "$WORKER_DEPLOY" 2>/dev/null; then
    emit "[FAIL] deployed worker fails syntax probe"; rc=1
  fi
  # Marker freshness: semantic.json should be younger than 3x the cadence. A stale
  # marker means the poller silently stopped producing.
  if [[ -f "$MARKER_DIR/semantic.json" ]]; then
    now="$(date +%s)"; mtime="$(stat -f %m "$MARKER_DIR/semantic.json" 2>/dev/null || stat -c %Y "$MARKER_DIR/semantic.json" 2>/dev/null || echo 0)"
    age=$(( now - mtime ))
    if [[ "$age" -gt $(( CADENCE * 3 )) ]]; then
      emit "[FAIL] semantic.json stale: ${age}s old (> 3x cadence ${CADENCE}s)"; rc=1
    fi
  else
    emit "[FAIL] no semantic.json marker yet at $MARKER_DIR"; rc=1
  fi
  if [[ "$rc" -eq 0 ]]; then echo "RESULT: CLEAN ($LABEL loaded, worker healthy, marker fresh)"; else echo "RESULT: DRIFT"; fi
  exit "$rc"
fi

# --------------------------------------------------------------------------
# install / reinstall
# --------------------------------------------------------------------------
[[ -f "$WORKER_SRC"    ]] || { echo "FATAL: worker missing at $WORKER_SRC" >&2; exit 2; }
[[ -f "$KEYHELPER_SRC" ]] || { echo "FATAL: key helper missing at $KEYHELPER_SRC" >&2; exit 2; }
[[ -f "$TEMPLATE"      ]] || { echo "FATAL: plist template missing at $TEMPLATE" >&2; exit 2; }

# 1. Deploy worker + key helper to the TCC-safe dir; ensure marker dir exists.
mkdir -p "$DEPLOY_DIR" "$MARKER_DIR"
cp "$WORKER_SRC" "$WORKER_DEPLOY";       chmod +x "$WORKER_DEPLOY"
cp "$KEYHELPER_SRC" "$KEYHELPER_DEPLOY"; chmod 600 "$KEYHELPER_DEPLOY"

# Dry-run (tests): deploy files only; never touch launchd, never resolve the key.
if [[ -n "${ARM_SEMANTIC_DRYRUN:-}" ]]; then
  echo "Dry-run: deployed ARM semantic poller (interval=${CADENCE}s, seat=${SEAT}) to ${DEPLOY_DIR}"
  echo "  Worker:  $WORKER_DEPLOY"
  echo "  Label:   $LABEL"
  echo "  Marker:  ${MARKER_DIR}/semantic.json"
  exit 0
fi

# 2. Resolve the terminal key (env → cache → 1Password). Fail loud if unresolved —
#    an authed poller with no key would only ever SKIP writes.
# shellcheck source=scripts/brisen_lab_terminal_key.sh
. "$KEYHELPER_SRC"
KEY="$(brisen_lab_read_terminal_key "$SEAT" "${ARM_SEMANTIC_KEY:-${BRISEN_LAB_TERMINAL_KEY:-}}" 2>/dev/null || true)"
if [[ -z "$KEY" ]]; then
  echo "FATAL: could not resolve terminal key for seat '$SEAT' (env → cache → 1Password all empty)" >&2
  exit 3
fi

# 3. Unload existing job if present.
launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true

# 4. Generate the plist. The key goes via env (ARM_SEMANTIC_KEY), NOT argv, so it
#    never appears in the process list. All other tokens are argv (non-secret).
ARM_SEMANTIC_KEY="$KEY" python3 -c "
import os, sys
tpl, worker, label, cadence, log, errlog, marker_dir, seat, semantic_log = sys.argv[1:10]
body = open(tpl).read()
for a, b in (('__WORKER_PATH__', worker), ('__LABEL__', label),
             ('__CADENCE__', cadence), ('__LOG__', log), ('__ERRLOG__', errlog),
             ('__MARKER_DIR__', marker_dir), ('__SEAT__', seat),
             ('__SEMANTIC_LOG__', semantic_log),
             ('__KEY__', os.environ['ARM_SEMANTIC_KEY'])):
    body = body.replace(a, b)
sys.stdout.write(body)
" "$TEMPLATE" "$WORKER_DEPLOY" "$LABEL" "$CADENCE" "$LOG" "$ERRLOG" "$MARKER_DIR" "$SEAT" "$SEMANTIC_LOG" \
  > "$INSTALLED_PLIST"
chmod 600 "$INSTALLED_PLIST"   # protect the embedded terminal key

# 5. Load the job.
launchctl load -w "$INSTALLED_PLIST"

echo "Installed ARM semantic delivery poller:"
echo "  Interval: ${CADENCE}s   Seat: ${SEAT}"
echo "  Worker:   $WORKER_DEPLOY"
echo "  Plist:    $INSTALLED_PLIST  (chmod 600 — embeds terminal key)"
echo "  Marker:   ${MARKER_DIR}/semantic.json  (arm_alarm_check.sh consumes this)"
echo "Verify:   launchctl list | grep $LABEL"
echo "Kill:     launchctl unload $INSTALLED_PLIST"
echo "Log:      $LOG"
