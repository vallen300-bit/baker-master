# B2 SHIP — WAKE_GUARD_FRESH_ROW_FIX_1

- **Dispatched by:** lead #7374 (from codex #7369 G3 finding on brisen-lab #105; out of
  TICKET_ID_DEDUP_1 scope — split to this brief). Priority above idle.
- **Date:** 2026-07-08
- **PR:** brisen-lab #106 · branch `b2/wake-guard-fresh-row-fix-1`.

## Defect
`bus._slug_live_elsewhere_sync` (brisen-lab/bus.py) is the cross-host duplicate-spawn
guard (F2 of WAKE_HANDLER_DUPLICATE_SPAWN_HARDENING_1): the Mac-Mini wake handler skips
a Terminal **spawn** when `GET /api/slug_live/<alias>` reports the alias fresh-live on
**any** host. The query picked exactly one row — `ORDER BY started_at DESC LIMIT 1` —
and returned *that* row's freshness. So a newer-started **stale/failed clone** (dead
heartbeat) **masked** an older-started still-live laptop session (fresh `last_alive_at`)
→ `slug_live=false` → the guard permitted the very cross-host duplicate spawn it exists
to prevent. Pre-existing; not introduced by #105 (my #105 diff never touched this fn).

## Fix
`EXISTS` over **any** open row with a fresh `last_alive_at` (within
`WORKING_FRESH_THRESHOLD_S`) instead of the freshness of the single newest-started row.
No single stale row can hide a live one. Fail-open + `last_alive_at`
(LIVENESS_WORKING_SPLIT_1) semantics unchanged; single-row fresh/stale/idle/dead
behavior identical.

## Tests — `tests/test_wake_duplicate_spawn_hardening.py`
- `test_slug_live_stale_newer_clone_does_not_mask_live_older` — mixed fresh-older +
  stale-newer both open → `live_elsewhere` True (both `_slug_live_elsewhere_sync` and the
  `/api/slug_live` endpoint). **Verified FAILS on the old query, PASSES on the fix.**
- `test_slug_live_multiple_all_stale_sessions_false` — converse: multiple open, all stale
  → False, so the fix can't over-correct to any-OPEN-row.

## Verification (literal pytest, local Postgres)
Ran against a local PG (`TEST_DATABASE_URL` set to a scratch DB) — not skipped:
- `test_wake_duplicate_spawn_hardening.py`: **11 passed** (my 2 new + 8 existing single-row
  + F1 source guard — proving the fix preserves single-row behavior).
- Regression proof: reverted `bus.py`, the mixed-session test **FAILED**; restored, it
  **PASSES**.
- Wider sweep (wake + schema + bus + ticket-dedup daemon): **76 passed**.

## Notes for lead
- Delta-scope re-gate requested to codex on this one finding.
- Closes a live cross-host duplicate-spawn hole in the anti-clone guard.
