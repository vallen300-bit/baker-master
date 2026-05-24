#!/usr/bin/env bash
# write_brief_sop_enforcer.sh — PreToolUse hook blocking Write/Edit on brief
# paths unless /write-brief skill was invoked in the current session.
#
# Director-ratified 2026-05-23 evening (AH2 bus #788).
# Pattern parallels ~/bm-aihead1/.claude/hooks/ui-surface-prebrief-check.sh.
#
# Stage: PreToolUse (Write | Edit | MultiEdit)
# Exit codes:
#   0 — pass / not applicable / malformed input (FAIL-OPEN)
#   2 — block; stderr surfaced to Claude as error context
#
# Fail-open posture: ANY internal error → exit 0 + stderr warning.
# Gate-logic bugs must NEVER block legitimate tool use.
#
# Bypass: env BAKER_BRIEF_SOP_BYPASS=1 (logged to stderr with timestamp + file_path).

set -u
trap 'echo "WARN [write-brief-sop-enforcer]: hook errored unexpectedly, failing open" >&2; exit 0' ERR

PAYLOAD="$(cat)"

# Validate JSON; fail-open if malformed.
if ! printf '%s' "$PAYLOAD" | jq -e . >/dev/null 2>&1; then
    echo "WARN [write-brief-sop-enforcer]: malformed JSON on stdin, failing open" >&2
    exit 0
fi

TOOL="$(printf '%s' "$PAYLOAD" | jq -r '.tool_name // empty')"
case "$TOOL" in
    Write|Edit|MultiEdit) ;;
    *) exit 0 ;;
esac

FILE_PATH="$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.file_path // empty')"
[ -z "$FILE_PATH" ] && exit 0

# Path filter: anchor on `(_ops/)?briefs/BRIEF_<name>.md` (at any directory depth).
# Excludes: briefs/_reports/* (B-code ship reports) and briefs/_tasks/CODE_*_PENDING.md
# (dispatch envelopes — AH1 edits directly, not via /write-brief).
if printf '%s' "$FILE_PATH" | grep -qE '/_reports/|/_tasks/CODE_[1-5]_(PENDING|COMPLETE|DROPPED|RETURN|PARKED)'; then
    exit 0
fi
if ! printf '%s' "$FILE_PATH" | grep -qE '(^|/)(_ops/)?briefs/BRIEF_[^/]+\.md$'; then
    exit 0
fi

# Bypass check — env BAKER_BRIEF_SOP_BYPASS=1. Logged for audit.
if [ "${BAKER_BRIEF_SOP_BYPASS:-}" = "1" ]; then
    printf 'INFO [write-brief-sop-enforcer]: bypass env set (BAKER_BRIEF_SOP_BYPASS=1); allowing write to %s at %s\n' \
        "$FILE_PATH" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
    exit 0
fi

TRANSCRIPT_PATH="$(printf '%s' "$PAYLOAD" | jq -r '.transcript_path // empty')"

# If no transcript_path, FAIL-OPEN with warning (skill-internal hook fires may
# lack transcript context; brief-time false-blocks are worse than false-passes).
if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
    echo "WARN [write-brief-sop-enforcer]: transcript_path missing or unreadable, failing open" >&2
    exit 0
fi

# Scan transcript JSONL for a `Skill` tool_use event with skill="write-brief".
# Each JSONL line is a complete JSON message; -s slurps the array.
# NOTE: Do NOT use `-e` here. Under our `set -u + trap ERR` posture, a `-e`-
# triggered non-zero exit from jq inside $(...) trips the ERR trap and the
# hook fails open silently — which would defeat the gate. Plain `-s` exits 0
# with stdout "true" or "false", which we then string-compare. Verified by
# Layer 2 test case 1 (no-skill blocks); regression caught the silent-bypass
# bug at first run.
SKILL_INVOKED="$(jq -s '
    map(select(
        .type == "assistant" and
        ((.message.content // []) | any(
            .type == "tool_use" and
            .name == "Skill" and
            (.input.skill // "") == "write-brief"
        ))
    )) | length > 0
' "$TRANSCRIPT_PATH" 2>/dev/null || echo "false")"

if [ "$SKILL_INVOKED" = "true" ]; then
    exit 0
fi

# Skill not invoked — block.
cat >&2 <<'MSG'
BLOCKED by write-brief-sop-enforcer: Write/Edit to a brief path requires the `/write-brief` skill to be invoked first in this session.

Run: Skill(skill="write-brief") and walk through the 6 SOP steps (EXPLORE → PLAN → WRITE → REVIEW → PRESENT → CAPTURE LESSONS).

Bypass for legitimate non-authoring edits (typo fix, status update, link refresh): set env `BAKER_BRIEF_SOP_BYPASS=1` before the tool call. Bypass usage is logged to stderr for audit.

Skill location: ~/.claude/skills/write-brief/SKILL.md
Director directive 2026-05-23 evening.
MSG
exit 2
