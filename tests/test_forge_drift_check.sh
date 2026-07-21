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
  && [[ -f "$BUNDLE/tests/fixtures/turn-bus-drain.sh" ]] \
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

# --- 5. drift bus post has the EXACT payload the daemon accepts --------------
# Intercept curl via a PATH shim that captures its args, give the wrapper a
# readable key (temp HOME so the real ~/.brisen-lab is untouched), tamper the
# host to force drift, then assert the posted JSON: kind MUST be a daemon
# VALID_KIND (dispatch, NOT alert -> codex #5653 HIGH), to=[lead], topic form.
BIN="$TMP/bin"; mkdir -p "$BIN"
CAP="$TMP/curl.capture"
cat > "$BIN/curl" <<SH
#!/usr/bin/env bash
: > "$CAP"
for a in "\$@"; do printf '%s\n' "\$a" >> "$CAP"; done
exit 0
SH
chmod +x "$BIN/curl"
THOME="$TMP/thome"; mkdir -p "$THOME/.brisen-lab/keys"
echo "testkey-abc123" > "$THOME/.brisen-lab/keys/testdaemon"
# host is already tampered (drift) from test 3. Run wrapper with the shim + key.
PATH="$BIN:$PATH" HOME="$THOME" FORGE_DRIFT_BUS_ROLE="testdaemon" \
  FORGE_CHECK_DIR="$BUNDLE/scripts" FORGE_DRIFT_LOG="$TMP/log3" \
  bash "$BUNDLE/forge_drift_check.sh"
# extract the JSON payload (the arg after -d) and assert fields
PAY="$(python3 - "$CAP" <<'PY'
import sys
lines=[l.rstrip("\n") for l in open(sys.argv[1])]
# the -d value is the arg following a "-d" line
pay=""
for i,l in enumerate(lines):
    if l=="-d" and i+1<len(lines): pay=lines[i+1]; break
print(pay)
PY
)"
verdict="$(PAY="$PAY" CAP="$CAP" python3 - <<'PY'
import json, os
cap=open(os.environ["CAP"]).read()
try: d=json.loads(os.environ["PAY"])
except Exception: print("FAIL no-json-payload"); raise SystemExit
VALID_KINDS={"dispatch","ack","broadcast","ratify_required","ratify_decision"}
oks=[]
oks.append(("kind-valid", d.get("kind") in VALID_KINDS and d.get("kind")=="dispatch"))
oks.append(("to-lead", d.get("to")==["lead"]))
oks.append(("topic-form", str(d.get("topic","")).startswith("drift/forge-agent-")))
oks.append(("tier-valid", d.get("tier_required") in {"A","B","director_only"}))
oks.append(("endpoint-msg-lead", "/msg/lead" in cap))
# BUS_POST_ENVELOPE_ID_MINT_1: a minted envelope id must be present + non-blank so the
# drift post survives BRISEN_LAB_REQUIRE_ENVELOPE_ID (else a silent missing_idempotency_key 400).
ik=d.get("idempotency_key")
oks.append(("envelope-id-minted", isinstance(ik,str) and bool(ik.strip())))
print(" ".join(("OK:" if v else "FAIL:")+k for k,v in oks))
print("ALLOK" if all(v for _,v in oks) else "SOMEFAIL")
PY
)"
if printf '%s' "$verdict" | grep -q "ALLOK"; then ok "drift post payload valid (kind=dispatch, to=lead, topic, /msg/lead)"; else bad "drift post payload: $verdict"; fi

rm -rf "$TMP"
echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
