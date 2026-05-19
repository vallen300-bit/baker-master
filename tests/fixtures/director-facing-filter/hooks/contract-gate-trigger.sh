#!/usr/bin/env bash
# contract-gate-trigger.sh — Stop hook (Filter #3).
# Detects >=4 enumerated options/paths in assistant message; checks for
# feasibility tags inline OR in $HOME/.claude/state/feasibility-tags.json
# (agent pre-tagged + fresh <5 min).
# If untagged + deliberate -> invoke contract-validator -> block on missing tags.
# If untagged + light      -> annotate-next-turn.
# Reentrancy-guarded.

set -u
INPUT="$(cat 2>/dev/null || true)"

ACTIVE="$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    print(json.loads(sys.stdin.read()).get("stop_hook_active", False))
except Exception:
    pass
' 2>/dev/null)"
[ "$ACTIVE" = "True" ] && exit 0

TRANSCRIPT="$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    print(json.loads(sys.stdin.read()).get("transcript_path", ""))
except Exception:
    pass
' 2>/dev/null)"
[ -z "$TRANSCRIPT" ] && exit 0
[ ! -f "$TRANSCRIPT" ] && exit 0

SIZE="$(wc -c <"$TRANSCRIPT" 2>/dev/null | tr -d ' ')"
[ -n "$SIZE" ] && [ "$SIZE" -gt 10485760 ] && exit 0

MODE_FILE="$HOME/.claude/state/brisen-filter-mode"
MODE="$(cat "$MODE_FILE" 2>/dev/null || echo light)"
HOOK_DIR="$HOME/.claude/hooks"

VERDICT="$(TRANSCRIPT="$TRANSCRIPT" HOOK_DIR="$HOOK_DIR" MODE="$MODE" python3 - <<'PY' 2>/dev/null
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.environ["HOOK_DIR"], "lib"))
try:
    from call_validator import validate
except ImportError:
    sys.exit(0)

path = os.environ["TRANSCRIPT"]
try:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
except Exception:
    sys.exit(0)

text = ""
for line in reversed(lines):
    try:
        t = json.loads(line)
    except Exception:
        continue
    if t.get("type") != "assistant":
        continue
    msg = t.get("message", {}) or {}
    content = msg.get("content", []) or []
    if isinstance(content, list):
        text = "\n".join(
            c.get("text", "")
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
    elif isinstance(content, str):
        text = content
    break

if not text.strip():
    sys.exit(0)

# Strip code fences (Phase 1 pattern: \x60 to avoid bash backtick confusion).
prose = re.sub(r"\x60\x60\x60.*?\x60\x60\x60", "", text, flags=re.DOTALL)

# Trigger: >=4 enumerated items.
items = re.findall(r"^\s*(?:\d+\.|[-*])\s+(\S.{5,200})", prose, flags=re.MULTILINE)
if len(items) < 4:
    sys.exit(0)

# Need options-vocab nearby (a numbered status summary should not fire).
OPTIONS_VOCAB = re.compile(
    r"\b(option|path|move|alternative|choice|route|approach|model|scenario)s?\b",
    re.IGNORECASE,
)
if not OPTIONS_VOCAB.search(prose):
    sys.exit(0)

# Inline-tag bypass: every option already tagged.
TAG_VOCAB = re.compile(
    r"\b(unilateral|consent[- ]required|amendment[- ]required|"
    r"breach[- ]required|litigation|timeline|feasibility:)\b",
    re.IGNORECASE,
)
tag_count = len(TAG_VOCAB.findall(prose))
if tag_count >= len(items):
    sys.exit(0)

# Evidence-file bypass: agent pre-tagged.
ev_file = os.path.expanduser("~/.claude/state/feasibility-tags.json")
ALLOWED_TAGS = {
    "unilateral",
    "consent-required",
    "amendment-required",
    "breach-required",
    "litigation",
    "timeline",
}
if os.path.isfile(ev_file):
    try:
        ev_age = time.time() - os.path.getmtime(ev_file)
        if ev_age < 300:
            with open(ev_file, "r", encoding="utf-8") as f:
                ev = json.load(f)
            ev_options = ev.get("options", []) if isinstance(ev, dict) else []
            tagged = [
                o
                for o in ev_options
                if isinstance(o, dict) and o.get("feasibility") in ALLOWED_TAGS
            ]
            if len(tagged) >= len(items):
                sys.exit(0)
    except Exception:
        pass

# Trigger fires -> call validator.
verdict = validate(
    skill_path=os.path.expanduser(
        "~/.claude/skills/director-facing-filter-contract-validator/SKILL.md"
    ),
    context={
        "options_count": len(items),
        "options_preview": items[:6],
        "full_message": prose[:4000],
    },
)

if verdict.get("decision") != "block":
    sys.exit(0)

reason_text = verdict.get("reason", "(no reason)")
mode = os.environ.get("MODE", "light")

if mode == "deliberate":
    print(json.dumps({
        "action": "block",
        "reason": f"Filter #3 (contract-gate): {reason_text}",
    }))
    sys.exit(0)

# Light mode -> annotation queue.
state_dir = os.path.expanduser("~/.claude/state")
try:
    os.makedirs(state_dir, exist_ok=True)
    pending_file = os.path.join(state_dir, "pending-annotations.json")
    if os.path.isfile(pending_file):
        try:
            with open(pending_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    else:
        existing = []
    existing.append({
        "filter": "contract-gate",
        "reason": reason_text,
        "options_count": len(items),
        "added_at": datetime.datetime.utcnow().isoformat() + "Z",
    })
    with open(pending_file, "w", encoding="utf-8") as f:
        json.dump(existing, f)
except Exception:
    pass
PY
)"

ACTION="$(printf '%s' "$VERDICT" | python3 -c '
import json, sys
try:
    print(json.loads(sys.stdin.read()).get("action", ""))
except Exception:
    pass
' 2>/dev/null)"

if [ "$ACTION" = "block" ]; then
    printf '%s' "$VERDICT" | python3 -c '
import json, sys
try:
    payload = json.loads(sys.stdin.read())
    print(json.dumps({"decision": "block", "reason": payload.get("reason", "")}))
except Exception:
    pass
' 2>/dev/null
fi
exit 0
