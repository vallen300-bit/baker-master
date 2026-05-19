#!/usr/bin/env bash
# stakeholder-authority-trigger.sh — Stop hook (Filter #1).
# Detects VIP authority assertion in assistant message; invokes Haiku validator
# via $HOME/.claude/hooks/lib/call_validator.py. Mode-aware:
#   deliberate -> block on validator BLOCK
#   light      -> write $HOME/.claude/state/pending-annotations.json (annotate-next-turn)
# Reentrancy-guarded. Degrades silently on any error.

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

PROFILES="${BRISEN_AUTHORITY_PROFILES:-$HOME/baker-vault/_ops/people/authority-profiles.yml}"
[ ! -f "$PROFILES" ] && exit 0

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

VERDICT="$(TRANSCRIPT="$TRANSCRIPT" PROFILES="$PROFILES" HOOK_DIR="$HOOK_DIR" MODE="$MODE" python3 - <<'PY' 2>/dev/null
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.environ["HOOK_DIR"], "lib"))
try:
    import yaml
    from call_validator import validate
except ImportError:
    sys.exit(0)

# Load latest assistant message text from JSONL transcript.
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

# Strip code fences + inline code (taxonomy verbs inside code blocks should not trigger).
# Backticks written as \x60 to avoid bash-parser confusion inside $(...) heredoc (Phase 1 pattern).
prose = re.sub(r"\x60\x60\x60.*?\x60\x60\x60", "", text, flags=re.DOTALL)
prose = re.sub(r"\x60[^\x60]*\x60", "", prose)

# Load authority profiles.
try:
    with open(os.environ["PROFILES"], "r", encoding="utf-8") as f:
        profiles = (yaml.safe_load(f) or {}).get("authority_profiles", {}) or {}
except Exception:
    sys.exit(0)

if not profiles:
    sys.exit(0)

# Authority-asserting verbs (case-insensitive, word-boundary). Per brief §Component 2.
AUTH_VERBS = re.compile(
    r"\b(owns?|co-?owns?|controls?|decides?|leads?|drives?|operationally|"
    r"responsible for|accountable for|signs off|approves?)\b",
    re.IGNORECASE,
)

sentences = re.split(r"(?<=[.!?])\s+", prose)

matched = None
for slug, profile in profiles.items():
    if not isinstance(profile, dict):
        continue
    names = [profile.get("canonical_name", "")] + (profile.get("aliases", []) or [])
    names = [n for n in names if n]
    if not names:
        continue
    for sent in sentences:
        for name in names:
            if re.search(r"\b" + re.escape(name) + r"\b", sent, re.IGNORECASE):
                if AUTH_VERBS.search(sent):
                    matched = (slug, profile, sent.strip())
                    break
        if matched:
            break
    if matched:
        break

if not matched:
    sys.exit(0)

slug, profile, asserted_claim = matched

# Cap 1 VIP/turn -> bounds API cost.
verdict = validate(
    skill_path=os.path.expanduser(
        "~/.claude/skills/director-facing-filter-stakeholder-validator/SKILL.md"
    ),
    context={
        "vip_canonical_name": profile.get("canonical_name", slug),
        "vip_role": profile.get("role", "unknown"),
        "vip_authority_class": profile.get("authority_class", "unknown"),
        "vip_raw_descriptions": profile.get("raw_descriptions", []),
        "asserted_claim": asserted_claim,
    },
)

if verdict.get("decision") != "block":
    sys.exit(0)

reason_text = verdict.get("reason", "(no reason)")
mode = os.environ.get("MODE", "light")

if mode == "deliberate":
    print(json.dumps({
        "action": "block",
        "reason": f"Filter #1 (stakeholder-authority): {reason_text}",
    }))
    sys.exit(0)

# Light mode -> append annotation for next-turn injection.
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
        "filter": "stakeholder-authority",
        "reason": reason_text,
        "asserted_claim": asserted_claim,
        "vip": profile.get("canonical_name", slug),
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
