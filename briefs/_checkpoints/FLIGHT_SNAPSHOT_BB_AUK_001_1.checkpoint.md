# CHECKPOINT — BAKER_OS_V2_FLIGHT_SNAPSHOT_BB_AUK_001_1

attempt: 1
owner: b2 · dispatched_by: lead (#5252) · date: 2026-07-04
brief: baker-master briefs/_tasks/BAKER_OS_V2_FLIGHT_SNAPSHOT_BB_AUK_001_1.md
work branch: b2/flight-snapshot-bb-auk-001-1 @03f3ace1

## STATUS: DONE — merged @0b6a68a, live, POST_DEPLOY_AC PASS (verdict #5269)
- Re-gate PASS #5264. Merged squash @0b6a68a. FLIGHT_SNAPSHOT_ENABLED=true on Render, live.
- AC6 live proof (b2 independent curl + lead #5265): GET /flights/BB-AUK-001 -> 200,
  banner + not-authoritative + timestamp + all D-24 fields, 0-outbound-rows clean.
  POST_DEPLOY_AC_VERDICT v1 emitted bus #5269 (lead+deputy). done_state DONE. NOTHING LEFT.

## (superseded) STATUS: b2 scope DONE — PR #456, codex F1 FIXED (re-ship #5262), awaiting re-gate + merge
- Codex gate #5260 REQUEST_CHANGES F1 (HIGH): resolve_project_number transitively did
  CREATE TABLE + commit (ensure_project_registry_table) → zero-write violation. FIXED
  @c9f1b06b: added resolve_project_number_readonly (SELECT-only) to project_registry_store.py;
  _project_meta uses it; new spy test test_project_meta_is_strictly_read_only proves no
  DDL/commit. 14 tests pass. Re-shipped #5262 for re-gate.

- T1 orchestrator/flight_snapshot.py (assembler + HTML render + index).
- T2 GET /flights/{code} + T3 GET /flights on cockpit (dashboard.py route reg only).
- Feature flag FLIGHT_SNAPSHOT_ENABLED default OFF (→404 until flipped).
- Zero writes (D-23) grep-clean. No mockup-v3 reuse (D-29).
- Tests: tests/test_flight_snapshot.py 13 passed + test_dashboard.py 6 passed regression.
- Ship report: briefs/_reports/B2_FLIGHT_SNAPSHOT_BB_AUK_001_1_SHIP_20260704.md.

## What's LEFT
1. Codex gate (lead routes, effort medium additive read-only) → lead merge.
2. Render auto-deploys from main on merge (flag OFF = dark, safe).
3. AC6 POST_DEPLOY_AC: after Director/lead flips FLIGHT_SNAPSHOT_ENABLED=true on Render,
   curl /flights/BB-AUK-001?key=<BAKER_API_KEY> → confirm banner + all D-24 fields render
   with 0 outbound rows → emit POST_DEPLOY_AC_VERDICT v1 to lead.

## Notes
- No flight lifecycle store exists (D-23); snapshot is evidence-assembled, labeled non-authoritative.
- airport_outbound_events is b4's writer output (may be 0 rows until his drain lands — 0-rows renders clean).
- Data fan-in keys: project_code (outbound_events + baker_actions payload), matter_slug (tickets + deadlines).
