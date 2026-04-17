#!/bin/bash
# kbl-pipeline-tick.sh — cron entry for the KBL Mac Mini pipeline.
# Per brief §8 of KBL-A_INFRASTRUCTURE_CODE_BRIEF.md.
#
# Sequence (under flock /tmp/kbl-pipeline.lock):
#   1. git pull --rebase -X ours origin main (baker-vault)   — Director wins on conflict
#   2. yq-source env.mac-mini.yml → KBL_* env vars           — guarded if yml missing
#   3. hard kill switch: KBL_FLAGS_PIPELINE_ENABLED=true?     — else exit 0
#   4. python3 -m kbl.gold_drain                             — drain /gold queue
#   5. python3 -m kbl.pipeline_tick                          — claim 1 signal

set -euo pipefail

LOCK_FILE="/tmp/kbl-pipeline.lock"
REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
VAULT="${KBL_VAULT:-${HOME}/baker-vault}"
LOG="/var/log/kbl/pipeline.log"

mkdir -p "$(dirname "${LOG}")" 2>/dev/null || true

# --- Load secrets (B2.B1: launchd does NOT source ~/.zshrc) ---
# ~/.kbl.env is populated by install_kbl_mac_mini.sh (chmod 600) with
# DATABASE_URL, ANTHROPIC_API_KEY, QDRANT_URL, QDRANT_API_KEY,
# VOYAGE_API_KEY. Absence isn't fatal here — the yml guard + pipeline
# flag below short-circuit before any Python import touches the env,
# so a first-install without secrets still logs cleanly.
[ -f "${HOME}/.kbl.env" ] && . "${HOME}/.kbl.env"

# --- Acquire lock (non-blocking: second tick exits silently) ---
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    exit 0
fi

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "${LOG}"
}
log "=== tick start PID=$$ ==="

# --- Step 1: sync config from baker-vault ---
cd "${VAULT}"
if ! git pull --rebase -X ours origin main >> "${LOG}" 2>&1; then
    log "CRITICAL: git pull conflict, aborting tick"
    git rebase --abort 2>/dev/null || true
    # R1.B3: argv dispatcher on kbl.logging (Phase 8) can escalate.
    (cd "${REPO}" && python3 -m kbl.logging emit_critical "git-conflict" "baker-vault pull failed — manual intervention required") >> "${LOG}" 2>&1 || log "WARN: emit_critical alert failed"
    exit 1
fi

# --- Step 2: source config (R1.M3 guard when yml not yet deployed) ---
if [ ! -f "${VAULT}/config/env.mac-mini.yml" ]; then
    log "INFO: ${VAULT}/config/env.mac-mini.yml not yet deployed — pipeline idle"
    exit 0
fi
eval "$(yq -r '
  [paths(scalars, arrays) as $p |
    select($p | last | type != "number") |
    "export KBL_" + ($p | map(. | ascii_upcase) | join("_")) + "=" +
    (getpath($p) |
      if type == "array" then join(",") else tostring end
    )
  ] | .[]
' "${VAULT}/config/env.mac-mini.yml")"

# --- Step 3: hard kill switch ---
if [ "${KBL_FLAGS_PIPELINE_ENABLED:-false}" != "true" ]; then
    log "pipeline disabled (KBL_FLAGS_PIPELINE_ENABLED=false), exiting"
    exit 0
fi

# --- Step 4: drain gold_promote_queue ---
log "draining gold_promote_queue"
cd "${REPO}" && python3 -m kbl.gold_drain >> "${LOG}" 2>&1 || log "WARN: gold_drain exited nonzero"

# --- Step 5: process 1 signal (KBL-A stub; KBL-B replaces body) ---
log "processing 1 signal"
cd "${REPO}" && python3 -m kbl.pipeline_tick >> "${LOG}" 2>&1 || log "WARN: pipeline_tick exited nonzero"

log "=== tick end ==="
# Lock released implicitly when exec 9 fd closes at script exit.
