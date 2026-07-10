---
brief_id: AGENT_WORK_QUEUE_V1
attempt: 2
status: STOOD DOWN — latency-fix lane (#8300) reassigned to b2 per lead #8329; b1 idle. Only future live render check remains (lead re-routes on pilot re-flip).
repo: brisen-lab (main @f9892dd — PR #109 MERGED)
work_branch: b1/agent-work-queue-v1
soak_start: 2026-07-09T21:49:47Z
soak_end_est: 2026-07-10T21:49:47Z
updated: 2026-07-10T01:40Z
---

# AGENT_WORK_QUEUE_V1 — checkpoint

## DONE
- All 6 features + G3 P1 fix built/committed/pushed/MERGED (brisen-lab PR #109 @f9892dd):
  F1 schema afc78fd · F2 API 840703f (+tests 3776bd5) · F3 sweeper 3d17392 · F6 heartbeat 0d2f509 · F4 dispatch-hook a8f64ad · F5 badge/drawer 49f7b3a · G3 fix f9892dd.
- tests/test_agent_queue.py = 36/36 green on live PG. Zero regressions (full-suite-minus-that-file = 438/2 clean-main baseline, re-proven each slice).
- codex G3 PASS-WITH-NOTES #8258 (no live-PG in codex shell; 36/36 = builder evidence). Merged 21:42Z.
- Deployed to prod (Render from main). Flag agent_queue_enabled default OFF.
- Flag-off INERT verified live: POST/GET /jobs -> 503 queue_disabled; /api/jobs-glance -> {enabled:false, badges:{}, jobs:[]}; /api/state,/v2/terminals,/v2/matters,/lifecycle/status,/wake_health -> 200 (zero behavior change).
- F5 render check PASS (Chrome, live page): jobs.js loads; Jobs button hidden (flag off); badges/drawer render correctly under mocked populated glance (hag-desk=3, b2=1; 3 rows id/role/state/lease-age, NO titles). No F5 console errors (404=favicon, 503=transient deploy-swap).
- Deploy-live + soak-start posted lead #8261.

## DONE (attempt 2 — Director-accelerated drill per lead #8263/#8264)
- Seeded-failure drill RUN + PASS (local PG bm_b1_queue_drill, identical merged code @f9892dd; prod flag stays OFF pending lead flip):
  create job#1 -> claim(att0) -> kill hb -> sweep#1=expired(att1, NO RED) -> re-claim(att1 preserved) -> kill hb -> sweep#2=expired(att2)->dead + RED alert.
  RED alert LANDED: bus msg#4 topic=queue/1/dead kind=alert to=[codex-arch,cowork-ah1,deputy,lead] body="DEAD job 1 ... attempts=2 ... (RED)."
  /api/jobs-glance: badges={hag-desk:1}, dead row {id,role,state,lease_age_secs} only — NO title/spec leak.
- Regression: tests/test_agent_queue.py 36/36 green on fresh PG.
- Drill harness written: tests/test_agent_queue_drill.py (UNCOMMITTED worktree artifact ~/bm-b1-brisen-lab; offered to lead to fold into suite).
- POST_DEPLOY_AC_VERDICT v1 PASS posted: lead #8267 (fleet/agent-work-queue) + deputy cc #8270 (post-deploy-ac/agent-work-queue-v1).

## FOLLOW-ON: pilot flip (#8272) — BLOCKED on prod creds/authority, escalated to lead (#8275)
Lead re-dispatched the pilot flip TO b1 (#8272, Director GO given): 1) flip prod brisen_lab_settings
agent_queue_enabled=on + agent_queue_pilot_roles=hag-desk; 2) live verify; 3) seed one live hag-desk
job -> confirm real-data render -> clean; 4) confirm on fleet/agent-work-queue.
BLOCKED (failed loud per #8272 "do NOT improvise creds"):
- No settings-write API endpoint on brisen-lab daemon (grep app.py) — flip = RAW prod DB write only.
- No identifiable brisen-lab PROD conn string in op: only TEST_DATABASE_URL_BRISEN_LAB (test),
  CODEX_NEON_READONLY (ro), generic DATABASE_URL (unlabeled — almost certainly baker-master, not brisen-lab).
- Authority gap: b1 cannot POST /jobs assigned hag-desk on live daemon (non-dispatcher 403) for step 3.
Escalated to lead #8275 with 2 paths (A: lead provides prod conn + dispatcher seed path, b1 does all;
B: lead does flip+seed, b1 does read-only live verify + render confirm). b1 leans B. AWAITING lead.

## UPDATE: lead flipped centrally (#8284) + handed b1 a live incident lane
- Lead executed step 1+2 (flip agent_queue_enabled=on + pilot=hag-desk, SELECT-verified 22:55:51Z, glance enabled:true). My #8275 fail-loud was confirmed correct; creds resolved lead-side via Render API.
- NEW b1 lane (#8284): diagnose live latency/pool incident (DB endpoints 10-26s, intermittent bus_busy_retry since ~22:50Z, predates flip). Report root cause + fix BEFORE code change.
- DELIVERED diagnosis -> lead #8296 (fleet/agent-work-queue). Two problems:
  A. latency/bus_busy_retry = Neon autosuspend + direct-conn stale-recycle loop (get_conn db.py:157-212, 15s tcp_user_timeout per stale probe) under wake surge of 8 shared-pool startup loops (maxconn=10, no warmer).
  B. DEFINITE bug: app.py:1754 /api/jobs-glance bare `except Exception` returns enabled:false on BusPoolExhausted -> falsely shows pilot DISABLED under load (the 0.12s enabled:false).
  Fix proposal (no code yet): 1) glance swallow fix; 2a) keep Neon warm / warmer loop; 2b) short per-probe statement_timeout (~2s); 2c) Neon max_conn vs fleet pools. Sequence 1+2b first.
- LIVE incident confirmed first-hand: my report post 503'd/timed out attempts 1-2, landed attempt 3 (#8296).

## STAND-DOWN (lead #8329, 2026-07-10T01:37Z) — b1 latency-fix lane closed
Sequence after diagnosis #8296: lead green-lit the fix to b1 (#8300, 23:13Z: fix 1 glance-swallow
+ fix 2b ~2s probe timeout, TDD, codex medium gate). Prior b1 seat went silent. Lead status-checked
(#8328, 00:49Z), then STOOD b1 DOWN (#8329, 01:37Z) and reassigned the lane to **b2**.
- Fresh b1 seat (this one) read + acked #8300/#8328/#8329 at ~01:39Z. Confirmed stand-down to lead
  (fleet/agent-work-queue #8331 — note: posted 4x #8331-8334 due to a success-check grep bug, harmless dupes).
- **DO NOT build the glance-swallow / probe-timeout fix — b2 owns it now.**
- b1 owes nothing on AGENT_WORK_QUEUE_V1 except the FUTURE live render check, which lead re-routes
  when the pilot re-flips (see LEFT #2).

## LEFT (b1 idle — single deferred item)
1. ~~Write failing pytest + PR for glance-swallow fix~~ — REASSIGNED to b2 (#8329). Not b1's.
2. Future live hag-desk render check — deferred; lead seeds the live job (b1 403 on cross-assign),
   b1 verifies render + confirms no title/spec leak, lead cleans. Lead re-routes to b1 when the
   pilot re-flips and the DB surface is stable. NOT actionable until lead pings.
3. Prod 24h soak observation ran in parallel through ~2026-07-10T21:49Z (non-gating; per #8264).

## KEY PATHS
- brisen-lab worktree: ~/bm-b1-brisen-lab (branch b1/agent-work-queue-v1; merged to main).
- Files: db.py, job_queue.py, app.py, bus.py, static/jobs.js, static/index.html, tests/test_agent_queue.py.
- Local test DB for drill/tests: psql -h localhost -p 5432 -d postgres -c "CREATE DATABASE bm_b1_queue_test"; export TEST_DATABASE_URL=postgresql://dimitry@localhost:5432/bm_b1_queue_test; python3 -m pytest tests/test_agent_queue.py -q; drop after.
- Gate isolation: full-suite-WITH-this-file shows ~25 pre-existing wake-cluster failures (BRISEN_LAB_TEST_ISOLATION_WAKE_CLUSTER_1) — use isolated run + full-suite-minus-file.

## NEXT CONCRETE STEP
NONE — b1 is STOOD DOWN (lead #8329). Do NOT build the glance-swallow/probe-timeout fix (b2 owns it).
Do NOT re-run the drill (PASS, #8267/#8270). Do NOT improvise prod DB or Render creds. Do NOT change code.
A future b1 seat: this arc is idle for b1. The only remaining b1 item is the deferred live render check
(LEFT #2), and it is NOT actionable until lead explicitly re-routes it on pilot re-flip. Idle until then.
