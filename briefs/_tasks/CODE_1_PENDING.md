# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** LOOP-SCHEMA-1 shipped at PR #5 (`51adc44`). LAYER0-LOADER-1 PR #4 APPROVED by B2 with 1 should-fix.
**Task posted:** 2026-04-18
**Status:** OPEN — two small follow-ups

---

## AI Head decision on BIGINT/INTEGER FK mismatch

**Decision: upgrade `signal_queue.id` to `BIGSERIAL`** in the same LOOP-SCHEMA-1 migration.

Rationale: `signal_queue` is the primary ingestion table; `INTEGER` (2.1B max) is a latent Phase-2+ overflow risk we remove cheaply now while the table is small. Downgrading the new FK columns would entrench the limit across loop infrastructure. No `REFERENCES` clauses — application-level integrity per your literal-brief read, preserves ledger immutability under CHANDA Inv 2 atomicity. Clean.

---

## Task A (immediate): Amend PR #5 — signal_queue.id → BIGSERIAL

### What to do

Add to `migrations/20260418_loop_infrastructure.sql` UP section, BEFORE the three CREATE TABLE blocks:

```sql
-- Upgrade signal_queue.id to BIGINT (prevents Phase 2+ integer overflow, matches new FK column types)
ALTER TABLE signal_queue ALTER COLUMN id TYPE BIGINT;
ALTER SEQUENCE signal_queue_id_seq AS BIGINT;
```

And to the DOWN section (rollback):

```sql
-- Downgrade signal_queue.id back to INTEGER (rollback — assumes row count fits in INTEGER)
ALTER TABLE signal_queue ALTER COLUMN id TYPE INTEGER;
ALTER SEQUENCE signal_queue_id_seq AS INTEGER;
```

Verify the sequence name with `SELECT pg_get_serial_sequence('signal_queue', 'id');` if it differs from the default naming.

Keep the new FK columns as `BIGINT` (unchanged from your PR #5).

### CHANDA pre-push

- Q1 Loop Test: schema-only table-type upgrade, no loop-mechanism modification. Pass.
- Q2 Wish Test: forward-compatibility for Phase 2+ signal volume. Wish-service. Pass.

### Dispatch back

> B1 PR #5 amended — signal_queue.id upgraded to BIGSERIAL, head `<SHA>`, <N>/<N> tests green. Ready for B2 review.

---

## Task B (after Task A): Amend PR #4 — version int-not-string (S1 from B2 review)

### What to do

On branch `layer0-loader-1`, apply the 3-line patch for S1:

1. In `kbl/layer0_rules.py`, change `version` field validation from `str` to `int` (matching `slug_registry.py` convention and B3's Step 0 draft `version: 1`)
2. In `tests/fixtures/layer0_rules_valid.yml` and `layer0_rules_malformed.yml`, change `version: "1.0.0"` to `version: 1`
3. In `tests/test_layer0_rules.py`, update the version-type assertion

Amend commit + force-push to `layer0-loader-1`.

### Why int not string

- Matches `slug_registry.py` convention (`version: 1`)
- Matches B3's Step 0 draft (`version: 1`) — without this, loader would reject B3's vault commit with `Layer0RulesError`
- Minimizes coordination cost with B3's parallel vault YAML work

### Dispatch back

> B1 PR #4 S1 amended — version field now int, head `<SHA>`, <N>/<N> tests green. Ready for Director merge.

---

## Sequence + timing

- Task A (PR #5 amend): ~10-15 min
- Task B (PR #4 S1 patch): ~10-15 min
- Total: ~20-30 min both

Can do either order — your call. PR #5 review by B2 is more time-sensitive (unblocks B3's Step 1 Inv-3 implementation), so A-first is preferred.

---

## Work-in-flight note

- PR #4 ready for Director merge as soon as Task B lands + tests re-green
- PR #5 in B2 queue right after Task A lands
- B3 is parallel-running Step 1 Inv-3 amendment; their Python-helper impl depends on `feedback_ledger` table existing (your PR #5). Merge order: PR #5 → PR #4 → B3's subsequent KBL-B wiring

---

*Posted 2026-04-18 by AI Head. Two small follow-ups to close both PRs in the pipe. PR #5 + S1 fix together unblock Director merges + B3 Step 1 wiring.*
