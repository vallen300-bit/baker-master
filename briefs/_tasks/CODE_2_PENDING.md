---
status: IN_PROGRESS
brief: briefs/BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md
trigger_class: MEDIUM
dispatched_at: 2026-04-28 14:50:00+00:00
dispatched_by: ai-head-a
prerequisite_pr: 74
prerequisite_state: MERGED 2026-04-28T14:45:05Z (squash 97f26b1)
claimed_at: '2026-04-28T14:52:00.560410+00:00'
claimed_by: b2
last_heartbeat: null
blocker_question: null
ship_report: null
autopoll_eligible: false
context_note: builder=b2 (App, fresh post-triage); reviewer=b3 (hottest Phase 5 context);
  blind-spot diversification per Director RA 2026-04-28T14:35Z
---

# CODE_2_PENDING — B2 (App): CORTEX_PHASE5_IDEMPOTENCY_1 — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b2` (App tab — active agent in Claude App; cd into worktree filesystem)
**Brief:** [`briefs/BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md`](../BRIEF_CORTEX_PHASE5_IDEMPOTENCY_1.md) (~210 lines)
**Branch:** `cortex-phase5-idempotency-1` (cut from `main` post PR #74 merge `97f26b1`)
**Estimated time:** ~30-45min
**Trigger class:** MEDIUM → b3 second-pair-review pre-merge

## §2 pre-dispatch busy-check (AI Head A verified)

- **B2 (App) prior state:** COMPLETE — backlog triage shipped (`b14a670`). IDLE.
- **Other B-codes:**
  - B1: COMPLETE — PR #74 second-pair-review APPROVE shipped (`6eb9dc8`). IDLE.
  - B3: COMPLETE — PR #74 (1C build) merged `97f26b1` + V1 DRY_RUN launch plan shipped (`01fa06d`). IDLE, warm for second-pair-review on this patch.
- **Lesson #50 review-in-flight pre-check:** N/A (build, not review).
- **Self-review block:** B2 cannot self-review own build → b3 = independent reviewer (b3 has Phase 5 context from 1C build, ideal for this patch).

## Source

AI Head B PR #74 structural-design verdict (relayed via Director 2026-04-28T14:30Z) surfaced:
- **OBS-1 HIGH** — `cortex_approve` not idempotent (4 handlers affected); double-fire creates duplicate GOLD entries + duplicate audit rows.
- **OBS-2 MEDIUM** — `_write_gold_proposals` silent-failure swallow on systemic errors (Director sees "approved" but zero GOLD written).
- OBS-3/4/5 LOW — backlog (separate post-V1 hardening pass).

This patch closes OBS-1 + OBS-2 only.

## What you're building

Two surgical changes in `orchestrator/cortex_phase5_act.py`:

1. **CAS guard at top of 4 handlers** (`cortex_approve`, `cortex_edit`, `cortex_refresh`, `cortex_reject`) — atomic `UPDATE ... WHERE status='proposed' RETURNING cycle_id` pattern; if 0 rows, return `{"warning": "already_actioned", ...}` with HTTP 200 (idempotent retry not an error).
2. **Partial-failure surfacing in `_write_gold_proposals` caller** — return `status="approved_with_errors"` (all fail) or `"approved_with_partial_errors"` (some fail) with explicit field counts.

Plus `_archive_cycle` defensive WHERE-clause hardening (1 line).

Plus 12 new idempotency tests + 2 partial-failure tests.

## Hard gate

MUST ship before Step 30 (first live cycle on AO matter, post-DRY_RUN). DRY_RUN-only firing in cycle 1 mitigates today; live double-fire would create duplicate GOLD entries + duplicate audit rows.

## Process

1. `git checkout main && git pull -q`
2. `git checkout -b cortex-phase5-idempotency-1`
3. Build per Brief §"Fix/Feature 1" + §"Fix/Feature 2"
4. Run literal pytest (Brief §"Verification"):
   ```bash
   pytest tests/test_cortex_phase5_idempotency.py tests/test_cortex_phase5_act.py -v 2>&1 | tail -50
   pytest tests/test_cortex_*.py tests/test_alerts_to_signal*.py -v 2>&1 | tail -10
   ```
5. Push branch, open PR with title `CORTEX_PHASE5_IDEMPOTENCY_1: CAS guard + partial-failure surfacing (B's PR #74 OBS-1 + OBS-2)`
6. Write ship report at `briefs/_reports/B2_pr<N>_cortex_phase5_idempotency_1_20260428.md`
7. Notify A in chat — A dispatches b3 second-pair-review + runs `/security-review`

## Files Modified (per brief §"Files Modified")

- `orchestrator/cortex_phase5_act.py` — CAS guard on 4 handlers + `_archive_cycle` WHERE-hardening + `_write_gold_proposals` partial-failure surfacing
- `tests/test_cortex_phase5_idempotency.py` — NEW (≥12 tests)
- `tests/test_cortex_phase5_act.py` — UPDATE existing tests if they assume unconditional UPDATE

## Files NOT to Touch

Per brief §"Files NOT to Touch" — `cortex_phase4_proposal.py`, `cortex_runner.py`, migrations, `kbl/gold_writer.py`, `kbl/gold_proposer.py`, `dashboard.py` endpoint signature (additive JSON fields only), rollback script.

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
