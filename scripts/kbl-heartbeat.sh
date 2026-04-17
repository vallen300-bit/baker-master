#!/bin/bash
# kbl-heartbeat.sh — 30-min Mac Mini liveness signal.
# Invoked by launchd (com.brisen.kbl.heartbeat, StartInterval=1800).
# Single-owner per R1.S7: only this path writes mac_mini_heartbeat.

set -euo pipefail

REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
LOG="/var/log/kbl/heartbeat.log"

mkdir -p "$(dirname "${LOG}")" 2>/dev/null || true

cd "${REPO}"
python3 -m kbl.heartbeat >> "${LOG}" 2>&1
