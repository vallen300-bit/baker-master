#!/usr/bin/env bash
# annotate-pending-checker.sh — UserPromptSubmit hook.
# Reads $HOME/.claude/state/pending-annotations.json; surfaces entries that
# belong to THIS session (Gate-3 HIGH #2: session-scoped filter; lenient on
# legacy entries lacking session_id so old queue items still surface once)
# + foreign-session entries are preserved in-file for their owning session
# to consume. Implements "annotate-on-next-turn" for light-mode Filter #1+#3.
#
# Drain ordering (Gate-3 HIGH #1): file is rewritten (drop-or-clear) BEFORE
# the injection is printed, so a failed printf still leaves the queue in a
# valid post-consume state. Atomic write via tempfile + mv (Deputy LOW #6).

set -u

# Drain stdin (we do not use it but Claude Code expects consumption).
cat >/dev/null 2>&1

PENDING="$HOME/.claude/state/pending-annotations.json"
[ ! -f "$PENDING" ] && exit 0

# Compute (a) the injection text from "ours" and (b) the JSON to write back
# (entries belonging to OTHER sessions, preserved). Python emits both
# separated by a sentinel so bash can split.
RESULT="$(PENDING="$PENDING" python3 - <<'PY' 2>/dev/null
import json
import os
import sys

path = os.environ["PENDING"]
try:
    with open(path, "r", encoding="utf-8") as f:
        annotations = json.load(f)
except Exception:
    sys.exit(0)

if not isinstance(annotations, list):
    sys.exit(0)

current_session = os.environ.get("CLAUDE_SESSION_ID", "")

ours, theirs = [], []
for a in annotations:
    if not isinstance(a, dict):
        continue
    entry_session = a.get("session_id", "")
    # Lenient: entry with missing/blank session_id is treated as ours
    # (legacy entries from older hook version, or pre-CLAUDE_SESSION_ID env).
    if not entry_session or entry_session == current_session:
        ours.append(a)
    else:
        theirs.append(a)

# Build injection text (only emit if at least one entry surfaces beyond header).
injection = ""
if ours:
    lines = ["LIGHT-MODE FILTER ANNOTATIONS (from prior turn, defer-blocked):"]
    for a in ours[:5]:
        filt = a.get("filter", "unknown")
        reason = a.get("reason", "(no reason)")
        lines.append(f"- [{filt}] {reason}")
        claim = a.get("asserted_claim", "")
        if claim:
            lines.append(f"  source claim: \"{claim[:200]}\"")
    if len(lines) > 1:
        text = "\n".join(lines)
        injection = json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": text,
            }
        })

# Emit both pieces with a sentinel separator. Bash splits below.
print("---REWRITE---")
print(json.dumps(theirs))
print("---INJECTION---")
print(injection)
PY
)"

if [ -z "$RESULT" ]; then
    exit 0
fi

# Split python output into rewrite payload + injection.
REWRITE="$(printf '%s' "$RESULT" | awk '/^---REWRITE---$/{flag=1;next}/^---INJECTION---$/{flag=0}flag')"
INJECTION="$(printf '%s' "$RESULT" | awk '/^---INJECTION---$/{flag=1;next}flag' | sed -e :a -e '/^$/{$d;N;ba' -e '}')"

# Drain-first: atomic write of remaining (foreign-session) entries BEFORE
# any printf. Failed printf below still leaves queue consistent.
if [ -n "$REWRITE" ]; then
    TMP="${PENDING}.tmp.$$"
    printf '%s' "$REWRITE" > "$TMP" && mv -f "$TMP" "$PENDING"
fi

if [ -n "$INJECTION" ]; then
    printf '%s' "$INJECTION"
fi
exit 0
