# BRIEF — BOX5_OUTBOUND_CORRELATION_FIX_1 (fix the live defect canary #4881 caught in the outbound connector)

**Author:** lead (AH1). **dispatched_by:** lead. **Ship report + gate verdicts → lead.**
**Task class:** production bug fix, additive/corrective; connector stays DARK behind `AIRPORT_OUTBOUND_INGEST_ENABLED` (lead rolled it back to false). **Harness-V2:** full.
**Builder:** b4 (built Increment 2 + diagnosed this defect in canary #4881).

## Context
The live canary (#4881, in-process against prod) proved the downstream state machine correct BUT found a defect that makes the whole outbound path non-functional in prod. Lead has already **rolled back** `AIRPORT_OUTBOUND_INGEST_ENABLED=false` (verified). This brief fixes the defect so we can re-gate → re-activate → re-canary.

### Surface contract: N/A — backend connector correlation fix; no clickable UI.

## Estimated time: ~2h · Complexity: Medium · Prerequisites: none (connector merged, PR #447)

## Diagnose gate (canary #4881 — build on this, do not re-litigate)
`orchestrator/airport_outbound_connector.py` `correlate()` step 4 → `_correlate_dispatcher_flight` runs:
`SELECT thread_key FROM dispatcher_bus_threads WHERE status IN ('open','waiting_reply') AND thread_key=%s …`
- **Bug A — schema mismatch:** prod `dispatcher_bus_threads` has **no `thread_key` column**; the real thread column is **`bus_thread_id`**. Full prod cols: `id, clickup_task_id, owner_slug, recipient_slug, bus_message_id, bus_thread_id, status, reason_code, condition_hash, last_sent_at, last_reply_at, payload, dedup_key, created_at, updated_at`. The `to_regclass('public.dispatcher_bus_threads')` guard PASSES (table exists) so the query is NOT skipped → `UndefinedColumn`. **Also the status vocabulary is wrong**: prod status values include **`replied`** (verified live), not `'open'`/`'waiting_reply'` (those don't exist). Confirm the real enum by grepping the dispatcher writer.
- **Bug B — except-without-rollback (the load-bearing hazard):** the `except` catches the error, returns `None`, but never `conn.rollback()`s. Under the connector's single-shared-transaction model (no commit; the bridge owns per-row commit), the PG txn is now **ABORTED**. The next write (`_update_event`) raises `psycopg2.errors.InFailedSqlTransaction`, **uncaught** in `process_outbound_event`, propagating to the bridge. `correlate()` runs for EVERY non-system outbound → **every ratifying AND routine outbound errors**. This is general: ANY transient correlation-read error nukes the whole event, not just this column bug.
- **Why tests missed it:** the unit-test `dispatcher_bus_threads` fixture either lacks the table (`to_regclass` None → early return) or doesn't match prod schema — so the mismatch was masked. **Fixture fidelity is part of this fix.**

## Engineering Craft Gates
- **Diagnose:** applies — done above (canary #4881). Feedback loop = new schema-accurate pytest + a re-canary after merge.
- **Prototype:** N/A — fix is settled.
- **TDD/verification:** applies — write the reproduction test FIRST: a schema-accurate `dispatcher_bus_threads` fixture + an assertion that a correlation-read error leaves the connector able to complete the event (no `InFailedSqlTransaction`). It must FAIL against current code, PASS after the fix.

## Implementation
1. **Fix Bug A (column + status vocab)** in `_correlate_dispatcher_flight` (and any sibling correlation read touching `dispatcher_bus_threads`):
   - `thread_key` → `bus_thread_id` in BOTH the SELECT and the WHERE.
   - Replace `status IN ('open','waiting_reply')` with the REAL non-terminal/active vocabulary. Grep the dispatcher writer (`orchestrator/dispatcher*.py`) for the status enum; "active flight" = threads not yet closed/resolved (prod shows `replied`; enumerate the full set — do not guess). If uncertain which statuses count as "active", prefer the explicit set the dispatcher uses for open work and document the choice.
2. **Fix Bug B (savepoint-guard every defensive correlation read)** — the load-bearing fix:
   - Wrap EACH defensive read in `correlate()` (steps 1-4, incl. thread + dispatcher-flight reads) in a `SAVEPOINT` and `ROLLBACK TO SAVEPOINT` on except — so a read error rolls back ONLY that read and the shared txn stays usable for the subsequent `_update_event` write. A plain `conn.rollback()` is WRONG here (it would discard the connector's prior good writes in the shared txn).
   - Audit ALL `except` blocks in the connector that precede a write for the same pattern; apply the savepoint guard uniformly.
3. **Fixture fidelity + tests** in `tests/test_box5_outbound_increment2.py`:
   - Make the `dispatcher_bus_threads` test fixture SCHEMA-ACCURATE to prod (real columns incl. `bus_thread_id`, real status values) so a schema-mismatch can never hide again.
   - Add: dispatcher-flight correlation works against the real schema (positive path).
   - Add: a correlation read that RAISES → `process_outbound_event` still completes the event to its correct state (EVIDENCE_ONLY / CLICKUP_BLOCKED / RATIFICATION_READY) with NO `InFailedSqlTransaction` (savepoint isolation).
   - Keep the existing 16 ACs green.

## Key Constraints
- Connector stays DARK (flag false) — this fix does not flip it; lead re-activates after gate+merge.
- Savepoint per correlation read; never a bare `conn.rollback()` that discards prior good writes in the shared txn (`.claude/rules/python-backend.md`).
- No new external calls; no ClickUp write path change; downstream state machine already proven — do not touch it beyond what the txn-safety fix requires.
- No migration (schema read fix only). Do NOT touch inbound D/E/(f) or the bridge outbound branch beyond what's needed.

## Verification (pytest, literal)
- Repro test fails on current code, passes after fix.
- Dispatcher-flight correlation returns correctly against a prod-accurate fixture.
- Correlation-read error → event still completes, no aborted-txn propagation.
- All 16 prior ACs green. `py_compile` + `scripts/check_singletons.sh` clean.

## Files Modified
- `orchestrator/airport_outbound_connector.py` — column + status fix; savepoint-guard correlation reads.
- `tests/test_box5_outbound_increment2.py` — schema-accurate fixture + repro/regression tests.

## Do NOT Touch
- The flag default / activation (lead owns). Inbound D/E/(f) lanes. The migration. The proven downstream state machine (ClickUp/flight write logic) except for txn-safety.

## Gate plan
G1 self-check (py_compile + full pytest + `bash scripts/check_singletons.sh`) → codex **G3 on the BUS** (topic `gate/box5-outbound-correlation-fix-g3`, effort HIGH; focus: real-schema correlation, status vocabulary correct, savepoint isolation prevents txn-abort, fixture matches prod, all 16 ACs still green) → lead **G4 `/security-review`** → lead squash-merge. FAIL → findings to b4, rework, re-gate.

## Done rubric
Done = the dispatcher-flight correlation runs against the real prod schema without error; ANY correlation-read error is savepoint-isolated so the event still completes (no `InFailedSqlTransaction`); the test fixture matches prod schema; repro test + 16 ACs green; codex G3 PASS; G4 clean. After merge, lead re-activates + re-runs the canary for the full end-to-end proof. Ship report answers THIS rubric.

## Branch / hygiene
Branch `box5-outbound-correlation-fix-1`. Path-scoped commits. Co-author trailer: Claude Opus 4.7 (1M context).
