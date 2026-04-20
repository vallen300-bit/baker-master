# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-20 (midday, two PRs waiting)
**Status:** OPEN — two reviews queued

---

## Status

**Two PRs waiting on your review. Recommended order: helper v2 first, then Phase B.**

### PR 1 (now, smaller): `LESSONS_GREP_HELPER_V2` — PR #26 on baker-master

B3 shipped head `ad62130` on branch `lessons-grep-helper-v2`. 80 LOC exactly + new synthetic tests file. B3 flagged TWO deviations from the brief spec:

**Deviation A — PR #24 regression.** Brief expected top-5 to include lessons #37 + #39. v2 ranks #26 + #24 instead. B3's argument: those are semantically more apt for dead-sensor retirement anyway; the regression is caused by the `+`-only filter per spec. You decide: accept deviation (brief-accurate interpretation) or require v1 ranking back (would require softening `+`-filter, contradicting brief rationale).

**Deviation B — heuristic swap.** Brief specified "fallback iff highest < 2× lowest." B3 swapped for "fallback iff positive_hits ≥ 80% of total lessons." Reason: IDF weighting collapses the score ratio; PR #22 real signal at 1.88× would falsely fallback under brief's rule. Coverage-based rule sidesteps that.

Both are defensible. Your call.

**Verdict focus:**
- N1 `--repo` + `LESSONS_FILE` work? (v1 silently swallowed `--repo`, scoring wrong repo's PR)
- N2 `+`-only filter + IDF weighting landed correctly?
- Regression check holds across all 4 of B3's smoke tests (baker-vault PR #3 fallback, PR #21→#42, PR #22→#37, PR #24→#37+#39 OR accepted deviation)
- 4/4 synthetic tests pass

Report to `briefs/_reports/B2_pr26_review_<YYYYMMDD>.md`. APPROVE / REDIRECT / REQUEST_CHANGES. AI Head auto-merges on APPROVE.

Expected: 15-20 min with your new template.

### PR 2 (after helper v2): `SOT_OBSIDIAN_UNIFICATION_1 Phase B` — PR #4 on baker-vault

B1 shipped head `0174b3e` on branch `sot-obsidian-1-phase-b`. 12 files (8 new + 4 modified). AI Dennis migration + memory split + sync_skills.sh real logic + 3 process docs + 2 Dropbox duplicates retired.

**Use your new template + helper v2** (once merged from PR 1) for this review — this is the first real use of v2 under cross-repo load.

**Verdict focus (from brief §Fix/Feature 2):**
- AI Dennis SKILL.md canonical at `_ops/skills/it-manager/` (zero diff vs March 5 source)
- Memory split: OPERATING ≤80 lines (B1 reports 34), LONGTERM ≤200 (117), ARCHIVE append-only (29) — all within budgets
- `sync_skills.sh` real logic + safe-skip on non-empty non-symlink runtime
- 3 process docs present (write-brief.md, bank-model.md, git-mailbox.md)
- TEMPLATE.md demoted to pointer (B1's choice — confirm acceptable)
- 2 Dropbox duplicates renamed `.retired-2026-04-20` with RETIRED banner (not `rm`)
- `AI_DENNIS_MEMORY.md` intentionally preserved (brief flagged as Phase B1, not this phase — confirm brief matches)
- Live runtime symlink flip deferred to post-merge manual step (window-of-risk — confirm brief §Key Constraints matches)

Report to `_reports/B2_sot_phase_b_review_<YYYYMMDD>.md` on baker-vault main. APPROVE / REDIRECT / REQUEST_CHANGES.

Expected: 25-35 min.

### After both approve

AI Head auto-merges each. Post-Phase-B merge, AI Head executes the live runtime symlink flip (Tier B — requires your heads-up in your review report whether the mechanical flip is safe to automate vs. needs Director eyes).

Phase C unblocks for B3 after Phase B merges. Bridge brief (ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1) is in flight with B1 in parallel — you'll have that to review next.
