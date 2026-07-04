# B2 SHIP REPORT — BAKER_OS_V2_FLIGHT_SNAPSHOT_BB_AUK_001_1

**Date:** 2026-07-04 · **Worker:** b2 · **Dispatcher:** lead (#5252)
**Brief:** baker-master `briefs/_tasks/BAKER_OS_V2_FLIGHT_SNAPSHOT_BB_AUK_001_1.md`
**PR:** baker-master **#456** (`b2/flight-snapshot-bb-auk-001-1` @03f3ace1)

## What shipped
- **T1 `orchestrator/flight_snapshot.py`** — pure-read snapshot assembler. `build_flight_snapshot(project_code)` fans into the full D-24 field contract from 5 independent evidence sources: `resolve_project_number` (registry meta), `airport_outbound_events` (by project_code), `airport_tickets` (by suspected_matter_slug/suspected_flight), `deadlines` (by matter_slug), `baker_actions` (by payload->>'project_code'). Each `_fetch` is try/except → degrades to [] on failure; missing evidence ⇒ explicit `no data yet` (never invented). `current_state` labeled "derived from evidence; NOT authoritative live flight-state" (D-23/D-24). Unknown code ⇒ None. `list_registered_flights()` for the index. All reads bounded (LIMIT).
- **T2 `GET /flights/{project_code}`** on the cockpit — server-rendered McKinsey-muted HTML (cream/navy, no framework, no mockup-v3 reuse). Prominent banner "READ-ONLY SNAPSHOT — assembled from evidence at <ts>; not authoritative flight state" + assembled_at. Feature flag `FLIGHT_SNAPSHOT_ENABLED` (default **OFF** ⇒ 404). Unknown code ⇒ 404. Auth via existing `_mcp_verify_key` (?key= or X-Baker-Key). dashboard.py change = route registration only (3 routes + 1 flag helper); logic in the module.
- **T3 `GET /flights`** — index of registered active projects, one-line state, links to per-flight pages. Assembler is per-project-code generic (BB-AUK-001 = pilot arg). No Control Tower (D-29 Surface 2, deferred).

## Constraints honored
Zero writes (D-23) — grep-clean, no INSERT/UPDATE/DELETE/commit/clickup-write in diff. Surgical on dashboard.py. No mockup-v3 content/layout reuse (D-29). 0-outbound-rows renders cleanly (b4's writer may not have drained). All DB reads try/except.

## Tests (literal pytest)
`tests/test_flight_snapshot.py` — **13 passed**: unknown/blank code ⇒ None; 0-evidence ⇒ every D-24 field present, purely-evidence fields "no data yet", registry-backed fields (next_owner=desk, clickup=list_id) honest; seeded evidence populates + current_state labeled derived + history newest-first; HTML escape; banner+timestamp+all field labels; route flag-off⇒404, no-key⇒401, unknown⇒404, known⇒200 render, index⇒200. `test_dashboard.py` regression: **6 passed**. App imports + all 3 /flights routes register.

## Acceptance criteria
- AC1 ✅ every D-24 field present (value or "no data yet"), banner + timestamp (tests).
- AC2 ✅ 0-outbound-rows renders cleanly (test); live curl proof at post-deploy.
- AC3 ✅ flag off ⇒ 404; unknown ⇒ 404 (route tests).
- AC4 ✅ zero writes (grep-provable).
- AC5 ✅ existing dashboard tests green + new assembler/route tests.
- AC6 ⏳ POST_DEPLOY_AC verdict on bus after Render auto-deploy (merge). Flag stays OFF until Director/lead flips `FLIGHT_SNAPSHOT_ENABLED=true`; live curl of `/flights/BB-AUK-001?key=` = the AC2 proof then.

## Post-deploy (after merge → Render auto-deploy)
Set `FLIGHT_SNAPSHOT_ENABLED=true` (lead/Director decision) → curl `/flights/BB-AUK-001?key=<BAKER_API_KEY>` → confirm banner + all fields render with 0 outbound rows → emit `POST_DEPLOY_AC_VERDICT v1`.
