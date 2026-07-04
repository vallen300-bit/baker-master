# BAKER_OS_V2_STEP2_ONWARD_JOURNEY_BLOCKS_2_4_1

**Repo:** `baker-master` (base `main` @9d81c0d) · **Worker:** b4 · **Dispatcher:** lead (AH1)
**Recommended effort:** high (bus protocol + prod ClickUp status writes on real legal traffic; new DB constraint migrations)
**Origin:** Baker OS V2 step-2 pilot spec (D-30): `baker-vault/_ops/build/baker-os-v2/05_outputs/baker-os-v2-step2-bb-desk-onward-journey-pilot-spec-cowork-ah1-20260703.md`. This brief = scope blocks 2 (Gate+Boarding claim) + 3 (In-Flight status mirror per D-25) + 4 (Landing + Arrival Receipt). Blocks 1/5/6 shipped as BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1 (PRs #458/#459, live, 20/20 drained).

## Context Contract

- **Task class:** production implementation, feature-flagged, reversible.
- **Entry points you built / know:**
  - `orchestrator/airport_lounge_writer.py` — your block-1/5/6 module. 20 lounge rows now sit at `event_state='CLICKUP_WRITTEN'` (`ticket_id` scheme `airport-lounge:<source_ticket_id>`), ClickUp tasks at status "to do" in BB-AUK-001 Timetable (`901524194809`).
  - `orchestrator/airport_outbound_connector.py` — D-25 resolver `_resolve_clickup_status(list_id, canonical_state)` + `_PER_LIST_STATUS_MAP["901524194809"]` (list vocab: to do, planning, in progress, at risk, update required, on hold, waiting, blocked, complete, cancelled). `_savepoint`, `_audit`, `_resolve_list_space`, `_BAKER_SPACE_ID`.
  - `orchestrator/airport_ticketing_bridge.py` — `post_ticket_to_bus()` / `format_ticket_for_bus()` = the proven bus work-packet pattern (POST `{base}/msg/{recipient}`, `X-Terminal-Key`, key precedence via `_bridge_key()`, `_bus_message_id(result)` extractor).
  - `orchestrator/airport_checkin_reader.py` — the proven reply-reader pattern: poll `GET {base}/msg/{slug}?limit=N&unread=true`, exactly-one-token parse (ambiguous→None), guarded UPDATE, ACK only after commit, TTL re-nudge (`run_ttl_nudge`).
  - `clickup_client.py` — status change/close primitive is `client.update_task(task_id, status=<literal>)` (counts against the 10/cycle cap); `post_comment(task_id, comment_text)`; `reset_cycle_counter()`.
- **Sequencing rulings (Controller-confirmed, do not relitigate):**
  - **D-23:** flight lifecycle store STILL does not exist. `flight_id`/`flight_from_state`/`flight_to_state`/`flight_idempotency_key` stay **NULL** on every row this brief touches. Journey progress is tracked on `event_state` + correlation JSON, never on flight columns. `reconcile()` flight-leak check must keep passing.
  - **D-28:** operating on the 20 existing lounge rows is NOT pilot widening (no new intake). Do not process tickets without a `CLICKUP_WRITTEN`-or-later lounge row.
  - **D-29:** ClickUp is Surface 1. No dashboard/Control Tower wiring.

## Problem

The 20 real tickets reached the Airside Lounge (ClickUp task + event row) but the journey still dead-ends there: no delivery to the desk, no claim, no status mirror, no landing, no receipt, no closure. Ratified non-negotiables still violated downstream: "Landing without receipt is not closed."

## Tasks

### T0 — Schema amendments (new migration; NEVER edit applied migrations)
1. New migration `migrations/20260704a_airport_onward_journey.sql`: amend `airport_outbound_events_state_check` to add `'BOARDING_POSTED'`, `'CLAIMED'`, `'LANDED'`, `'RECEIPT_WRITTEN'`; amend `airport_tickets_status_check` to add `'closed'`.
2. Mirror BOTH amendments verbatim in the `_ensure_*` bootstrap functions (Lesson #37/#50 — bootstrap/migration drift is a known killer). Drop/re-add constraint idempotently.

### T1 — Gate + Boarding claim (block 2)
1. New module (or extension — your call, surface in ship report): for each `CLICKUP_WRITTEN` lounge row for `baden-baden-desk`, post a WORK_PACKET to the desk over the bus (reuse `post_ticket_to_bus` transport pattern + key precedence). Packet body: `WORK_PACKET v1` — ticket ref, ClickUp task id + list, matter slug, luggage summary, an **accept token** (deterministic, e.g. `claim:v1:<ev_ticket_id>` hashed), and the reply grammar (below). Record bus message id + token in `correlation` JSON; `event_state → 'BOARDING_POSTED'`. Idempotent: a row already at `BOARDING_POSTED`-or-later never re-posts.
2. Claim reader (checkin_reader pattern, own slug env like `AIRPORT_BOARDING_READER_SLUG`, default the same dispatcher identity as the packet poster): desk replies `CLAIM <token>` → verify token match → `event_state → 'CLAIMED'` → mirror ClickUp status to `_resolve_clickup_status(list_id, "in progress"-canonical)` via `update_task`. Guarded UPDATE (only from `BOARDING_POSTED`), ACK after commit, ambiguous parse → leave unread + log.

### T2 — In-Flight status mirror per D-25 (block 3)
Desk transition messages (same reader): `STATUS BLOCKED|WAITING|UPDATE_REQUIRED <token> [note]` → map through a small canonical→connector-state table → literal via `_resolve_clickup_status(list_id, canonical)` → `update_task(task_id, status=...)` + `post_comment` with the note. Event row stays `CLAIMED` (mirror is ClickUp-surface only; record last mirrored status + ts in correlation). Cap + readonly: every `update_task`/`post_comment` counts a write — respect `_MAX_WRITES_PER_CYCLE=10` with the same `reset_cycle_counter()` alignment `run_lounge_drain` uses; `BAKER_CLICKUP_READONLY` short-circuits to a logged no-op.

### T3 — Landing + Arrival Receipt (block 4)
1. Desk replies `LANDED <token>` + returned package (state / evidence / asks — free text after the token line). Reader: `event_state → 'LANDED'`, package stored in correlation JSON.
2. Receipt writer: ClickUp task → literal for canonical "Closed" (`complete` on this list) + `post_comment` receipt summary; `event_state → 'RECEIPT_WRITTEN'`; bus proof: post a RECEIPT ack back to the desk, store that bus message id on the row; then source `airport_tickets.status → 'closed'` (guarded: only from `checked_in`). Only after ALL of task-closed + receipt-row + bus-proof-id: journey Closed. Partial failure → row parks at `LANDED` with `last_error`, fail-loud, retried next cycle.

### T4 — Exception lane continuity
No claim within TTL (env, default 48h) → re-nudge once (reuse `run_ttl_nudge` pattern: `last_nudged_at`/`nudge_count` analog in correlation), second expiry → `event_state → 'NEEDS_CONTROLLER'` + ClickUp status "update required". Unparseable desk replies never ACKed silently — logged loudly. Nothing silently discarded.

### T5 — Desk SOP deliverable (not code)
Write `briefs/_reports/BB_DESK_ONWARD_JOURNEY_SOP_DRAFT_1.md`: the exact reply grammar (`CLAIM <token>` / `STATUS <state> <token> [note]` / `LANDED <token>` + package format), for lead to install vault-side into the baden-baden-desk orientation. Code parses ONLY this grammar — SOP and parser must match verbatim.

## Constraints
- Feature flag: env `AIRPORT_BOARDING_FLOW_ENABLED` (default false); flag-off = total no-op (merge dark).
- BAKER Space only (`_resolve_list_space` guard on every write path); max 10 ClickUp writes/cycle; kill switch honored.
- All DB/API calls try/except with `conn.rollback()` in except; per-item commit like `run_lounge_drain`; `_savepoint` for reads on shared txns.
- Flight columns NULL everywhere (extend `FLIGHT_NULL_SQL`-style check to new states); no dashboards; no new intake; the 3 `sent` tickets stay out of scope.
- Bus posting from Render: key env precedence per `_bridge_key()` — confirm which `BRISEN_LAB_TERMINAL_KEY_*` is present on the service BEFORE relying on it; surface in ship report if a new env var is needed (lead flips it, Lesson #91/#99: env changes apply at deploy).

## Done rubric / Acceptance criteria (live proofs, not compile-clean)
1. ≥1 real ticket driven fully end-to-end in prod: BOARDING_POSTED → CLAIMED → (≥1 mirrored STATUS transition) → LANDED → RECEIPT_WRITTEN, with `clickup_task_id` + boarding bus id + receipt bus proof id on the row, ClickUp task at "complete", source ticket `status='closed'`. (Lead coordinates the live baden-baden-desk replies — request the pilot window on bus.)
2. Idempotent re-run at every stage: no duplicate packets, no duplicate ClickUp writes, no double state advance (prove with rerun log).
3. Exception lane proven: ≥1 no-claim TTL re-nudge fires (TTL shrunk via env for the proof), escalation to NEEDS_CONTROLLER visible in ClickUp.
4. Write cap + kill switch verified in run log; readonly dry-run mode non-mutating end-to-end.
5. Reconciliation extended and green: 0 flight-column leaks across new states, 0 rows in undefined states, every non-terminal row accounted (state + age readout).
6. Existing suites green (`test_airport_lounge_writer.py`, `test_box5_outbound_increment2.py`, checkin reader); new tests: token verify, guarded transitions (wrong-order replies rejected), parser grammar incl. ambiguous cases, cap/readonly, migration+bootstrap constraint parity (SQL-string assertion per Lesson #42).

## Gate plan
1. pytest green (unit + live-PG tier with TEST_DATABASE_URL).
2. Codex gate on the PR (lead routes to codex bus; effort=high — new bus protocol + state machine).
3. Merge dark → lead flips flag + runs pilot window with the live desk → run report to lead on bus BEFORE any wide run.
4. POST_DEPLOY_AC verdict on bus per `post-deploy-ac-bus-gate` before DONE.

## Notes for worker
- Branch: `b4/step2-onward-journey-blocks-2-4-1`. PR to `main`, ship report + gate verdicts to lead on bus.
- Sequencing: finish the #459 post-deploy AC first (my #5307), then this.
- Mirror your own savepoint/audit patterns; audit every ClickUp + bus write to `baker_actions` (new `airport_boarding.*` action types).
- The desk end is an agent on the Mac Mini woken by lead — design the protocol so a slow/absent desk never wedges a row (that's what T4 is for).
