---
brief_id: AGENT_WORK_QUEUE_V1
attempt: 2
status: DRILL-IN-PROGRESS (attempt 2 — successor seat claimed per lead #8263/#8264, Director-accelerated drill)
repo: brisen-lab (main @f9892dd — PR #109 MERGED)
work_branch: b1/agent-work-queue-v1
soak_start: 2026-07-09T21:49:47Z
soak_end_est: 2026-07-10T21:49:47Z
updated: 2026-07-09T22:41Z
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

## LEFT (only remaining work = post-soak AC; NO code left)
1. After 24h soak (~2026-07-10T21:49Z) OR lead's post-soak dispatch on topic fleet/agent-work-queue: run seeded-failure drill = the AC (lead #8259 step 4). Drill needs the queue exercised; lead flips agent_queue_enabled for pilot only AFTER the verdict.
2. Drill: create job -> claim -> kill heartbeat (lease expires, no heartbeat) -> sweeper expired (attempt1) -> expired (attempt2) -> dead + RED alert bus post to dispatcher set (topic queue/<id>/dead, kind=alert). Verify the alert lands.
3. Post POST_DEPLOY_AC_VERDICT v1 to lead (post-deploy-ac-bus-gate skill) with drill result + evidence (job ids, transitions, alert msg id).
4. Owed: F5 populated render on LIVE data re-confirms during the drill (flag on).

## KEY PATHS
- brisen-lab worktree: ~/bm-b1-brisen-lab (branch b1/agent-work-queue-v1; merged to main).
- Files: db.py, job_queue.py, app.py, bus.py, static/jobs.js, static/index.html, tests/test_agent_queue.py.
- Local test DB for drill/tests: psql -h localhost -p 5432 -d postgres -c "CREATE DATABASE bm_b1_queue_test"; export TEST_DATABASE_URL=postgresql://dimitry@localhost:5432/bm_b1_queue_test; python3 -m pytest tests/test_agent_queue.py -q; drop after.
- Gate isolation: full-suite-WITH-this-file shows ~25 pre-existing wake-cluster failures (BRISEN_LAB_TEST_ISOLATION_WAKE_CLUSTER_1) — use isolated run + full-suite-minus-file.

## NEXT CONCRETE STEP
Wait for soak to elapse / lead post-soak drill dispatch, then run the seeded-failure drill and post POST_DEPLOY_AC_VERDICT v1. Verification only — nothing to build.
