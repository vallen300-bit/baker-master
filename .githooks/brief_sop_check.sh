#!/usr/bin/env bash
# MIRROR OF baker-vault/.githooks/brief_sop_check.sh — keep in sync. Drift caught by test harnesses in both repos.
# canonical /write-brief structure.
#
# Director-ratified 2026-05-23 evening (AH2 bus #790 amendment to #788).
# Layer 3 of two-layer enforcement; parallel to render_env_guard pre-commit Part 4.
#
# Triggers on:
#   git diff --cached --name-only --diff-filter=AM matches
#     (briefs/BRIEF_*.md OR _ops/briefs/BRIEF_*.md)
#   AND NOT (briefs/_reports/* OR briefs/_tasks/CODE_*_PENDING|COMPLETE|...md)
#
# Blocks if 3+ of 5 canonical SOP section headers are missing in the staged
# content:
#   1. ## Context
#   2. ## Problem  (or ### Problem inside a ## Fix/Feature block)
#   3. ## Files Modified  (or ## Files to touch)
#   4. ## Verification  (or ## Verification SQL)
#   5. ## Quality Checkpoints  (or ## Acceptance criteria)
#
# Bypass: commit-msg trailer `Brief-SOP-bypass: <reason>`. Audit-permanent in
# git log. DIFFERENT bypass from Layer 2 (env var) BY DESIGN — Layer 3 is
# git-time + auditable-forever.
#
# Stage: pre-commit (chained from .githooks/pre-commit orchestrator in vault;
# Part 5 in baker-master pre-commit).
#
# Must complete <1s for the common case (no LLM, regex-only).

set -u
trap 'echo "WARN [brief-sop-check]: hook errored unexpectedly, failing open" >&2; exit 0' ERR

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$REPO_ROOT" || exit 0

# Bypass via commit-msg trailer — read COMMIT_EDITMSG if present.
# Note: pre-commit fires BEFORE git writes COMMIT_EDITMSG for `-m`/`-F` flows
# on some git versions, so the env override below is the practical path for
# those flows. Modern git (≥ 2.36) does write COMMIT_EDITMSG before pre-commit
# for `-m`/`-F`; older versions don't.
COMMIT_MSG_FILE=".git/COMMIT_EDITMSG"
if [ -f "$COMMIT_MSG_FILE" ]; then
    if grep -qE '^Brief-SOP-bypass:' "$COMMIT_MSG_FILE" 2>/dev/null; then
        REASON="$(grep -E '^Brief-SOP-bypass:' "$COMMIT_MSG_FILE" | head -1 | sed 's/^Brief-SOP-bypass:[[:space:]]*//')"
        echo "INFO [brief-sop-check]: bypass via commit trailer ($REASON); allowing." >&2
        exit 0
    fi
fi
# Env-var bypass for `-m`/`-F` flows where COMMIT_EDITMSG isn't yet written
# (matches render-env-guard Part 4 pattern for the same constraint).
if [ "${BAKER_BRIEF_SOP_BYPASS:-}" = "1" ]; then
    echo "INFO [brief-sop-check]: bypass env BAKER_BRIEF_SOP_BYPASS=1 set; allowing." >&2
    exit 0
fi

# Detect staged formal-brief files (additions + modifications; no rename/delete).
STAGED_BRIEFS="$(git diff --cached --name-only --diff-filter=AM \
    | grep -E '(^|/)(_ops/)?briefs/BRIEF_[^/]+\.md$' \
    | grep -vE '/_reports/|/_tasks/CODE_[1-5]_(PENDING|COMPLETE|DROPPED|RETURN|PARKED)' \
    || true)"

[ -z "$STAGED_BRIEFS" ] && exit 0

# For each staged brief, scan staged content for required section headers.
# 3+ missing of 5 = block. Required headers (accept variant headings):
#   1. Context  — `^## Context`
#   2. Problem  — `^## Problem` OR `^### Problem` (inside a Fix/Feature block)
#   3. Files Modified  — `^## Files Modified` OR `^## Files to touch`
#   4. Verification  — `^## Verification` OR `^## Verification SQL`
#   5. Quality Checkpoints  — `^## Quality Checkpoints` OR `^## Acceptance criteria`

VIOLATIONS=""

while IFS= read -r brief_path; do
    [ -z "$brief_path" ] && continue
    # Get staged content (not on-disk — `git show :path` reads staged blob)
    STAGED_CONTENT="$(git show ":$brief_path" 2>/dev/null)" || continue

    MISSING=()
    grep -qE '^##? Context' <<< "$STAGED_CONTENT" || MISSING+=("Context")
    grep -qE '^(##|###) Problem' <<< "$STAGED_CONTENT" || MISSING+=("Problem")
    grep -qE '^## Files (Modified|to touch)' <<< "$STAGED_CONTENT" || MISSING+=("Files Modified")
    grep -qE '^## Verification( SQL)?' <<< "$STAGED_CONTENT" || MISSING+=("Verification")
    grep -qE '^## (Quality Checkpoints|Acceptance criteria)' <<< "$STAGED_CONTENT" || MISSING+=("Quality Checkpoints/Acceptance criteria")

    if [ ${#MISSING[@]} -ge 3 ]; then
        VIOLATIONS+=$'\n  - '"$brief_path"' — missing: '"${MISSING[*]}"
    fi
done <<< "$STAGED_BRIEFS"

if [ -n "$VIOLATIONS" ]; then
    cat >&2 <<MSG
[pre-commit] BLOCKED (brief-sop-check): staged brief(s) lack 3+ of 5 canonical /write-brief section headers:$VIOLATIONS

Required (accepts variants): Context, Problem, Files Modified (or "Files to touch"), Verification (or "Verification SQL"), Quality Checkpoints (or "Acceptance criteria").

Run \`/write-brief\` to regenerate, or add the missing sections.

Bypass for legitimate cases (corrections to historical briefs, archival edits):
  - Commit-msg trailer: \`Brief-SOP-bypass: <reason>\` (audit-permanent in git log)
  - Env (for \`-m\`/\`-F\` flows): \`BAKER_BRIEF_SOP_BYPASS=1 git commit -m "..."\`

Skill: ~/.claude/skills/write-brief/SKILL.md
Director directive 2026-05-23 evening.
MSG
    exit 1
fi

exit 0
