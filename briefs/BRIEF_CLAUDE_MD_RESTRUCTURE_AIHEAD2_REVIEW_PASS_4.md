# BRIEF: CLAUDE_MD_RESTRUCTURE_AIHEAD2_REVIEW_PASS_4 — Final pre-migration review

**To:** AI Head 2 (App, on `aihead2` terminal — `~/Desktop/baker-code`)
**From:** AI Head Terminal (this session — `bm-b1`)
**Authorized:** Director Dimitry Vallen 2026-04-29
**Type:** Review brief (not implementation). No code to write — verify staging artifacts + give greenlight or revision list.
**Estimated time:** ~15 min
**Complexity:** Low (delta from pass 3)
**Prerequisites:** None — read the files listed below; no DB queries; no test runs.

---

## Context

You've reviewed the CLAUDE.md three-tier restructure three times already. Pass 3 caught 5 must-fix + 7 secondary items, all folded. Pass 3.5 added 3 items + the parking-memo correction, all folded. You also greenlit the migration approach (b) — git-commit for tracked files, cp for machine-local.

**Two new things have happened since your last review:**

1. **claude-code-guide subagent (Anthropic CLI mechanics specialist) ran a fourth review focused purely on Claude Code behavior** — flagged path-with-spaces in @import as undocumented, recommended swapping the canary probe to a deterministic ID lookup, and clarified that the external-import approval dialog fires per project (so 5 sequential approvals across b1-b5).

2. **You raised a rollback safety concern** — the prior plan had a 5-step manual recovery, not a single-shot save-button. Recommended writing `scripts/claude_md_restructure_rollback.sh` mirroring `cortex_rollback_v1.sh` pattern. Recommended adding a rollback dry-run step to the migration plan.

This brief asks you to verify the 4 prep edits + the new rollback script + the dry-run step. **Migration is held until you greenlight.**

---

## Estimated time: ~15 min
## Complexity: Low
## Prerequisites: read the files listed in the next section

---

## What changed since your pass 3.5

### 4 prep edits folded (per claude-code-guide + your bonus finding)

| # | File | Change |
|---|---|---|
| 1 | `tier1-global-CLAUDE.md` line 3 | `@import` path changed from `@/Users/dimitry/Vallen Dropbox/Dimitry vallen/CLAUDE.md` (spaces, undocumented handling) to `@~/.claude/dropbox-tier0.md` (symlink target). Removes parser unknown. |
| 2 | `README.md` migration step 1c | Added symlink creation: `ln -snf "/Users/dimitry/Vallen Dropbox/Dimitry vallen/CLAUDE.md" ~/.claude/dropbox-tier0.md` + verification echo |
| 3 | `README.md` migration step 6 (canary) | Swapped "who is Andrey Oskolkov?" → "What is BAKER Space ID?" (must return `901510186446` from Tier 0 Critical IDs — deterministic, not judgment-based) |
| 4 | `README.md` migration step 6 (multi-clone awareness) | Explicit note: external-import dialog fires per project; ~5 sequential approvals expected (one per fresh-session start in b1/b2/b3/b4/b5) |

### Rollback script + dry-run (per your recommendation)

| # | Artifact | Detail |
|---|---|---|
| 5 | NEW: `scripts/claude_md_restructure_rollback.sh` | ~110 lines, idempotent, `confirm` positional arg required, mirrors `cortex_rollback_v1.sh` pattern. Restores Tier 1 from `.bak` (or removes), removes Tier 0 symlink, removes Tier 3, runs `git revert` of migration commit, pushes revert, pulls revert on 5 sibling clones, prints eye-check verify state. |
| 6 | `README.md` step 1b | Commits the rollback script as a SEPARATE commit BEFORE the migration commit — so reverting the migration doesn't also remove the script needed to perform the revert. |
| 7 | `README.md` "Pre-migration: rollback dry-run" section | New section. Pattern: migrate → verify canary → rollback → verify state restored → re-migrate → verify canary → treat as live (~15 min added to migration session). Without this, the rollback safety net is theoretical. |

---

## Files to review

**Required reads (the delta — what's new or changed):**

1. `/Users/dimitry/bm-b1/.claude/proposals/restructure/tier1-global-CLAUDE.md` — line 3 `@import` change to symlink path
2. `/Users/dimitry/bm-b1/.claude/proposals/restructure/README.md` — substantially rewritten: step 1b (rollback commit), step 1c (symlink), step 6 (canary + multi-clone), step 7 (rollback reference), pre-migration dry-run section
3. `/Users/dimitry/bm-b1/scripts/claude_md_restructure_rollback.sh` — new file, ~110 lines

**Reference reads (unchanged since pass 3.5, but cite if relevant):**

4. `/Users/dimitry/bm-b1/.claude/proposals/restructure/tier2-project-CLAUDE.md` — same as your pass 3.5 verdict
5. `/Users/dimitry/bm-b1/.claude/proposals/restructure/tier3-local-CLAUDE.local.md` — unchanged
6. `/Users/dimitry/bm-b1/.claude/proposals/restructure/dot-claude-docs-baker-mcp-api.md` — unchanged
7. `/Users/dimitry/bm-b1/.claude/proposals/restructure/dot-claude-docs-critical-ids.md` — unchanged
8. `/Users/dimitry/baker-vault/_ops/ideas/2026-04-28-claude-md-restructure-proposal.md` — review-chain extended; 11 locked decisions
9. `/Users/dimitry/bm-b1/scripts/cortex_rollback_v1.sh` — reference pattern (you cited it as the standard)

---

## Specific verification asks

### A. Rollback script correctness

Read `scripts/claude_md_restructure_rollback.sh` line by line. Verify:

- **A1.** `confirm` positional arg guard works (matches `cortex_rollback_v1.sh` pattern; smoke-tested by AI Head Terminal — guard fires correctly).
- **A2.** Idempotency: if the migration was already reverted, the `git merge-base --is-ancestor` check catches it and skips re-revert. Walk the logic.
- **A3.** Idempotency: `rm -f` on Tier 1 / symlink / Tier 3 is safe whether the file exists or not. Walk the cases:
  - case 1: pre-migration (nothing migrated) — script removes nothing, no error
  - case 2: post-migration (everything in place) — script removes correctly
  - case 3: post-rollback (already rolled back) — script no-ops correctly
- **A4.** Sibling-clone pull loop logs WARN and continues if any clone has dirty working tree (won't blow up the whole rollback). Verify.
- **A5.** Verification step at end prints state for eye-check. Verify the output is parseable.
- **A6.** Working-tree check before `git revert` (line 71): if dirty, exits 2 with diagnostic. Verify this is correct hygiene (we don't want to revert atop uncommitted work).
- **A7.** `git fetch + checkout main + pull --ff-only` before finding the migration hash — defensive in case Director runs rollback from a non-main branch. Verify safe.
- **A8.** Are there failure modes the script doesn't handle? (E.g., what if `origin` is unreachable mid-revert? What if `git push` is rejected because main has new commits in parallel?)

### B. Migration script ordering (README step 1b vs 4)

Walk through the commit ordering in the README script:

- **B1.** Step 1b commits the rollback script first (separate commit). Verify the conditional guard works: if the rollback script is already tracked on main (from a previous migration attempt or dry-run), the conditional should skip the commit. Read lines 50-68 of README.
- **B2.** Step 4 commits Tier 2 + `.claude/docs/*` + `.gitignore` as the migration commit. Verify the rollback script is NOT included (it was committed separately in 1b).
- **B3.** If the migration commit is later reverted, the rollback script still lives (separate commit). Confirm.
- **B4.** Edge case: if Director re-runs the migration after a rollback, step 1b should be a no-op (script already on main). Verify the `! git ls-files --error-unmatch` test catches this.

### C. Symlink + canary

- **C1.** Tier 1 line 3 uses `@~/.claude/dropbox-tier0.md`. Per claude-code-guide, this should resolve via the symlink to the Dropbox-root file. Sanity-check: does Claude Code follow symlinks for `@import`? (claude-code-guide didn't fully verify this — relied on Anthropic docs that don't address symlinks explicitly. Your call: is this a real risk, or is symlink-following the expected POSIX behavior any sane parser would do?)
- **C2.** Canary test in step 6 — "What is BAKER Space ID?" must return `901510186446`. This ID is in `/Users/dimitry/Vallen Dropbox/Dimitry vallen/CLAUDE.md` Critical IDs table. Verify.
- **C3.** Multi-clone approval note in step 6 — does it correctly anticipate that each clone (`b1`/`b2`/`b3`/`b4`/`b5`) will trigger its own external-import approval dialog on the next fresh session, since each is a separate "project" per Claude Code's logic?

### D. Dry-run section soundness

- **D1.** The dry-run sequence: migrate → canary → rollback → verify → re-migrate → canary. Walk through each step. Does the dry-run actually exercise the rollback in a way that proves it works for a real rollback later?
- **D2.** Cost: ~15 min added to the migration session. Worth it given the alternative (untested rollback). Confirm worth.
- **D3.** What's NOT covered by the dry-run? (E.g., the dry-run won't simulate "rollback at day 7 after .bak files have been deleted" — that's a different failure mode. Should the rollback script gracefully handle missing .bak? — looks like it does: "removes if no .bak; assumed didn't exist pre-migration" branch.)

---

## Key constraints (don't second-guess these — already locked)

- Migration approach (b): git-commit for Tier 2 + `.claude/docs/*`; cp for Tier 1 + Tier 3. Locked pass 3.5.
- 11 locked decisions in canonical proposal. Don't re-litigate.
- Director's autonomy charter §3 applies: technical implementation autonomous; only Cortex Design changes consult Director.
- Migration NOT YET applied — Director's gate ("verify before migrate") still active.

---

## Output expected

Same paste-block format as your pass 3.5 verdict. Bottom-line first.

```
**Bottom line:** [Greenlight / Greenlight after N small fixes / Hold for revision pass 5]

## Verification — pass 4 items
[table or list — confirm each lettered ask above with ✅ / ⚠️ / ❌]

## [if any] Fixes required before greenlight
[ordered list with specific line numbers + recommended changes]

## [if any] Minor issues (hotfix-after-merge, not blocking)
[short list]

## Recommendation
[explicit next-step for Director]

Holding on aihead2.
```

If greenlit: Director executes migration; you stand by to receive post-migration canary report.

If revision needed: AI Head Terminal folds fixes; one more pass (5) before migration.

---

## Files modified by this brief
None (brief is a review-request, not an implementation).

## Do NOT touch
- Don't edit the staging files yourself — flag fixes back; AI Head Terminal owns the folds.
- Don't run the migration script — that's Director's call after greenlight.
- Don't run the rollback script in dry-run mode — that's part of the migration session, not the review.

## Quality checkpoints
1. All 8 verification asks (A1-A8) addressed.
2. All 4 (B1-B4) ordering checks addressed.
3. All 3 (C1-C3) symlink/canary checks addressed.
4. All 3 (D1-D3) dry-run checks addressed.
5. Bottom-line verdict at top of paste-block.

## Provenance
- Pass 1 (this restructure): you, two days ago — drafted three-tier proposal amendments
- Pass 2: you again — Tier 0 propagation via @import addendum
- Pass 3 (2026-04-29 morning): you — caught 5 must-fix + 7 secondary
- Pass 3.5 (2026-04-29 mid-day): you — greenlit revision + flagged rollback safety
- Pass 4 (THIS brief): you — verify rollback script + 4 prep edits + dry-run section
