#!/usr/bin/env bash
# synthesis-vs-taxonomy.sh — Stop hook (Filter #2).
# Blocks last_assistant_message if it contains ≥4 enumerated items AND no
# synthesis marker. Active only in deliberate mode. Reentrancy-guarded.

set -u
INPUT="$(cat 2>/dev/null || true)"

# Reentrancy guard — skip if hook-induced rewrite turn.
ACTIVE="$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    print(json.loads(sys.stdin.read()).get("stop_hook_active", False))
except Exception:
    pass
' 2>/dev/null)"
[ "$ACTIVE" = "True" ] && exit 0

# Mode guard — block only in deliberate.
MODE_FILE="$HOME/.claude/state/brisen-filter-mode"
[ ! -f "$MODE_FILE" ] && exit 0
[ "$(cat "$MODE_FILE" 2>/dev/null)" != "deliberate" ] && exit 0

TRANSCRIPT="$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    print(json.loads(sys.stdin.read()).get("transcript_path", ""))
except Exception:
    pass
' 2>/dev/null)"
[ -z "$TRANSCRIPT" ] && exit 0
[ ! -f "$TRANSCRIPT" ] && exit 0

# Skip if transcript >10MB (degrade gracefully, mirrors recommendation-check.sh).
SIZE="$(wc -c <"$TRANSCRIPT" 2>/dev/null | tr -d ' ')"
[ -n "$SIZE" ] && [ "$SIZE" -gt 10485760 ] && exit 0

PACK="$HOME/.claude/hooks/packs/synthesis-markers.txt"  # deployed alongside hook

WARNING="$(TRANSCRIPT="$TRANSCRIPT" PACK="$PACK" python3 - <<'PY' 2>/dev/null
import json, os, re, sys
path = os.environ["TRANSCRIPT"]
pack = os.environ.get("PACK", "")
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
        text = "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    elif isinstance(content, str):
        text = content
    break

if not text.strip():
    sys.exit(0)

# Strip code fences + inline code (mirrors recommendation-check.sh pattern).
# Backticks written as \x60 to avoid bash-parser confusion inside $(...) heredoc.
prose = re.sub(r"\x60\x60\x60.*?\x60\x60\x60", "", text, flags=re.DOTALL)
prose = re.sub(r"\x60[^\x60]*\x60", "", prose)

# Count enumerated items (numbered OR bulleted).
items = re.findall(r"^\s*(?:\d+\.|[-*])\s+\S", prose, flags=re.MULTILINE)
if len(items) < 4:
    sys.exit(0)

# Load synthesis-marker pack (fallback to inline defaults if absent).
markers = []
if pack and os.path.isfile(pack):
    try:
        markers = [l.strip().lower() for l in open(pack) if l.strip() and not l.lstrip().startswith("#")]
    except Exception:
        markers = []
if not markers:
    markers = [
        "recommendation:", "priority:", "i recommend", "the answer is",
        "rank:", "pick:", "collapse:", "bottom line:",
    ]

lower = prose.lower()
if any(m in lower for m in markers):
    sys.exit(0)

print(
    f"Stop hook (Filter #2 synthesis-vs-taxonomy): response presents {len(items)} "
    "enumerated items but no synthesis marker (recommendation / priority / rank / "
    "collapse / bottom line). Per director-facing-filter-v1 in deliberate mode, "
    "collapse the list into a ranked recommendation before sending."
)
PY
)"

if [ -n "$WARNING" ]; then
    printf '%s' "$WARNING" | python3 -c '
import json, sys
print(json.dumps({"decision": "block", "reason": sys.stdin.read()}))
' 2>/dev/null
fi
exit 0
