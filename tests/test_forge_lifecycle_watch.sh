#!/usr/bin/env bash
# SWEEP_TIMING_ACTIVE_WORK_GUARD_1 — lifecycle restart autosave proof.
# Uses a fake authenticated bus response and a real temporary Git worktree.

set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WATCHER="$REPO/scripts/forge-agent/lifecycle-watch.sh"
PASS=0
FAIL=0
ok() { PASS=$((PASS+1)); printf 'ok   - %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf 'FAIL - %s\n' "$1"; }

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/worktrees/wip"
git -C "$T/worktrees/wip" init -q
git -C "$T/worktrees/wip" config user.name "forge-test"
git -C "$T/worktrees/wip" config user.email "forge-test@example.test"
printf 'base\n' > "$T/worktrees/wip/README"
git -C "$T/worktrees/wip" add README
git -C "$T/worktrees/wip" commit -q -m base
printf 'uncommitted\n' >> "$T/worktrees/wip/README"
printf 'untracked\n' > "$T/worktrees/wip/WIP.txt"

cat > "$T/server.py" <<'PY'
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

port_file = Path(sys.argv[1])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"messages": [{"id": 901, "topic": "lifecycle/restart"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
port_file.write_text(str(server.server_port))
server.serve_forever()
PY
python3 "$T/server.py" "$T/port" >/dev/null 2>&1 &
SERVER="$!"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -s "$T/port" ] && break
  sleep 0.1
done
PORT="$(cat "$T/port")"

sleep 4 &
PARENT="$!"
HOME="$T" \
BRISEN_LAB_TERMINAL_KEY="test-key" \
FORGE_LIFECYCLE_WATCH_TEST_URL="http://127.0.0.1:$PORT" \
FORGE_CODEX_WORKTREE_ROOTS="$T/worktrees" \
FORGE_LIFECYCLE_WATCH_INTERVAL=1 \
FORGE_AUTOSAVE_DIR="$T/autosave" \
FORGE_AUTOSAVE_LOG="$T/autosave.log" \
  bash "$WATCHER" session-1 deputy-codex "$PARENT" >/dev/null 2>&1 &
WATCHER_PID="$!"
sleep 3
kill "$WATCHER_PID" "$SERVER" 2>/dev/null || true
wait "$WATCHER_PID" 2>/dev/null || true
wait "$PARENT" 2>/dev/null || true
wait "$SERVER" 2>/dev/null || true

if [ -n "$(git -C "$T/worktrees/wip" status --porcelain --untracked-files=normal)" ]; then
  ok "lifecycle/restart leaves live worktree untouched"
else
  bad "lifecycle/restart mutated live worktree"
fi
if git -C "$T/worktrees/wip" for-each-ref --format='%(refname)' refs/wip/autosave-* | grep -q .; then
  ok "autosave creates refs/wip/autosave-*"
else
  bad "autosave ref missing"
fi
if find "$T/autosave" -name '*.tar.gz' -print -quit 2>/dev/null | grep -q .; then
  ok "autosave archives untracked WIP"
else
  bad "untracked WIP archive missing"
fi
if grep -q 'alias=deputy-codex' "$T/autosave.log" 2>/dev/null; then
  ok "autosave writes bounded audit line"
else
  bad "autosave audit line missing"
fi

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
