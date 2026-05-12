#!/usr/bin/env bash
# Stop hook: warn when assistant's final response asks a question or presents
# options but contains no `Recommendation:` line.
#
# Canonical source: tests/fixtures/recommendation-check.sh in baker-master.
# Deployed as user-global at ~/.claude/hooks/recommendation-check.sh.
# Drift detectable via:
#   diff ~/.claude/hooks/recommendation-check.sh tests/fixtures/recommendation-check.sh
#
# Contract (revised 2026-05-12 Director-authorized — token economy fix):
# - On violation: emit valid Stop-hook JSON `{"decision":"block","reason":...}`.
#   Blocks the Stop event + feeds `reason` back to model so it rewrites WITH
#   the Recommendation line. Costs +1 turn per violation, but the rewrite is
#   itself terse and the hook stops firing once Recommendation is present.
# - On pass: emit nothing. Exit 0. Zero context-window cost.
# - Schema-invalid `hookSpecificOutput.additionalContext` removed (Stop hooks
#   don't support that field — Claude Code rejected with a 30-line error block
#   on every Stop, ~250 tokens × N turns of pure noise).
# - ≤4s wall time. Skip transcript walk if file >10MB. Errors stay silent.
#
# Anchor: project CLAUDE.md HARD RULE 2 — every multi-option / multi-Q reply
# ends with explicit Recommendation. Mnilax (May 2026): hooks lift compliance
# from ~80% to ~100% on mechanically-checkable rules.

# Read stop-event JSON from stdin.
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

# Skip if transcript >10MB (degrade gracefully).
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

has_question = "?" in text
has_numbered = bool(re.search(r"^\s*\d+\.", text, flags=re.MULTILINE))
lower = text.lower()
has_option_word = any(w in lower for w in ("options", "choose", "which"))
trigger = has_question or has_numbered or has_option_word
if not trigger:
    sys.exit(0)

has_rec = bool(re.search(r"^\s*\**\s*recommendation\s*:", text, flags=re.MULTILINE | re.IGNORECASE))
if has_rec:
    sys.exit(0)

print("Stop-hook: assistant response asks a question or presents options but contains no \"Recommendation:\" line. Per project CLAUDE.md HARD RULE 2, every multi-option / multi-Q reply ends with explicit Recommendation.")
' 2>/dev/null)"

if [ -n "$WARNING" ]; then
    printf '%s' "$WARNING" | python3 -c '
import json, sys
text = sys.stdin.read()
print(json.dumps({"decision": "block", "reason": text}))
' 2>/dev/null || true
fi

exit 0
