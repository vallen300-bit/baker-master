#!/usr/bin/env bash
# SessionStart hook: emit per-role context block based on $BAKER_ROLE,
# wrapped in the additionalContext JSON envelope so Claude Code injects it
# into the session's system prompt area.
#
# CONTRACT: Always exit 0 — never block claude from starting. Drain stdin
# (Claude passes session metadata as JSON; we don't need it but must not SIGPIPE).
#
# Resolution order:
#   1. $BAKER_ROLE env var (set by macOS Terminal profile)
#   2. cwd-based fallback (~/bm-b<N> -> b<N>; otherwise unknown)
#
# If no role can be resolved, emit a one-line nudge as additionalContext so
# Director sees the gap inside the session itself.

# Drain stdin (claude passes JSON; we don't consume it, just absorb it).
cat >/dev/null 2>&1 || true

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ROLE="${BAKER_ROLE:-}"

if [ -z "$ROLE" ]; then
  case "$REPO_ROOT" in
    */bm-aihead1|*/bm-aihead1/.claude/worktrees/*) ROLE="aihead1" ;;
    */bm-aihead2|*/bm-aihead2/.claude/worktrees/*) ROLE="aihead2" ;;
    */bm-b1|*/bm-b1/.claude/worktrees/*) ROLE="b1" ;;
    */bm-b2|*/bm-b2/.claude/worktrees/*) ROLE="b2" ;;
    */bm-b3|*/bm-b3/.claude/worktrees/*) ROLE="b3" ;;
    */bm-b4|*/bm-b4/.claude/worktrees/*) ROLE="b4" ;;
    */bm-b5|*/bm-b5/.claude/worktrees/*) ROLE="b5" ;;
    *)      ROLE="" ;;
  esac
fi

# Helper: emit a JSON envelope with the given text as additionalContext.
# Uses python3 to handle JSON escaping safely (newlines, quotes, etc.).
_emit() {
  python3 -c '
import json, sys
text = sys.stdin.read()
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
' 2>/dev/null || true
}

if [ -z "$ROLE" ]; then
  _emit <<'EOF'
[role-onboard] BAKER_ROLE env var not set and cwd not under bm-b<N>. Cannot auto-onboard role.
Director: set BAKER_ROLE in this terminal profile (Terminal → Settings → Profiles → "Run command: export BAKER_ROLE=<role>"). Valid values: aihead1, aihead2, b1, b2, b3, b4, b5 (case-insensitive; file lookup is lowercased).
Until set, paste the role identity manually as before.
EOF
  exit 0
fi

ROLE_LC="$(echo "$ROLE" | tr '[:upper:]' '[:lower:]')"

# WORKER_SELFWAKE_PHASE_1: write wake.lock for interactive picker sessions on
# b1-b4 so the launchd worker (com.baker.worker-bN) skips its wake cycle while
# this interactive session is open. Lock holds parent claude PID ($PPID); the
# worker auto-cleans the lock when that PID dies (session close) or after its
# 15-min stale-TTL, whichever comes first. b5 / aiheads ignored (no Phase 1 worker).
case "$ROLE_LC" in
  b1|b2|b3|b4)
    _wake_lock_dir="$HOME/Library/Application Support/baker/worker-$ROLE_LC"
    if [ -d "$_wake_lock_dir" ]; then
      python3 - "$_wake_lock_dir/wake.lock" 2>/dev/null <<'PY' || true
import json, os, sys, time
try:
    with open(sys.argv[1], "w") as f:
        f.write(json.dumps({
            "pid": int(os.environ.get("PPID") or os.getppid()),
            "start_ts": time.time(),
            "source": "interactive-picker",
        }))
except Exception:
    pass
PY
    fi
    ;;
esac

CTX_FILE="$REPO_ROOT/.claude/role-context/${ROLE_LC}.md"

if [ ! -f "$CTX_FILE" ]; then
  printf '[role-onboard] BAKER_ROLE=%s but no context file at %s. No injection this session.\n' "$ROLE" "$CTX_FILE" \
    | _emit
  exit 0
fi

_emit < "$CTX_FILE"
exit 0
