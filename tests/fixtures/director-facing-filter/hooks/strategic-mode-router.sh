#!/usr/bin/env bash
# strategic-mode-router.sh — UserPromptSubmit hook (Filter #5).
# Detects deliberate-mode trigger keywords in user's latest prompt, writes mode
# state to ~/.claude/state/brisen-filter-mode for downstream Stop hooks.
#
# Modes:
#   deliberate — block on filter violations
#   light      — annotate (Phase 2) or skip (Phase 1)
#
# Default mode = light. Deliberate mode triggered by keyword.
# Brainstorm trigger keywords (per director-comm-lint.py:53-60) auto-OVERRIDE to light.

set -u
INPUT="$(cat 2>/dev/null || true)"

USER_TEXT="$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    # UserPromptSubmit payload has user_message or prompt field
    print(d.get("user_message", "") or d.get("prompt", ""))
except Exception:
    pass
' 2>/dev/null)"

mkdir -p "$HOME/.claude/state"

# Brainstorm override → light (matches director-comm-lint.py BRAINSTORM_TRIGGERS).
# Brainstorm always wins over deliberate per Rule 4 of director-comm-rules.md.
if echo "$USER_TEXT" | grep -qiE '\b(brainstorm|thinking out loud|free[- ]form|talk freely|explore with me|let'"'"'s explore)\b'; then
    echo "light" > "$HOME/.claude/state/brisen-filter-mode"
    exit 0
fi

# Deliberate triggers
if echo "$USER_TEXT" | grep -qiE '\b(strategy|strategic|take|purpose|achieve|factor|hinge|big picture|big-picture|frame|framework)\b'; then
    echo "deliberate" > "$HOME/.claude/state/brisen-filter-mode"
    exit 0
fi

# Default → light
echo "light" > "$HOME/.claude/state/brisen-filter-mode"
exit 0
