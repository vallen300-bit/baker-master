#!/usr/bin/env bash
# Stop hook: warn when assistant's final response claims completion / pass /
# ship but contains no explicit verification phrase.
#
# Canonical source: tests/fixtures/fail-loud-check.sh in baker-master.
# Deployed as user-global at ~/.claude/hooks/fail-loud-check.sh.
# Drift detectable via:
#   diff ~/.claude/hooks/fail-loud-check.sh tests/fixtures/fail-loud-check.sh
#
# Contract (revised 2026-05-12 Director-authorized — token economy fix):
# - On violation: emit valid Stop-hook JSON `{"decision":"block","reason":...}`.
#   Blocks the Stop event + feeds `reason` back to model so it rewrites WITH
#   an explicit verification phrase (or removes the unverified claim).
# - On pass: emit nothing. Exit 0. Zero context-window cost.
# - Schema-invalid `hookSpecificOutput.additionalContext` removed (Stop hooks
#   don't support that field — Claude Code rejected with a 30-line error block
#   on every Stop, ~250 tokens × N turns of pure noise).
# - Trigger tightened (same revision): "completed" / "done" / "shipped" /
#   "merged" removed from claim_words — those are routine status updates, not
#   pass-claims. Only "tests pass" / "all green" still fire fail-loud.
# - ≤4s wall time. Skip transcript walk if file >10MB.
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
# Trigger ONLY on testing/CI pass-claims. Removed (2026-05-12 Director-authorized):
# "completed", "done", "shipped", "merged" — those are routine status updates,
# not assertions about test outcomes; firing on them produced false-positives on
# every ship/merge turn and would cascade into token-multiplying rewrites under
# the new block-on-violation contract.
claim_words = ("tests pass", "all green", "all tests pass", "tests passed")
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
print(json.dumps({"decision": "block", "reason": text}))
' 2>/dev/null || true
fi

exit 0
