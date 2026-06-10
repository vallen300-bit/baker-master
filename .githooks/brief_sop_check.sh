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
# Detect staged formal-brief files (additions + modifications; no rename/delete).
STAGED_BRIEFS="$(git diff --cached --name-only --diff-filter=AM \
    | grep -E '(^|/)(_ops/)?briefs/BRIEF_[^/]+\.md$' \
    | grep -vE '/_reports/|/_tasks/CODE_[1-5]_(PENDING|COMPLETE|DROPPED|RETURN|PARKED)' \
    || true)"

# Env-var bypass for `-m`/`-F` flows where COMMIT_EDITMSG isn't yet written
# (matches render-env-guard Part 4 pattern for the same constraint).
# HARDENED 2026-06-10 (HARNESS_V2_ADOPTION_AUDIT — silent-bypass drift on PR
# #337): env bypass leaves NO audit trace, so it is REFUSED when formal
# BRIEF_*.md files are staged. Those must use the audit-permanent
# `Brief-SOP-bypass: <reason>` commit-msg trailer (modern git >= 2.36 writes
# COMMIT_EDITMSG before pre-commit even on -m/-F, so the trailer path works).
if [ "${BAKER_BRIEF_SOP_BYPASS:-}" = "1" ]; then
    if [ -n "$STAGED_BRIEFS" ]; then
        echo "WARN [brief-sop-check]: BAKER_BRIEF_SOP_BYPASS=1 IGNORED — formal BRIEF_*.md staged; env bypass leaves no audit trace. Use commit-msg trailer: Brief-SOP-bypass: <reason>" >&2
        # fall through to the section checks below
    else
        echo "INFO [brief-sop-check]: bypass env BAKER_BRIEF_SOP_BYPASS=1 set (no formal briefs staged); allowing." >&2
        exit 0
    fi
fi

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

    # Section regexes are anchored at the start of a line + literal "## " or
    # "### " — never just "# " (H1 doesn't satisfy spec). AH2 gate-4 fold:
    # the previous `^##?` allowed the `#` count to be 1 or 2; that lets H1-only
    # briefs slip through.
    MISSING=()
    grep -qE '^## Context' <<< "$STAGED_CONTENT" || MISSING+=("Context")
    grep -qE '^(##|###) Problem' <<< "$STAGED_CONTENT" || MISSING+=("Problem")
    grep -qE '^## Files (Modified|to touch)' <<< "$STAGED_CONTENT" || MISSING+=("Files Modified")
    grep -qE '^## Verification( SQL)?' <<< "$STAGED_CONTENT" || MISSING+=("Verification")
    grep -qE '^## (Quality Checkpoints|Acceptance criteria)' <<< "$STAGED_CONTENT" || MISSING+=("Quality Checkpoints/Acceptance criteria")

    if [ ${#MISSING[@]} -ge 3 ]; then
        VIOLATIONS+=$'\n  - '"$brief_path"' — missing: '"${MISSING[*]}"
    fi

    # --- Harness V2 adoption lock (Director-ratified 2026-05-31) ---
    # Production implementation briefs must carry the Harness V2 essentials:
    # Context Contract, task class, done rubric / done-state class, gate plan.
    # Safe escape: a brief that declares `Harness-V2: N/A — <reason>` (docs-only,
    # small non-production, or research brief) skips this check. Classification is
    # author-declared via that line, NOT guessed from content — non-brittle by
    # design. Phrase-presence (case-insensitive) keeps false-blocks low; 2+ of 4
    # missing = block.
    if ! grep -qiE '^Harness-V2:[[:space:]]*N/?A' <<< "$STAGED_CONTENT"; then
        HV2_MISSING=()
        grep -qiE 'context contract' <<< "$STAGED_CONTENT" || HV2_MISSING+=("Context Contract")
        grep -qiE 'task[ _-]?class' <<< "$STAGED_CONTENT" || HV2_MISSING+=("task class")
        grep -qiE 'done[ -]?state|done rubric|required final state' <<< "$STAGED_CONTENT" || HV2_MISSING+=("done rubric/done-state class")
        grep -qiE 'gate plan' <<< "$STAGED_CONTENT" || HV2_MISSING+=("gate plan")
        if [ ${#HV2_MISSING[@]} -ge 2 ]; then
            VIOLATIONS+=$'\n  - '"$brief_path"' — Harness V2 blocks missing: '"${HV2_MISSING[*]}"' (add them, or declare `Harness-V2: N/A — <reason>`)'
        fi
    fi
done <<< "$STAGED_BRIEFS"

if [ -n "$VIOLATIONS" ]; then
    cat >&2 <<MSG
[pre-commit] BLOCKED (brief-sop-check): staged brief(s) fail the /write-brief structure check (3+ of 5 headers) and/or the Harness V2 adoption lock:$VIOLATIONS

Required SOP headers (accepts variants): Context, Problem, Files Modified (or "Files to touch"), Verification (or "Verification SQL"), Quality Checkpoints (or "Acceptance criteria").

Harness V2 essentials for production implementation briefs (Director-ratified 2026-05-31): Context Contract, task class, done rubric / done-state class, gate plan. See _ops/build/INDEX.md. Docs-only / small non-production briefs: declare \`Harness-V2: N/A — <reason>\` to skip.

Run \`/write-brief\` to regenerate, or add the missing sections.

Bypass for legitimate cases (corrections to historical briefs, archival edits):
  - Commit-msg trailer: \`Brief-SOP-bypass: <reason>\` (audit-permanent in git log) — the ONLY bypass for formal BRIEF_*.md
  - Env \`BAKER_BRIEF_SOP_BYPASS=1\` is honored only when NO formal brief is staged (hardened 2026-06-10)

Skill: ~/.claude/skills/write-brief/SKILL.md
Director directive 2026-05-23 evening.
MSG
    exit 1
fi

exit 0
