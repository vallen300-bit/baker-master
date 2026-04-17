#!/bin/bash
# kbl-gold-drain.sh — standalone runner for the Gold promotion drain.
# Normally invoked by kbl-pipeline-tick.sh (Step 4), but can be run
# ad-hoc (e.g., to flush the queue after WAHA outage recovery).
#
# Assumes env.mac-mini.yml has already been sourced if called directly;
# pipeline-tick variant sources it via yq before invoking.

set -euo pipefail

REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
LOG="/var/log/kbl/gold-drain.log"

mkdir -p "$(dirname "${LOG}")" 2>/dev/null || true

cd "${REPO}"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] gold drain start PID=$$" >> "${LOG}"
python3 -m kbl.gold_drain >> "${LOG}" 2>&1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] gold drain end" >> "${LOG}"
