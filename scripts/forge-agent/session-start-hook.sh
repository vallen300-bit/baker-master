#!/bin/bash
# Brisen Lab — SessionStart hook. Reads $FORGE_TERMINAL and registers this
# Claude Code session with the agent's local sessions.json + Render Lab.
#
# CONTRACT: Always exit 0 — never block claude from starting. All branches
# guarded by `|| true` / `2>/dev/null`. Do NOT add `set -e`.

if [ -z "$FORGE_TERMINAL" ]; then
  exit 0   # not a watched terminal, do nothing
fi

# Claude Code passes hook input as JSON on stdin
INPUT=$(cat)
SESSION_UUID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null)
PROJECT_PATH=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null)

if [ -z "$SESSION_UUID" ]; then
  exit 0
fi

# 1. Append to local sessions.json (atomic via temp file)
SESSIONS_FILE="$HOME/forge-agent/sessions.json"
mkdir -p "$(dirname "$SESSIONS_FILE")"
[ -f "$SESSIONS_FILE" ] || echo '{}' > "$SESSIONS_FILE"

python3 - "$SESSIONS_FILE" "$SESSION_UUID" "$FORGE_TERMINAL" <<'PY' 2>/dev/null || true
import json, sys, os, tempfile
path, uuid, alias = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f: data = json.load(f)
data[uuid] = alias
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as f: json.dump(data, f)
os.replace(tmp, path)
PY

# 2. POST to Render so dashboard renders the new session immediately
if [ -n "$FORGE_KEY" ] && [ -n "$LAB_URL" ]; then
  curl -s -X POST "$LAB_URL/api/register" \
    -H "X-Forge-Key: $FORGE_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"session_uuid\":\"$SESSION_UUID\",\"terminal_alias\":\"$FORGE_TERMINAL\",\"project_path\":\"$PROJECT_PATH\"}" \
    --max-time 5 >/dev/null 2>&1 || true
fi

# 3. FORGE_HEARTBEAT_FRESHNESS_1 — spawn the per-session heartbeat ticker,
# detached and backgrounded so it survives this hook returning but is NOT a
# zombie: it watches THIS hook's parent ($PPID = the Claude Code session
# process) and exits when that process dies. $PPID is captured now, before the
# `&` detaches the child (where its own parent would become init). Fire-and-
# forget: any failure to spawn must never block claude from starting.
CLAUDE_SESSION_PID="$PPID"
TICKER="$HOME/forge-agent/heartbeat-ticker.sh"
if [ -x "$TICKER" ] || [ -f "$TICKER" ]; then
  nohup bash "$TICKER" "$SESSION_UUID" "$FORGE_TERMINAL" "$CLAUDE_SESSION_PID" \
    >/dev/null 2>&1 &
fi

exit 0
