# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-21 (post-BRIDGE_HOT_MD_AND_TUNING_1 ship)
**Status:** OPEN — review coupled PR pair

---

## Task: Review the BRIDGE_HOT_MD_AND_TUNING_1 pair

**PR pair** (coupled — must merge together):
- **baker-master PR #29** — bridge code, migration, scheduler job, ship report. 9 files / +1143 / -12.
- **baker-vault PR #7** — `_ops/hot.md` scaffold.

**Shipped by:** B1
**Ship report:** `briefs/_reports/B1_bridge_hot_md_ship_20260421.md` on baker-master.
**Brief:** `briefs/BRIEF_BRIDGE_HOT_MD_AND_TUNING_1.md` at commit `2ca3865`.

Tests: **129 passed / 2 skipped (live-PG) / 0 failed** across 7 files. 67 new green:
- hot.md parser + matcher + axis-5 integration
- xact-lock serialization (incl. contention short-circuit)
- 14 new stop-list patterns + 11 regression + 5 false-positive guards
- Saturday-nudge body/env/cron shape

Pre-merge verification (lesson-#40 pattern per your N3 nit from Phase D — now part of the brief template as of this PR): recorded in the ship report. Migration clean on fresh DB, dry-run promotes a Hagenauer alert via axis 5 with `hot_md_match` populated, advisory lock short-circuits correctly, nudge wrapper uses `outputs/whatsapp_sender.py` helper with zero parallel-WAHA paths.

---

## Five flagged deviations (your call)

1. **Xact-scoped lock variant.** Brief recommended advisory lock (session-level); B1 chose xact-scoped (`pg_try_advisory_xact_lock`). Difference: xact-scoped releases automatically on COMMIT/ROLLBACK — no explicit unlock, survives exceptions cleanly. Question: does the bridge tick wrap the whole read-filter-insert cycle in a single transaction so xact-scope is sufficient? Or is there a path where the lock drops mid-work?

2. **Empty-alert commit to release lock.** Derivative of #1 — when the tick has no work, B1 still does an empty COMMIT to release the xact-scoped lock. Check: is this clean, or does it generate noise in Postgres statement logs?

3. **New `skipped_locked` counts key.** B1 added a counter for ticks that short-circuited on lock contention. Check: does the counter increment path actually fire under your contention test? Is it exposed on `/health` or just internal?

4. **Skipped bare "Adler" pattern (surname collision).** Brief listed "Adler" in the stop-list for Batch #1 #6 (German Retail: TK Maxx Replaces Adler). B1 correctly noted that "Adler" is a common surname (VIPs, counterparties) and would false-positive. B1 kept the broader pattern ("retail market update", "TK Maxx") without bare "Adler". **This is a judgment improvement over the brief — accept.** Confirm B1's implementation has a test proving a "Peter Adler" contact email doesn't get falsely stop-listed.

5. **`load_hot_md_patterns` swallows failures.** If the hot.md file is malformed or missing, B1's loader returns an empty pattern list rather than raising. Failure mode: bridge runs with no hot.md axis active (axes 1-4 + stop-list still fire). Check: is there a log line so we'd see silent degradation? Would you prefer noisy-fail (bridge tick fails loudly until hot.md is fixed) or silent-degrade (current)? My take: silent-degrade is correct for a new Director-curated file that might briefly be missing or malformed during edits, but log level should be WARNING, not INFO.

---

## Verdict focus beyond deviations

- **Migration reversibility:** `hot_md_match` column added TEXT NULL. Can be dropped cleanly if we ever roll back? Tested?
- **Axis-5 ordering vs stop-list:** stop-list override still wins (the whole point of the stop-list). Confirm axis-5 match doesn't bypass stop-list (e.g., hot.md has "scam" in it by accident → stop-list "phone scam" should still suppress).
- **Short-pattern floor:** brief required 4-char minimum. Hot.md parser enforces? Tested with 3-char pattern?
- **Saturday nudge idempotency:** if Render redeploys Saturday morning, job doesn't fire twice. APScheduler `coalesce` applied to this job?
- **Secret audit on baker-vault PR #7:** hot.md scaffold is empty-seeded with comments — zero secrets expected.

**Reviewer-separation:** B1 implemented. You did Phase D review + Phase C ship (unrelated). Clean to review.

Reports:
- baker-master PR #29: `briefs/_reports/B3_pr29_bridge_hot_md_review_20260421.md` on baker-master.
- baker-vault PR #7: `_reports/B3_pr7_hot_md_scaffold_review_20260421.md` on baker-vault.

Single combined verdict OK if the PRs are as coupled as they appear. **Both APPROVE → AI Head auto-merges both together per Tier A.**

## After this

Once merged and deployed:
- AI Head writes an initial hot.md with Director's active priorities (Tier B — AI Head proposes, Director confirms before commit).
- Day 2 teaching fires: pre-flagged Batch #2 surfaces as soon as 5-10 new signals land.
- Pipeline diagnostic (why Steps 2-7 freeze signals at triage) becomes next dispatch — you or whoever's free.

Close tab after reports shipped.
