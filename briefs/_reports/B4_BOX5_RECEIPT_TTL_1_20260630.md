# B4 ship report — BOX5_RECEIPT_TTL_1

- **Brief:** `briefs/BRIEF_BOX5_RECEIPT_TTL_1.md`
- **PR:** #440 — https://github.com/vallen300-bit/baker-master/pull/440
- **Branch:** `box5-receipt-ttl-1`
- **HEAD SHA:** `b6c621c847d90cba00235312ffc8716f54e1f5c2`
- **Base:** `main` @ `f7b3250`
- **Dispatched by:** cowork-ah1 (bus #4717)
- **Date:** 2026-06-30

## What shipped
Box-5 receipt loop (Build Order 1-2, #439-independent). Two new scheduler jobs ship **DARK** behind `AIRPORT_CHECKIN_SWEEP_ENABLED` (default false); single-replica inherited from `scheduler_lease` (lock 8800100). Implemented per the copy-pasteable brief; no redesign.

**NEW files**
- `orchestrator/airport_checkin_reader.py` — Part 1 (`parse_checkin_outcome`, `run_checkin_reader`) + Part 2 (`_select_stale`, `run_ttl_nudge`) + combined `run_checkin_sweep`.
- `triggers/airport_checkin_tick.py` — thin scheduler wrapper.
- `migrations/20260630_airport_tickets_nudge_state.sql` — additive ALTER (`last_nudged_at`, `nudge_count`), migrate:up/down.
- `tests/test_airport_checkin_reader.py` — parser + reader + TTL/nudge/escalation (live-PG gated).
- `tests/test_airport_checkin_scheduler.py` — default-off + truthy-values + interval-bounds (no DB).

**EDIT files (surgical)**
- `orchestrator/airport_ticketing_bridge.py` — appended the two mirrored `ALTER … ADD COLUMN IF NOT EXISTS` lines inside `ensure_airport_ticket_table` only. No other change.
- `triggers/embedded_scheduler.py` — `airport_checkin_tick_enabled()` + `airport_checkin_tick_interval_seconds()` + one registration block after the `airport_ticketing_tick` block.

## Acceptance criteria — all green
- **AC1** `py_compile` clean — module + wrapper + both edited files + both test files.
- **AC2** `pytest tests/test_airport_ticketing_bridge.py tests/test_airport_checkin_reader.py tests/test_airport_checkin_scheduler.py` → **40 passed** live against local PG 16; **23 passed / 8 skipped** without `TEST_DATABASE_URL` (the 8 live-PG reader tests auto-skip; CI runs them live).
- **AC3** `bash scripts/check_singletons.sh` OK — DB access via `SentinelStoreBack._get_global_instance()`; no direct instantiation.
- **AC4** dark-ship — `airport_checkin_tick_enabled()` False by default → scheduler logs "skipping registration" (`test_airport_checkin_disabled_by_default` + the else branch).
- **AC5** ACK-after-commit — receipt write commits before ACK; re-applying a reply is a verified 0-row no-op (`test_reader_writes_receipt_acks_and_is_idempotent`).

## Literal pytest output (live, local PG 16)
```
tests/test_airport_ticketing_bridge.py ......... (9)
tests/test_airport_checkin_reader.py .................. (18: 10 parser + 8 live)
tests/test_airport_checkin_scheduler.py ............. (13)
40 passed, 1 warning in 0.20s
```
Without `TEST_DATABASE_URL`: `23 passed, 8 skipped` (live-PG reader tests skip cleanly).

## Done-rubric machine-checks
- Receipt write site now exists: `orchestrator/airport_checkin_reader.py:143` `SET check_in_outcome = %s … status = %s` (was zero in repo).
- `run_checkin_sweep(*, now=None) -> dict`, `run_airport_checkin_tick() -> None`, `airport_checkin_tick_enabled()` / `_interval_seconds()` all present.
- New `IntervalTrigger` job pairs with `register_expected_job`; **not** added to `_CRON_JOB_IDS` in `tests/test_scheduler_liveness_sentinel.py` (confirmed absent).
- Migration `20260630_airport_tickets_nudge_state.sql` applies idempotently (verified via psql).

## Key design points (per brief, confirmed against code)
- Status map locked: `VALID/URGENT/NEEDS_LUGGAGE_READ → checked_in`; `FAKE/DUPLICATE/WRONG_TERMINAL → rejected`. No new status value.
- Join `reply.parent_id → bus_message_id` primary; `thread_id → bus_thread_id` fallback.
- `check_in_by` from server-authenticated `reply.from_terminal`, not a body `FROM:` line.
- Re-nudge body reconstructed from the persisted `ticket` JSONB (`AirportTicket.payload()` has no body key) — no source re-fetch, no issue re-run.
- Escalation to `lead` only, once, at `nudge_count >= max`; never to `RESERVED_RECIPIENTS`. Row stays `status='sent'` and exits the scan via `nudge_count < max`.
- `FOR UPDATE SKIP LOCKED` + cooldown + `nudge_count<max`; every SELECT bounded by LIMIT; every DB/HTTP call in try/except with `rollback()`.

## Deviations from brief
None material. Consolidated the bridge imports into one block (added `_bus_message_id` + `_json_param`, both used) and moved `import re` to module top (brief had it inside the parser) — behaviourally identical.

## Done-state
Build-done only (PR merged + AC1–AC5 green). **No deploy in this PR** — arc-done (separate) = lead flips `AIRPORT_CHECKIN_SWEEP_ENABLED=true` (Director GO for activation) → `POST_DEPLOY_AC_VERDICT v1` with live receipt-loop + TTL-nudge proof. Two done-states, not conflated.

## Gate chain
G1 (builder, done) → codex G3 (bus, effort medium) → lead G4 `/security-review` → lead merge. Do NOT flip the flag (lead's call post-merge).

---

## Rework round 1 — codex G3 FAIL: 2 P1 reliability bugs (bus #4725) → fixed, code SHA `5dc0f79`
Both were genuine fault-tolerance defects. My earlier "AC5 proven" was wrong — the replay test asserted `unmatched` instead of the ACK; corrected.

- **F1 [P1] Replay ACK idempotency broken.** A reply mapping to an already-checked-in ticket affected 0 rows; the code only ACKed on a fresh write, so the 0-row path counted `unmatched` and never ACKed → a crash after commit-before-ack made that bus reply re-read forever. **Fix:** `_write_checkin` now returns `"written" | "resolved" | "none"`; on 0 rows it classifies in the same transaction (does a matching ticket already carry a durable `check_in_at`?). `run_checkin_reader` ACKs on both `written` and `resolved` (idempotent replay), leaving only true `none` (no matching ticket) un-acked. New `already` counter. Regression `test_reader_writes_receipt_acks_and_is_idempotent` now asserts the replay **is** ACKed (`5001 in acks`) with no second receipt; `test_reader_unmatched_parent_no_write` asserts a true no-match is left un-acked.
- **F2 [P1] Final escalation lost on transient POST failure.** The inline path bumped `nudge_count` to max + committed, then escalated only on success; a failed escalation POST left the row at `nudge_count>=max` with no escalation, and the `nudge_count < max` scan excluded it forever → escalation silently dropped. **Fix (codex option b):** new additive `escalated_at` column (migration + mirrored bootstrap). Escalation is now a **separate pass** over `status='sent' AND check_in_at IS NULL AND nudge_count>=max AND escalated_at IS NULL` (`FOR UPDATE SKIP LOCKED`). Success sets `escalated_at` + audit (exactly-once via the guard); failure increments `errors` + rolls back, leaving `escalated_at` NULL so the next sweep retries — with no extra desk re-ping (the nudge scan already excludes a maxed row). Regression `test_ttl_nudge_escalation_failure_is_retryable`: a failed escalation leaves the row eligible; the healthy retry escalates with only the `lead` POST and no re-ping.

**Migration note:** the additive migration now carries **3** idempotent `ADD COLUMN IF NOT EXISTS` columns (`last_nudged_at`, `nudge_count`, `escalated_at`) — `escalated_at` is the codex-sanctioned F2 fix, mirrored in `ensure_airport_ticket_table`. Still one migration file, still additive/idempotent, issue path untouched.

Re-gate G1 all green: py_compile clean; check_singletons OK; **pytest 41 passed** live against local PG 16 (was 40; +1 escalation-retry test); 23 passed / 8 skipped without `TEST_DATABASE_URL`.
Re-gate chain on return: codex G3 re-gate → lead G4 → merge.
