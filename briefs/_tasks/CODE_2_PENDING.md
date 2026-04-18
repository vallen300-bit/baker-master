# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous:** PR #4 review APPROVE (with S1 should-fix) filed at `cc211ed`. Process incident cleanly self-corrected. Standing down until next task.
**Task posted:** 2026-04-18
**Status:** OPEN — three deliverables in sequence

---

## Task A (now): Review PR #5 — LOOP-SCHEMA-1

**PR:** https://github.com/vallen300-bit/baker-master/pull/5
**Branch:** `loop-schema-1`
**Head:** `51adc44` (will be amended to new SHA after B1 applies the `signal_queue.id → BIGSERIAL` fix — check PR state before starting review)
**Tests:** 19/19 green + 1 live-PG skip by design

### Scope of review

**IN**
- Three new tables: `feedback_ledger`, `kbl_layer0_hash_seen`, `kbl_layer0_review`
- Schema fidelity to CHANDA §2 Leg 2 (Capture) + B2 S5/S6 Step 0 findings
- Rollback (DOWN section) correctness — DROP TABLE IF EXISTS × 3 order
- Index coverage (hot query paths: ledger by created_at + target_matter; layer0_hash by ttl; layer0_review pending)
- `signal_queue.id → BIGSERIAL` upgrade (ALTER TABLE + ALTER SEQUENCE) — verify:
  - UP section runs before CREATE TABLE blocks
  - DOWN section restores to INTEGER
  - Sequence name matches actual PG serial sequence (B1 verified; sanity-check)
- Application-level integrity (no REFERENCES clauses) — confirm this is the ratified choice, not an omission
- `tests/test_migrations.py` entry runs UP + DOWN cleanly

**OUT**
- Writer code (Step 1 reader, ledger writer, Layer 0 hash writer) — KBL-B impl + KBL-C
- Row-level security / grants — out of scope for this migration
- Backfill logic — tables start empty, correct initial state

### Specific scrutiny

1. **`BIGSERIAL` upgrade safety** — `ALTER TABLE signal_queue ALTER COLUMN id TYPE BIGINT` rewrites the table. Confirm it's fast on current empty/near-empty table. Flag if production signal_queue row count could make this slow.
2. **FK column types match** — `feedback_ledger.signal_id`, `kbl_layer0_hash_seen.source_signal_id`, `kbl_layer0_review.signal_id` all `BIGINT`. Confirm.
3. **No REFERENCES decision** — confirm B1 captured in PR body that application-level integrity is intentional, not an oversight.
4. **CHANDA compliance check** — tables themselves are passive storage. No invariant directly bound. But `feedback_ledger` as the Leg 2 spine implies Inv 2 ("atomic ledger write or action fails") is now physically possible. Confirm schema admits the atomic-write pattern (no required fields that would fail the ledger-write + force action-failure loop).

### Format

`briefs/_reports/B2_pr5_review_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline

~20-30 min.

### Dispatch back

> B2 PR #5 review done — `briefs/_reports/B2_pr5_review_20260418.md`, commit `<SHA>`. Verdict: <...>.

---

## Task B (queued, fires when AI Head commits REDIRECT fold)

AI Head is folding Step 6 REDIRECT into KBL-B brief §2, §3.2, §4.7, §6, §8, §9, §10, §11. Expected commit in ~20-30 min. When you see `fold(KBL-B): Step 6 REDIRECT` in git log:

### Scope of review

**IN**
- All 8 sections updated consistently (no residual Sonnet references)
- §4.7 rewrite matches the concrete `step6_finalize()` spec you authored in your scope-challenge report
- §8 retry ladder: Sonnet paths deleted; Opus R3 ladder carries frontmatter-validation-failure case
- §9 cost-control: no `sonnet_step6` ledger rows written; enum value preserved per your note
- §3.2 state enum cleanup: `awaiting_sonnet`/`sonnet_running`/`sonnet_failed` removed; opus-side renamed to `awaiting_finalize`/`finalize_running`/`finalize_failed` for Step 6 side
- §10 fixture path coverage updated for deterministic Step 6
- §11 observability: no Sonnet latency / cost metric; finalize latency metric added

**OUT**
- Re-opening REDIRECT (ratified)
- Step 6 Pydantic schema field list (impl-level, KBL-B impl ticket)

### Format

`briefs/_reports/B2_kbl_b_redirect_fold_review_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline

~20-30 min.

---

## Task C (after Tasks A + B): CHANDA.md Onboarding

Same pattern as B1 + B3's acks. Read CHANDA, internalize §2 loop + §3 invariants + §5 test, file ack at `briefs/_reports/B2_chanda_ack_20260418.md`. ~15-20 min.

### Additionally audit your prior reviews

You have authored reviews on: KBL-A PR #1, SLUGS-1 PR #2, PR #3 TCC fix, KBL-B §4-5 phase-2, KBL-B Step 1/3 prompts, KBL-B Step 0 Layer 0 rules, PR #4, Step 6 scope challenge, PR #5 (this task), KBL-B REDIRECT fold (next task). Ack report should include a compliance audit: do any of your prior review verdicts conflict with CHANDA invariants in hindsight? Flag if so, don't silently absorb.

---

## Parallel state

- B1: amending PR #5 + PR #4 (two quick follow-ups)
- B3: Step 1 Inv-3 amendment in-flight, depends on PR #5 merge for `feedback_ledger` schema
- AI Head: REDIRECT fold in progress

### Dispatch back (after each task)

> B2 PR #5 review done — `<report path>`, commit `<SHA>`. Verdict: <...>.

> B2 KBL-B REDIRECT fold review done — `<report path>`, commit `<SHA>`. Verdict: <...>.

> B2 CHANDA ack + prior-review audit done — `<report path>`, commit `<SHA>`. <any flags>.

---

*Posted 2026-04-18 by AI Head. Clean reviewer-separation maintained: B2 now reviews 3 independent architectural decisions in sequence.*
