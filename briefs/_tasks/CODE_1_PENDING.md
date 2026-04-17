# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous task:** R1 review on KBL-A brief — complete, report filed in chat (pre-report-mailbox; from next review onwards, file reports per `briefs/_reports/README.md`)
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution

---

## Task: R2 Narrow-Scope Re-Review on KBL-A v2

### Target

**File:** `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md`
**Commit:** `4efca68`
**URL:** https://github.com/vallen300-bit/978-baker-master/blob/main/briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md

(Correct URL: https://github.com/vallen300-bit/baker-master/blob/main/briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md)

### Scope — NARROW (not a full re-read)

V2 is a revision of v1, not a new brief. Focus R2 **only** on:

**(a) Verify all 6 R1 blockers are actually resolved.** One-by-one check:

| R1 Blocker | Expected V2 Fix Location | What to verify |
|---|---|---|
| B1 started_at column | §5 schema additions | `ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ` present |
| B2 "NOW()" literal | §8 pipeline_tick + anywhere qwen_active_since is set | No literal `"NOW()"` strings stored; uses `datetime.now(timezone.utc).isoformat()` |
| B3 __main__ dispatchers | §9 gold_drain.py end + §12 logging.py end | Both files have `if __name__ == "__main__":` blocks with argv parsing |
| B4 Gold push failure rollback | §9 gold_drain.py drain_queue restructure | Commit+push BEFORE PG row marking; push failure triggers `git checkout` rollback + rows stay pending |
| B5 FileHandler import safety | §12 logging.py module top | try/except around FileHandler creation; NullHandler+stderr fallback |
| B6 Price-key normalizer | §11 cost.py | `_model_key()` function exists, called in both estimate_cost + log_cost_actual |

**(b) Spot-check the 10 should-fixes applied.** Not exhaustive — sample 3-4 randomly and verify they landed as described in the "R1 Review Response Log" section.

**(c) Verify no NEW blockers introduced.** The v2 delta is ~400 lines. Skim for:
- Broken references (function/class/file names that don't exist elsewhere in the brief)
- Logic bugs in new code (especially the Gold drain rollback path — easy to get subtly wrong)
- Schema changes that miss the `_ensure_*` ordering invariant

**(d) Confirm B2 schema reconciliation adoption.** §5 should adopt B2's inline FK form (auto-named), match `briefs/_drafts/KBL_A_SCHEMA.sql` v3 at commit `8782813`.

### Do NOT

- Re-open should-fixes that were deferred (S6 = separate doc fix, already pushed; S11 = Phase 2; N1-N4 = mostly absorbed/deferred)
- Re-open architectural decisions (those are ratified in `DECISIONS_PRE_KBL_A_V2.md`)
- Full 1407-line re-read (v2 delta only)

### Output structure

Same format as R1. Pass criteria:

| Result | Next step |
|---|---|
| 0 blockers | Director ratifies KBL-A → dispatch to implementation |
| 1-2 blockers | Fast v3 revision |
| ≥3 blockers | Stop — something in v2 regressed, diagnose |

### File your report per the new pattern

Per `briefs/_reports/README.md`, file substantive reports to `briefs/_reports/`:

Expected path: `briefs/_reports/B1_kbl_a_r2_review_20260417.md`

Header should reference this task file commit:
```
Re: briefs/_tasks/CODE_1_PENDING.md commit <SHA when you read this>
```

Chat one-liner when filed:
```
Report at briefs/_reports/B1_kbl_a_r2_review_20260417.md, commit <SHA>.
TL;DR: <X> blockers, <Y> should-fix, verdict <pass|v3|restructure>.
```

### Time budget

**20-30 minutes** (narrower scope than R1's 48 min). If you find yourself reading the whole brief, you've drifted from narrow scope — stop and refocus.

### Parallel context (informational)

- Code Brisen #2 standing by with no pending task. Will be asked for further work post-ratification or if R2 surfaces blockers.
- Decisions doc updated (separate commit) for R1.S6 env var name drift — non-behavioral fix.
- Director's D1 eval-labeling session still pending — independent critical path, not blocking R2 or KBL-A ratification.

---

*Task posted by AI Head 2026-04-17. Previous report: Code Brisen #1 R1 review (delivered in chat, 48 min, 6B/12S/4N/4M — pre-report-mailbox pattern). Overwritten when next task lands.*
