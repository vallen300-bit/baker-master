#!/usr/bin/env bash
# test_install_forge_agent.sh — smoke + drift tests for scripts/install_forge_agent.sh.
# Pure filesystem: installs into a throwaway HOME (env overrides), never touches
# the real ~/.claude, ~/forge-agent, or ~/.zshrc, and never hits the network.
#
# Run: bash tests/test_install_forge_agent.sh   (exit 0 = all pass)

set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$REPO/scripts/install_forge_agent.sh"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf 'ok   - %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL - %s\n' "$1"; }

new_env() {
  TMP="$(mktemp -d)"
  export FORGE_AGENT_HOME="$TMP/forge-agent" CLAUDE_HOME="$TMP/.claude" \
         FORGE_AGENT_ZSHRC="$TMP/.zshrc" BRISEN_LAB_HOST_CLASS_FILE="$TMP/host-class"
}
run_install() { FORGE_KEY="dummy" LAB_URL="https://example.test" bash "$INSTALLER" "$@" >/dev/null 2>&1; }

# --- 1. install then --check is clean (headless) ---------------------------
new_env
run_install --headless
if bash "$INSTALLER" --check --headless >/dev/null 2>&1; then ok "install -> check clean (headless)"; else bad "install -> check clean (headless)"; fi

# 4 forge scripts + 2 bus hooks deployed + executable
depl=0; for s in session-start-hook.sh heartbeat-ticker.sh turn-start-hook.sh turn-stop-hook.sh; do [[ -x "$FORGE_AGENT_HOME/$s" ]] && depl=$((depl+1)); done
for h in session-start-bus-drain.sh stop-bus-ack.sh; do [[ -x "$CLAUDE_HOME/hooks/$h" ]] && depl=$((depl+1)); done
[[ "$depl" -eq 6 ]] && ok "6 scripts deployed + executable" || bad "6 scripts deployed (got $depl)"

# active/ dir + sessions.json seeded
{ [[ -d "$FORGE_AGENT_HOME/active" ]] && [[ -f "$FORGE_AGENT_HOME/sessions.json" ]]; } && ok "active/ + sessions.json seeded" || bad "active/ + sessions.json seeded"

# --- 2. drift detection on script tamper -----------------------------------
echo "# tamper" >> "$FORGE_AGENT_HOME/heartbeat-ticker.sh"
bash "$INSTALLER" --check --headless >/dev/null 2>&1 && bad "tamper -> drift exit non-zero" || ok "tamper -> drift exit non-zero"
rm -rf "$TMP"

# --- 3. drift detection on missing env -------------------------------------
new_env
run_install --headless
: > "$FORGE_AGENT_ZSHRC"   # wipe env exports
bash "$INSTALLER" --check --headless >/dev/null 2>&1 && bad "missing env -> drift" || ok "missing env -> drift"
rm -rf "$TMP"

# --- 4. idempotency: re-install adds no duplicate hook groups ---------------
new_env
run_install --headless
run_install --headless
dupes="$(python3 - "$CLAUDE_HOME/settings.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); h=d.get("hooks",{})
bad=0
for ev,gs in h.items():
    seen=set()
    for g in gs:
        key=tuple(x.get("command") for x in g.get("hooks",[]))
        if key in seen: bad+=1
        seen.add(key)
print(bad)
PY
)"
[[ "$dupes" == "0" ]] && ok "idempotent re-install (no duplicate hook groups)" || bad "idempotent re-install (dupes=$dupes)"
rm -rf "$TMP"

# --- 5. settings.json preserves pre-existing unrelated keys ----------------
new_env
mkdir -p "$CLAUDE_HOME"
echo '{"model":"opus[1m]","theme":"light","permissions":{"allow":["Read"]}}' > "$CLAUDE_HOME/settings.json"
run_install --headless
kept="$(python3 -c 'import json;d=json.load(open("'"$CLAUDE_HOME"'/settings.json"));print(int(d.get("model")=="opus[1m]" and d.get("theme")=="light" and "hooks" in d))')"
[[ "$kept" == "1" ]] && ok "preserves pre-existing settings keys" || bad "preserves pre-existing settings keys"
rm -rf "$TMP"

# --- 6. headless purity: Director-facing hook on headless -> drift ----------
new_env
run_install --headless
python3 - "$CLAUDE_HOME/settings.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p))
d["hooks"].setdefault("Stop",[]).append({"hooks":[{"type":"command","command":"/x/.claude/hooks/laconic-reminder.sh"}]})
json.dump(d,open(p,"w"))
PY
bash "$INSTALLER" --check --headless >/dev/null 2>&1 && bad "Director hook on headless -> drift" || ok "Director hook on headless -> drift"
# same settings under --laptop class is NOT a drift (Director hook allowed there)
if bash "$INSTALLER" --check --laptop >/dev/null 2>&1; then ok "Director hook under laptop class -> clean"; else bad "Director hook under laptop class -> clean"; fi
rm -rf "$TMP"

# --- 7. missing wiring -> drift --------------------------------------------
new_env
run_install --headless
echo '{"model":"x"}' > "$CLAUDE_HOME/settings.json"   # blow away hooks
bash "$INSTALLER" --check --headless >/dev/null 2>&1 && bad "missing wiring -> drift" || ok "missing wiring -> drift"
rm -rf "$TMP"

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
