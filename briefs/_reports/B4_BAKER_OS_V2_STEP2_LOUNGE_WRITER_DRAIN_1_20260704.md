# B4 ship report — BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1

- **PR:** #458 → main · branch `b4/step2-lounge-writer-drain-1`
- **Dispatcher:** lead · **Class:** production, feature-flagged, reversible · **State:** dark (flag OFF, merge = no-op)
- **Gate:** G1 self ✅ → G3 codex (medium) → G4 AH1 /security-review → AH1 merge + flag flip + live canary (gated on your GO)

## Done rubric / AC answers (live proofs)
- **AC1 — 0 orphans after drain.** `reconcile()` + `ORPHAN_SQL` left-join proves 0 checked-in VALID/URGENT BB tickets without a lounge row. Test `test_ac1_reconcile_zero_orphans_after_drain` GREEN.
- **AC2 — event rows + idempotent.** `airport_outbound_events` row with `clickup_task_id` per ticket; re-run skips (no dup task). `test_ac2_ratifying_creates_one_task_and_event`, `test_ac2_idempotent_rerun_no_duplicate` GREEN.
- **AC3 — exception lane visible.** No-matter ticket → `update required` parking task + `NEEDS_CONTROLLER` event + `ttl_renudge_pending` marker. Re-nudge scheduler intentionally a loud-logged stub (flagged). `test_ac3_exception_lane_visible_parking` GREEN.
- **AC4 — cap + kill switch.** ≤10 ClickUp writes/cycle enforced in the drain loop (only ACT_WRITE/ACT_PARK consume budget); deferred-past-cap drain next cycle. `BAKER_CLICKUP_READONLY` dry-run logs intended writes, no ClickUp call. `test_ac4_write_cap_enforced_two_cycles`, `test_ac4_dry_run_readonly_logs_no_write` GREEN.
- **AC5 — flight NULL (D-23).** `FLIGHT_NULL_SQL` = 0 leak; asserted on every written row. GREEN.
- **AC6 — tests.** New AC2/AC3/AC4 tests + existing suites green.

## Design decisions (surfaced per brief)
- **New module** `orchestrator/airport_lounge_writer.py` (not an extension of the connector) — keeps the ratification connector focused; reuses its event table + space-guard + audit via import (single-source, no drift).
- **Event key scheme** `airport-lounge:<source_ticket_id>` (distinct from `airport-outbound:<message_id>`); idem key `airport-lounge:v1:<ticket_id>`; trigger_source `airport_lounge_writer`.
- **Desk→list map** `baden-baden-desk → 901524194809` (BB-AUK-001 Timetable). Unknown desk → exception lane (`no_target_list`), never a mis-routed write. Config-table design deferred if more lists onboard.
- **Disposition:** no list → BLOCK (event-only, loud log); list but no matter_slug → PARK (`update required` + NEEDS_CONTROLLER); else WRITE (`to do`, priority 1 urgent / 3 normal).
- **Dup-scan (D-28):** group by `source_id`; urgent-then-oldest primary writes, rest → EVIDENCE_ONLY + `dup_of`.

## Test evidence
- 21/21 GREEN vs local Postgres 16 (10 pure-unit run everywhere; 11 live-PG auto-skip without TEST_DATABASE_URL/NEON — CI provisions). Connector+bridge suites 33/33 regression-clean.
- End-to-end 16-ticket live-sim (fake ClickUp): cycle1=10 writes / cycle2=6 (+10 idempotent-skip), urgent-first, 16 tasks total, 0 orphans, 0 flight leaks.

## Live drain (gated — awaiting your GO)
Operator entry `scripts/run_lounge_drain.py`. Recommend dry-run first:
`DATABASE_URL=... AIRPORT_LOUNGE_WRITER_ENABLED=true BAKER_CLICKUP_READONLY=true python3 scripts/run_lounge_drain.py`
then live (drop readonly). POST_DEPLOY_AC verdict to follow after the real drain run per post-deploy-ac-bus-gate.
