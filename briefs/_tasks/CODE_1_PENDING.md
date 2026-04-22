# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1
**Task posted:** 2026-04-22 ~11:50 UTC
**Status:** OPEN — `CLAIM_LOOP_RUNNING_STATES_3` (continuation of PR #39; B3's N3 nit)

---

## Brief-route note (charter §6A)

Freehand dispatch. Continuation-of-work after your PR #39 (CLAIM_LOOP_ORPHAN_STATES_2). B3's review of PR #39 flagged N3: "Orphan scope does not cover `*_running` mid-step crashes. Pre-existing gap; out of scope per brief. Candidate `CLAIM_LOOP_RUNNING_STATES_3`." This is that brief.

Director cleared "all outstanding" at 2026-04-22 ~11:48 UTC. Dispatching in parallel with B2's STEP5 investigation.

---

## Context — what PR #39 did NOT cover

PR #39's 5-deep claim chain handles `awaiting_classify` / `awaiting_opus` / `awaiting_finalize` (crash BEFORE a step started). But if a tick dies WHILE a step is executing, the row lands in the corresponding `*_running` state:

- `classify_running` — Step 4 was mid-flight when the worker crashed.
- `opus_running` — Step 5 was mid-flight (Opus API call in progress, R3 ladder mid-cycle, etc.).
- `finalize_running` — Step 6 was mid-flight (Pydantic validation mid-stream, vault write mid-commit, etc.).

These rows are INVISIBLE to PR #39's chain. They sit `*_running` with stale `started_at` and never get re-claimed. Only manual `UPDATE signal_queue` recovers them — exactly the pattern PR #38 + #39 retired for the `awaiting_*` class.

Current queue snapshot shows ONE row actively `finalize_running` — that's legitimate mid-flight, not an orphan. But orphans of this class have appeared in prior recoveries; a future crash will produce more.

## Scope — ONE reset function covering all three running states

**Design decision (AI Head):** do NOT mirror PR #39's pattern of per-state dispatchers. Simpler shape — one reset function that flips `*_running` rows back to the corresponding `awaiting_*` state when `started_at` is stale. PR #39's chain then picks them up naturally on the next tick.

### 1. New function in `kbl/pipeline_tick.py`

**`reset_stale_running_orphans(conn) -> int`** — returns the number of rows reset.

Single SQL statement. For each of the three `*_running` states, UPDATE back to the prior `awaiting_*` state when `started_at < NOW() - _RUNNING_ORPHAN_STALE_INTERVAL`. Keep `FOR UPDATE SKIP LOCKED` semantics to be safe with concurrent ticks.

**Staleness guard:** pick **15 minutes** — same as PR #39's `_AWAITING_ORPHAN_STALE_INTERVAL`. Rationale:
- `finalize_running` max legit duration: seconds (Pydantic + YAML serialize, then Mac Mini takeover).
- `opus_running` max legit duration: ~180s (Step 5 R3 ladder × 60s Opus call).
- `classify_running` max legit duration: seconds (Step 4 is local).
- 15 min is ≥5× the slowest. Safe margin.

**Shape (exemplar — you refine):**

```python
_RUNNING_ORPHAN_STALE_INTERVAL = "15 minutes"

_RUNNING_RESET_SQL = """
UPDATE signal_queue
   SET status = CASE status
     WHEN 'classify_running' THEN 'awaiting_classify'
     WHEN 'opus_running'     THEN 'awaiting_opus'
     WHEN 'finalize_running' THEN 'awaiting_finalize'
   END
 WHERE status IN ('classify_running', 'opus_running', 'finalize_running')
   AND started_at < NOW() - INTERVAL '15 minutes'
 RETURNING id, status
"""


def reset_stale_running_orphans(conn: Any) -> int:
    """Flip stale *_running rows back to awaiting_* so PR #39's chain
    can reclaim them on the next tick. Called once per tick before the
    claim chain."""
    with conn.cursor() as cur:
        cur.execute(_RUNNING_RESET_SQL)
        n = cur.rowcount
    conn.commit()
    return n
```

Module-level constant for the interval (same style as `_AWAITING_ORPHAN_STALE_INTERVAL`). Bare SQL interval literal — no injection surface.

### 2. Wire into `main()` BEFORE the claim chain

```python
def main():
    ...
    n_reset = reset_stale_running_orphans(conn)
    if n_reset:
        logger.info(f"reset {n_reset} stale running orphans")
    # then the PR #39 chain:
    if signal_id := claim_one_signal(conn):
        ...
```

One call per tick, before claim attempts. No dispatch; just state reset. PR #39's chain handles the advancement.

### 3. NO new dispatch functions

Deliberately. The reset is pure state; advancement is PR #39's job. This keeps the brief small and preserves the "one responsibility per function" shape of your PR #39.

## Tests — 6 in `tests/test_pipeline_tick.py`

1. `test_reset_stale_running_orphans_flips_classify_running` — stale row → awaiting_classify, returns 1.
2. `test_reset_stale_running_orphans_flips_opus_running` — stale row → awaiting_opus, returns 1.
3. `test_reset_stale_running_orphans_flips_finalize_running` — stale row → awaiting_finalize, returns 1.
4. `test_reset_stale_running_orphans_skips_fresh_rows` — fresh started_at on any `*_running` row → NOT flipped, returns 0.
5. `test_reset_stale_running_orphans_returns_zero_when_empty` — no eligible rows → returns 0.
6. `test_main_calls_reset_before_claim_chain` — mock `reset_stale_running_orphans` + `claim_one_signal`; assert call order (reset FIRST).

## Integration — regression against PR #39 chain

One extra test at the `main()` level: a stale `opus_running` row should be:
- Reset to `awaiting_opus` by `reset_stale_running_orphans`.
- Claimed by `claim_one_awaiting_opus` in the SAME tick (NOT the next tick — reset commits before claim runs, same connection).
- Dispatched to `_process_signal_opus_remote` for Step 5-6 continuation.

Name: `test_main_reset_and_reclaim_in_same_tick`. Mocks Steps 5+6 to succeed; asserts the stale `opus_running` row ends up at `awaiting_commit` (or whatever the successful terminal of Step 6 is in the mock).

## Full pytest gate

Run `pytest tests/` full suite. Expected baseline: `16 failed, 805 passed, 21 skipped` (post PR #40). Your additions: +7 tests = `16 failed, 812 passed, 21 skipped`. Any new failure → REQUEST_CHANGES on yourself.

## Out of scope (explicit)

- **No changes to PR #39 chain.** Pure extension.
- **No changes to step modules** (`step4_classify.py`, `step5_opus.py`, `step6_finalize.py`).
- **No schema changes.** Reuses `status` + `started_at` columns.
- **No cleanup of existing orphans.** This brief only prevents future ones. If any `*_running` row is currently orphaned, next tick after deploy will reset + reclaim it organically.

## Ship shape

- PR title: `CLAIM_LOOP_RUNNING_STATES_3: reset stale *_running rows for organic reclaim`
- Branch: `claim-loop-running-states-3`
- Files: `kbl/pipeline_tick.py` + `tests/test_pipeline_tick.py`. 2 files.
- Commit style: one clean commit (match PR #38/#39/#40).
- Ship report path: `briefs/_reports/B1_claim_loop_running_states_3_20260422.md`. Include:
  - §before/after in `kbl/pipeline_tick.py` (line numbers + diff excerpt)
  - Full pytest log head+tail (no "by inspection")
  - Open-PR link for AI Head routing to B3
- Tier A auto-merge on B3 APPROVE.

**Timebox:** 2.5h. Smaller than PR #39 — one function, one SQL statement, 7 tests.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-22 ~11:52 UTC (parallel with B2 STEP5_EMPTY_DRAFT)
