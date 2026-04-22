# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1
**Task posted:** 2026-04-22 (post Gate-2 close)
**Status:** OPEN — CLAIM_LOOP_OPUS_FAILED_RECLAIM_1 (production-hardening)

---

## Context

PR #37 merged. Gate 2 closed mechanically (14 real vault files with `step_5_decision='full_synthesis'` as of 05:35 UTC). But production has a chronic recurring orphan — **every row that fails Step 6 validation lands at `status='opus_failed'` and stays stuck forever**. Recovery #7 flipped 16 rows manually; as the remaining 44 pending drain through Step 6, more will orphan the same way.

### Root cause (investigated during recovery #7)

Step 6 validation failure flips the row to `status='opus_failed'` and raises. Step 6 docstring at `kbl/steps/step6_finalize.py:25` explicitly says:

> ``opus_failed``. pipeline_tick re-queues into Step 5 for the R3

— but **that reclaim path was never implemented**. `kbl/pipeline_tick.py:84-105` `claim_one_signal()` only selects `status='pending'`. An `opus_failed` row with `finalize_retry_count=1` sits orphaned; the design intent (bump counter → Step 5 regens → Step 6 re-validates, up to 3 reflips) never fires.

Same bug-class surfaced earlier this session for `awaiting_classify` (recovery #6) and `awaiting_finalize` (recoveries #3 + #4). This brief fixes the highest-frequency case: `opus_failed`.

### Recovery log anchor

`memory/actions_log.md` — recoveries #3, #4, #6, #7. All four cost Tier B recovery UPDATEs tonight alone. Each signal that hits opus_failed produces one manual-intervention event. Not sustainable.

---

## Scope — ship the secondary claim path

### 1. New function in `kbl/pipeline_tick.py`

Add a secondary claim function that picks up `opus_failed` rows with `finalize_retry_count < _MAX_OPUS_REFLIPS` (3; import the constant from `step6_finalize`):

```python
def claim_one_opus_failed(conn) -> int | None:
    """Claim the next opus_failed row within retry budget. Returns signal_id or None.
    Complements claim_one_signal — the implementation of the R3 reclaim
    contract documented in step6_finalize.finalize() docstring.
    """
    ...SELECT ... WHERE status='opus_failed' AND finalize_retry_count < _MAX_OPUS_REFLIPS
    ORDER BY priority DESC, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
```

On claim: flip to `awaiting_opus` (Step 5's pre-state — see `kbl/steps/step5_opus.py:49`). Step 5 then runs its internal R3 ladder (IDENTICAL→PARED→MINIMAL within one call), produces a fresh draft, Step 6 re-validates. If Step 6 fails again, the existing Step 6 code path increments `finalize_retry_count` and flips back to `opus_failed` (budget-guarded by this brief's claim function).

### 2. Dispatch path in `pipeline_tick.main()`

Primary claim remains first. If `claim_one_signal` returns None, try `claim_one_opus_failed`. If that returns a row, call a new `_process_signal_reclaim_remote` that starts at Step 5 (skip Steps 1-4 — primary_matter, triage_score, opus_draft_markdown from prior run are still valid; Step 5 overwrites opus_draft_markdown).

**Important:** do NOT call full `_process_signal_remote` on reclaim — Step 1 would re-triage, overwrite `primary_matter` (wasted LLM + matter-shift risk). The reclaim path is narrow: Steps 5 → 6 only (Step 7 remains Mac Mini's poller domain).

### 3. Step-5 idempotency on reclaim

Step 5 `synthesize()` needs to run cleanly when called on an `awaiting_opus` row that already has non-null `opus_draft_markdown` from a prior attempt. Walk the current Step 5 logic and confirm it overwrites `opus_draft_markdown` unconditionally on success. If not, add the overwrite + a small test.

### 4. Regression tests (5 minimum)

Add to `tests/test_pipeline_tick.py` (or create if missing):

1. `test_claim_one_opus_failed_returns_eligible_row` — fixture row at `status='opus_failed'`, `finalize_retry_count=1`, function returns its id, flips it to `awaiting_opus`.
2. `test_claim_one_opus_failed_skips_budget_exhausted` — row at `finalize_retry_count=3` is not claimed, stays at `opus_failed`.
3. `test_claim_one_opus_failed_returns_none_when_empty` — no eligible rows → returns None.
4. `test_reclaim_runs_steps_5_6_not_1_4` — mock Step 5 + Step 6, assert primary_matter untouched on reclaim path (or equivalent: Step 1 never called).
5. `test_reclaim_budget_exhaustion_routes_to_finalize_failed` — 3rd reflip hits `_MAX_OPUS_REFLIPS`, Step 6's existing logic promotes to `finalize_failed` terminal.

### 5. No-scope-creep

- No schema changes (use existing `finalize_retry_count`).
- No new env vars.
- No changes to `claim_one_signal` — add new sibling function.
- No changes to Mac Mini poller (`kbl/poller.py` — awaiting_commit reclaim is a different brief).
- Do not touch `awaiting_classify` / `awaiting_finalize` / `awaiting_commit` orphan-state reclaim — that's a follow-up (`CLAIM_LOOP_ORPHAN_STATES_2`), not this brief.

### 6. Mandatory gates

- `memory/feedback_no_ship_by_inspection.md` — full `pytest tests/` log in ship report.
- `memory/feedback_migration_bootstrap_drift.md` — N/A (no columns).

---

## Deliverable

- PR on baker-master, branch `claim-loop-opus-failed-reclaim-1`, reviewer B3.
- Ship report at `briefs/_reports/B1_claim_loop_opus_failed_reclaim_20260422.md`.
- Report sections:
  - §before/after (pipeline_tick.main + new claim function)
  - §reclaim-semantics (which steps run, which fields get overwritten, budget guard)
  - §test-matrix (5 regressions above, plus any you add)
  - §full pytest output (no-ship-by-inspection gate)
  - §production-impact: after merge + deploy, AI Head does NOT need recovery #7-style manual UPDATEs on opus_failed rows anymore — the claim loop handles it automatically within the 3-reflip budget. Recovery #6 / awaiting_classify orphaning is NOT fixed by this brief.

## Constraints

- **Effort: S-M (~60-90 min).**
- Timebox: 2 hours.
- Working dir: `~/bm-b1`. `git checkout main && git pull -q` first.

## Why now (Director-level context)

Production just opened. 44 pending signals are draining; each Step 6 failure = one permanent orphan without this fix. AI Head has been running manual recovery UPDATEs all night — not sustainable path to steady-state. This brief closes the loop on the highest-frequency case. Director directive: "task is production ASAP."

On APPROVE, AI Head auto-merges (Tier A) and deploys.

— AI Head
