#!/bin/bash
# Brisen Lab — FORGE_HEARTBEAT_TURN_GATED_1 — mark this session's turn ACTIVE so
# the heartbeat ticker beats (amber = actively working, incl reasoning).
#
# Wired to UserPromptSubmit. Self-gates on $FORGE_TERMINAL (genuine no-op for
# non-watched lead/AH/Director sessions). CONTRACT: always exit 0 — a hook
# failure must NEVER block the agent's turn. No `set -e`.
[ -z "$FORGE_TERMINAL" ] && exit 0
INPUT=$(cat)
# printf not echo — safer for arbitrary prompt JSON (codex #1634 nit).
SID=$(printf '%s' "$INPUT" | python3 -c "import sys,json;print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)
[ -z "$SID" ] && exit 0
mkdir -p "$HOME/forge-agent/active" 2>/dev/null || true
: > "$HOME/forge-agent/active/$SID" 2>/dev/null || true

# Fire-and-forget working heartbeat -> dashboard can turn amber immediately,
# without waiting up to the ticker's 45s polling interval. Short timeout; all
# output discarded (never the key, never the body); `|| true` so a curl failure
# can never block the turn. Only attempts when creds are present.
if [ -n "$FORGE_KEY" ] && [ -n "$LAB_URL" ]; then
  curl -s -o /dev/null --max-time 1 -X POST "$LAB_URL/api/heartbeat" \
    -H "X-Forge-Key: $FORGE_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"session_uuid\":\"$SID\",\"terminal_alias\":\"$FORGE_TERMINAL\"}" \
    >/dev/null 2>&1 || true
fi
exit 0
