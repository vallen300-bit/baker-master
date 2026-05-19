#!/usr/bin/env bash
# pre-send-checklist.sh — UserPromptSubmit hook (ADD-ON #3).
# In deliberate mode, injects 3-question checklist into agent context.
# No-op in light mode. ~50 tokens / turn cost.

set -u
MODE_FILE="$HOME/.claude/state/brisen-filter-mode"

# Drain stdin (UserPromptSubmit payload — we don't need it but Claude Code expects us to consume it).
cat >/dev/null 2>&1

[ ! -f "$MODE_FILE" ] && exit 0
MODE="$(cat "$MODE_FILE" 2>/dev/null)"
[ "$MODE" != "deliberate" ] && exit 0

python3 - <<'PY' 2>/dev/null
import json
checklist = (
    "PRE-SEND CHECKLIST (deliberate mode active): before sending your next reply, "
    "ensure you can answer (1) Who has decision authority on this? "
    "(2) What's contractually feasible? (3) What's your recommendation?"
)
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": checklist,
    }
}))
PY
exit 0
