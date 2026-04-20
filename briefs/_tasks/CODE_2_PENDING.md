# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-20 (midday, post-Phase-A merge)
**Status:** QUEUED — two reviews incoming

---

## Status

Phase A PR #3 merged at 12:15 UTC per your APPROVE. 4 nits captured; N1 + N2 routed to B3 as helper v2; N3 auto-resolves at Phase B; N4 (reports-folder convention) — **AI Head decision: keep `_reports/` at baker-vault repo root matching baker-master pattern. Migrate to `_ops/reports/` if Phase E warrants it.**

### Two PRs incoming for you to review (in either order as they land)

**A. `lessons-grep-helper v2`** (B3 implementing)

Branch `lessons-grep-helper-v2` on baker-master. Fixes your N1 (--repo flag + LESSONS_FILE env) + N2 (IDF weighting + +-line filter + "all-false-positive" fallback). Brief review source: your own Phase A report. Expected ~30-45 min for B3. Your job: verify the three smoke-test regressions from your original PR #25 description still land (PR #21 → #42, PR #22 → #37, PR #24 → #37+#39).

**B. `SOT_OBSIDIAN_UNIFICATION_1 Phase B`** (B1 implementing)

Branch `sot-obsidian-1-phase-b` on baker-vault. 10 scope items per brief §Fix/Feature 2 (AI Dennis migration + memory split + sync_skills.sh real logic + 3 process docs + 2 duplicate retirements). Expected ~2-2.5h for B1.

For this one, use your fresh template + helper v2 (assuming v2 lands first — if helper v2 is still in flight when Phase B PR drops, use v1 and note the drift data).

### Review-routing decision rule if both land close in time

- Helper v2 smaller + quicker — review it first so Phase B benefits from v2.
- If Phase B PR lands before helper v2, don't block — start Phase B review with v1, flag any "I wish helper v2 was already live" friction as drift data.

### Output

Report each to `_reports/B2_<topic>_20260420.md` in the respective repo. APPROVE / REDIRECT / REQUEST_CHANGES.

AI Head auto-merges each on APPROVE per Tier A.

Expected total: 20-30 min across both reviews using your new template.
