#!/usr/bin/env bash
# test_heartbeat_ticker_idle_keepalive.sh — LIVENESS_WORKING_SPLIT_1 PR 2.
# Proves the heartbeat ticker's idle keepalive: while IDLE it POSTs idle=true
# (refreshes last_alive_at -> slug_live stays true) but NEVER a bare working beat
# (which would set last_seen_at=NOW and RELIGHT the dashboard amber — the exact
# regression the AC forbids, #5661/#5625). While a turn is ACTIVE it POSTs a
# working beat (idle omitted). Pure filesystem; curl is shimmed, no network.
#
# Each scenario runs in its OWN temp dir + unique uuid and kills only its own
# ticker PID (never `pkill -f heartbeat-ticker.sh` — that would kill this box's
# real live-session tickers).
#
# Run: bash tests/test_heartbeat_ticker_idle_keepalive.sh   (exit 0 = all pass)

set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TICKER="$REPO/scripts/forge-agent/heartbeat-ticker.sh"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf 'ok   - %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf 'FAIL - %s\n' "$1"; }

# run one hermetic ticker scenario.
#   $1 = "idle" | "active" | "nokey"   $2 = seconds to run
# echoes the capture-file path on stdout.
run_scenario() {
  local mode="$1" secs="$2"
  local T B C uuid parent tk
  T="$(mktemp -d)"; B="$T/bin"; C="$T/cap"; uuid="u-$mode-$$"
  mkdir -p "$B" "$T/forge-agent/active"
  cat > "$B/curl" <<SH
#!/usr/bin/env bash
prev=""; for a in "\$@"; do [ "\$prev" = "-d" ] && printf '%s\n' "\$a" >> "$C"; prev="\$a"; done; printf '200'
SH
  chmod +x "$B/curl"; : > "$C"
  [ "$mode" = active ] && touch "$T/forge-agent/active/$uuid"
  local key="k" url="https://example.test"
  [ "$mode" = nokey ] && { key=""; url=""; }
  sleep 30 & parent=$!
  PATH="$B:$PATH" HOME="$T" FORGE_KEY="$key" LAB_URL="$url" \
    HEARTBEAT_INTERVAL=1 HEARTBEAT_IDLE_KEEPALIVE_INTERVAL=1 \
    bash "$TICKER" "$uuid" "b2" "$parent" >/dev/null 2>&1 & tk=$!
  sleep "$secs"
  kill "$tk" 2>/dev/null; kill "$parent" 2>/dev/null
  wait "$tk" 2>/dev/null; wait "$parent" 2>/dev/null
  cp "$C" "$C.final"; echo "$C.final"
}

# --- 1. IDLE -> idle=true keepalive, NO bare working beat --------------------
CAP="$(run_scenario idle 3)"
grep -q '"idle":true' "$CAP" && ok "idle -> posts idle=true keepalive" || bad "idle -> idle=true (cap: $(tr '\n' '|' < "$CAP"))"
if grep '"session_uuid"' "$CAP" | grep -vq '"idle":true'; then bad "idle emitted a bare working beat (would relight amber)"; else ok "idle -> NO bare working beat (amber stays off)"; fi

# --- 2. ACTIVE -> working beat (idle omitted), never idle=true ---------------
CAP="$(run_scenario active 3)"
{ grep -q '"session_uuid"' "$CAP" && ! grep -q '"idle":true' "$CAP"; } && ok "active -> working beat, no idle flag" || bad "active beat (cap: $(tr '\n' '|' < "$CAP"))"

# --- 3. no key/url -> no POST (unchanged guard) -----------------------------
CAP="$(run_scenario nokey 2)"
[ ! -s "$CAP" ] && ok "no key/url -> no POST" || bad "no key/url -> unexpected POST"

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
