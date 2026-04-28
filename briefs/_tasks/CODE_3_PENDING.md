---
status: OPEN
brief: review_pr_75
trigger_class: MEDIUM
dispatched_at: 2026-04-28T15:05:00Z
dispatched_by: ai-head-a
review_target_pr: 75
review_target_brief: briefs/BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
autopoll_eligible: false
---

# CODE_3_PENDING — B3: SECOND-PAIR REVIEW PR #75 (CORTEX_PHASE5_IDEMPOTENCY_1) — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b3`
**PR to review:** [#75 cortex-phase5-idempotency-1](https://github.com/vallen300-bit/baker-master/pull/75) (HEAD `d55e850`, +1065/-41, 5 files)
**Brief:** [`briefs/BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md`](../BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md)
**Builder:** B2 (App). B3 = independent reviewer (you wrote 1C / Phase 5 — ideal context).
**Trigger class:** MEDIUM (cross-capability state-write hardening on cortex_cycles + GOLD path)

## §2 pre-dispatch busy-check (AI Head A verified)

- **B3 prior state:** COMPLETE — V1 DRY_RUN launch plan shipped (`01fa06d`); PR #74 merged `97f26b1`. IDLE.
- **Other B-codes:**
  - B1: COMPLETE — PR #74 review APPROVE shipped (`6eb9dc8`). IDLE.
  - B2 (App): just shipped PR #75 IDEMPOTENCY build (`d55e850`); cannot self-review.
- **Lesson #50 review-in-flight pre-check:** `gh pr view 75 --json reviewDecision` empty; no `briefs/_reports/B3_pr75*` exists; CLEAN.

## What you're reviewing

PR #75 closes B's PR #74 OBS-1 (HIGH idempotency on 4 handlers) + OBS-2 (MEDIUM partial-failure surfacing on `_write_gold_proposals`). Single-file patch on `orchestrator/cortex_phase5_act.py` plus 21 new tests.

B2's ship report claims:
- 41 passed in 0.04s on dedicated suite (21 new + 20 existing)
- 182 passed + 5 skipped on full cortex+alerts regression (was 161, +21 new)
- Math: 1A 31 + 1B 48 + 1C 82 = 161 baseline + 21 new = 182 ✓
- 4 transient `*ing` statuses live ('approving', 'editing', 'refreshing', 'rejecting')
- `_cas_lock_cycle` helper centralizes CAS pattern (DRY); fail-CLOSED on DB error
- `_cas_release_to_proposed` for edit/refresh (re-loop pattern)
- `_archive_cycle` gains optional `from_status` param (legacy `from_status=None` preserved)
- `_write_gold_proposals` returns rich dict (3 existing tests updated)
- autouse `_bypass_cas` fixture keeps existing 20 tests focused on non-CAS

## B3 review checklist (7 criteria — 5 brief-mandated + 2 design-validation)

Per b1-trigger-class second-pair review:

1. **Brief acceptance match** — every line in `BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md` §"Quality Checkpoints" (10 items) + §"Verification" verified against shipped code. Flag any missing.
2. **CAS guard correctness** — verify all 4 handlers have CAS guard at TOP (before any other DB read/write). Verify the WHERE clause matches expected source status (`'proposed'` for all 4) and target intermediate status matches per-handler table in brief §Fix/Feature 1. Flag any handler missing the guard.
3. **Idempotency proof in tests** — run literal `pytest tests/test_cortex_phase5_idempotency.py -v 2>&1 | tail -50` AND full regression `pytest tests/test_cortex_*.py tests/test_alerts_to_signal*.py -v 2>&1 | tail -10`. Paste literal stdout into review report. 21 new pass + 182 total green required per B2 claim.
4. **`_archive_cycle` defensive WHERE-clause** — verify `WHERE cycle_id=%s AND status='approving'` (or whatever from_status passed). Verify legacy `from_status=None` path still UPDATEs unconditionally for backward-compat (existing call sites that don't pass from_status).
5. **Boundaries respected** — `kbl/gold_writer.append` NOT called from any cortex_* file (Amendment A1 preserved). `kbl/gold_proposer.propose` IS the only cortex-side GOLD write path. Caller-authorized guard at `kbl/gold_writer.py:_check_caller_authorized` not touched.

## Design-validation checks (additional 2 criteria specific to this patch)

6. **Status state machine consistency** — verify the 4 transient `*ing` statuses round-trip correctly:
   - `proposed → approving → approved` (via Phase 6 archive)
   - `proposed → editing → ??? → proposed` (re-loop via `_cas_release_to_proposed`) — verify the release helper is actually called on edit-success path
   - `proposed → refreshing → ??? → proposed` (re-loop via re-running Phase 3) — same release helper check
   - `proposed → rejecting → rejected` (terminal)
   Flag any state that can deadlock (e.g., stuck in `*ing` with no release path).

7. **Partial-failure surfacing semantics** — verify `_write_gold_proposals` returns:
   - `status="approved"` when all selected files succeed
   - `status="approved_with_partial_errors"` when some fail (with `failed_files` list + counts)
   - `status="approved_with_errors"` when ALL fail (with `errors` list + warning)
   Verify the dashboard endpoint surface (additive JSON fields, no breaking changes per brief).

## Output: review report at `briefs/_reports/B3_pr75_cortex_phase5_idempotency_1_20260428.md`

Then post verdict on PR via `gh pr comment 75 --body "<verdict>"` (formal APPROVE blocked by self-PR rule per #67/#69/#70/#71/#72/#74 precedent — comment is the gate).

## Parallel work this window

- AI Head A runs `/security-review` skill on PR #75 (Lesson #52 mandatory) in parallel.
- Both verdicts (B3 + AI Head A) gate the merge. AI Head A merges Tier-A on all-clear.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
