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

# 6 forge scripts + 3 bus hooks deployed + executable
depl=0; for s in session-start-hook.sh heartbeat-ticker.sh turn-start-hook.sh turn-stop-hook.sh codex-worktree.sh lifecycle-watch.sh; do [[ -x "$FORGE_AGENT_HOME/$s" ]] && depl=$((depl+1)); done
for h in session-start-bus-drain.sh turn-bus-drain.sh stop-bus-ack.sh; do [[ -x "$CLAUDE_HOME/hooks/$h" ]] && depl=$((depl+1)); done
[[ "$depl" -eq 9 ]] && ok "9 scripts deployed + executable" || bad "9 scripts deployed (got $depl)"
grep -q 'lifecycle-watch.sh' "$FORGE_AGENT_HOME/session-start-hook.sh" \
  && ok "session-start wires lifecycle watcher" \
  || bad "session-start lifecycle watcher wiring missing"

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

# --- 8. executable-bit drift: a deployed hook that loses +x -> drift ---------
new_env
run_install --headless
chmod -x "$FORGE_AGENT_HOME/heartbeat-ticker.sh"
bash "$INSTALLER" --check --headless >/dev/null 2>&1 && bad "lost +x -> drift" || ok "lost +x -> drift"
rm -rf "$TMP"

# --- 9. headless install CONVERGES: strips Director-facing hooks -------------
new_env
run_install --headless
# inject a Director-facing enforcement hook (as a stale prior-install leftover)
python3 - "$CLAUDE_HOME/settings.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p))
d["hooks"].setdefault("Stop",[]).append({"hooks":[{"type":"command","command":"/x/.claude/hooks/recommendation-check.sh"}]})
json.dump(d,open(p,"w"))
PY
# re-run headless install: must remove it (converge), not warn-and-leave
run_install --headless
stray="$(python3 -c 'import json;d=json.load(open("'"$CLAUDE_HOME"'/settings.json"));print(sum(1 for ev in d.get("hooks",{}) for g in d["hooks"][ev] for h in g.get("hooks",[]) if "recommendation-check" in h.get("command","")))')"
[[ "$stray" == "0" ]] && ok "headless install strips Director hook (converges)" || bad "headless install strips Director hook (stray=$stray)"
# and now --check is clean (no unhealable loop)
if bash "$INSTALLER" --check --headless >/dev/null 2>&1; then ok "post-converge --check clean (no install/check loop)"; else bad "post-converge --check clean"; fi
# forge+bus wiring survived the strip
kept="$(python3 -c 'import json;d=json.load(open("'"$CLAUDE_HOME"'/settings.json"));print(sum(1 for ev in d.get("hooks",{}) for g in d["hooks"][ev] for h in g.get("hooks",[]) if "session-start-hook" in h.get("command","") or "turn-stop-hook" in h.get("command","")))')"
[[ "$kept" -ge 2 ]] && ok "forge hooks survive Director-hook strip" || bad "forge hooks survive strip (kept=$kept)"
rm -rf "$TMP"

# --- 10. $HOME-form wiring is recognized (no false drift, no re-install dup) --
# Claude Code expands $HOME at runtime; the laptop wires turn hooks as
# "$HOME/forge-agent/...". The check + dedup must treat that as == the absolute
# form. Test env lives UNDER $HOME so the $HOME-form path resolves to FORGE_HOME.
HTMP="$(mktemp -d "$HOME/.forge-agent-test.XXXXXX")"
export FORGE_AGENT_HOME="$HTMP/forge-agent" CLAUDE_HOME="$HTMP/.claude" \
       FORGE_AGENT_ZSHRC="$HTMP/.zshrc" BRISEN_LAB_HOST_CLASS_FILE="$HTMP/host-class"
run_install --headless
python3 - "$CLAUDE_HOME/settings.json" "$HOME" <<'PY'
import json,sys
p,home=sys.argv[1],sys.argv[2]
d=json.load(open(p))
for ev in ("UserPromptSubmit","Stop","SessionStart"):
    for g in d["hooks"].get(ev,[]):
        for h in g.get("hooks",[]):
            c=h.get("command","")
            if c.startswith(home): h["command"]="$HOME"+c[len(home):]
json.dump(d,open(p,"w"))
PY
if bash "$INSTALLER" --check --headless >/dev/null 2>&1; then ok 'HOME-form wiring recognized (no false drift)'; else bad 'HOME-form wiring recognized (false drift)'; fi
run_install --headless   # re-install against $HOME-form settings must not duplicate
dupct="$(python3 -c 'import json;d=json.load(open("'"$CLAUDE_HOME"'/settings.json"));print(sum(1 for g in d["hooks"].get("UserPromptSubmit",[]) for h in g.get("hooks",[]) if "turn-start-hook" in h.get("command","")))')"
[[ "$dupct" == "1" ]] && ok "re-install no dup vs HOME-form turn hook" || bad "re-install no dup vs HOME-form (count=$dupct)"
rm -rf "$HTMP"

# --- 11. UserPromptSubmit turn drain renders once, then cooldown is silent ----
new_env
run_install --headless
export HOME="$TMP"
mkdir -p "$TMP/bin"
cat > "$TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "called" >> "$CURL_LOG"
printf '%s\n' '{"messages":[{"id":991,"kind":"dispatch","from_terminal":"lead","to_terminals":["lead"],"topic":"turn-test","thread_id":"t-1","acknowledged_at":null,"created_at":"2026-07-20T09:00:00Z","body_preview":"mid-session arrival"}]}'
SH
chmod +x "$TMP/bin/curl"
export PATH="$TMP/bin:$PATH" BAKER_ROLE=lead BRISEN_LAB_TERMINAL_KEY=dummy \
       CURL_LOG="$TMP/curl.log"
first="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
if grep -q 'UserPromptSubmit' <<<"$first" \
   && grep -q 'turn-test' <<<"$first" \
   && [[ "$(cat "$TMP/.brisen-lab-bus-last-seen-lead.txt")" == "2026-07-20T09:00:00Z" ]] \
   && grep -qx '991' "$TMP/.brisen-lab-bus-rendered-lead.txt" \
   && [[ "$(wc -l < "$CURL_LOG")" -eq 1 ]]; then
  ok "turn drain renders additionalContext"
else
  bad "turn drain renders additionalContext"
fi
second="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
if [[ -z "$second" && "$(wc -l < "$CURL_LOG")" -eq 1 ]]; then
  ok "turn drain cooldown skips curl"
else
  bad "turn drain cooldown skips curl"
fi

# HTTP-error JSON must not arm the cooldown; the next prompt retries the daemon.
cat > "$TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "called" >> "$CURL_LOG"
printf '%s\n' '{"detail":"bus_busy_retry"}'
SH
chmod +x "$TMP/bin/curl"
rm -f "$TMP/.brisen-lab-bus-turn-drain-lead.txt"
http_error_first="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
http_error_second="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
if grep -q 'daemon error' <<<"$http_error_first" \
   && grep -q 'daemon error' <<<"$http_error_second" \
   && [[ "$(wc -l < "$CURL_LOG")" -eq 3 ]]; then
  ok "HTTP-error response does not arm cooldown"
else
  bad "HTTP-error response does not arm cooldown"
fi

# A malformed messages envelope must also stay retryable and never arm cooldown.
cat > "$TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "called" >> "$CURL_LOG"
printf '%s\n' '{"messages":"malformed"}'
SH
chmod +x "$TMP/bin/curl"
rm -f "$TMP/.brisen-lab-bus-turn-drain-lead.txt"
malformed_first="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
malformed_second="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
if grep -q 'malformed daemon response' <<<"$malformed_first" \
   && grep -q 'malformed daemon response' <<<"$malformed_second" \
   && [[ "$(wc -l < "$CURL_LOG")" -eq 5 ]] \
   && [[ ! -e "$TMP/.brisen-lab-bus-turn-drain-lead.txt" ]]; then
  ok "malformed response does not arm cooldown"
else
  bad "malformed response does not arm cooldown"
fi

# A typed-but-invalid message must not arm cooldown before state persistence.
cat > "$TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "called" >> "$CURL_LOG"
printf '%s\n' '{"messages":[{"id":993,"kind":"dispatch","from_terminal":"lead","to_terminals":["lead"],"acknowledged_at":null,"created_at":null,"body_preview":"bad timestamp"}]}'
SH
chmod +x "$TMP/bin/curl"
rm -f "$TMP/.brisen-lab-bus-turn-drain-lead.txt"
typed_invalid_first="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
typed_invalid_second="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
if grep -q 'malformed daemon response' <<<"$typed_invalid_first" \
   && grep -q 'malformed daemon response' <<<"$typed_invalid_second" \
   && [[ "$(wc -l < "$CURL_LOG")" -eq 7 ]] \
   && [[ ! -e "$TMP/.brisen-lab-bus-turn-drain-lead.txt" ]]; then
  ok "typed-invalid response does not arm cooldown"
else
  bad "typed-invalid response does not arm cooldown"
fi

# A non-ISO cursor timestamp must not be persisted or arm cooldown.
cat > "$TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "called" >> "$CURL_LOG"
printf '%s\n' '{"messages":[{"id":994,"kind":"dispatch","from_terminal":"lead","to_terminals":["lead"],"acknowledged_at":null,"created_at":"not-a-date","body_preview":"bad cursor"}]}'
SH
chmod +x "$TMP/bin/curl"
rm -f "$TMP/.brisen-lab-bus-turn-drain-lead.txt" \
      "$TMP/.brisen-lab-bus-last-seen-lead.txt"
invalid_cursor_first="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
invalid_cursor_second="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
if grep -q 'malformed daemon response' <<<"$invalid_cursor_first" \
   && grep -q 'malformed daemon response' <<<"$invalid_cursor_second" \
   && [[ "$(wc -l < "$CURL_LOG")" -eq 9 ]] \
   && [[ ! -e "$TMP/.brisen-lab-bus-turn-drain-lead.txt" ]] \
   && [[ ! -e "$TMP/.brisen-lab-bus-last-seen-lead.txt" ]]; then
  ok "invalid cursor timestamp does not arm cooldown"
else
  bad "invalid cursor timestamp does not arm cooldown"
fi

# Concurrent prompts for one slug: the atomic claim lets exactly one drain
# render/ledger the arrival while the other exits silently.
cat > "$TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "called" >> "$CURL_LOG"
sleep 0.2
printf '%s\n' '{"messages":[{"id":992,"kind":"dispatch","from_terminal":"lead","to_terminals":["lead"],"topic":"race-test","thread_id":"t-2","acknowledged_at":null,"created_at":"2026-07-20T09:01:00Z","body_preview":"single render"}]}'
SH
chmod +x "$TMP/bin/curl"
rm -f "$TMP/.brisen-lab-bus-turn-drain-lead.txt" \
      "$TMP/.brisen-lab-bus-last-seen-lead.txt" \
      "$TMP/.brisen-lab-bus-rendered-lead.txt" \
      "$TMP/.brisen-lab-bus-turn-drain-lead.lock" \
      "$CURL_LOG"
printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh" > "$TMP/race-a.out" 2>/dev/null &
race_a=$!
sleep 0.05
printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh" > "$TMP/race-b.out" 2>/dev/null &
race_b=$!
wait "$race_a"
wait "$race_b"
race_rendered="$(grep -h -c 'race-test' "$TMP/race-a.out" "$TMP/race-b.out" 2>/dev/null | awk '{sum += $1} END {print sum+0}')"
if [[ "$(wc -l < "$CURL_LOG")" -eq 1 \
   && "$race_rendered" -eq 1 \
   && "$(wc -l < "$TMP/.brisen-lab-bus-rendered-lead.txt")" -eq 1 ]]; then
  ok "concurrent turn drain renders once"
else
  bad "concurrent turn drain renders once"
fi

cat > "$TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
exit 28
SH
chmod +x "$TMP/bin/curl"
rm -f "$TMP/.brisen-lab-bus-turn-drain-lead.txt"
failed="$(printf '{}' | "$CLAUDE_HOME/hooks/turn-bus-drain.sh")"
if grep -q 'daemon unreachable' <<<"$failed"; then
  ok "turn drain failure stays non-blocking"
else
  bad "turn drain failure stays non-blocking"
fi
rm -rf "$TMP"

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
