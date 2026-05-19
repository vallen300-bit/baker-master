#!/usr/bin/env bash
# authority-profile-preload.sh — UserPromptSubmit hook (ADD-ON #2).
# Scans user message for VIP names from authority-profiles.yml; injects compact
# profile block into agent context via hookSpecificOutput.additionalContext.
#
# Caps at 3 VIPs / turn (cost bound). ~50-150 tokens per matched VIP.

set -u
INPUT="$(cat 2>/dev/null || true)"
PROFILES="$HOME/baker-vault/_ops/people/authority-profiles.yml"
[ ! -f "$PROFILES" ] && exit 0  # profiles not yet built → no-op

INJECTION="$(PROFILES="$PROFILES" INPUT_JSON="$INPUT" python3 - <<'PY' 2>/dev/null
import json, sys, os, re
try:
    import yaml
except ImportError:
    sys.exit(0)
try:
    d = json.loads(os.environ.get("INPUT_JSON", "") or "{}")
    user_text = d.get("user_message", "") or d.get("prompt", "")
except Exception:
    sys.exit(0)
if not user_text:
    sys.exit(0)
try:
    profiles = (yaml.safe_load(open(os.environ["PROFILES"])) or {}).get("authority_profiles", {})
except Exception:
    sys.exit(0)

# Match any alias or canonical name (case-insensitive, word-boundary).
matched = []
for slug, p in profiles.items():
    if not isinstance(p, dict):
        continue
    names = [p.get("canonical_name", "")] + list(p.get("aliases", []) or [])
    for name in names:
        if name and re.search(r'\b' + re.escape(name) + r'\b', user_text, re.IGNORECASE):
            matched.append((slug, p))
            break
    if len(matched) >= 3:
        break

if not matched:
    sys.exit(0)

lines = ["AUTHORITY PROFILES (auto-loaded from authority-profiles.yml):"]
for slug, p in matched:
    lines.append(f"- {p.get('canonical_name', slug)} ({slug}): {p.get('role', 'unknown role')} · authority_class={p.get('authority_class', 'unknown')}")
    for raw in (p.get("raw_descriptions", []) or [])[:1]:
        lines.append(f"  source ({raw.get('desk', '?')}): {raw.get('text', '')}")
text = "\n".join(lines)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}, ensure_ascii=False))
PY
)"

if [ -n "$INJECTION" ]; then
    printf '%s' "$INJECTION"
fi
exit 0
