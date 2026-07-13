---
brief_id: BUS_READ_PATH_FALSE_EMPTY_FIX_1
dispatched_by: lead (#10329) + Plan v3 riders deputy-codex (#10403)
reply_target: lead + deputy-codex
attempt: 2
updated: 2026-07-13 (fresh seat claim)
claimed_by: B1 fresh seat (attempt->2) — implementing Option A per riders 1-5
status: RULING LANDED (lead #10553, thread #10539/#10542) — Option A ACCEPTED (my rec):
  single threading.BoundedSemaphore(pool_cap) chokepoint INSIDE get_conn; REVERT the async
  db_gate sweep. Checkpoint bumped with ruling per lead's "you're deep + E17-interactive —
  bump checkpoint FIRST, then dispatcher rolls a fresh seat." Fresh seat implements. attempt
  stays 1; the FRESH SEAT claims by bumping attempt -> 2 (checkpoint discipline, NOT a bus ack).

MERGE HAZARD: PR #130 remote HEAD = 46609b0 "WIP (DO NOT MERGE — unverified) full async
sweep, 93 to_thread->db_gate.db_call" — the prior seat COMMITTED + PUSHED the sweep (it was
NOT stashed as an earlier note said; git stash is empty). Do NOT merge #130 as-is. The fresh
seat force-pushes the branch off the WIP once the chokepoint replacement is verified.

A/B RESULT (settled): the isolated unread test FAILS at clean base 4b41467 (sweep absent) too,
with FK contamination — bg delivery/wake tasks insert delivery_receipt/wake_events for msg_id=1
while msg_id=1 is not in brisen_lab_msg (cross-TestClient DB-state bleed from module-global
db._pool + per-test bootstrap). Per the A/B logic (base FAIL => environmental), the unread
"drop" is a TEST-HARNESS ISOLATION ARTIFACT, NOT a read-logic bug. Read logic + async sweep
both EXONERATED. The full-suite DeadlockDetected (bootstrap ALTER TABLE AccessExclusiveLock
across repeated TestClients) is ALSO harness, and the threading-sem chokepoint does NOT change
async bg-task timing, so it should not reproduce that deadlock.
---

# Checkpoint — BUS_READ_PATH_FALSE_EMPTY_FIX_1 (E27 read-path)

## Brief
Fix brisen-lab bus read path (lead #10329 + Plan v3 riders #10403). Two harms (E27):
(a) degraded read returns a false-empty 200 (reads as "0 pending"); (b) unread=true
view silently drops older-than-`since` / beyond-limit unacked rows. AC: degraded reads
=> 503 never a clean empty; unread must be a COMPLETE unacked view.

## Root cause (C1) — CONFIRMED (lead #10369, researcher #10380)
Not capacity (0.14 req/s, ~10000x PG headroom). `app.py _startup()` pins the asyncio DEFAULT
executor to ThreadPoolExecutor(max_workers=pool_maxconn()=10). ALL blocking DB I/O runs
through it; `get_conn()`'s bounded-acquire retry + stale-probe call `time.sleep()` INSIDE those
workers. A few slow ops pin all threads; the request HANGS. Threadpool, not PG, is the bottleneck.

## LEAD RULING (#10553) — Option A, FIVE BINDING RIDERS
Mechanism: **`threading.BoundedSemaphore(pool_cap)` chokepoint INSIDE `get_conn`.** Invariant
provably holds at the single funnel (every DB op passes through get_conn), one edit, no bg-task
timing change. Riders (all mandatory this PR):
1. **REVERT the 98-site async db_gate sweep in the SAME PR** — ship ONE mechanism, not both.
2. **Bounded acquire w/ timeout -> fail-loud busy_retry/503, never indefinite block** — match
   lab#118 bounded-acquire semantics.
3. **Prove get_conn is never called on the event-loop thread** (blocking acquire there = daemon
   freeze) — add an assert/guard OR enumerate call paths in the PR description.
4. **Clean test read on CI's isolated ephemeral Neon branch**, not the flaky shared branch.
5. **codex re-gate MANDATORY** — state plainly the chokepoint satisfies the <=pool_cap invariant
   STRONGER than any sweep; if codex still FAILs, ESCALATE to lead (do NOT iterate blind).

## Current brisen-lab branch state (b1/bus-read-path-false-empty-fix-1)
- HEAD 46609b0 = WIP full async sweep (REVERT — rider 1).
- 4b41467 = rider a: async db_gate on write+ack hot paths (REVERT — replaced by chokepoint).
- 9aef527 = Plan v3 folds b+d: keyset pagination + soak/limiter test (KEEP — orthogonal).
- 60983f0 = folds a(read-path)+c: async db_gate read-path + auth-gate pool_stats (KEEP the
  pool_stats auth-gate + gauge; REMOVE the async db_gate.db_call read-path wiring).
- 1cc72c6 = executor decouple + authoritative read envelope + unread oldest-first + pool_stats (KEEP).
- db_gate.py (asyncio.Semaphore) is REPLACED by the get_conn threading.BoundedSemaphore — delete
  or reduce db_gate.py; remove every db_gate.db_call() call site.

## NEXT CONCRETE STEP (fresh seat — claim by bumping attempt -> 2 first)
1. Fresh `git -C ~/bm-b1/brisen-lab fetch && checkout b1/bus-read-path-false-empty-fix-1` (HEAD 46609b0).
2. REVERT the async db_gate mechanism: remove all `db_gate.db_call()` call sites (the 93/98-site
   sweep @46609b0 + the read/write/ack sites @60983f0/4b41467); delete db_gate.py. ONE mechanism.
3. Add `threading.BoundedSemaphore(pool_maxconn())` INSIDE `get_conn()` (db.py). Acquire with a
   bounded timeout; on timeout RAISE a fail-loud busy_retry/503 (match lab#118 semantics) — never
   block indefinitely. Release in the get_conn finally/context-exit path.
4. Guard rider 3: assert get_conn is not invoked on the event-loop thread (compare
   threading.current_thread() against the loop thread, or enumerate every call path in the PR body).
5. KEEP: keyset unread pagination (9aef527), soak/limiter test (9aef527), pool_stats auth-gate +
   gauge (60983f0), authoritative envelope + unread oldest-first (1cc72c6).
6. Re-verify FULL suite on CI's isolated ephemeral Neon branch (rider 4). Expect the harness
   deadlock + FK-contamination to clear once the async-timing sweep is gone; if the unread FK
   contamination persists, it is a pre-existing test-isolation bug — fix test setup (per-test msg
   FK integrity / bootstrap once), do NOT touch read logic.
7. Force-push branch (resets PR #130 off WIP 46609b0). Re-request codex G2; in the request state
   the chokepoint proves the <=pool_cap invariant globally (stronger than sweep). If codex FAILs,
   escalate to lead on thread #10553 — no blind iterate (rider 5).

## Separate queued (unchanged)
#10408 — P2 #547 retro ship report. Branch `b1/case-one-p2-lease-heartbeat-emitter` exists;
report `briefs/_reports/B1_CASE_ONE_P2_LIVENESS_LIFECYCLE_20260713.md` present. File retro.

## Bus trail
#10329 dispatch; #10369 C1->lead; #10380 C1->researcher; #10411 consolidated plan->deputy-codex;
#10539/#10542 my rec (threading-sem chokepoint)->lead; **#10553 lead RULING Option A + 5 riders
(ACKED)**. All inbound acked through #10553.
