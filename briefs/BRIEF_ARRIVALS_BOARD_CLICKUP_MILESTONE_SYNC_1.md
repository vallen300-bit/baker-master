# BRIEF: ARRIVALS_BOARD_CLICKUP_MILESTONE_SYNC_1 — auto-derive board arrival from ClickUp timetable

## Context
The arrivals board's `arrives_on` / `arrives_label` are hand-entered per flight and rot the moment
a desk forgets to update them — the exact failure the board was meant to prevent. Director ratified
(GO via lead #11688) that these should **auto-derive** from the flight's ClickUp timetable: the next
incomplete task with a due date = the next milestone. Desks keep manual control (a manual edit wins
for 24h, anti-flap). This brief is sequenced FIRST; the Friday schedule-review rule
(ARRIVALS_BOARD_FRIDAY_SCHEDULE_REVIEW) references it.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: none (piggybacks the existing embedded scheduler; reads ClickUp only)

## Baker Agent Vault Rails
Relevant: **verification-surfaces** (arrivals board is a Director-facing surface), **build-command-center**
(scheduler tick), **memory-and-lessons** (independent-poller + column-name lessons). Ignore:
standing-contract, skills-and-playbooks, loop-runner.

## Context Contract (Harness V2)
- **Repo:** baker-master. **Files:** `orchestrator/arrivals_board.py` (derive + guarded write),
  `triggers/embedded_scheduler.py` (register the tick), a new migration only IF a column is needed
  (it is NOT — see below), `tests/`.
- **Reads:** `clickup_client.get_tasks(list_id)`, `project_registry.clickup_list_id`,
  `flight_board_state` rows.
- **Writes:** `flight_board_state` via the existing `upsert_board_state()` path only; audit to
  `baker_actions`. NO ClickUp writes. NO bus-DB SQL.
- **Out of scope / read-only:** overlay/`effective_status` logic (must stay unchanged), the
  `POST /api/flight-board` manual endpoint, project_registry write paths, any other seat's files.

## Task class (Harness V2)
**Production-executed — Director-facing surface — HIGH-IMPACT.** Full gate chain incl. mandatory
codex verify on the build (#11665).

## Problem
`arrives_on` / `arrives_label` (table `flight_board_state`, `migrations/20260708a_flight_board_state.sql:14-15`)
are only ever set by the manual `POST /api/flight-board/{project_code}` path
(`outputs/dashboard.py:8584` → `orchestrator/arrivals_board.py:133 upsert_board_state`). Nothing
keeps them current from the flight's real schedule, so they go stale silently.

## Current State (verified)
- **Board write:** `upsert_board_state(project_code: str, fields: dict, updated_by: str)`
  (`orchestrator/arrivals_board.py:133`) — validates `arrives_on` via `_parse_date_value`,
  `arrives_label` via `_optional_text(max_len=128)`, UPSERTs with `COALESCE` partial-update, audits
  to `baker_actions(action_type='flight_board.upsert', trigger_source='arrivals_board')`.
- **Row carries provenance:** `flight_board_state.updated_by TEXT NOT NULL` +
  `updated_at TIMESTAMPTZ` (`migration :20-21`) — **the anti-flap key already exists; no new column
  needed.**
- **Registry link:** `project_registry.clickup_list_id TEXT` (nullable)
  (`kbl/project_registry_store.py:60-75`); `list_board_rows()` already LEFT JOINs registry→board
  (`arrivals_board.py:203`). Pilot BB-AUK-001 has `clickup_list_id="901524194809"`.
- **ClickUp read:** `clickup_client.get_tasks(list_id: str, date_updated_gt: int = None) -> list`
  (`clickup_client.py:197`) returns raw task dicts incl. `name`, `due_date` (ms epoch or None),
  `status` (dict with `status`/`type`; closed = `type=="closed"`). Reads are NOT gated by
  `BAKER_CLICKUP_READONLY` (that only blocks writes, `clickup_client.py:130`).
- **Overlay:** `effective_status(row, today)` (`arrivals_board.py:227`) computes DELAYED at READ time
  (no DB write) when `arrives_on < today` and status ∉ `{LANDED,DIVERTED,DELAYED}`. Because the sync
  only writes the base `arrives_on`, **the machine DELAYED overlay is preserved automatically.**
- **Scheduler:** `triggers/embedded_scheduler.py:_register_jobs()` (`:210`) — add
  `scheduler.add_job(func, IntervalTrigger(seconds=N), id=..., coalesce=True, max_instances=1)` +
  `register_expected_job(id, N)` for the liveness watchdog.

## Engineering Craft Gates
- **Diagnose:** N/A — greenfield sync, no bug to reproduce.
- **Prototype:** N/A — data shape + rules specified below; no open UI/state question.
- **TDD/verification:** APPLIES. Seams: (1) pure `derive_next_milestone(tasks, today)` — write tests
  FIRST for: earliest incomplete task with a due date wins; closed tasks ignored; no-due-date tasks
  ignored; empty/all-closed → None. (2) `sync_should_write(row, now)` anti-flap — manual write <24h
  ago → skip; machine or >24h → write. No ClickUp HTTP mocking of internals — feed `get_tasks`
  return dicts into the pure deriver.

## Implementation
1. **Deriver (pure, testable)** in `arrivals_board.py`:
   ```python
   def derive_next_milestone(tasks, today):
       # tasks = raw ClickUp task dicts from clickup_client.get_tasks(list_id)
       cand = []
       for t in tasks:
           st = (t.get("status") or {})
           if str(st.get("type") or "").lower() == "closed":
               continue
           due_ms = t.get("due_date")
           if not due_ms:
               continue
           # R2 (lead #11692): TZ-pin the ms-epoch so a midnight-CET due date does not
           # day-shift on a UTC host. datetime.fromtimestamp(..., tz=utc).date(), NOT bare
           # date.fromtimestamp (host-local). Test with a 23:00Z-equivalent epoch.
           due = datetime.fromtimestamp(int(due_ms) / 1000, tz=timezone.utc).date()
           cand.append((due, t.get("name") or ""))
       if not cand:
           return None  # no upcoming milestone -> leave existing value untouched
       cand.sort(key=lambda x: x[0])
       due, name = cand[0]
       return {"arrives_on": due, "arrives_label": name[:128]}
   ```
2. **Anti-flap guard (pure, testable)**:
   ```python
   _SYNC_UPDATED_BY = "arrivals_clickup_sync"
   _MANUAL_HOLD_S = 24 * 3600
   def sync_should_write(row, now):
       # row = current flight_board_state row (or None). Manual desk edit wins for 24h.
       if not row:
           return True
       if row.get("updated_by") == _SYNC_UPDATED_BY:
           return True  # last writer was us -> safe to refresh
       updated_at = row.get("updated_at")
       if updated_at is None:
           return True
       return (now - updated_at).total_seconds() >= _MANUAL_HOLD_S
   ```
3. **Sync worker** `run_clickup_milestone_sync()` in `arrivals_board.py`:
   - For each active project with `clickup_list_id` NOT NULL (join registry→board): fetch
     `get_tasks(list_id)`, `derive_next_milestone(...)`. If None → skip (fallback: manual value
     stands). Read current board row; if `sync_should_write(row, now)` is False → skip (manual hold).
     Else write ONLY when the derived value differs from current (no-op writes suppressed).
     **R1 (lead #11692, BUILD-BLOCKER):** `upsert_board_state` calls `_normalize_status(fields.get('status'))`
     (`arrivals_board.py:126-130`/`:133`) which **raises `ValueError` when status is absent** — a
     `{arrives_on, arrives_label}`-only payload throws on EVERY machine write. The worker MUST thread
     the current status through unchanged:
     `fields = {"arrives_on": ..., "arrives_label": ..., "status": (row["status"] if row else "CHECK-IN")}`,
     then `upsert_board_state(project_code, fields, updated_by=_SYNC_UPDATED_BY)`. The sync never
     changes status — it preserves the existing one verbatim (default `CHECK-IN` only when no board
     row exists yet).
   - Fallback when `clickup_list_id` unset: skip the flight entirely (manual value untouched).
   - Every write is audited by the existing `upsert_board_state` baker_actions path; ALSO log one
     summary `baker_actions(action_type='flight_board.clickup_sync', trigger_source=_SYNC_UPDATED_BY,
     payload={checked, written, skipped_manual, skipped_no_milestone})` per tick.
   - Wrap ClickUp + DB calls in try/except with `conn.rollback()` on DB error; a single flight's
     failure must not abort the others (independent-poller lesson).
4. **Register the tick** in `embedded_scheduler.py:_register_jobs()`:
   `scheduler.add_job(run_clickup_milestone_sync, IntervalTrigger(seconds=900), id="arrivals_clickup_sync", name="Arrivals board <- ClickUp milestone sync", coalesce=True, max_instances=1)` +
   `register_expected_job("arrivals_clickup_sync", 900)`. (15-min cadence — cheap, ClickUp reads only;
   settle with lead.)

## Key Constraints
- **Overlay untouched:** write only base `arrives_on`/`arrives_label`; never write DELAYED. DELAYED
  stays a read-time overlay (`effective_status`).
- **Manual override wins 24h:** never overwrite a row whose last writer is a desk and whose
  `updated_at` is <24h old.
- **No ClickUp writes**; reads only. Respect that `get_tasks` is unauth-gated for reads.
- **Independent per flight** — one flight's ClickUp/DB error must not kill the tick for others.
- **No-op suppression** — do not upsert (and do not audit) when the derived value equals current.
- **All DB/API calls try/except + rollback.**

## Files Modified
- `orchestrator/arrivals_board.py` — `derive_next_milestone()`, `sync_should_write()`, `run_clickup_milestone_sync()`, `_SYNC_UPDATED_BY`.
- `triggers/embedded_scheduler.py` — register the `arrivals_clickup_sync` job + expected-job liveness.
- `tests/test_arrivals_board.py` (or new) — deriver + anti-flap + no-op tests.

## Do NOT Touch
- `effective_status` / overlay logic — must stay byte-identical.
- `POST /api/flight-board` manual endpoint semantics.
- `clickup_client` write paths / kill switch.
- `project_registry` write paths.

## Verification
- **Unit (write first):** `derive_next_milestone` — earliest incomplete+due wins; closed/no-due
  ignored; empty→None. `sync_should_write` — manual <24h → False; machine or >24h or no row → True.
- **Integration (local):** seed a `flight_board_state` row + a fake `get_tasks` return; run
  `run_clickup_milestone_sync()`; assert the row's `arrives_on`/`arrives_label` update, `updated_by`
  = `arrivals_clickup_sync`, and a `flight_board.clickup_sync` audit row is written.
- **Anti-flap:** manual upsert (updated_by=desk) then immediate sync → row unchanged; fast-forward
  `updated_at` >24h → sync writes.

## Quality Checkpoints (Acceptance criteria)
- **AC1** Next-milestone derivation correct (earliest incomplete task with a due date; closed / no-due excluded; ms-epoch → DATE).
- **AC2** `clickup_list_id` unset → flight skipped, manual value untouched.
- **AC3** Overlay unchanged — DELAYED still computed at read-time; sync never writes a status/overlay value.
- **AC4** Every write audited to `baker_actions`; per-tick summary audit written.
- **AC5** Desk manual override wins for 24h (anti-flap): a manual edit within 24h is never overwritten by the sync.
- **AC6** No-op suppression — derived == current ⇒ no upsert, no audit row.
- **AC7** Independence + fault-tolerance — one flight's failure doesn't abort the tick; all DB/API calls try/except + rollback.
- **AC8** Tick registered on the embedded scheduler with liveness (`register_expected_job`).
- **AC9** (R1) Machine write threads the row's current `status` verbatim (default `CHECK-IN` when no row exists); a status-bearing row's status is unchanged after sync. Test asserts no `ValueError` and status preserved.
- **AC10** (R2) `due_date` ms-epoch → DATE is UTC-pinned (`datetime.fromtimestamp(ms/1000, tz=timezone.utc).date()`); test with a 23:00Z-equivalent epoch proves no day-shift.

## Rollout (per-flight activation; lead rider #11689)
Registry audit 2026-07-15: only **BB-AUK-001** carries `clickup_list_id` (`901524194809`); the other
7 flights (AI-HTL / AO-OSK / BRI-GRP / FA-ACA / HAG-RG7 / MO-VIE / MO-WAR) are NULL. The sync is
therefore **self-gating and incremental** — it acts only on flights whose `clickup_list_id` is set,
so it is safe to ship before the backfill. **BB-AUK-001 is the pilot row** (validate the live tick
there first). Each remaining flight activates automatically the moment its `clickup_list_id` lands
via the backfill (deputy-codex, lead-ordered, after the discipline SOP merges). No code change per
activation — data-driven. NULL-list flights are skipped (AC2), never errored.

## Done rubric / done-state (Harness V2)
DONE = AC1-AC8 green **and** codex verify PASS on the diff **and** deputy cross-lane review PASS
**and** lead merge **and** post-deploy live check (a real BB-AUK-001 sync tick updates the board
from its ClickUp list, audit visible, manual-hold honored). Compile-clean ≠ done (Lesson #8).

## Gate plan (Harness V2)
Author (deputy) → **lead line-read [pending] → dispatch worker** → build (TDD: deriver + anti-flap
tests first) → **codex verify (high-impact, MANDATORY)** → rewrite on findings → deputy cross-lane
review → lead merge → deputy post-deploy live AC on BB-AUK-001.
