# CODE_3_QUEUED — B3: AMEX_RECURRING_DEADLINE_1 — 2026-04-26 (next-up)

**Dispatcher:** AI Head B (Build-reviewer, M2 lane)
**Trigger to promote:** B3 mailbox flips COMPLETE on GOLD_COMMENT_WORKFLOW_1 PR merge
**Brief (already drafted):** `briefs/BRIEF_AMEX_RECURRING_DEADLINE_1.md` (commit `820fa9a`)
**Status:** STAGED — promote to CODE_3_PENDING.md when GOLD ships
**Trigger class:** **MEDIUM** (DB migration on `deadlines` table + 4 new columns) → B1 second-pair-of-eyes review per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`. Builder ≠ B1.

---

## Pre-promotion notes

**Director Q-resolutions (already locked):**
- Q1 (recurrence types): monthly / weekly / quarterly / annual — V1; cron in V2
- Q2 (AmEx anchor): **3rd of every month** (Director RA-21 2026-04-26 PM)
- Q3 (UX): both — checkbox at creation + dashboard "make recurring" action
- Q4 (other recurring candidates): **deferred to acceptance-test phase** — post-AmEx Triaga survey for Director tick

**B-code dependencies cleared:**
- ✅ Brief at `briefs/BRIEF_AMEX_RECURRING_DEADLINE_1.md`
- ✅ Q-resolutions in brief §4 + §11
- ✅ Trigger-class flagged
- ✅ Acceptance test scoped: AmEx (#1438) → recurrence=monthly + anchor_date=2026-05-03 + verify spawn on mark_completed

## Pattern C lane note

Per RA-21 Pattern C orchestration 2026-04-26 PM: M1 lane = AI Head A (PR #65/#64 merge cycles), M2 lane = AI Head B (this dispatcher). AMEX is M2-natural. GOLD ships first, AMEX second on same B-code (B3) per natural sequencing.

## Promotion procedure (when triggered)

When B3 mailbox flips COMPLETE on GOLD ship:

1. AI Head B reads `briefs/_staging/CODE_3_QUEUED.md` (this file)
2. Verifies brief at `briefs/BRIEF_AMEX_RECURRING_DEADLINE_1.md` still consistent
3. Overwrites `briefs/_tasks/CODE_3_PENDING.md` with new dispatch text (§2 busy-check, §3 hygiene, ship-gate template — same shape as GOLD dispatch above in the chain)
4. Commits + pushes
5. Wake-pastes B3
6. Removes this `_staging/CODE_3_QUEUED.md` file in same commit

## Out of scope at promote-time

- NO re-drafting AMEX brief (Rule 0 lapse from earlier session noted in ARCHIVE Session 3; brief content is acceptable per spec; if Director instructs full re-draft via /write-brief, do that first)
- NO change to Q-resolutions
- NO inclusion of cron expressions (V2 per Q1 default)
- NO inclusion of holiday/business-day adjustments (V2)
- NO calendar integration (out of scope per brief §6)

---

**Authority:** Director RA-21 2026-04-26 PM ("Q2 RESOLVED: anchor_date = 3rd of every month") + Director default-fallback ("Your 3 question — you default. I skip") + RA-21 reroute ("M2 = your natural lane").
