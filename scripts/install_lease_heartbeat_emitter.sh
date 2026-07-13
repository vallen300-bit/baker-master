#!/usr/bin/env bash
# install_lease_heartbeat_emitter.sh — CASE_ONE_P2_LIVENESS_LIFECYCLE_1 (P2.2).
# Install or reinstall the per-seat structural lease-heartbeat emitter launchd
# agent. Idempotent: unloads existing, regenerates plist, reloads. Mirrors
# install_forge_push.sh (TCC-safe deploy dir + Python str.replace substitution +
# crash-only KeepAlive).
#
# Usage:
#   BAKER_ROLE=b1 [BRISEN_LAB_TERMINAL_KEY=…] \
#     [BRISEN_LAB_HEARTBEAT_CADENCE_S=60] bash scripts/install_lease_heartbeat_emitter.sh
#
# The seat slug comes from BAKER_ROLE (one emitter per seat → one Label per seat,
# so multiple seats on one host never collide). The terminal key is read the same
# way the worker reads it (env → key cache → 1Password) and embedded in the plist.
# Cadence (StartInterval) is config, not a constant — rider (b).
#
# Env:
#   BAKER_ROLE                       required. The seat this emitter renews.
#   BRISEN_LAB_TERMINAL_KEY          optional. Falls back to the key cache / 1P.
#   BRISEN_LAB_HEARTBEAT_CADENCE_S   optional. StartInterval seconds. Default 60.
#   LEASE_EMITTER_DEPLOY_DIR         optional (tests). Worker deploy dir override.
#   LEASE_EMITTER_DRYRUN             optional (tests). Deploy files only; skip launchctl.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/agent_identity_generated.sh
. "$SCRIPT_DIR/agent_identity_generated.sh"
# shellcheck source=scripts/brisen_lab_terminal_key.sh
. "$SCRIPT_DIR/brisen_lab_terminal_key.sh"

if ! SEAT="$(agent_identity_resolve_role "${BAKER_ROLE:-}")"; then
  echo "FATAL: BAKER_ROLE unset or unrecognized: '${BAKER_ROLE:-}'" >&2
  exit 2
fi

KEY="$(brisen_lab_read_terminal_key "$SEAT" "${BRISEN_LAB_TERMINAL_KEY:-}" 2>/dev/null || true)"
if [[ -z "$KEY" ]]; then
  echo "FATAL: terminal key empty for seat=${SEAT} (no env, no cache, no 1P)" >&2
  exit 2
fi

# Cadence (rider b): config, not a constant. Clamp to a sane floor.
CADENCE="${BRISEN_LAB_HEARTBEAT_CADENCE_S:-60}"
if ! [[ "$CADENCE" =~ ^[0-9]+$ ]] || [[ "$CADENCE" -lt 1 ]]; then CADENCE=60; fi

LABEL="com.baker.lease-heartbeat-emitter.${SEAT}"
WORKER_SRC="${SCRIPT_DIR}/lease_heartbeat_emitter.sh"
IDENTITY_SRC="${SCRIPT_DIR}/agent_identity_generated.sh"
KEYHELPER_SRC="${SCRIPT_DIR}/brisen_lab_terminal_key.sh"
TEMPLATE="${SCRIPT_DIR}/launchd/com.baker.lease-heartbeat-emitter.plist"

DEPLOY_DIR="${LEASE_EMITTER_DEPLOY_DIR:-$HOME/Library/Application Support/baker}"
WORKER_DEPLOY="${DEPLOY_DIR}/lease_heartbeat_emitter.sh"
IDENTITY_DEPLOY="${DEPLOY_DIR}/agent_identity_generated.sh"
KEYHELPER_DEPLOY="${DEPLOY_DIR}/brisen_lab_terminal_key.sh"
INSTALLED_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG="$HOME/Library/Logs/lease-heartbeat-emitter.${SEAT}.log"
ERRLOG="$HOME/Library/Logs/lease-heartbeat-emitter.${SEAT}.err.log"

[[ -f "$WORKER_SRC"    ]] || { echo "FATAL: worker missing at $WORKER_SRC"       >&2; exit 2; }
[[ -f "$IDENTITY_SRC"  ]] || { echo "FATAL: identity missing at $IDENTITY_SRC"   >&2; exit 2; }
[[ -f "$KEYHELPER_SRC" ]] || { echo "FATAL: key helper missing at $KEYHELPER_SRC" >&2; exit 2; }
[[ -f "$TEMPLATE"      ]] || { echo "FATAL: plist template missing at $TEMPLATE"  >&2; exit 2; }

# 1. Deploy worker + its two sourced siblings to the TCC-safe dir.
mkdir -p "$DEPLOY_DIR"
cp "$WORKER_SRC" "$WORKER_DEPLOY";       chmod +x "$WORKER_DEPLOY"
cp "$IDENTITY_SRC" "$IDENTITY_DEPLOY";   chmod 600 "$IDENTITY_DEPLOY"
cp "$KEYHELPER_SRC" "$KEYHELPER_DEPLOY"; chmod 600 "$KEYHELPER_DEPLOY"

# Dry-run (tests): deploy files only; never touch launchd or the live agent.
if [[ -n "${LEASE_EMITTER_DRYRUN:-}" ]]; then
  echo "Dry-run: deployed emitter for seat=${SEAT} (cadence=${CADENCE}s) to ${DEPLOY_DIR}"
  echo "  Worker:   $WORKER_DEPLOY"
  echo "  Label:    $LABEL"
  exit 0
fi

# 2. Unload existing agent for THIS seat if present.
launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true

# 3. Generate the plist via Python str.replace (safe regardless of key content).
# The key is passed via env (LEASE_EMITTER_KEY), NOT argv, so it never appears in
# the process list. All other tokens are argv (non-secret).
LEASE_EMITTER_KEY="$KEY" python3 -c "
import os, sys
tpl, worker, seat, label, cadence, log, errlog = sys.argv[1:8]
body = open(tpl).read()
for a, b in (('__WORKER_PATH__', worker), ('__SEAT__', seat), ('__LABEL__', label),
             ('__CADENCE__', cadence), ('__LOG__', log), ('__ERRLOG__', errlog),
             ('__KEY__', os.environ['LEASE_EMITTER_KEY'])):
    body = body.replace(a, b)
sys.stdout.write(body)
" "$TEMPLATE" "$WORKER_DEPLOY" "$SEAT" "$LABEL" "$CADENCE" "$LOG" "$ERRLOG" \
  > "$INSTALLED_PLIST"
chmod 600 "$INSTALLED_PLIST"   # protect the embedded secret

# 4. Load the agent.
launchctl load -w "$INSTALLED_PLIST"

echo "Installed lease-heartbeat emitter:"
echo "  Seat:    $SEAT   (cadence ${CADENCE}s)"
echo "  Worker:  $WORKER_DEPLOY"
echo "  Plist:   $INSTALLED_PLIST"
echo "Verify: launchctl list | grep $LABEL"
echo "Log:    $LOG"
