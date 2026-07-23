-- 20260723a_close_stuck_cortex_cycles.sql
-- CORTEX_RETIRE_PHASE1_1 — close the residual stuck Cortex cycles.
--
-- Binding spec: briefs/BRIEF_CORTEX_RETIRE_PHASE1_1.md (Director-ratified Cortex
-- retirement 2026-07-23). Decision memo:
-- briefs/_plans/CORTEX_RETIREMENT_MEMO_2026-07-23.md.
--
-- Cortex is retired (38 cycles ever, last 2026-05-20, 64 days zero demand). Two
-- rows remain in the non-terminal 'tier_b_pending' status and, with the cycle
-- service now guarded off, they can never be advanced by a live cycle. Sweep
-- them to the terminal 'rejected' status so the stuck-cycle sentinel (also
-- disabled by this brief) has nothing left to alarm on and the history tables
-- read cleanly.
--
-- Scope: this is a DATA migration only. It does NOT drop, rename, or
-- schema-change cortex_cycles / cortex_phase_outputs (those tables stay intact
-- for read-only history per the retirement brief). Idempotent: after the first
-- run the WHERE clause matches 0 rows, so re-application is a no-op. The
-- LIMIT-free UPDATE is acceptable because the WHERE is a terminal-state sweep of
-- a bounded, non-terminal status (2 rows verified 2026-07-23).

BEGIN;

UPDATE cortex_cycles
   SET status = 'rejected'
 WHERE status = 'tier_b_pending';
-- Expected rowcount: 2 (verified 2026-07-23). Re-runs affect 0 rows.

COMMIT;
