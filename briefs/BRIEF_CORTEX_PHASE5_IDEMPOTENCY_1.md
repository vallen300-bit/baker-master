# BRIEF: CORTEX_PHASE5_IDEMPOTENCY_1 — CAS guard + partial-failure surfacing

**Source:** AI Head B PR #74 structural-design verdict ([comment relayed via Director 2026-04-28T14:30Z])
**Authority:** Director RA 2026-04-28T14:35Z accepted Decision 1+2: A merges PR #74 + drafts follow-up + dispatches to b2 (App) for build, b3 for second-pair review.
**Estimated time:** ~30-45min
**Complexity:** Low (surgical — single file + tests; well-defined fix shapes from B's verdict)
**Trigger class:** MEDIUM (cross-capability state-write hardening on cortex_cycles + GOLD propagation path) → b3 second-pair-review pre-merge per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`. Builder ≠ reviewer (b2 builds, b3 reviews).
**Prerequisites:** PR #74 merged (`97f26b1` 2026-04-28T14:45:05Z) — `cortex_phase5_act.py` exists on main.
**Hard gate:** MUST ship BEFORE Step 30 (first live cycle on AO matter, post-DRY_RUN). DRY_RUN-only firing in cycle 1 is sufficient mitigation today; live double-fire would create duplicate GOLD entries + duplicate audit rows.

---

## Context

PR #74 (CORTEX_3T_FORMALIZE_1C) shipped Phase 4/5 + scheduler + dry-run + rollback. AI Head B's structural-design pass surfaced 1 HIGH-confidence and 1 MEDIUM-confidence finding on `cortex_phase5_act.py`. AI Head A's `/security-review` and B1's formal independent review both cleared on auth/security/correctness axes; idempotency is a different concern (correctness under retry/double-click) that those reviews don't typically catch.

This brief is the surgical follow-up that closes both findings before V1 enters live production.

---

## Problem

### OBS-1 (HIGH conf) — `cortex_approve` is not idempotent

**Anchor:** `orchestrator/cortex_phase5_act.py:49-89` (`cortex_approve`) + `cortex_phase5_act.py:376-416` (`_archive_cycle`).

Director double-clicks Approve in Slack OR Slack proxy retries on transient network blip → Phase 5 executes twice. Specific impacts:
- `_archive_cycle` does unconditional `UPDATE cortex_cycles SET status='approved'` — no `WHERE status='proposed'` guard → succeeds on every call.
- `_write_gold_proposals` creates DUPLICATE `ProposedGoldEntry` rows in the `## Proposed Gold (agent-drafted)` section (visible to Director, polluting the curated review surface).
- `_archive_cycle` inserts a SECOND `final_archive` row in `cortex_phase_outputs`.
- Rsync to wiki is idempotent — only mitigates curated-file propagation, not the GOLD/DB writes.

`_is_fresh()` only blocks if a Director email mentioning the matter landed within 30 min — it is NOT a guard against double-fire of the same button click.

Same pattern applies to `cortex_edit`, `cortex_refresh`, `cortex_reject` — all 4 handlers must have CAS-style transition guards.

### OBS-2 (MEDIUM conf) — `_write_gold_proposals` silent-failure swallow on systemic errors

**Anchor:** `cortex_phase5_act.py:309-331` (the per-file try/except loop).

Per-file try/except is correct (one bad file shouldn't kill siblings). But if all proposals fail (DB down at the moment, schema mismatch, gold_proposer module bug), the function returns:
- API returns `{"status": "approved", "gold_files_written": 0}`
- Director sees Approve succeeded — but ZERO GOLD was actually written
- Cycle archived as `'approved'` — proposals silently lost forever

The user-visible "Approved" success state diverges from actual durable state.

---

## Solution

Two surgical changes in `orchestrator/cortex_phase5_act.py`:

1. **CAS guard at top of each of 4 handlers** (`cortex_approve`, `cortex_edit`, `cortex_refresh`, `cortex_reject`). Atomic UPDATE with WHERE-clause-on-current-status-and-RETURNING. If 0 rows updated, another invocation already transitioned — bail with `{"warning": "already_actioned", "current_status": <re-read>, "cycle_id": <id>}` and HTTP 200 (idempotent re-fire is not an error).

2. **Partial-failure surfacing in `_write_gold_proposals`** caller path. After the per-file loop, if `selected_files` is non-empty and `written == 0`, return status `"approved_with_errors"` + `warning="all_gold_proposals_failed"` to the API caller (the dashboard endpoint that posts to Slack). If `0 < written < len(selected_files)`, return `"approved_with_partial_errors"` + count details. Cycle archive still proceeds (status='approved'), but Director sees the discrepancy in the response payload.

---

## Fix/Feature 1: CAS guard on 4 handlers

### Implementation pattern (per handler)

Each of the 4 handlers (`cortex_approve`, `cortex_edit`, `cortex_refresh`, `cortex_reject`) gets this pattern at the very top of its body, before any other DB read or write:

```python
def cortex_approve(*, cycle_id: str, body: dict) -> dict:
    """..."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cortex_cycles
                SET status = 'approving', updated_at = NOW()
                WHERE cycle_id = %s AND status = 'proposed'
                RETURNING cycle_id
                """,
                (cycle_id,),
            )
            row = cur.fetchone()
            if row is None:
                # Another invocation already transitioned this cycle out of 'proposed'.
                # Re-read current status for diagnostic; HTTP 200 (idempotent retry).
                cur.execute(
                    "SELECT status FROM cortex_cycles WHERE cycle_id = %s",
                    (cycle_id,),
                )
                current_row = cur.fetchone()
                current = current_row[0] if current_row else "<not-found>"
                conn.commit()
                return {
                    "warning": "already_actioned",
                    "current_status": current,
                    "cycle_id": cycle_id,
                    "action_attempted": "approve",
                }
            conn.commit()
        # ... rest of existing approve logic continues unchanged
        # (it can assume status was 'proposed' and is now 'approving';
        # final transition to 'approved' happens in _archive_cycle)
    except Exception:
        conn.rollback()
        raise
    finally:
        _put_conn(conn)
```

### Per-handler CAS pre-conditions

| Handler | WHERE clause | New intermediate status | Action_attempted label |
|---|---|---|---|
| `cortex_approve` | `status = 'proposed'` | `'approving'` | `"approve"` |
| `cortex_edit` | `status = 'proposed'` | `'editing'` | `"edit"` |
| `cortex_refresh` | `status = 'proposed'` | `'refreshing'` | `"refresh"` |
| `cortex_reject` | `status = 'proposed'` | `'rejecting'` | `"reject"` |

### Status state machine (post-patch)

```
proposed → approving → approved (Phase 6 archive)
proposed → editing → edited → proposed (re-loop) OR approved
proposed → refreshing → re-runs Phase 3 → proposed
proposed → rejecting → rejected (terminal)
```

Intermediate `*ing` states are short-lived (<5s typical) but durable — visible to monitoring during execution. If a handler crashes mid-execution, the cycle stays in `*ing` state and a follow-up sentinel (parked at `_ops/ideas/2026-04-28-cortex-archive-failure-alerting.md`) will catch it post-V1.

### `_archive_cycle` change (1 line)

**Current** (`cortex_phase5_act.py:376-416`):
```python
cur.execute("UPDATE cortex_cycles SET status='approved', ... WHERE cycle_id=%s", (cycle_id,))
```

**New** (defensive — should already be `approving` due to CAS):
```python
cur.execute(
    "UPDATE cortex_cycles SET status='approved', ... WHERE cycle_id=%s AND status='approving' RETURNING cycle_id",
    (cycle_id,),
)
if cur.fetchone() is None:
    # Cycle was not in 'approving' state — log warning, leave as-is
    logger.warning(
        "cortex_archive_cycle_unexpected_state",
        extra={"cycle_id": cycle_id, "expected": "approving"},
    )
    return {"warning": "archive_unexpected_state", "cycle_id": cycle_id}
```

---

## Fix/Feature 2: Partial-failure surfacing on GOLD writes

### Implementation

In the function/section that calls `_write_gold_proposals` (likely inside `cortex_approve` body), after the loop completes:

```python
# ... existing per-file loop ...
written = len([r for r in results if r.get("status") == "ok"])
total = len(selected_files)

if total > 0 and written == 0:
    # All GOLD proposals failed — Director must know
    return {
        "status": "approved_with_errors",
        "warning": "all_gold_proposals_failed",
        "cycle_id": cycle_id,
        "gold_files_attempted": total,
        "gold_files_written": 0,
        "errors": [r.get("error") for r in results if r.get("status") != "ok"],
    }
elif total > 0 and written < total:
    return {
        "status": "approved_with_partial_errors",
        "warning": "some_gold_proposals_failed",
        "cycle_id": cycle_id,
        "gold_files_attempted": total,
        "gold_files_written": written,
        "failed_files": [r.get("filename") for r in results if r.get("status") != "ok"],
    }
# else: full success path (existing return)
```

The dashboard endpoint that calls into `cortex_approve` and posts to Slack should surface these warnings in the Slack DM update.

---

## Files Modified

- `orchestrator/cortex_phase5_act.py` — 4 handlers get CAS guard at top + `_archive_cycle` gets WHERE-clause hardening + `_write_gold_proposals` caller gets partial-failure surfacing
- `tests/test_cortex_phase5_idempotency.py` — NEW. 12 tests minimum (3 per handler × 4 handlers = 12 idempotency tests covering: first-fire happy path / second-fire idempotent return / third-fire still idempotent return). Plus 2 for partial-failure surfacing (all-fail / some-fail).
- `tests/test_cortex_phase5_act.py` — UPDATE if existing tests assume unconditional UPDATE; add CAS-guard fixtures.

## Files NOT to Touch

- `orchestrator/cortex_phase4_proposal.py` — Phase 4 is fine; idempotency concern is on Phase 5 transitions only.
- `orchestrator/cortex_runner.py` — runner sequencing already handles `proposed → in_flight` gracefully.
- `migrations/*.sql` — NO schema change. CAS guard uses existing `status` column.
- `kbl/gold_writer.py` / `kbl/gold_proposer.py` — boundary preserved (Amendment A1 in PR #74).
- `dashboard.py` `POST /cortex/cycle/{id}/action` — endpoint signature stays; new warning fields are additive in JSON response.
- `scripts/cortex_rollback_v1.sh` — not affected.

## Verification (Lesson #47 — literal pytest mandatory)

```bash
cd ~/bm-b2
pytest tests/test_cortex_phase5_idempotency.py tests/test_cortex_phase5_act.py -v 2>&1 | tail -50
pytest tests/test_cortex_*.py tests/test_alerts_to_signal*.py -v 2>&1 | tail -10  # full regression
```

Paste literal stdout into ship report. **All new tests must pass + 1A's 31/31 + 1B's 48/48 + 1C's 82/82 must still pass** (full cortex regression: 161+ + new). NO "by inspection."

## Quality Checkpoints

1. CAS guard fires on `cortex_approve` second invocation → returns `warning="already_actioned"` with `current_status` reflecting actual state.
2. Same for `cortex_edit` / `cortex_refresh` / `cortex_reject` (3 separate tests).
3. CAS guard does NOT fire on first invocation → handler proceeds normally.
4. `_archive_cycle` hardened WHERE clause — if cycle is not in `'approving'` state, returns warning, does NOT silently overwrite.
5. `_write_gold_proposals` partial-failure path: 3 selected files, all 3 fail → returns `status="approved_with_errors"`.
6. Same: 3 selected files, 2 fail → returns `status="approved_with_partial_errors"` with `failed_files` list.
7. Same: 3 selected files, 0 fail → returns existing success path unchanged.
8. Status state machine: `proposed → approving → approved` transitions visible in `cortex_cycles` row.
9. Zero schema changes (no new migration; existing `status` column accepts new transient values via existing CHECK constraint or no constraint — verify which).
10. Zero changes to `kbl/gold_writer.py` / `kbl/gold_proposer.py` / `dashboard.py` endpoint signature (additive JSON fields only, no breaking changes).

## Verification SQL (post-deploy, not test-time)

```sql
-- Confirm new transient statuses populate during execution
SELECT cycle_id, status, updated_at
FROM cortex_cycles
WHERE status IN ('approving', 'editing', 'refreshing', 'rejecting')
ORDER BY updated_at DESC LIMIT 10;
-- Expect: rows during DRY_RUN test cycle if they appear; quick transit (<5s) means we're seeing intermediate state correctly.
```

## /security-review (Lesson #52 mandatory)

Trigger class MEDIUM (per b1-situational-review-trigger; cross-capability state-write hardening on cortex_cycles + GOLD path). After b3 second-pair-review APPROVE, AI Head A runs `/security-review` skill. Both verdicts gate the merge. AI Head A merges Tier-A on all-clear.

## Self-PR rule reminder

Same canonical pattern as PR #67/#69/#70/#71/#72/#74: open PR, post `/security-review` verdict as PR comment (formal APPROVE blocked by self-PR rule), AI Head A Tier-A direct squash-merge after b3 + A both clear.

## Risk + rollback

Rollback path: revert the patch commit (single file change in `cortex_phase5_act.py`). No schema migration to roll back. CAS guard adds defensive UPDATE — removing it returns to PR #74 behavior (silent double-fire).

If CAS guard introduces regression in DRY_RUN cycle (e.g. status transition wrong), Step 30 promotion is delayed by however long the patch takes — DRY_RUN doesn't ship live cycles until idempotency is proven.

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
