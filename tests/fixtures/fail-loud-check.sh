#!/usr/bin/env bash
# Stop hook: warn when assistant's final response claims completion / pass /
# ship but contains no explicit verification phrase.
#
# Canonical source: tests/fixtures/fail-loud-check.sh in baker-master.
# Deployed as user-global at ~/.claude/hooks/fail-loud-check.sh.
# Drift detectable via:
#   diff ~/.claude/hooks/fail-loud-check.sh tests/fixtures/fail-loud-check.sh
#
# Contract: never block. Exit 0 on every path. ≤4s wall time. Skip transcript
# walk if file >10MB.
#
# Anchor: project CLAUDE.md ENGINEERING RULES Fail-loud — surface uncertainty,
# don't hide it. "Completed" is wrong if anything was skipped silently.

INPUT="$(cat 2>/dev/null || true)"

TRANSCRIPT="$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    p = d.get("transcript_path", "")
    if isinstance(p, str):
        print(p)
except Exception:
    pass
' 2>/dev/null)"

[ -z "$TRANSCRIPT" ] && exit 0
[ ! -f "$TRANSCRIPT" ] && exit 0

SIZE="$(wc -c <"$TRANSCRIPT" 2>/dev/null | tr -d ' ')"
[ -n "$SIZE" ] && [ "$SIZE" -gt 10485760 ] && exit 0

WARNING="$(TRANSCRIPT="$TRANSCRIPT" python3 -c '
import json, os, re, sys

path = os.environ["TRANSCRIPT"]
text = ""
try:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    for line in reversed(lines):
        try:
            turn = json.loads(line)
        except Exception:
            continue
        if turn.get("type") != "assistant":
            continue
        msg = turn.get("message") or {}
        content = msg.get("content") or []
        parts = []
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(c.get("text", ""))
        elif isinstance(content, str):
            parts.append(content)
        text = "\n".join(parts)
        break
except Exception:
    sys.exit(0)

if not text.strip():
    sys.exit(0)

lower = text.lower()
claim_words = ("completed", "done", "tests pass", "shipped", "merged", "all green")
trigger = any(w in lower for w in claim_words)
if not trigger:
    sys.exit(0)

verification_patterns = [
    r"\d+\s+skipped",
    r"\bverified\b",
    r"\bliteral\b",
    r"\b0\s+fail",
    r"no edge case missed",
]
if any(re.search(p, lower) for p in verification_patterns):
    sys.exit(0)

print("Stop-hook: assistant response claims completion / pass / ship but contains no explicit verification phrase. Per project CLAUDE.md ENGINEERING RULES Fail-loud, surface uncertainty rather than hiding it.")
' 2>/dev/null)"

if [ -n "$WARNING" ]; then
    printf '%s' "$WARNING" | python3 -c '
import json, sys
text = sys.stdin.read()
print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": text}}))
' 2>/dev/null || true
fi

exit 0
