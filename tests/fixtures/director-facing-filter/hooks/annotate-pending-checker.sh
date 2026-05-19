#!/usr/bin/env bash
# annotate-pending-checker.sh — UserPromptSubmit hook.
# Reads $HOME/.claude/state/pending-annotations.json; if any pending, injects
# them via additionalContext + clears file. Implements "annotate-on-next-turn"
# for light-mode filter triggers (Filter #1 + #3).

set -u

# Drain stdin (we do not use it but Claude Code expects consumption).
cat >/dev/null 2>&1

PENDING="$HOME/.claude/state/pending-annotations.json"
[ ! -f "$PENDING" ] && exit 0

OUTPUT="$(PENDING="$PENDING" python3 - <<'PY' 2>/dev/null
import json
import os
import sys

path = os.environ["PENDING"]
try:
    with open(path, "r", encoding="utf-8") as f:
        annotations = json.load(f)
except Exception:
    sys.exit(0)

if not isinstance(annotations, list) or not annotations:
    sys.exit(0)

lines = ["LIGHT-MODE FILTER ANNOTATIONS (from prior turn, defer-blocked):"]
for a in annotations[:5]:
    if not isinstance(a, dict):
        continue
    filt = a.get("filter", "unknown")
    reason = a.get("reason", "(no reason)")
    lines.append(f"- [{filt}] {reason}")
    claim = a.get("asserted_claim", "")
    if claim:
        lines.append(f"  source claim: \"{claim[:200]}\"")
if len(lines) == 1:
    sys.exit(0)

text = "\n".join(lines)
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": text,
    }
}))
PY
)"

# Clear pending file regardless of whether injection produced output —
# malformed entries should not stick around either.
echo "[]" > "$PENDING"

if [ -n "$OUTPUT" ]; then
    printf '%s' "$OUTPUT"
fi
exit 0
