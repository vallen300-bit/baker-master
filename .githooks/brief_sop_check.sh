#!/usr/bin/env bash
# MIRROR OF baker-vault/.githooks/brief_sop_check.sh — keep in sync. Drift caught by test harnesses in both repos.
# canonical /write-brief structure.
#
# Director-ratified 2026-05-23 evening (AH2 bus #790 amendment to #788).
# Layer 3 of two-layer enforcement; parallel to render_env_guard pre-commit Part 4.
#
# Triggers on:
#   git diff --cached --name-only --diff-filter=AM matches
#     (briefs/BRIEF_*.md OR _ops/briefs/BRIEF_*.md OR briefs/_tasks/<slug>.md)
#   AND NOT (briefs/_reports/* OR briefs/_tasks/CODE_*_PENDING|COMPLETE|...md)
#
# Extended 2026-07-07 (AH2 HARNESS_V2_ADOPTION_AUDIT, lead #5987): the
# briefs/_tasks/<slug>.md dispatch path was hook-blind — every 2026-06-29..07-07
# production brief lived there (not the BRIEF_ prefix) and skipped this gate.
# Now covered; CODE_*_PENDING state-flips + _reports stay excluded.
#
# Extended 2026-07-21 (AH2 HARNESS_V2_ADOPTION_AUDIT 07-21, lead #14741): inline
# mailbox dispatches (briefs/_tasks/CODE_<N>_PENDING.md) were still hook-blind —
# 5/8 sampled production PRs shipped inline with no formal brief, so items 2-5
# (Context Contract, task class, done rubric, gate plan / post-deploy AC) escaped
# the gate entirely. Now the CODE_<N>_PENDING dispatch is checked for the Harness
# V2 essentials, but WARN-ONLY (never hard-blocks — an incident fix dispatched
# inline must not stall). Escalate to hard-block after a clean week by setting
# BAKER_BRIEF_SOP_INLINE_HARD_BLOCK=1 (default 0). CODE_* state-flips
# (COMPLETE/DROPPED/...) + _reports stay fully excluded.
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
# Detect staged brief files (additions + modifications; no rename/delete).
# Covers formal BRIEF_*.md + the briefs/_tasks/<slug>.md dispatch path; excludes
# the CODE_*_PENDING dispatch envelopes (state-flip mailbox files) + _reports.
STAGED_BRIEFS="$(git diff --cached --name-only --diff-filter=AM \
    | grep -E '(^|/)(_ops/)?briefs/(BRIEF_[^/]+|_tasks/[^/]+)\.md$' \
    | grep -vE '/_reports/|/_tasks/CODE_[1-5]_(PENDING|COMPLETE|DROPPED|RETURN|PARKED)' \
    || true)"

# Inline mailbox dispatches (CODE_<N>_PENDING only — the fresh-dispatch envelope;
# state-flips COMPLETE/DROPPED/RETURN/PARKED are NOT re-checked). These get the
# WARN-level Harness V2 pass below (lead #14741). Kept as a SEPARATE set so the
# formal-brief hard-block path is untouched.
STAGED_INLINE="$(git diff --cached --name-only --diff-filter=AM \
    | grep -E '(^|/)briefs/_tasks/CODE_[1-5]_PENDING\.md$' \
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
        echo "WARN [brief-sop-check]: BAKER_BRIEF_SOP_BYPASS=1 IGNORED — brief file(s) staged; env bypass leaves no audit trace. Use commit-msg trailer: Brief-SOP-bypass: <reason>" >&2
        # fall through to the section checks below
    else
        echo "INFO [brief-sop-check]: bypass env BAKER_BRIEF_SOP_BYPASS=1 set (no formal briefs staged); allowing." >&2
        exit 0
    fi
fi

[ -z "$STAGED_BRIEFS" ] && [ -z "$STAGED_INLINE" ] && exit 0

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

# --- Inline mailbox dispatch (CODE_<N>_PENDING) — Harness V2 WARN-level pass ---
# lead #14741 (deputy HARNESS_V2_ADOPTION_AUDIT 2026-07-21): inline dispatches
# escaped the gate because the trigger above excludes CODE_*_PENDING. Enforce the
# HV2 essentials here too, but WARN-ONLY on the first pass so an incident fix
# dispatched inline is never stalled. The 4th essential accepts gate plan OR
# post-deploy AC OR acceptance criteria (lead's #14741 wording folds items 5+6).
# Flip to hard-block after a clean week via BAKER_BRIEF_SOP_INLINE_HARD_BLOCK=1.
if [ -n "$STAGED_INLINE" ]; then
    INLINE_WARN=""
    while IFS= read -r inline_path; do
        [ -z "$inline_path" ] && continue
        STAGED_CONTENT="$(git show ":$inline_path" 2>/dev/null)" || continue
        # Author escape hatch, same convention as the formal path.
        grep -qiE '^Harness-V2:[[:space:]]*N/?A' <<< "$STAGED_CONTENT" && continue
        HV2_MISSING=()
        grep -qiE 'context contract' <<< "$STAGED_CONTENT" || HV2_MISSING+=("Context Contract")
        grep -qiE 'task[ _-]?class' <<< "$STAGED_CONTENT" || HV2_MISSING+=("task class")
        grep -qiE 'done[ -]?state|done rubric|required final state' <<< "$STAGED_CONTENT" || HV2_MISSING+=("done rubric/done-state class")
        grep -qiE 'gate plan|post[ -]?deploy ac|acceptance criteria' <<< "$STAGED_CONTENT" || HV2_MISSING+=("gate plan / post-deploy AC")
        if [ ${#HV2_MISSING[@]} -ge 2 ]; then
            INLINE_WARN+=$'\n  - '"$inline_path"' — Harness V2 essentials missing: '"${HV2_MISSING[*]}"
        fi
    done <<< "$STAGED_INLINE"

    if [ -n "$INLINE_WARN" ]; then
        cat >&2 <<MSG
WARN [brief-sop-check]: inline dispatch(es) missing Harness V2 essentials:$INLINE_WARN

  Add Context Contract, task class, done rubric / done-state, and gate plan / post-deploy AC,
  or declare \`Harness-V2: N/A — <reason>\`. First-pass WARN only (lead #14741) — not blocking.
MSG
        if [ "${BAKER_BRIEF_SOP_INLINE_HARD_BLOCK:-0}" = "1" ]; then
            echo "[pre-commit] BLOCKED (brief-sop-check): inline hard-block mode enabled (BAKER_BRIEF_SOP_INLINE_HARD_BLOCK=1)." >&2
            exit 1
        fi
    fi
fi

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
