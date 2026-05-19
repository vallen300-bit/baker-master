#!/usr/bin/env bash
# standing-rules-scan.sh — Stop hook (Filter #4).
# Loads standing-rules-pack.md from baker-vault, scans last_assistant_message
# for any rule violation, blocks with rule name + reason.
# Active only in deliberate mode. Reentrancy-guarded.

set -u
INPUT="$(cat 2>/dev/null || true)"

# Reentrancy guard.
ACTIVE="$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    print(json.loads(sys.stdin.read()).get("stop_hook_active", False))
except Exception:
    pass
' 2>/dev/null)"
[ "$ACTIVE" = "True" ] && exit 0

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

SIZE="$(wc -c <"$TRANSCRIPT" 2>/dev/null | tr -d ' ')"
[ -n "$SIZE" ] && [ "$SIZE" -gt 10485760 ] && exit 0

PACK="${BRISEN_STANDING_RULES_PACK:-$HOME/baker-vault/_ops/processes/standing-rules-pack.md}"
[ ! -f "$PACK" ] && exit 0

# Note: no `2>/dev/null` here — Gate-4 fix expects WARN lines on malformed
# pack entries to reach the user. Python's try/except still swallows runtime
# errors, so only the explicit sys.stderr.write calls below produce output.
WARNING="$(TRANSCRIPT="$TRANSCRIPT" PACK="$PACK" python3 - <<'PY'
import json, os, re, sys
path = os.environ["TRANSCRIPT"]
pack_path = os.environ["PACK"]
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

# Pack format: each non-blank, non-comment line = <regex>::<rule-name>::<block-reason>
# Malformed lines (too few :: fields, regex fails to compile) emit one stderr
# WARN each instead of failing silently. :: is a reserved delimiter (pack header).
violations = []
try:
    with open(pack_path, "r", encoding="utf-8", errors="replace") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("::", 2)
            if len(parts) != 3:
                sys.stderr.write(
                    "standing-rules-scan.sh WARN: " + pack_path + ":" + str(lineno) +
                    " skipped \u2014 expected <regex>::<name>::<reason>, got " +
                    str(len(parts)) + " field(s).\n"
                )
                continue
            rx, name, reason = parts
            try:
                if re.search(rx, text, re.IGNORECASE | re.MULTILINE):
                    violations.append((name, reason))
            except re.error as e:
                sys.stderr.write(
                    "standing-rules-scan.sh WARN: " + pack_path + ":" + str(lineno) +
                    " skipped \u2014 regex " + repr(rx) + " did not compile (" + str(e) + ").\n"
                )
                continue
except Exception:
    sys.exit(0)

if not violations:
    sys.exit(0)

msg_lines = ["Stop hook (Filter #4 standing-rules-scan): response violates the following standing rule(s):"]
for name, reason in violations[:5]:
    msg_lines.append(f"  - {name}: {reason}")
print("\n".join(msg_lines))
PY
)"

if [ -n "$WARNING" ]; then
    printf '%s' "$WARNING" | python3 -c '
import json, sys
print(json.dumps({"decision": "block", "reason": sys.stdin.read()}))
' 2>/dev/null
fi
exit 0
