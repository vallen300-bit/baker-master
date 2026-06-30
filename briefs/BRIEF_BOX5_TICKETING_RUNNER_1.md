# BRIEF: BOX5_TICKETING_RUNNER_1 — extend run_tick: per-source cursor + SKIP-LOCKED claim + status-guarded terminal write + kill-switch

## Context

Box 5, Build Order 5 — **the runner**. BRIEF-A (receipt/TTL loop, `orchestrator/airport_checkin_reader.py`) and BRIEF-B (`BOX5_SCHEMA_FOUNDATION_1`, PR #441, commit `ddb2ea4`) are both **already merged** on `origin/main` @ `c63a3d2`. This brief EXTENDS the existing `airport_ticketing_tick` / `run_tick` (`orchestrator/airport_ticketing_bridge.py:780`) — it does NOT add a new scheduler, a new lease, or a new cursor table.

BRIEF-C **writes** the `terminal_status` column (and siblings) that BRIEF-B added via `ensure_airport_ticket_terminal_columns` (`orchestrator/airport_ticketing_bridge.py:343`). There is currently **no `terminal_status` writer anywhere on `origin/main`** (grep for `SET terminal_status` returns zero outside the `ADD COLUMN`/`CHECK` DDL) — this brief is net-new terminal-write plumbing on top of BRIEF-B's columns.

Locked design from the ratified second-pair review:

- **Blocker 4 (no parallel scheduler / no lease columns).** The whole embedded scheduler already runs single-replica behind `scheduler_lease` advisory lock `8800100` (`triggers/embedded_scheduler.py:374` comment "single-replica inherited from scheduler_lease (lock 8800100)"; lock acquired once at `embedded_scheduler.py:1984` via `acquire_singleton_lock()`). `airport_ticketing_tick` is registered at `embedded_scheduler.py:352-366` and runs **inside** that already-leased process, so `run_tick` **inherits** single-replica for free. BRIEF-C MUST NOT call `acquire_singleton_lock`, MUST NOT add `lease_owner`/`lease_expires_at` columns, MUST NOT add a parallel scheduler. `FOR UPDATE SKIP LOCKED` is the **intra-tick row** backstop (APScheduler tick overlapping a manual on-demand run), not replica coordination.

- **Blocker 7 (two-layer kill-switch).** (a) Master gate = reuse the existing `AIRPORT_TICKETING_BRIDGE_ENABLED` (default `false`) read by `bridge_enabled()` (`airport_ticketing_bridge.py:107`); the runner ships dark. (b) A NEW separate `BOX5_FAST_LANE_ENABLED` (default `false`) that, when false, routes **every** non-deterministic-clear arrival to the safe default `terminal_status='TICKET'` (full desk review) while the runner still clears backlog — so a misroute is frozen by a flag flip, no deploy.

- **Blocker D3 (error never auto-clears).** A registry/manifest/classify **exception** must NOT silently downgrade to a clear or a fast-lane bypass. Distinguish "threw" (→ safe-default `TICKET`, or skip + log + count `failed`) from "no match" (→ normal routing). In BRIEF-C there is no fast lane yet, but the deterministic-clear + default path must already honor this.

- **Safe-by-default = TICKET.** BRIEF-C implements **deterministic clears only** — DUPLICATE (existing `dedup_key` collision) and REJECT_NOISE (existing automated-sender filter / no-active-keyword path). It does NOT implement the project-number hard fast lane (BRIEF-D) or the manifest soft fast lane (BRIEF-E), and it does NOT use VISIBLE_HOLD (its own brief). Without D/E built, **every arrival that is not a deterministic clear becomes a desk `TICKET`** — the runner is safe-by-default.

### Surface contract: N/A — backend scheduler runner extension, no clickable UI surface.

### Harness V2

**Context Contract**

- **Inputs:**
  - `run_tick(*, now=None)` — invoked by the scheduled job `airport_ticketing_tick` (wrapper `triggers/airport_ticketing_tick.py:5`, which discards the return value), or directly in tests.
  - Env flags: `AIRPORT_TICKETING_BRIDGE_ENABLED` (master gate, existing), `BOX5_FAST_LANE_ENABLED` (NEW, default false), `AIRPORT_TICKETING_KEYWORDS`, `AIRPORT_TICKETING_LOOKBACK_HOURS`, `AIRPORT_TICKETING_MAX_POSTS_PER_TICK`.
  - Raw source: `email_messages` table ONLY (read via `fetch_email_arrivals`, `airport_ticketing_bridge.py:406`). WhatsApp / transcripts / `signal_queue` are later briefs.
  - Per-source cursor: existing `trigger_watermarks` store via the `trigger_state` singleton (`triggers/state.py:529`).
- **Outputs:** the extended `run_tick` return dict — existing `{ok, issued, skipped, failed}` PLUS new `{claimed, terminal_written, lease_skipped, deterministic_cleared, defaulted_ticket, stuck_arrivals}`; one `logger.info` per-tick summary line emitted INSIDE `run_tick` (the wrapper drops the dict).
- **Side-effects:** writes `airport_tickets.terminal_status` + `terminal_reason` + `processed_at` + `terminal_outcome_written_at` + `raw_source_table` + `raw_source_id` (and a `baker_actions` audit row `airport_ticket.terminal_written`); advances the per-source watermark; existing `issue_ticket` bus-post side-effects unchanged.
- **Idempotency invariants:**
  - The **status-guarded write** `... WHERE id=%s AND terminal_status IS NULL` is the ONLY terminal-write path. Re-running a tick (or a lease-expired reclaim) matches 0 rows on the second pass → `rowcount=0`, no double-write. This is the backstop, separate from the `dedup_key` UNIQUE that prevents duplicate ROWS.
  - Row claim uses **`FOR UPDATE SKIP LOCKED`** so two overlapping ticks never both process the same arrival; a row another claimer holds increments `lease_skipped`, not an error.
  - Watermark advances ONLY to the max `received_date` of arrivals that reached a terminal write on a clean tick; a tick that threw before completing does NOT advance the cursor (re-scan is safe because of the status-guard + `dedup_key`).
  - Single-replica is **inherited** from the scheduler lease `8800100`; the runner adds no lock of its own.

**Task class:** extend an existing scheduler runner, **additive**. No new job, no new table, no new lock, no schema migration (BRIEF-B's columns are live). Pure extension of `run_tick` + two new module-level helpers in the same file.

**Done rubric (machine-checkable):**

1. The change **extends `run_tick`** (`airport_ticketing_bridge.py:780`) — it does NOT register a new scheduler job. `grep -c "add_job\|IntervalTrigger" orchestrator/airport_ticketing_bridge.py` is unchanged from main (0 in this file).
2. `FOR UPDATE SKIP LOCKED` is present in the row-claim query: `grep -c "FOR UPDATE SKIP LOCKED" orchestrator/airport_ticketing_bridge.py` ≥ 1.
3. The terminal write is **status-guarded**: every `SET terminal_status` statement is followed by `WHERE ... terminal_status IS NULL`. No unguarded `UPDATE airport_tickets SET terminal_status` exists.
4. `BOX5_FAST_LANE_ENABLED` defaults **false**: the new helper returns `False` when the env var is unset (`os.environ.get(_FAST_LANE_ENV, "false")`).
5. **Error never auto-clears**: in the per-row block, an exception path increments `failed` (and routes to safe-default `TICKET` or skip+log) — it NEVER increments `deterministic_cleared` and NEVER writes `REJECT_NOISE`/`DUPLICATE`.
6. **Per-tick stats returned**: the success return dict contains the keys `claimed, terminal_written, lease_skipped, deterministic_cleared, defaulted_ticket, stuck_arrivals` in addition to `ok, issued, skipped, failed`.
7. **Deterministic clears only, default TICKET**: the only two terminal statuses written by the clear path are `DUPLICATE` (dedup collision) and `REJECT_NOISE` (automated-sender / no-active-keyword); every other arrival writes `TICKET`. No `FAST_TICKET`, no project-number lane, no manifest lane, no `VISIBLE_HOLD`.
8. **No D/E logic**: `grep -iE "project_code|manifest_match|registry_version|FAST_TICKET" orchestrator/airport_ticketing_bridge.py` shows no NEW write logic for those columns (they stay NULL/default — BRIEF-D/E own them).

**Gate plan:** G1 (builder self-test: `pytest` new tests green + targeted bridge tests + `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_ticketing_bridge.py', doraise=True)"`) → **codex G3** (verifier verdict on the diff) → **lead `/security-review` G4** → **lead merge**. Ships **dark** behind `AIRPORT_TICKETING_BRIDGE_ENABLED` (default false) with the inner `BOX5_FAST_LANE_ENABLED` also default false. **Deploy = lead flips the flag** (Render env) after merge; no code deploy gate.

## Estimated time

4–6 hours (one builder). Most of the cost is the idempotency + concurrency + error-routing test matrix, not the runner edits.

## Complexity

**Medium/High.** The edits are surgical and the precedents are all in-repo, but the correctness surface is concurrency (SKIP LOCKED), idempotency (status-guard), and fault isolation (error-never-auto-clears) — each must be proven by test, not by inspection.

## Prerequisites

- **BRIEF-B MERGED — the `terminal_status` column MUST exist.** Confirmed live on `origin/main` @ `c63a3d2` (PR #441, `ddb2ea4`): `ensure_airport_ticket_terminal_columns` (`airport_ticketing_bridge.py:343`) ALTERs in `terminal_status` + the 6-state CHECK + `raw_source_table`/`raw_source_id`/`processed_at`/`terminal_outcome_written_at`. **Dependency already satisfied.**
- **#439 merged** (prerequisite ratified in the locked review).
- **Serialize-after-B (explicit).** BRIEF-C must branch from a base that already contains BRIEF-B's columns. Because BRIEF-B is already on `main`, branch BRIEF-C off current `origin/main` (`c63a3d2` or later). Do NOT start BRIEF-C from a pre-#441 base. If for any reason BRIEF-B is reverted, BRIEF-C is blocked until it is re-merged — the runner writes columns that only exist because of B.

### Problem

`run_tick` today scans a constant 48h lookback window, builds tickets, issues them to the bus, and returns `{ok, issued, skipped, failed}`. It writes the **live `status`** axis (candidate/sent/failed) but writes **no terminal outcome** — the BRIEF-B `terminal_status` columns sit empty. There is no per-source cursor (every tick re-scans the same window; only `dedup_key` UNIQUE stops re-issue), no explicit row-claim for terminal processing, and no idempotent terminal-write guard. The Box-5 design needs exactly one terminal outcome recorded per arrival, crash-safe and flag-frozen.

### Current State (file:line from map)

- `run_tick` — `orchestrator/airport_ticketing_bridge.py:780` — `def run_tick(*, now: Optional[datetime] = None) -> dict[str, Any]`. Lines 781-784 gate on `bridge_enabled()` + `max_posts_per_tick()`. 786-792 acquire `SentinelStoreBack._get_global_instance()` conn (singleton — NEVER instantiate directly, CI guard). 800-803 init counters + `current = now or _utc_now()`. 805 `ensure_airport_ticket_table(conn)` (idempotent DDL, now also ensures BRIEF-B terminal cols). **806 `since = current - timedelta(hours=lookback_hours())`** — CONSTANT lookback, NO watermark. 807 `arrivals = fetch_email_arrivals(conn, since=since, limit=cap*4)`. 808-832 per-arrival loop: `build_email_ticket` → if None `skipped += 1` → else `issue_ticket(ticket, conn)` + `conn.commit()` inside per-row `try/except` with `rollback`. 833 `return {ok, issued, skipped, failed}`. 834-843 outer except rolls back + returns `{ok:False, error}`; `finally store._put_conn(conn)`.
- `fetch_email_arrivals` — `:406` — reads `email_messages` (`message_id, thread_id, sender_name, sender_email, subject, full_body, received_date, source`). `message_id` (row[0], TEXT) = natural key → `raw_source_id`; `received_date` (row[6], TIMESTAMPTZ, UTC-coerced) = cursor column.
- `build_email_ticket` — `:199` — returns `None` for automated senders (`_is_automated_email_arrival`, `:192` → REJECT_NOISE) and for no-active-keyword arrivals (→ REJECT_NOISE / REJECT_LOW_RELEVANCE); else builds `AirportTicket` with `dedup_key`, `source_channel='email'`, `source_id=message_id`, `source_received_at=received_date`. **This None-vs-ticket split is the deterministic-clear hook.**
- `_is_automated_email_arrival` — `:192` — matches `_SKIP_EMAIL_SENDER_PATTERNS` (`noreply@`, `no-reply@`, `notifications@`, `notification@`, `@clickup.com`, `@todoist.com`).
- `active_keywords` — `:128` — env `AIRPORT_TICKETING_KEYWORDS` or default `aukera/annaberg/lilienmatt`.
- `issue_ticket` — `:758` — `reserve_ticket` → if not reserved returns `{skipped:True, reason:'duplicate', id}` (DUPLICATE precedent); else post to bus → `mark_ticket_sent`/`mark_ticket_failed`.
- `reserve_ticket` — `:485` — `INSERT ... ON CONFLICT (dedup_key) DO NOTHING RETURNING id`; empty RETURNING = dedup collision = DUPLICATE signal. `_dedup_key` at `:170` = `airport-ticket:v1:{channel}:{source_id}:{desk}`.
- `mark_ticket_sent` — `:680` — writes the LIVE `status` axis, NOT `terminal_status`. BRIEF-C adds a NEW terminal write alongside, never replacing this.
- `ensure_airport_ticket_terminal_columns` — `:343` — BRIEF-B (merged); all BRIEF-C target columns already exist; 6-state CHECK `DUPLICATE/REJECT_NOISE/REJECT_LOW_RELEVANCE/FAST_TICKET/TICKET/FILE_UNSORTED` (no VISIBLE_HOLD).
- `bridge_enabled` — `:107` — master gate `AIRPORT_TICKETING_BRIDGE_ENABLED`, default false.
- `trigger_state` singleton — `triggers/state.py:529` — `from triggers.state import trigger_state`; `.get_watermark(source)->tz-aware UTC datetime` (default NOW-24h), `.set_watermark(source, ts=None)` upsert. Backing table `trigger_watermarks(source PK, last_seen TIMESTAMPTZ, cursor_data TEXT)`. Existing email keys IN USE: `email_poll`, `email_poll_checked` — BRIEF-C MUST use a DISTINCT key so it never rewinds the live email poll.
- `claim_one_signal` — `kbl/pipeline_tick.py:92` — canonical `SELECT id ... LIMIT 1 FOR UPDATE SKIP LOCKED` then `UPDATE` + `commit` claim pattern.
- batch-claim idiom — `orchestrator/waiting_room.py:172` — `UPDATE ... WHERE id IN (SELECT id ... ORDER BY ... LIMIT %s FOR UPDATE SKIP LOCKED) RETURNING id`.
- fault-tolerance template — `orchestrator/airport_checkin_reader.py:337` (`run_ttl_nudge`) — outer try/except+rollback, per-row try/commit/except-rollback-continue, status-guarded `UPDATE ... WHERE id=%s AND status='sent' AND check_in_at IS NULL` (the direct analogue of the BRIEF-C `terminal_status IS NULL` guard); `_select_stale` `:265` shows the `< NOW() - interval` idiom for the stuck gauge.

### Engineering Craft Gates

**Diagnose.** The bug-shaped risk is double-writing a terminal outcome under (a) overlapping ticks, (b) lease-expired reclaim, (c) a tick that re-scans an already-cleared window. Reproduce each as a test BEFORE building the guard: run `run_tick` twice over the same `email_messages` rows and assert the second run writes 0 terminal rows. The status-guard `WHERE terminal_status IS NULL` is the fix; the test must fail without it.

**Prototype.** Before wiring the full loop, prototype the status-guarded write helper + the SKIP-LOCKED claim against a `TEST_DATABASE_URL` Neon branch with two concurrent connections, and confirm only one connection wins the row (the other gets 0 rows, increments `lease_skipped`). Throw away the prototype; fold the verified shape into the runner.

**TDD.** Write the idempotency test, the safe-default-TICKET test, the deterministic-clear tests (DUPLICATE + REJECT_NOISE), and the error-never-auto-clears test FIRST. They must fail against current `main` (no terminal writer exists) and pass after the change.

### Implementation

All edits are in `orchestrator/airport_ticketing_bridge.py` (one new flag helper, one new terminal-write helper, one new stuck-gauge helper, and the `run_tick` body extension). Signatures below are VERIFIED against `origin/main` @ `c63a3d2`.

**1. New kill-switch flag helper — mirror `bridge_enabled()` verbatim (place beside it, ~line 107):**

```python
_FAST_LANE_ENV = "BOX5_FAST_LANE_ENABLED"
_WATERMARK_SOURCE = "airport_ticketing:email"  # DISTINCT from live 'email_poll' keys
_STUCK_ARRIVAL_MINUTES = 30


def fast_lane_enabled() -> bool:
    """When False, every non-deterministic-clear arrival routes to TICKET (full desk
    review). Freeze-by-flag kill switch (blocker 7b); default closed, no deploy needed
    to freeze a misroute. In BRIEF-C there is no fast lane yet — this only future-proofs
    D/E, but it must be read and honored now."""
    raw = os.environ.get(_FAST_LANE_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}
```

**2. Status-guarded terminal-write helper — the ONLY terminal-write path, idempotent (new function in the same file):**

```python
def write_terminal_status(
    conn: Any,
    *,
    ticket_row_id: int,
    terminal_status: str,
    terminal_reason: str,
    raw_source_id: str,
) -> bool:
    """Single idempotent terminal write. Returns True iff THIS call wrote the terminal
    outcome (rowcount == 1). The `AND terminal_status IS NULL` guard makes re-runs and
    lease-expired reclaims no-ops (0 rows). dedup_key UNIQUE guards duplicate ROWS; this
    guards duplicate terminal WRITES. Caller wraps in per-row try/except + rollback."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE airport_tickets
               SET terminal_status = %s,
                   terminal_reason = %s,
                   processed_at = NOW(),
                   terminal_outcome_written_at = NOW(),
                   raw_source_table = 'email_messages',
                   raw_source_id = %s
             WHERE id = %s
               AND terminal_status IS NULL
            RETURNING id, ticket_id
            """,
            (terminal_status, terminal_reason, raw_source_id, ticket_row_id),
        )
        won = cur.fetchone()
        wrote = won is not None
        if wrote:
            ticket_id_text = won[1]
            # audit trail — match the LIVE baker_actions column set used by
            # reserve_ticket (:552) and mark_ticket_sent (:704): the shape is
            # (action_type, target_task_id, payload, trigger_source, success),
            # payload via _json_param() (:146), success TRUE. No jsonb_build_object.
            cur.execute(
                """
                INSERT INTO baker_actions
                    (action_type, target_task_id, payload, trigger_source, success)
                VALUES ('airport_ticket.terminal_written', %s, %s,
                        'airport_ticketing_bridge', TRUE)
                """,
                (
                    ticket_id_text,
                    _json_param(
                        {
                            "ticket_id": ticket_id_text,
                            "terminal_status": terminal_status,
                            "terminal_reason": terminal_reason,
                        }
                    ),
                ),
            )
        return wrote
    finally:
        cur.close()
```

> NOTE: the `baker_actions` insert above uses the VERIFIED live column set `(action_type, target_task_id, payload, trigger_source, success)` with `_json_param()` for the payload and `TRUE` for success — matching `reserve_ticket` (`:552`) and `mark_ticket_sent` (`:704`). Do NOT use `jsonb_build_object` or a `created_at` column (the table defaults it). `_json_param` is module-local at `:146` — no new import.

**3. Stuck-arrivals gauge — net-new COUNT (model on `_select_stale`'s interval idiom, `airport_checkin_reader.py:265`):**

```python
def _count_stuck_arrivals(conn: Any) -> int:
    """Journey gauge (NOT scheduler liveness): arrivals that never reached a terminal.
    source_received_at is a real existing column populated by reserve_ticket."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*)
              FROM airport_tickets
             WHERE terminal_status IS NULL
               AND source_received_at < NOW() - (%s || ' minutes')::interval
            LIMIT 1
            """,
            (_STUCK_ARRIVAL_MINUTES,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        cur.close()
```

**4. `run_tick` body extension (`:780`). Five surgical edits — keep every existing line that is not replaced:**

```python
def run_tick(*, now: Optional[datetime] = None) -> dict[str, Any]:
    # (a) MASTER GATE — unchanged (line 781): ships dark behind AIRPORT_TICKETING_BRIDGE_ENABLED
    if not bridge_enabled():
        return {"skipped": True, "reason": "bridge_disabled"}
    cap = max_posts_per_tick()
    if cap <= 0:
        return {"skipped": True, "reason": "cap_zero"}

    store = SentinelStoreBack._get_global_instance()  # singleton — never instantiate directly
    conn = store._get_conn()
    if conn is None:
        return {"ok": False, "error": "database_unavailable"}

    current = now or _utc_now()
    # existing counters
    issued = skipped = failed = 0
    # NEW journey counters (blocker: per-tick stats)
    claimed = terminal_written = lease_skipped = deterministic_cleared = defaulted_ticket = 0
    fast_lane = fast_lane_enabled()  # honored now; only future-proofs D/E
    max_received: Optional[datetime] = None

    try:
        ensure_airport_ticket_table(conn)  # idempotent; also ensures BRIEF-B terminal cols

        # (b) CURSOR — replace the constant `since` (line 806) with the per-source watermark.
        #     Keep the lookback as a FLOOR fallback when no watermark exists (mirrors
        #     get_watermark's NOW-24h default). DISTINCT source key — never the live email poll.
        floor = current - timedelta(hours=lookback_hours())
        wm = trigger_state.get_watermark(_WATERMARK_SOURCE)
        since = max(wm, floor)  # get_watermark (state.py:180) never returns None (NOW-24h fallback)

        arrivals = fetch_email_arrivals(conn, since=since, limit=cap * 4)

        for arrival in arrivals:
            if issued >= cap:
                break
            # (c) PER-ROW FAULT ISOLATION — one bad row never crashes the tick (blocker D3)
            try:
                ticket = build_email_ticket(arrival)

                # (d) DETERMINISTIC CLEAR — REJECT_NOISE (automated sender / no active keyword).
                #     build_email_ticket already returns None for exactly these two cases.
                if ticket is None:
                    # write a terminal row instead of silently skipping. We must re-fetch /
                    # reserve a row id to attach the terminal to; for a None-ticket arrival
                    # there may be no airport_tickets row yet — reserve a noise-cleared row so
                    # the terminal write has a target. (If your design records noise without a
                    # row, write to a noise ledger instead — confirm with lead before deviating.)
                    noise_id = reserve_noise_row(conn, arrival)  # see NOTE below
                    if write_terminal_status(
                        conn,
                        ticket_row_id=noise_id,
                        terminal_status="REJECT_NOISE",
                        terminal_reason="automated_sender_or_no_active_keyword",
                        raw_source_id=arrival.message_id,
                    ):
                        terminal_written += 1
                        deterministic_cleared += 1
                    skipped += 1
                    conn.commit()
                    max_received = _advance(max_received, arrival.received_date)
                    continue

                # (e) RESERVE — DUPLICATE deterministic clear via dedup_key collision
                result = issue_ticket(ticket, conn)
                row_id = result.get("id")

                if result.get("skipped") and result.get("reason") == "duplicate" and row_id:
                    # CLAIM the row for terminal write (FOR UPDATE SKIP LOCKED).
                    claim = _claim_for_terminal(conn, row_id)
                    if claim is None:
                        lease_skipped += 1
                        conn.commit()
                        continue
                    claimed += 1
                    if write_terminal_status(
                        conn,
                        ticket_row_id=row_id,
                        terminal_status="DUPLICATE",
                        terminal_reason="dedup_key_collision",
                        raw_source_id=arrival.message_id,
                    ):
                        terminal_written += 1
                        deterministic_cleared += 1
                    skipped += 1
                    conn.commit()
                    max_received = _advance(max_received, arrival.received_date)
                    continue

                # (f) SAFE DEFAULT — TICKET (full desk review). With no D/E fast lane built,
                #     and/or fast_lane False, ALL non-clear arrivals land here.
                if row_id:
                    claim = _claim_for_terminal(conn, row_id)
                    if claim is None:
                        lease_skipped += 1
                        conn.commit()
                        continue
                    claimed += 1
                    if write_terminal_status(
                        conn,
                        ticket_row_id=row_id,
                        terminal_status="TICKET",
                        terminal_reason="safe_default_desk_review",
                        raw_source_id=arrival.message_id,
                    ):
                        terminal_written += 1
                        defaulted_ticket += 1
                    if result.get("ok"):
                        issued += 1
                    elif result.get("reason") == "bus_failed":
                        failed += 1
                    conn.commit()
                    max_received = _advance(max_received, arrival.received_date)

            except Exception as exc:  # ERROR NEVER AUTO-CLEARS (blocker D3)
                conn.rollback()
                failed += 1
                # an exception routes to safe-default / skip+log — NEVER to a clear.
                logger.warning("airport_ticketing run_tick row failed: %s", exc)
                continue

        # (g) ADVANCE CURSOR only on a clean tick, only to max received_date actually processed
        if max_received is not None:
            trigger_state.set_watermark(_WATERMARK_SOURCE, max_received)

        stuck_arrivals = _count_stuck_arrivals(conn)
        stats = {
            "ok": True,
            "issued": issued,
            "skipped": skipped,
            "failed": failed,
            "claimed": claimed,
            "terminal_written": terminal_written,
            "lease_skipped": lease_skipped,
            "deterministic_cleared": deterministic_cleared,
            "defaulted_ticket": defaulted_ticket,
            "stuck_arrivals": stuck_arrivals,
        }
        logger.info("airport_ticketing run_tick stats: %s", stats)
        return stats

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("airport_ticketing run_tick failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        store._put_conn(conn)
```

**5. SKIP-LOCKED row claim (copy the `claim_one_signal` shape, `kbl/pipeline_tick.py:92`):**

```python
def _claim_for_terminal(conn: Any, ticket_row_id: int) -> Optional[int]:
    """Intra-tick row claim. Returns the id iff this tick won the row (not already locked
    by a concurrent overlapping tick). Single-replica is inherited from scheduler_lease
    8800100 — this is row-level overlap safety only, NOT a process lease."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id
              FROM airport_tickets
             WHERE id = %s
               AND terminal_status IS NULL
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """,
            (ticket_row_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        cur.close()
```

> **`_advance` helper:** `def _advance(cur_max, candidate): return candidate if cur_max is None or (candidate and candidate > cur_max) else cur_max` — tracks the max `received_date` processed this tick (coerce naive → UTC, consistent with `fetch_email_arrivals`).

> **`reserve_noise_row` NOTE (decision for the builder, confirm with lead):** a REJECT_NOISE arrival may have no `airport_tickets` row (because `build_email_ticket` returned None before any reserve). Two valid shapes: (i) reserve a minimal row keyed by `_dedup_key('email', message_id, '<noise-desk>')` so the terminal write has a target row and the `dedup_key` UNIQUE still de-dups repeated noise; or (ii) write the noise terminal to a dedicated noise ledger. Prefer (i) — it reuses the existing `dedup_key` UNIQUE + status-guard machinery and keeps one terminal-write path. Do NOT invent a classifier; the noise decision is already made by `build_email_ticket` returning None. Surface the chosen shape in the ship report.

### Key Constraints

- **Status-guarded write is the ONLY terminal-write path.** No other code writes `terminal_status`. Every write carries `AND terminal_status IS NULL`.
- **`FOR UPDATE SKIP LOCKED`** for every row claim. No `SELECT ... FOR UPDATE` without `SKIP LOCKED` on `airport_tickets`.
- **Reuse `scheduler_lease` (lock 8800100).** Add NO advisory lock, NO `lease_owner`/`lease_expires_at`, NO parallel scheduler (blocker 4).
- **Cursor via `trigger_watermarks`** (`trigger_state` singleton) with a DISTINCT source key `airport_ticketing:email`. NO new cursor table.
- **`BOX5_FAST_LANE_ENABLED` default false.** When false, every non-deterministic-clear arrival = `TICKET`.
- **Error never auto-clears.** A thrown classify/registry/DB error → `failed` + safe default or skip+log; NEVER `deterministic_cleared`, NEVER `REJECT_NOISE`/`DUPLICATE`.
- **Every SELECT has `LIMIT`.** Every `except` calls `conn.rollback()`. All DB calls in try/except. Per-row try/except (one bad row never crashes the tick).
- **`raw_source_table='email_messages'` + `raw_source_id=message_id` populated on EVERY terminal write.**
- **Deterministic clears only** — DUPLICATE (real `dedup_key` collision) + REJECT_NOISE (real `_is_automated_email_arrival` / no-active-keyword). Do NOT invent a classifier, a project-number lane, a manifest lane, or `VISIBLE_HOLD`.
- **Pilot source = `email_messages` ONLY.** No WhatsApp / transcripts / `signal_queue`.

### Verification

Live-PG tests require `TEST_DATABASE_URL` (CI auto-provisions an ephemeral Neon branch); else they auto-skip. New file `tests/test_box5_ticketing_runner.py`.

1. **Idempotency (highest value).** Seed N `email_messages` rows + matching `airport_tickets` candidates. Run `run_tick` twice. Assert: after run 1, each processed row has a non-NULL `terminal_status` and a `terminal_outcome_written_at`; after run 2, **`terminal_outcome_written_at` is UNCHANGED** for every row (capture before/after timestamps and assert equality) and `terminal_written == 0` in run-2 stats. This proves the `terminal_status IS NULL` guard.
2. **SKIP-LOCKED concurrency (note + test).** With two connections on a `TEST_DATABASE_URL` branch, open a `FOR UPDATE` on one row in connection A, then call `_claim_for_terminal(connB, row_id)` and assert it returns `None` (skipped, not blocked) and the tick increments `lease_skipped`. Note in the ship report: SKIP LOCKED is intra-tick row safety, single-replica is already inherited from lock 8800100 — do not add a second lock.
3. **Safe-default TICKET.** Seed a relevant, non-duplicate, non-noise arrival with `BOX5_FAST_LANE_ENABLED` unset (false). Assert its `terminal_status == 'TICKET'`, `terminal_reason == 'safe_default_desk_review'`, `defaulted_ticket == 1`, and the bus post still occurred (existing `issue_ticket` path).
4. **Deterministic clears.** (a) DUPLICATE: seed two arrivals that collide on `dedup_key`; assert the second writes `terminal_status='DUPLICATE'`, `deterministic_cleared` counts it. (b) REJECT_NOISE: seed an arrival from `noreply@example.com` (and separately one with no active keyword); assert `terminal_status='REJECT_NOISE'` for both. (c) **None-id duplicate (reserve race):** when `reserve_ticket` loses an `ON CONFLICT … DO NOTHING` race it returns `{reserved:False, id:None}`, so `issue_ticket` yields `id=None`; assert that arrival falls through to NO terminal write this tick (counts as `lease_skipped`/no-op), raises NO exception, and leaves `terminal_status` NULL — the `and row_id` guard must hold, not crash.
5. **Error never auto-clears.** Monkeypatch `write_terminal_status` (or `build_email_ticket`) to raise on one specific row. Assert: that row's `terminal_status` stays NULL (or routes to TICKET — per design), the tick increments `failed` (NOT `deterministic_cleared`), no `REJECT_NOISE`/`DUPLICATE` is written for it, and the tick completes processing the remaining rows (one bad row did not crash the tick).
6. **Cursor advance.** Assert `trigger_state.get_watermark('airport_ticketing:email')` equals the max processed `received_date` after a clean tick, and that a tick which throws mid-way does NOT advance the watermark past unprocessed rows. Assert the key is `airport_ticketing:email`, never `email_poll`.
7. **Kill-switch.** With `AIRPORT_TICKETING_BRIDGE_ENABLED` unset, assert `run_tick` returns `{skipped:True}` and writes nothing. With it on but `BOX5_FAST_LANE_ENABLED` unset, assert every non-clear arrival = `TICKET`.
8. **Compile + targeted suite.** `python3 -c "import py_compile; py_compile.compile('orchestrator/airport_ticketing_bridge.py', doraise=True)"`; `pytest tests/test_box5_ticketing_runner.py -v`; plus any existing `tests/test_airport_ticketing*.py` to prove no regression in the issue path.

## Files Modified

- `orchestrator/airport_ticketing_bridge.py` — add `fast_lane_enabled()` + module constants (`_FAST_LANE_ENV`, `_WATERMARK_SOURCE`, `_STUCK_ARRIVAL_MINUTES`); add `write_terminal_status()`, `_claim_for_terminal()`, `_count_stuck_arrivals()`, `_advance()` (+ `reserve_noise_row()` if shape (i) chosen); extend `run_tick` body. Add `from triggers.state import trigger_state` import if not present.
- `tests/test_box5_ticketing_runner.py` — NEW test file (cases 1–8 above).

## Do NOT Touch

- The live `status` CHECK and `check_in_outcome` CHECK — orthogonal axes; BRIEF-C writes ONLY `terminal_status` + siblings.
- BRIEF-B's `terminal_status` CHECK definition / the 6-state list / `ensure_airport_ticket_terminal_columns` DDL — write the columns, do not redefine the CHECK.
- `scheduler_lease` lock id `8800100` / `acquire_singleton_lock` / `embedded_scheduler.py` lock acquisition — do NOT re-acquire, do NOT add a parallel lock.
- The issue path's existing behavior — `reserve_ticket`, `issue_ticket`, `mark_ticket_sent`/`_failed`, the bus post. BRIEF-C adds a terminal write ALONGSIDE; it does not change reserve/issue/mark semantics.
- The live email-poll watermarks `email_poll` / `email_poll_checked` — use a DISTINCT key.
- No new scheduler job, no new lease columns, no new cursor table, no migration (B's columns are live).
- No D/E logic: `project_code`, `matter_slug` write-routing, `manifest_match_signals`, `registry_version`, `classification_version`, `FAST_TICKET`, `VISIBLE_HOLD` — BRIEF-D/E own these; they stay NULL/default here.

## Quality Checkpoints

- [ ] Branch off `origin/main` @ `c63a3d2` or later (BRIEF-B's columns present).
- [ ] `grep "FOR UPDATE SKIP LOCKED" orchestrator/airport_ticketing_bridge.py` ≥ 1.
- [ ] Every `SET terminal_status` is followed by `WHERE ... terminal_status IS NULL`.
- [ ] `fast_lane_enabled()` returns False when env unset; `bridge_enabled()` still the master gate.
- [ ] Every SELECT has `LIMIT`; every `except` has `conn.rollback()`; per-row try/except present.
- [ ] `raw_source_table='email_messages'` + `raw_source_id` set on every terminal write.
- [ ] Watermark key = `airport_ticketing:email`, NOT `email_poll`.
- [ ] No new add_job / lease columns / cursor table / advisory lock / migration.
- [ ] Idempotency test (run twice, `terminal_outcome_written_at` unchanged) green.
- [ ] Error-never-auto-clears test green (exception → `failed`, never `deterministic_cleared`).
- [ ] codex G3 verdict obtained; lead `/security-review` G4 passed before merge.
- [ ] Ship report names the `reserve_noise_row` shape chosen + the `baker_actions` insert shape confirmed.

## Verification SQL

```sql
-- (1) Idempotency: no terminal row should EVER have terminal_status set without the write timestamp,
--     and a re-run must not move the timestamp. Run before/after a second tick; expect identical.
SELECT id, terminal_status, terminal_outcome_written_at, raw_source_table, raw_source_id
  FROM airport_tickets
 WHERE terminal_status IS NOT NULL
 ORDER BY terminal_outcome_written_at DESC
 LIMIT 50;

-- (2) Safe-default proof: with no fast lane built, non-clear arrivals must be TICKET.
SELECT terminal_status, COUNT(*)
  FROM airport_tickets
 WHERE terminal_status IS NOT NULL
 GROUP BY terminal_status
 LIMIT 10;
-- Expect only: TICKET / DUPLICATE / REJECT_NOISE  (no FAST_TICKET, no VISIBLE_HOLD, no project lane)

-- (3) Stuck-arrivals gauge (the journey metric the tick logs):
SELECT COUNT(*) AS stuck
  FROM airport_tickets
 WHERE terminal_status IS NULL
   AND source_received_at < NOW() - INTERVAL '30 minutes'
 LIMIT 1;

-- (4) raw_source_* populated on every terminal write:
SELECT COUNT(*) AS missing_raw_source
  FROM airport_tickets
 WHERE terminal_status IS NOT NULL
   AND (raw_source_table IS NULL OR raw_source_id IS NULL)
 LIMIT 1;
-- Expect 0.

-- (5) Audit trail present:
SELECT action_type, COUNT(*)
  FROM baker_actions
 WHERE action_type = 'airport_ticket.terminal_written'
 GROUP BY action_type
 LIMIT 1;

-- (6) Cursor advanced on the DISTINCT key, not the live email poll:
SELECT source, last_seen, updated_at
  FROM trigger_watermarks
 WHERE source = 'airport_ticketing:email'
 LIMIT 1;
```