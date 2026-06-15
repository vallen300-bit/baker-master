---
status: PENDING
brief_id: LONG_RUNNING_JOB_OWNERSHIP_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-15
reply_target: lead (bus)
task_class: feature — ownership register + cursor-stall sentinel + heartbeat plumbing
gate_plan: G1 pytest (+ synthetic-stall integration test) -> G3 codex code gate -> lead merge -> POST_DEPLOY_AC_VERDICT (sentinel fires on a real stalled job)
arc: RELIABILITY_OWNERSHIP (anchor: Lesson #100 — 4-day silent graph-backfill stall)
Harness-V2: in scope
---

# LONG_RUNNING_JOB_OWNERSHIP_1 — ownership register + cursor-stall sentinel

## Context (why)

On 2026-06-11→06-15 the graph (brisengroup.com) email backfill silently stalled for 4 days at 27%
complete. Nobody noticed because (a) no agent owned the job and (b) no alarm fired on a frozen
progress cursor — forward live-polling kept ingesting today's mail, which MASKED the dead historical
run. Root cause + rules captured in `tasks/lessons.md` Lesson #100. Prior-art survey:
`baker-vault/wiki/research/2026-06-15-long-running-task-ownership-prior-art.md` (researcher, #3031).

Industry answer is two pillars + one third trick, all confirmed in that survey:
1. **Ownership** = no job runs without a named owner stored as machine-readable data pointing to a
   stable **role slug** (never a person/session), Git-versioned + validated.
2. **Liveness** = alert on the *absence* of an expected signal, not on an error.
3. **Cursor-stall** = a job can be alive + health-green yet make zero forward progress. Alarm on
   `cursor delta == 0 AND state == RUNNING` past a per-job threshold (Burrow STALLED rule). This is
   exactly the alarm that was missing.

**Build the cheap version** — copy the schema + discipline, NOT the platforms (no Backstage / Temporal
/ Airflow / Prometheus / Burrow). ~90% of the value at near-zero infra for a ~10-agent fleet.

**Closest existing analog to MIRROR:** `triggers/scheduler_liveness_sentinel.py` — already a DB-driven
liveness sentinel (reads `scheduler_executions`, alerts on stale `MAX(fired_at)`, has a cold-start
grace anchor via `_MODULE_LOAD_TIME` / `reset_cold_start_anchor()`, registry built at startup). Your
new sentinel is the SAME shape but keyed on a progress cursor instead of a fire-timestamp. Read it
first and follow its conventions (logger name `sentinel.<x>`, grace handling, registry pattern).

**Verified facts (don't re-discover):**
- Existing progress table `email_backfill_progress` columns: `source` (key), `cursor`, `done_count`,
  `total_estimate`, `updated_at`. Use `done_count` as the cursor_col, `updated_at` as updated_col,
  `source` as the key for the two backfill jobs.
- Sentinels live in `triggers/`; scheduling happens in `triggers/embedded_scheduler.py` via
  `add_job(...)` + `register_expected_job(...)`.

## Director-ratified design decisions (do NOT re-litigate)

- **Trigger criteria** — a job belongs in the register if it is ANY of: detached (runs in background
  with no live session babysitting it), expected > ~6h wall-clock, OR genuinely spans 3+ sessions.
  (NOT "any task over one session" — Director explicitly rejected that bar.)
- **Owner = role slug** (`lead`, `researcher`, `hag-desk`, …), never a person or session.
- **RACI per job:** Responsible (runs/babysits, e.g. the executing worker), Accountable (one neck —
  default `lead`), Consulted (e.g. `aid` for infra/creds/Neon limits), Informed (`director`).
- **Heartbeat transport:** DB table (`job_heartbeats`) for per-job cursor heartbeats; the sentinel
  ALSO emits its own heartbeat so it is itself watchable (meta-watchdog). Bus is the alert channel.
- **Threshold:** fixed per-job (column in the register), not learned. Default 6h if unset.
- **Enforcement teeth:** FLAG now (bus alert), do not block dispatch yet. (Block-on-ownerless is a
  later phase once the register is trusted.)

## Acceptance criteria

**AC1 — ownership register (config-as-code).**
- NEW `config/long_running_jobs.yml`: list of entries, each with `job_id`, `description`,
  `cursor_source` (see AC3), `stall_threshold_hours` (int), `trigger_reason` (detached |
  long-runtime | multi-session), and RACI fields `responsible` / `accountable` / `consulted` (list)
  / `informed` (list) — all role slugs validated against the repo's known slug set (reuse whatever
  slug list the codebase already exposes; if none, hardcode the current fleet slugs with a TODO).
- Seed ONE entry PER PROGRESS PARTITION (deputy-codex pre-flight S1 #3035 — a stalled SentItems can
  hide while Inbox advances). The live partitions are: `graph:Inbox`, `graph:SentItems`,
  `bluewin:INBOX`, `bluewin:Sent Items` (verified against `email_backfill_progress` + `backfill_graph.py:327,383`
  + `backfill_bluewin.py:68`). Four entries: `graph_inbox_backfill`, `graph_sentitems_backfill`,
  `bluewin_inbox_backfill`, `bluewin_sentitems_backfill` (accountable: lead; responsible: b1;
  consulted: [aid]; informed: [director]; threshold 6; cursor_source = progress_table on
  `email_backfill_progress`, keyed by the exact `source` value above).
- NEW `scripts/validate_long_running_jobs.py`: exits non-zero if any entry is missing a required
  field, names an unknown role slug, or has a non-positive threshold. Wire into the existing
  `.githooks` pre-commit chain (follow the existing hook pattern; do NOT duplicate a hook runner).

**AC2 — heartbeat store.**
- NEW migration `migrations/<date>_job_heartbeats.sql`: TWO tables —
  `job_heartbeats(job_id TEXT PRIMARY KEY, cursor_text TEXT, state TEXT NOT NULL DEFAULT 'RUNNING',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now())`, `state` ∈ {RUNNING, DONE, FAILED, PAUSED};
  AND `sentinel_cursor_seen(job_id TEXT PRIMARY KEY, observed_cursor TEXT, observed_at TIMESTAMPTZ
  NOT NULL DEFAULT now(), last_alert_window_start TIMESTAMPTZ)` (separate table so the sentinel's own
  writes never refresh the heartbeat timestamp it checks — deputy-codex S2 #3035).
- NEW `orchestrator/job_heartbeat.py` with `beat(job_id, cursor, state='RUNNING')` (UPSERT, ON
  CONFLICT update cursor_text/state/updated_at) and `read(job_id)`. Every DB call in try/except WITH
  `conn.rollback()` in except; fault-tolerant (a heartbeat failure must NEVER crash the caller's real
  work — log + continue).

**AC3 — cursor-stall sentinel.**
- NEW `triggers/cursor_stall_sentinel.py`, mirroring `scheduler_liveness_sentinel.py`.
- For each register entry, resolve current cursor + `updated_at` + RUNNING-ness from its
  `cursor_source`. Support two kinds: (a) `heartbeat` → read `job_heartbeats` (`state` column is
  authoritative); (b) `progress_table` → declared `{table, cursor_col, updated_col, key_col, key_val,
  total_col}` over `email_backfill_progress` (no backfill rewrite). All SELECTs LIMITed.
  **State for progress_table (deputy-codex S1 #3035 — that table has NO state column):** RUNNING ⇔
  `cursor_col < total_col` (incomplete). When `cursor_col >= total_col`, treat as DONE → never alarm.
- ALARM when: RUNNING (per above) AND `now - updated_at > stall_threshold_hours` AND the cursor value
  has NOT advanced since the previous sentinel observation. **Persist last-seen in a SEPARATE table
  `sentinel_cursor_seen(job_id PK, observed_cursor, observed_at, last_alert_window_start)` —
  do NOT reuse `job_heartbeats` (deputy-codex S2 #3035: a heartbeat UPSERT refreshes `updated_at`,
  which would mask the very staleness you're checking).** Respect a cold-start grace window like the
  liveness sentinel.
- On alarm: FIRST atomically claim the alert window before posting (deputy-codex S2 #3035 — dedupe
  must be DB-atomic, `bus_post.sh` is a non-idempotent one-shot POST): `INSERT INTO sentinel_cursor_seen
  ... ON CONFLICT (job_id) DO UPDATE SET last_alert_window_start = excluded... WHERE
  sentinel_cursor_seen.last_alert_window_start IS DISTINCT FROM <this_window> RETURNING job_id` — only
  post if a row is returned (claim won). THEN bus-post via `scripts/bus_post.sh <slug> <body> <topic>`
  (header `X-Terminal-Key`) to the job's `accountable` slug AND `lead`; topic
  `alert/job-stalled/<job_id>`; body = job_id + cursor value + hours-since-progress + owner.
- Sentinel emits its OWN heartbeat (`beat('cursor_stall_sentinel', <run_ts>)`) each run.

**AC4 — schedule + meta-watchdog.**
- Register the sentinel in `triggers/embedded_scheduler.py` at a 30-min interval, following the
  existing `add_job(...)` + `register_expected_job(...)` pattern so the scheduler-liveness sentinel
  watches the watcher (this IS the meta-watchdog — no new infra).
- **Also add a `reset_cold_start_anchor()` to the sentinel AND call it from `start_scheduler()`
  alongside the existing `scheduler_liveness_sentinel.reset_cold_start_anchor()` call (deputy-codex
  S2 #3035 — restart-safe grace only works because the reference sentinel's anchor is reset on
  scheduler restart; mirror it). Test that an in-process restart re-applies the grace window.**

**AC5 — real coverage now.**
- Make `scripts/backfill_graph.py` + `scripts/backfill_bluewin.py` call `job_heartbeat.beat(...)`
  with their done_count cursor at each existing progress-commit point; set `state='DONE'` on clean
  completion / `'FAILED'` on exhaustion. Surgical — one beat per existing commit point, no refactor.

**AC6 — tests.**
- `tests/test_cursor_stall_sentinel.py`: (a) flat-line cursor + RUNNING + past-threshold → alarm;
  (b) advancing cursor → no alarm; (c) DONE (`cursor >= total` for progress_table / state=DONE for
  heartbeat) → no alarm; (d) within grace → no alarm; (e) re-alert de-dupe holds; (f) TWO concurrent
  sentinel runs claim the same window → exactly ONE bus-post (atomic-claim test, deputy-codex S2);
  (g) in-process restart re-applies cold-start grace. Mock DB + bus (no live creds in CI).
- `tests/test_validate_long_running_jobs.py`: ownerless / unknown-slug / bad-threshold entries fail.

## Files to modify / create
- NEW `config/long_running_jobs.yml`
- NEW `scripts/validate_long_running_jobs.py`
- NEW `migrations/<date>_job_heartbeats.sql`
- NEW `orchestrator/job_heartbeat.py`
- NEW `triggers/cursor_stall_sentinel.py`
- NEW `tests/test_cursor_stall_sentinel.py`, `tests/test_validate_long_running_jobs.py`
- EDIT `triggers/embedded_scheduler.py` (one add_job + register_expected_job)
- EDIT `scripts/backfill_graph.py`, `scripts/backfill_bluewin.py` (heartbeat beats)
- EDIT `.githooks` pre-commit chain (call the validator)

## Do NOT touch
- `triggers/scheduler_liveness_sentinel.py` (read-only reference — mirror, don't edit).
- Backfill scripts' IMAP/Graph logic or cursor math — only add `beat()` calls.
- Any other sentinel.

## Out of scope (do NOT build)
- Block-on-ownerless dispatch enforcement (later phase).
- Any external SaaS (Healthchecks.io etc.), Prometheus, Temporal, Airflow, Backstage.
- The `long-running-task-ownership` SKILL.md — **lead authors that** (SOP-codification rule). Don't
  write it; leave the register + sentinel clean for the skill to reference.
- Learned/adaptive thresholds.

## Done rubric (answer these in the ship report, not "tests pass")
1. A deliberately stalled job row (RUNNING, old updated_at, unchanged cursor) produces a bus alert to
   its accountable owner within one sentinel interval — show the bus message id.
2. `validate_long_running_jobs.py` rejects an ownerless entry — show the non-zero exit.
3. `pytest tests/test_cursor_stall_sentinel.py tests/test_validate_long_running_jobs.py -v` literal
   green output pasted.
4. The real `graph_email_backfill` job appears in `job_heartbeats` with an advancing cursor.

## Key constraints / lessons applied
- Lesson #100: alert on cursor flat-line, not on errors; don't let aggregate health mask a dead job.
- Fault-tolerant: every DB/bus call try/except + rollback; a monitoring failure must not crash work.
- Tests-first: write the flat-line-alarm test, watch it fail, then build.
- Render restart survival: register-driven, DB-backed — no in-memory state that dies on redeploy.
- Reply on the bus to `lead` at each state change (dispatch ack, blocker, ship).
