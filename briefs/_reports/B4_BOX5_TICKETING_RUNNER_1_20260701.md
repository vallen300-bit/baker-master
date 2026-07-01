# B4 ship report — BOX5_TICKETING_RUNNER_1

- **Brief:** `briefs/BRIEF_BOX5_TICKETING_RUNNER_1.md`
- **PR:** #442 — https://github.com/vallen300-bit/baker-master/pull/442
- **Branch:** `box5-ticketing-runner-1`
- **HEAD SHA:** `8a168eb6a71389778fb391127e133cc12d071327`
- **Base:** `main` @ `a87cab2`
- **Dispatched by:** cowork-ah1 (bus #4740)
- **Date:** 2026-07-01

## What shipped
Box 5 Build Order 5 — the runner. EXTENDS the existing `airport_ticketing` `run_tick` in `orchestrator/airport_ticketing_bridge.py` (no new scheduler/lease/cursor table; single-replica still inherited from `scheduler_lease` 8800100). Ships DARK behind `AIRPORT_TICKETING_BRIDGE_ENABLED` + new `BOX5_FAST_LANE_ENABLED` (both default false). One file changed + one new test file.

New helpers (same file): `fast_lane_enabled()`, `write_terminal_status()` (status-guarded single write + audit), `_claim_for_terminal()` (FOR UPDATE SKIP LOCKED), `reserve_noise_row()` (shape i), `_count_stuck_arrivals()`, `_advance()`, `trigger_state_get/set_watermark()` (lazy wrappers).

run_tick extension: per-source cursor via `trigger_watermarks` key `airport_ticketing:email` (lookback kept as floor); deterministic clears DUPLICATE + REJECT_NOISE; safe-default TICKET; error-never-auto-clears; None-id reserve-race no-op; watermark advances only to max processed; per-tick stats + log; stuck gauge. No D/E logic.

## Acceptance criteria
- **AC1** `py_compile` clean; `check_singletons.sh` OK.
- **AC2** reliability matrix `tests/test_box5_ticketing_runner.py` → **10 passed** live PG 16; existing airport bridge + checkin + terminal tests → **36 passed** (no regression); all auto-skip without `TEST_DATABASE_URL` (CI live).
- **AC3** re-run over an already-terminal row = 0 rows updated — proven by `test_idempotent_terminal_write` (run twice, `terminal_written==0` on run 2, `terminal_outcome_written_at` unchanged).
- **AC4** — see conflict note below.
- **AC5** a raised exception in classify leaves `terminal_status` NULL + increments `failed` — `test_error_never_auto_clears`.

## Literal pytest output (live, local PG 16)
```
tests/test_box5_ticketing_runner.py ..........  (10 passed)
tests/test_airport_ticketing_bridge.py + test_airport_checkin_reader.py + test_airport_terminal_columns.py  (36 passed, no regression)
```

## Done-rubric machine-checks
- Extends `run_tick`; `grep -c "add_job|IntervalTrigger"` in the file = **0** (no new scheduler).
- `grep -c "FOR UPDATE SKIP LOCKED"` = **1**.
- The single `SET terminal_status` (line ~835) is immediately followed by `WHERE id=%s AND terminal_status IS NULL`. No unguarded terminal write.
- `fast_lane_enabled()` returns False when env unset.
- Error path increments `failed`, never `deterministic_cleared`, never writes `REJECT_NOISE`/`DUPLICATE`.
- Stats dict carries `claimed, terminal_written, lease_skipped, deterministic_cleared, defaulted_ticket, stuck_arrivals` (+ existing + `fast_lane`).
- Only `DUPLICATE`/`REJECT_NOISE`/`TICKET` written; no `FAST_TICKET`/project/manifest/`VISIBLE_HOLD` write logic.
- Issue path (`reserve_ticket`/`issue_ticket`/`mark_ticket_*`) + both live CHECKs untouched (diff deletions confined to the old `run_tick` body).

## ⚠️ AC4 wording conflict — surfaced to lead (do not silently average)
AC4 (both envelope and brief) reads: *"BOX5_FAST_LANE_ENABLED=false → every arrival → TICKET (no deterministic clearing); flag true → DUPLICATE/REJECT_NOISE clear deterministically."*

This **contradicts** the rest of the brief:
- The brief's `run_tick` pseudo-code does deterministic clears **unconditionally** and computes `fast_lane` without ever branching on it.
- The brief's own comments: *"In BRIEF-C there is no fast lane yet — this only future-proofs D/E"* (line 112) and *"honored now; only future-proofs D/E"* (line 227).
- Blocker 7b: *"…routes every non-deterministic-clear arrival to the safe default…while the runner still clears backlog"* — clears still happen when the flag is off.
- Operational safety: routing genuine automated-sender noise to a human desk (what AC4-literal implies when the flag is off) is the opposite of safe.

**Implemented:** the brief-body reading — deterministic clears (DUPLICATE/REJECT_NOISE) always on; `fast_lane` is read + surfaced in the stats dict and gates only the future D/E lanes (which don't exist yet). `fast_lane_enabled()` still defaults false (done-rubric #4 satisfied).

If lead instead wants the literal AC4 (gate DUPLICATE/REJECT_NOISE behind `fast_lane`, route everything to TICKET when off), it is a localized change in the run_tick clear branches — flag it at G4 and I'll turn it in one pass. Recommending the brief-body reading stands (matches the explicit "only future-proofs D/E" + safety).

## Decisions surfaced (per brief)
- **`reserve_noise_row` shape (i)** chosen (brief-preferred): a minimal `airport_tickets` row keyed by `_dedup_key('email', message_id, 'unrouted')` so the single status-guarded terminal write has a target and repeated noise de-dups. Sentinel desk slug = `'unrouted'`.
- **`baker_actions` insert shape** confirmed: `(action_type, target_task_id, payload, trigger_source, success)` with `_json_param()` + `TRUE`, matching `reserve_ticket`/`mark_ticket_sent` (no `jsonb_build_object`, no `created_at`).
- **SKIP LOCKED note:** intra-tick row safety only; single-replica is already inherited from lock 8800100 — no second lock added.

## Done-state
Build-done only (PR merged + AC1–AC5 green). Ships DARK; NO activation this build (later Director GO via flag flip). C must merge before D/E dispatch (they plug into C's classify hook in this file).

## Gate chain
G1 (builder, done) → codex G3 (bus, effort medium, focus reliability) → lead G4 `/security-review` → lead merge.
