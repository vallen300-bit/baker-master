#!/usr/bin/env bash
# cortex_rollback_v1.sh — Director-only manual fire. <5 min RTO target.
#
# Restores ao_signal_detector direct trigger + ao_project_state writes
# after Cortex Stage 2 V1 decommission of those paths (Steps 34-35 in
# _ops/processes/cortex-stage2-v1-tracker.md).
#
# Usage:
#   bash scripts/cortex_rollback_v1.sh confirm
#
# Behaviour:
#   1. Re-enables ao_signal_detector (sets AO_SIGNAL_DETECTOR_ENABLED=true
#      via Render env-var PATCH).
#   2. Halts new Cortex cycles on AO matter (CORTEX_LIVE_PIPELINE=false).
#   3. Renames the frozen ao_project_state_legacy_frozen_<date> table
#      back to ao_project_state.
#   4. Triggers a Render redeploy.
#   5. Posts Slack DM to Director confirming rollback.
#
# Prerequisites:
#   * 1Password CLI logged in (`op signin`) — secrets pulled from
#     `op://` paths below. The exact paths must be verified by the
#     Director (op item list) before the first live-run.
#   * `confirm` positional arg required (defensive against accidental fire).
#
# Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

set -euo pipefail

if [[ "${1:-}" != "confirm" ]]; then
  cat <<'USAGE'
Usage: bash scripts/cortex_rollback_v1.sh confirm

This is a DESTRUCTIVE rollback that re-enables the legacy
ao_signal_detector + ao_project_state path and halts the Cortex
pipeline. <5 min RTO target. Director-only.

Pass `confirm` as the first positional argument to proceed.
USAGE
  exit 1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cortex_rollback_v1: START"

# --- secrets via 1Password CLI -----------------------------------------------
# B-code TODO: verify these op:// paths with `op item list` before first live
# run. They follow the canonical Brisen vault layout but secrets paths are
# environment-specific and may have moved.
RENDER_API_KEY="${RENDER_API_KEY:-$(op read 'op://Private/Render API Key/credential' 2>/dev/null || true)}"
DB_URL="${DB_URL:-$(op read 'op://Private/Baker DB URL/credential' 2>/dev/null || true)}"
SERVICE_ID="${SERVICE_ID:-srv-d6dgsbctgctc73f55730}"

if [[ -z "${RENDER_API_KEY}" ]]; then
  echo "[ERROR] RENDER_API_KEY not available — pass via env or fix op:// path" >&2
  exit 2
fi
if [[ -z "${DB_URL}" ]]; then
  echo "[WARN] DB_URL not available — table-rename step will be skipped"
fi

# --- 1. Render env-var PATCH (re-enable detector + halt cortex) --------------
curl -fsS -X PATCH "https://api.render.com/v1/services/${SERVICE_ID}/env-vars" \
  -H "Authorization: Bearer ${RENDER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '[
    {"key":"AO_SIGNAL_DETECTOR_ENABLED","value":"true"},
    {"key":"CORTEX_LIVE_PIPELINE","value":"false"},
    {"key":"CORTEX_PIPELINE_ENABLED","value":"false"}
  ]' >/dev/null
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] env vars updated (detector ON, cortex OFF)"

# --- 2. Restore ao_project_state from frozen alias ---------------------------
if [[ -n "${DB_URL}" ]]; then
  # The frozen alias name pattern is ao_project_state_legacy_frozen_YYYYMMDD.
  # Pick the most recent match if multiple exist; do nothing if zero exist.
  FROZEN_NAME=$(psql "${DB_URL}" -At -c "
    SELECT tablename FROM pg_tables
    WHERE tablename LIKE 'ao_project_state_legacy_frozen_%'
    ORDER BY tablename DESC LIMIT 1
  " || echo "")
  if [[ -n "${FROZEN_NAME}" ]]; then
    psql "${DB_URL}" -c "ALTER TABLE ${FROZEN_NAME} RENAME TO ao_project_state;" || \
      echo "[WARN] table rename failed — may already be ao_project_state"
  else
    echo "[INFO] no frozen ao_project_state alias found — skipping table rename"
  fi
fi

# --- 3. Render redeploy to pick up env changes -------------------------------
curl -fsS -X POST "https://api.render.com/v1/services/${SERVICE_ID}/deploys" \
  -H "Authorization: Bearer ${RENDER_API_KEY}" >/dev/null
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redeploy triggered — wait for healthy then verify ao_signal_detector"

# --- 4. Slack DM Director (best-effort) --------------------------------------
curl -fsS -X POST "https://baker-master.onrender.com/api/slack/dm-director" \
  -H "X-Baker-Key: ${BAKER_API_KEY:-bakerbhavanga}" \
  -H "Content-Type: application/json" \
  -d '{"message":"⚠️ Cortex V1 rollback executed — ao_signal_detector restored, Cortex pipeline halted. Verify within 5 min."}' \
  >/dev/null || echo "[WARN] Slack DM failed — manually notify Director"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cortex_rollback_v1: DONE — verify manually within 5 min"
