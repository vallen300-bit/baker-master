#!/bin/bash
# Brisen Lab — FORGE_HEARTBEAT_TURN_GATED_1 — mark this session's turn DONE so
# the heartbeat ticker stops beating; last_seen_at then stales and the dashboard
# extinguishes amber.
#
# DASHBOARD_CARD_SIGNAL_POLISH_1 (Part B) — on top of clearing the flag, fire a
# one-shot `idle:true` heartbeat so the backend BACKDATES last_seen_at past the
# freshness window immediately. That extinguishes amber within one dashboard poll
# (~seconds) instead of waiting out the full ~120s window (Director fix #2).
#
# Wired to Stop. Self-gates on $FORGE_TERMINAL. CONTRACT: always exit 0 — a hook
# failure must NEVER block the agent's turn. No `set -e`. Never logs FORGE_KEY.
[ -z "$FORGE_TERMINAL" ] && exit 0
INPUT=$(cat)
# printf not echo — safer for arbitrary prompt JSON (codex #1634 nit).
SID=$(printf '%s' "$INPUT" | python3 -c "import sys,json;print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)
[ -z "$SID" ] && exit 0
rm -f "$HOME/forge-agent/active/$SID" 2>/dev/null || true

# Fire-and-forget idle heartbeat → instant backend backdate. Short timeout; all
# output discarded (never the key, never the body); `|| true` so a curl failure
# can never block the turn. Only attempts when creds are present.
if [ -n "$FORGE_KEY" ] && [ -n "$LAB_URL" ]; then
  curl -s -o /dev/null --max-time 1 -X POST "$LAB_URL/api/heartbeat" \
    -H "X-Forge-Key: $FORGE_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"session_uuid\":\"$SID\",\"terminal_alias\":\"$FORGE_TERMINAL\",\"idle\":true}" \
    >/dev/null 2>&1 || true
fi
exit 0
