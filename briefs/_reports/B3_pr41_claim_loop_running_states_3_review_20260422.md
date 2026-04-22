# B3 Review — PR #41 CLAIM_LOOP_RUNNING_STATES_3

**Reviewer:** Code Brisen #3
**Date:** 2026-04-22
**PR:** https://github.com/vallen300-bit/baker-master/pull/41
**Branch:** `claim-loop-running-states-3`
**Head SHA:** `5e4e253`
**Author:** B1
**Ship report:** `briefs/_reports/B1_claim_loop_running_states_3_20260422.md`

---

## §verdict

**APPROVE PR #41.** All 9 focus items green. Full-suite regression delta reproduced locally with cmp-confirmed identical 16-failure set. Closes the N3 nit I flagged on PR #39 (`*_running` mid-step crash orphans). Single-SQL CASE-WHEN reset is simpler and tighter than the per-state-claim shape of PR #39 — right choice for this class. Tier A auto-merge greenlit.

---

## §focus-verdict

1. ✅ **`reset_stale_running_orphans` correctness.**
2. ✅ **`main()` wire-in — reset BEFORE claim chain, unconditional, log only on N>0.**
3. ✅ **CASE-WHEN completeness — 3 states covered, no ELSE, WHERE IN matches.**
4. ✅ **15-min staleness constant — separate from PR #39's constant.**
5. ✅ **Same-tick reset→claim integration — proven via ordering test.**
6. ✅ **7 new tests — SQL-text inspection + exact call_log ordering.**
7. ✅ **Regression delta — +7 passed, 0 regressions, identical failure set.**
8. ✅ **Scope — 2 files only.**
9. ✅ **Ship report has full pytest with literal counts.**

---

## §1 `reset_stale_running_orphans` correctness

`kbl/pipeline_tick.py:214-244`. Reads cleanly:

```python
with conn.cursor() as cur:
    cur.execute(_RUNNING_RESET_SQL)
    n = cur.rowcount
conn.commit()
return n
```

Driven by `_RUNNING_RESET_SQL` (lines 193-203):

```sql
UPDATE signal_queue
   SET status = CASE status
     WHEN 'classify_running' THEN 'awaiting_classify'
     WHEN 'opus_running'     THEN 'awaiting_opus'
     WHEN 'finalize_running' THEN 'awaiting_finalize'
   END
 WHERE status IN ('classify_running', 'opus_running', 'finalize_running')
   AND started_at < NOW() - INTERVAL '{_RUNNING_ORPHAN_STALE_INTERVAL}'
RETURNING id, status
```

- **Single atomic UPDATE.** No `FOR UPDATE SKIP LOCKED` needed — one statement acquires row-level locks as Postgres scans; concurrent ticks with `max_instances=1` (APScheduler) won't overlap, and even if they did, Postgres serializes statement-level updates on the same rows. ✓
- **Race with PR #39's claim chain:** filter sets are disjoint. Reset targets `*_running` states, claims target `awaiting_*` states. No overlap. ✓
- **Commit semantics:** one `conn.commit()` on success. ✓
- **Return value:** `cur.rowcount` — number of reset rows. Caller (`main()`) uses this for the info-log gate. ✓
- **RETURNING id, status** — present but not consumed. PG evaluates RETURNING lazily; unconsumed rows carry no cost. Could be used for per-row structured logs later; harmless as-is.

## §2 `main()` wire-in ordering

`kbl/pipeline_tick.py:791-805`:

```python
with get_conn() as conn:
    try:
        n_reset = reset_stale_running_orphans(conn)
    except Exception:
        conn.rollback()
        raise
    if n_reset:
        _local.info(
            "[pipeline_tick] reset %d stale *_running orphan(s) to awaiting_*",
            n_reset,
        )

    try:
        signal_id = claim_one_signal(conn)
    ...
```

- **Unconditional call:** no `if` gate; reset runs on EVERY tick. ✓
- **Before claim chain:** verified — `claim_one_signal` (primary, start of chain) is called after reset. ✓
- **Rollback-on-error + re-raise:** exception in reset propagates via APScheduler listener. ✓
- **Log only when N>0:** `if n_reset:` gate correctly suppresses noise when there's nothing to reset. ✓
- **Same connection:** reset and claim chain share `conn` from the single `get_conn()` block, so the reset's commit makes the newly-flipped row visible to the same tick's claim functions. That's the same-tick pickup contract. ✓

## §3 CASE-WHEN completeness

- 3 WHEN branches: `classify_running`, `opus_running`, `finalize_running`.
- No `ELSE` clause. But that's safe because `WHERE status IN (...)` restricts the UPDATE to the same 3 values — an unexpected state can never reach the CASE. WHERE and CASE are kept in sync by construction.
- Potential future footgun: if someone adds a 4th running state to the WHERE IN clause without adding a matching WHEN, the CASE would evaluate to NULL and UPDATE would set status to NULL. Worth a guard comment; non-gating. Flagged as N1.
- Tests #1, #2, #3 each assert their state's WHEN→THEN mapping is present in the SQL; test #3 additionally asserts the full `status in ('classify_running', 'opus_running', 'finalize_running')` WHERE clause. Structural enforcement. ✓

## §4 15-min staleness constant

`kbl/pipeline_tick.py:191` — `_RUNNING_ORPHAN_STALE_INTERVAL = "15 minutes"`. Separate constant from PR #39's `_AWAITING_ORPHAN_STALE_INTERVAL` (line 180) per dispatch spec. ✓

Rationale documented in the preceding comment block (lines 183-189): Step 5 Opus R3 at ~180s is the slowest legitimate running step; 15 min is ~5× safety margin; `max_instances=1` prevents legitimate overlap. Sound reasoning. ✓

Code-only constant, f-string-embedded into `_RUNNING_RESET_SQL`. No injection surface (matches PR #39's pattern for `INTERVAL` literals where psycopg2 cannot parametrize).

## §5 Same-tick reset→claim integration

Verified by `test_main_reset_and_reclaim_in_same_tick` (tests/test_pipeline_tick.py:1648-1711). The test:

1. Mocks `reset_stale_running_orphans` to return 1 (one orphan reset).
2. Mocks `claim_one_awaiting_opus` to return 777 (the just-reset row).
3. Mocks `_process_signal_opus_remote` to record the dispatch.
4. Asserts `call_log == ["reset", "primary", "opus_failed", "awaiting_classify", "awaiting_opus", "dispatch_opus:777"]` — exact ordering through the full chain.
5. Asserts `awaiting_finalize` is NEVER called (stopped at awaiting_opus hit).
6. Asserts `_process_signal_opus_remote.assert_called_once_with(777, fake_conn)`.

This proves: reset commits → claim chain sees the newly-flipped row → claim picks it up → dispatch runs → awaiting_finalize never consulted (stop-at-first-hit honored). Same-tick closure demonstrated. ✓

**Not directly tested but verified by inspection:** the reset's commit is on the OUTER `conn` (from `get_conn()`), not a fresh connection — so the subsequent `claim_one_awaiting_opus` on the same `conn` sees the committed new status without needing a new transaction. The claim function's `FOR UPDATE SKIP LOCKED` re-locks the row under its own logic. Correct.

## §6 Test matrix — 7 new tests

`tests/test_pipeline_tick.py:1517-1762`. Read each body:

| # | Test | Pins |
|---|------|------|
| 1 | `test_reset_stale_running_orphans_flips_classify_running` | `n == 1`, 1 commit, 0 rollback; single UPDATE; SQL contains `when 'classify_running' then 'awaiting_classify'`; `_RUNNING_ORPHAN_STALE_INTERVAL` + `started_at` + `now() - interval` |
| 2 | `test_reset_stale_running_orphans_flips_opus_running` | SQL contains `when 'opus_running'` + `then 'awaiting_opus'` |
| 3 | `test_reset_stale_running_orphans_flips_finalize_running` | SQL contains `when 'finalize_running'` + `then 'awaiting_finalize'`; full `status in ('classify_running', 'opus_running', 'finalize_running')` WHERE clause present |
| 4 | `test_reset_stale_running_orphans_skips_fresh_rows` | rowcount=0 → n=0, UPDATE still fires (single statement), 1 commit / 0 rollback, staleness guard present in SQL |
| 5 | `test_reset_stale_running_orphans_returns_zero_when_empty` | rowcount=0 → n=0, 1 commit (idempotent) |
| 6 | `test_main_calls_reset_before_claim_chain` | `call_log == ["reset", "primary"]` — strict pre-chain ordering |
| 7 | `test_main_reset_and_reclaim_in_same_tick` | Full `call_log` through all 5 claim functions + dispatch; `awaiting_finalize` `call_count==0`; dispatch called with exact `(777, fake_conn)` |

All use SQL-text substring inspection, exact-value assertions (`n == 1`, rowcount counts), or exact-ordering `call_log == [...]` lists. No presence-only asserts. ✓

Count math: `pipeline_tick.py` was 47 green after PR #39 + 7 new = 54 total. Matches B1's claim. ✓

**N2 — honest limitation acknowledged in test #5 docstring:** mock cannot distinguish "staleness-guarded out" from "no rows exist" since both surface as `rowcount=0` at the function boundary. Same honest pattern as PR #38/#39 boundary tests. Non-gating.

## §7 Full-suite regression delta

Reproduced locally in `/tmp/b3-venv` (Python 3.12):

```
main baseline:       16 failed / 805 passed / 21 skipped / 19 warnings  (12.01s)
pr41 head (5e4e253): 16 failed / 812 passed / 21 skipped / 19 warnings  (12.62s)
Delta:               +7 passed, 0 regressions, 0 new errors, 0 new skips
```

**Failure-set identity check:** `cmp -s /tmp/b3-main5-failures.txt /tmp/b3-pr41-failures.txt` → exit 0 (IDENTICAL).

`+7 passed` matches the 7 new test functions exactly. `805 + 7 = 812` math holds — B1's absolute counts match mine exactly. ✓

## §8 Scope discipline

- **2 files:** `kbl/pipeline_tick.py` (+80/-0), `tests/test_pipeline_tick.py` (+249/-0). `git diff $(merge-base)..pr41 --name-only` confirms. ✓
- **No schema migration:** no `ALTER TABLE`, no `CREATE`, no DDL. Reuses existing `status` + `started_at` columns. ✓
- **No new env vars:** `grep "os.environ\|os.getenv" diff` returns nothing. ✓
- **No step module changes:** `grep "step[1-7]" diff` shows only doc-comment references inside the new docstring (mentioning Step 5's R3 ladder as the slowest legitimately-running step for rationale). ✓
- **No changes to PR #39 claim functions:** `claim_one_awaiting_classify`, `claim_one_awaiting_opus`, `claim_one_awaiting_finalize` unchanged (diff context only). ✓
- **No new deps:** no `requirements.txt` change. ✓

## §9 Ship report — no "by inspection"

Ship report §test-results carries:

```
$ /tmp/b1-venv/bin/pytest tests/ 2>&1 | tee /tmp/b1-pytest-running-states.log
...
=========== 16 failed, 812 passed, 21 skipped, 19 warnings in 12.40s ===========
```

Literal counts present (16/812/21). 16 FAILED rows enumerated with per-test failure reason. `grep -n "by inspection"` in ship report → zero matches. Phrase absent. `memory/feedback_no_ship_by_inspection.md` honored. ✓

---

## §non-gating

- **N1 — CASE-WHEN maintenance footgun.** If someone adds a 4th `*_running` state to the WHERE IN clause in the future but forgets to add a matching WHEN branch, the CASE would evaluate to NULL and UPDATE would set status to NULL — corrupting the row. Cheap mitigation: add an `ELSE status` clause (preserves existing status on unknown input, surfaces the bug via "no rows updated" instead of "row corrupted"). Or add a comment coupling the WHERE IN values to the WHEN branches. Not gating; current code is correct for the 3 states shipped.

- **N2 — test boundary limitation.** Tests #4 (`skips_fresh_rows`) and #5 (`returns_zero_when_empty`) are functionally identical at the mock layer — both return rowcount=0 from the cursor. The live staleness filter is exercised only in integration, not unit. Same honest acknowledgement present in PR #38/#39 tests. Non-gating.

- **N3 — RETURNING clause unused.** `RETURNING id, status` fires lazily in PG but the caller only reads `cur.rowcount`, never iterates the result set. Harmless today; could be wired to structured-log the affected signal_ids in a future follow-up. Not gating.

---

## §regression-delta

```
$ wc -l /tmp/b3-main5-failures.txt /tmp/b3-pr41-failures.txt
      16 /tmp/b3-main5-failures.txt
      16 /tmp/b3-pr41-failures.txt

$ cmp -s /tmp/b3-main5-failures.txt /tmp/b3-pr41-failures.txt && echo IDENTICAL
IDENTICAL
```

Raw logs at `/tmp/b3-main5-pytest-full.log` and `/tmp/b3-pr41-pytest-full.log` (local).

---

## §post-merge

- Tier A auto-merge (squash) proceeds.
- Render redeploys. On next tick, any stranded `*_running` rows with `started_at > 15min` are flipped back to their corresponding `awaiting_*` state by the reset; PR #39's claim chain picks them up organically within the same tick (or the next one).
- `*_running` orphan class structurally retired. Combined with PRs #38 + #39, the full crash-recovery surface is now covered:
  - PR #38: `opus_failed` retry state (post-Step-6 validation failure).
  - PR #39: `awaiting_classify` / `awaiting_opus` / `awaiting_finalize` (crashes BETWEEN steps).
  - PR #41: `classify_running` / `opus_running` / `finalize_running` (crashes DURING steps).

The only remaining "orphan" class is `paused_cost_cap`, which is not a crash state — it's a deliberate hold until the cost gate reopens. That's out of scope for this track.

**APPROVE PR #41.**

— B3
