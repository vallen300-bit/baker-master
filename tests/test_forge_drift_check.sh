#!/usr/bin/env bash
# test_forge_drift_check.sh — smoke tests for the forge drift-check cron tooling
# (install_forge_drift_cron.sh + forge_drift_check.sh). Pure filesystem; no
# launchctl (dry-run), no network. FORGE_DRIFT_BUS_ROLE is set to a bogus slug so
# the drift path can NEVER post a real bus alert during tests.
#
# Run: bash tests/test_forge_drift_check.sh   (exit 0 = all pass)

set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRON="$REPO/scripts/install_forge_drift_cron.sh"
INSTALLER="$REPO/scripts/install_forge_agent.sh"
export FORGE_DRIFT_BUS_ROLE="test-no-such-slug-xyz"   # guarantees no real bus post
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf 'ok   - %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf 'FAIL - %s\n' "$1"; }

TMP="$(mktemp -d)"
BUNDLE="$TMP/bundle"

# --- 1. cron installer dry-run deploys bundle + renders plist ---------------
FORGE_DRIFT_BUNDLE_DIR="$BUNDLE" FORGE_DRIFT_LOGDIR="$TMP/logs" FORGE_DRIFT_DRYRUN=1 \
  bash "$CRON" >/dev/null 2>&1
{ [[ -f "$BUNDLE/forge_drift_check.sh" ]] && [[ -f "$BUNDLE/scripts/install_forge_agent.sh" ]] \
  && [[ -f "$BUNDLE/scripts/forge-agent/heartbeat-ticker.sh" ]] \
  && [[ -f "$BUNDLE/tests/fixtures/stop-bus-ack.sh" ]]; } \
  && ok "bundle layout (installer + forge scripts + fixtures + wrapper)" || bad "bundle layout"

if [[ -f "$BUNDLE/.rendered.plist" ]]; then
  if grep -q '__WRAPPER__\|__BUNDLE__\|__LOGDIR__' "$BUNDLE/.rendered.plist"; then bad "plist placeholders replaced"; else ok "plist placeholders replaced"; fi
  grep -q "$BUNDLE/forge_drift_check.sh" "$BUNDLE/.rendered.plist" && ok "plist ProgramArguments -> wrapper" || bad "plist -> wrapper"
else bad "rendered plist produced"; fi

# --- simulate a deployed host (clean), installed from the same canonical -----
HOST="$TMP/host"
export FORGE_AGENT_HOME="$HOST/forge-agent" CLAUDE_HOME="$HOST/.claude" \
       FORGE_AGENT_ZSHRC="$HOST/.zshrc" BRISEN_LAB_HOST_CLASS_FILE="$HOST/host-class"
mkdir -p "$HOST"; echo headless > "$BRISEN_LAB_HOST_CLASS_FILE"
FORGE_KEY=dummy LAB_URL=https://example.test bash "$INSTALLER" --headless >/dev/null 2>&1
LOG="$TMP/forge-drift.log"

# --- 2. wrapper on clean host -> CLEAN log line -----------------------------
FORGE_CHECK_DIR="$BUNDLE/scripts" FORGE_DRIFT_LOG="$LOG" bash "$BUNDLE/forge_drift_check.sh"
grep -q ' CLEAN$' "$LOG" && ok "clean host -> CLEAN log line" || bad "clean host -> CLEAN log line"

# --- 3. wrapper on drifted host -> DRIFT log line, still exit 0 -------------
echo "# tamper" >> "$FORGE_AGENT_HOME/heartbeat-ticker.sh"
FORGE_CHECK_DIR="$BUNDLE/scripts" FORGE_DRIFT_LOG="$LOG" bash "$BUNDLE/forge_drift_check.sh"; rc=$?
grep -q ' DRIFT ' "$LOG" && ok "drifted host -> DRIFT log line" || bad "drifted host -> DRIFT log line"
[[ "$rc" -eq 0 ]] && ok "wrapper exit 0 on drift (sentinel contract)" || bad "wrapper exit 0 on drift (rc=$rc)"

# --- 4. missing bundle -> ERROR log line, exit 0 ----------------------------
FORGE_CHECK_DIR="$TMP/nope" FORGE_DRIFT_LOG="$TMP/log2" bash "$BUNDLE/forge_drift_check.sh"; rc=$?
{ grep -q ' ERROR ' "$TMP/log2" && [[ "$rc" -eq 0 ]]; } && ok "missing bundle -> ERROR log, exit 0" || bad "missing bundle -> ERROR log/exit"

rm -rf "$TMP"
echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
