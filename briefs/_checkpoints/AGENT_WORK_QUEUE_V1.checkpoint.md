---
brief_id: AGENT_WORK_QUEUE_V1
attempt: 2
status: DRILL DONE — PASS verdict posted (lead #8267 + deputy cc #8270); only lead flag-flip remains (lead-owned)
repo: brisen-lab (main @f9892dd — PR #109 MERGED)
work_branch: b1/agent-work-queue-v1
soak_start: 2026-07-09T21:49:47Z
soak_end_est: 2026-07-10T21:49:47Z
updated: 2026-07-09T22:49Z
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

## LEFT (lead-owned; nothing owed by b1)
1. Lead flips agent_queue_enabled (hag pilot only) per #8263 on this PASS verdict.
2. Prod 24h soak observation continues in parallel through ~2026-07-10T21:49Z (not gating; per #8264).

## KEY PATHS
- brisen-lab worktree: ~/bm-b1-brisen-lab (branch b1/agent-work-queue-v1; merged to main).
- Files: db.py, job_queue.py, app.py, bus.py, static/jobs.js, static/index.html, tests/test_agent_queue.py.
- Local test DB for drill/tests: psql -h localhost -p 5432 -d postgres -c "CREATE DATABASE bm_b1_queue_test"; export TEST_DATABASE_URL=postgresql://dimitry@localhost:5432/bm_b1_queue_test; python3 -m pytest tests/test_agent_queue.py -q; drop after.
- Gate isolation: full-suite-WITH-this-file shows ~25 pre-existing wake-cluster failures (BRISEN_LAB_TEST_ISOLATION_WAKE_CLUSTER_1) — use isolated run + full-suite-minus-file.

## NEXT CONCRETE STEP
NONE owed by b1. Arc DONE on b1 side: drill PASS + verdict posted (lead #8267, deputy #8270). Remaining action is lead's flag flip. If a fresh b1 seat resumes this checkpoint, stand down — do NOT re-run the drill.
