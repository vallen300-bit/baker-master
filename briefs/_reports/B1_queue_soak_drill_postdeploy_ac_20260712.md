# B1 — AGENT_WORK_QUEUE_V1 Checkpoint-8 Soak Drill — POST_DEPLOY_AC_VERDICT v1

**Dispatch:** #9259 (lead, `dispatch/queue-soak-drill`, owed from 07-09). **Arc:** AGENT_WORK_QUEUE_V1 (pilot LIVE hag-desk, flag re-ON 07-10). **Author:** b1. **Date:** 2026-07-12.
**Lead rulings folded:** #9277 — flag-ON expected (brief premise stale), seed synthetic `DRILL-` job (don't touch real id=2), capture the 503 read-path defect as a finding, id=2 routed to deputy.

## Verdict: **PASS-WITH-FINDINGS** (1 real defect, 1 mechanic to confirm)

Queue deployed live-on (flag ON, hag pilot). Lifecycle + guards + bus-mirror verified on production; the seeded expire→dead→RED path verified by the brief-prescribed deterministic drill. One real reliability defect found (503 read-path flap). One checkpoint-8 mechanic needs lead confirmation (see §Open).

## AC results

| # | Acceptance criterion | Result | Evidence |
|---|---|---|---|
| 1 | Flag-on soak: queue serves live-on for hag pilot | **PASS** | `GET /jobs` 200 serving; flag ON confirmed (#9277 ruling 1) |
| 2 | create → row in `created` (+ bus mirror) | **PASS** | seeded `DRILL-queue-soak-b1` → id=3 `created`; bus mirror `queue/3/created` from daemon (#9282) |
| 3 | claim → `claimed`, lease set | **PASS** | `/jobs/3/claim` → `claimed`, lease_until +24h |
| 4 | heartbeat producer refreshes/extends | **PASS** | `/jobs/3/heartbeat` → 200, lease extended |
| 5 | never-self-verify guard | **PASS** | `/jobs/3/verify` (owner=b1) → **403 `verify_requires_dispatcher`** |
| 6 | done requires proof | **PASS** | `/jobs/3/done` no proof → **400 `proof_required`**; valid `bus_msg` proof → `done` |
| 7 | sweeper: stalled seat → expired (attempt++) | **PASS (deterministic drill)** | `test_sweeper_expires_and_deadletters` PASSED (local PG) |
| 8 | sweeper: expired@attempt>=2 → **dead + RED alert** | **PASS (deterministic drill)** | same test asserts `state='dead'` + alert row in `brisen_lab_msg`; brief-prescribed mechanic (line 211) |
| 9 | slow seat (live hb past lease) → amber alert, NOT expired | **PASS (deterministic drill)** | `test_sweeper_slow_seat_not_expired` PASSED |
| 10 | sweeper never touches `blocked` | **PASS** | `test_sweeper_ignores_blocked` PASSED |
| 11 | concurrent sweepers (2 replicas) no double-work | **PASS** | `test_two_sweepers_no_wedge` PASSED (xact advisory lock) |
| 12 | RED badge = dead+expired per card | **PASS** | `test_jobs_glance_badges_dead_expired_only` PASSED |

**Deterministic drill:** `tests/test_agent_queue.py` on a fresh local PG — **35 passed, 1 failed**. The 1 failure (`test_session_heartbeat_touches_active_jobs`) **passes in isolation** → test-ordering/settings-cache artifact (matches the G0 rev3 "test isolation in conftest" nit), **not** a deployed defect (Feature-6 heartbeat producer proven working on prod, AC#4). Literal counts recorded; not claimed green-by-inspection.

## Findings

**F-503 (REAL DEFECT — per lead ruling 3, do not fix this lane).** `/jobs` endpoints intermittently return **`503 {"detail":"bus_busy_retry"}`** on the READ path (`GET /jobs`) *and* WRITE paths (`/jobs/{id}/verify`, `/heartbeat`, `/done`), masking the real response. Repro: rate **variable 5%–60%** across bursts (1/20 one run, 3/5 another); correlates with high tail latency (`GET /jobs` `time_total` 0.6s–7.4s). Header sample on success: `HTTP/2 200`, `x-render-origin-server: uvicorn`, `cf-ray … -VIE`. Impact: a read-only fleet view (e.g. `/bus-console`, dashboard Jobs drawer) sporadically fails; callers must retry. Root-cause hypothesis: the bus-busy advisory-lock guard wraps queue endpoints including reads. Owner: lead to dispatch a fix lane.

**N-1 (test-isolation flake, not deployed):** `test_session_heartbeat_touches_active_jobs` order-dependent (settings cache/`_enable_queue` state bleed). Passes isolated. Recommend conftest reset of the settings row per test.

## Open — checkpoint-8 mechanic for lead

The **prod** expire→dead→RED path could **not** be observed end-to-end in one session: lease default is **24h**, `dead` requires a re-claim→re-expire cycle (attempt_count≥2), and I have **no prod-DB backdate access** to compress it. I verified that path via the deterministic drill (the exact mechanic brief line 211 prescribes: seed past-lease + attempt=1 → run sweep → dead + alert). **Confirm:** does the deterministic drill satisfy checkpoint-8's dead-letter AC, or do you want a scheduled ~25h prod natural-expiry run (I'd seed a `DRILL-` job, stop heartbeating, and re-check on a timer)?

## Cleanup

Synthetic `DRILL-` job **id=3** parked as `state=done` (owner-terminal state; I cannot self-verify). **Dispatcher action needed:** verify-close or delete id=3. Real job **id=2** untouched (routed to deputy per ruling 4). No other bus/DB writes beyond the drill job + self-acks.
