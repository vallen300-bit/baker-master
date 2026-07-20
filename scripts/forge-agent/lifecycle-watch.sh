#!/usr/bin/env bash
# Watch the authenticated seat bus for lifecycle/restart and autosave Codex WIP.
#
# This is deliberately Codex-only. Claude/B-code seats have separate lifecycle
# and worktree ownership rules. The watcher is fire-and-forget and exits with
# its parent session.

SESSION_UUID="${1:-}"
TERMINAL_ALIAS="${2:-}"
PARENT_PID="${3:-}"
INTERVAL="${FORGE_LIFECYCLE_WATCH_INTERVAL:-5}"
DAEMON_URL="https://brisen-lab.onrender.com"
# Test-only seam. Production has no endpoint override, preventing a terminal
# key from being redirected by an inherited environment variable.
if [ -n "${FORGE_LIFECYCLE_WATCH_TEST_URL:-}" ]; then
  DAEMON_URL="$FORGE_LIFECYCLE_WATCH_TEST_URL"
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/codex-worktree.sh" 2>/dev/null || exit 0

is_codex_family "$TERMINAL_ALIAS" || exit 0
[ -n "$SESSION_UUID" ] || exit 0
[ -n "$PARENT_PID" ] || exit 0
kill -0 "$PARENT_PID" 2>/dev/null || exit 0

KEY="${BRISEN_LAB_TERMINAL_KEY:-}"
if [ -z "$KEY" ] && [ -r "$HOME/.brisen-lab/keys/$TERMINAL_ALIAS" ]; then
  KEY="$(tr -d '\r\n' < "$HOME/.brisen-lab/keys/$TERMINAL_ALIAS" 2>/dev/null || true)"
fi
[ -n "$KEY" ] || exit 0

STATE_DIR="$HOME/forge-agent/lifecycle-watch"
SEEN_FILE="$STATE_DIR/$TERMINAL_ALIAS.seen"
mkdir -p "$STATE_DIR" 2>/dev/null || exit 0
touch "$SEEN_FILE" 2>/dev/null || exit 0

_fetch_messages() {
  DAEMON_URL="$DAEMON_URL" TERMINAL_ALIAS="$TERMINAL_ALIAS" TERMINAL_KEY="$KEY" \
    python3 - <<'PY' 2>/dev/null || true
import json
import os
from urllib.request import Request, urlopen

try:
    url = "{}/msg/{}?limit=100".format(
        os.environ["DAEMON_URL"].rstrip("/"),
        os.environ["TERMINAL_ALIAS"],
    )
    request = Request(url, headers={"X-Terminal-Key": os.environ["TERMINAL_KEY"]})
    with urlopen(request, timeout=4) as response:
        payload = json.loads(response.read().decode("utf-8"))
    print(json.dumps(payload, separators=(",", ":")))
except Exception:
    pass
PY
}

_lifecycle_ids() {
  python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
rows = data.get("messages", []) if isinstance(data, dict) else data
for row in rows if isinstance(rows, list) else []:
    if isinstance(row, dict) and row.get("topic") == "lifecycle/restart" and row.get("id") is not None:
        print(str(row["id"]))
' 2>/dev/null || true
}

while kill -0 "$PARENT_PID" 2>/dev/null; do
  response="$(_fetch_messages)"
  if [ -n "$response" ]; then
    while IFS= read -r message_id; do
      [ -n "$message_id" ] || continue
      if grep -Fxq "$message_id" "$SEEN_FILE" 2>/dev/null; then
        continue
      fi
      if codex_autosave_dirty_worktrees "$TERMINAL_ALIAS"; then
        printf '%s\n' "$message_id" >> "$SEEN_FILE" 2>/dev/null || true
        tail -500 "$SEEN_FILE" > "$SEEN_FILE.tmp" 2>/dev/null \
          && mv "$SEEN_FILE.tmp" "$SEEN_FILE" 2>/dev/null || true
      fi
    done < <(printf '%s' "$response" | _lifecycle_ids)
  fi
  sleep "$INTERVAL"
done

exit 0
