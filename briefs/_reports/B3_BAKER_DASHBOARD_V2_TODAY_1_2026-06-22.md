# Ship Report — BAKER_DASHBOARD_V2_TODAY_1

**Builder:** B3
**Date:** 2026-06-22
**Branch:** `b3/baker-dashboard-v2-today-1` (off `main` — incl. #405/#406/#407, head bdd34f0)
**Dispatch:** bus #3889 (deputy / codex-arch #3884), acked
**Merge:** HELD — deputy is Director-authorized merge owner; gate chain G0→G1→G2 must PASS first.

---

## What shipped

V2 "Verified Operating Room" **Tranche 4 (live build step 3)** — the first
trusted Today read API. **Backend-only, read-only.** No UI, no model calls, no
migrations, no writes (AC10).

Files:
- `models/verified_items.py` — adds `list_today_items(limit=200)` (read-only,
  trusted states, Today sort order). `list_items` unchanged.
- `orchestrator/today_v2.py` — new deep module: lane mapping, source-ref
  sanitization, per-lane assembly. Reads only via `list_today_items`.
- `outputs/dashboard.py` — one thin `GET /api/today` route (delegates to the
  service; no SQL of its own). Existing routes untouched.
- `tests/test_today_v2.py` — 11 pure/endpoint + 1 live-PG integration.

---

## DONE RUBRIC

**1. What exact rows can enter Today?**
Only `verified_items` rows whose `state ∈ {verified, ratified}` AND whose
`item_type` maps to an allowlisted lane. Everything else is excluded.

**2. What exact rows are excluded?**
`candidate` + `dismissed` states (dropped by the state filter); unknown
`item_type` (dropped, counted under `excluded`). `signal_candidates`, raw
`alerts`, raw `deadlines`, calendar/trip rows, and legacy critical/deadline
helpers are **never read** — the service only ever calls `list_today_items`,
which selects exclusively from `verified_items`.

**3. How are the four lanes mapped?**
`ITEM_TYPE_TO_LANE` allowlist (AC3): critical/critical_item→`critical`;
promise/commitment/deadline/action_item→`promises`; meeting/meeting_prep/
meeting_followup→`meetings`; travel/travel_obligation/trip→`travel`. Unknown
types increment `counts.excluded` — no 5th lane is invented.

**4. How are source refs sanitized?**
`sanitize_source_refs` recursively strips any dict key equal to or ending in
`body`/`raw_body`/`text`/`content`/`snippet`/`source_snippet`/`transcript` (so
`email_body`, `full_text`, nested `raw_body`, etc. all go). Non-list input →
`([], 0)`. `source_refs_count` reflects the pre-strip count so a card can show
"N sources" while exposing only metadata.

**5. Which tests prove candidates/raw legacy rows cannot leak?**
- `test_build_excludes_candidate_and_dismissed` (AC8 4-row: candidate+dismissed
  excluded, only verified+ratified appear).
- `test_list_today_items_sql_reads_only_verified_items` (captures the executed
  SQL; asserts `verified_items` + `state IN ('verified','ratified')` and that
  `signal_candidates`/`alerts`/`deadlines` never appear).
- `test_today_service_does_not_read_raw_tables` + `test_get_today_route_is_thin_and_delegates`
  (structural — no query path to raw tables; route runs no SQL).
- `test_source_refs_sanitized` + `test_build_strips_raw_keys_end_to_end` + the
  live integration test (body stripped end-to-end against real PG).

**6. Which command output proves the endpoint works?**
`python3.12 -m pytest tests/test_today_v2.py tests/test_verified_items.py
tests/test_candidate_ingest.py` → **72 passed** (12 today_v2 + 60 regression).
The live integration test (`test_get_today_payload_live_read_path`) runs the real
read path against Postgres: empty DB → stable empty shape (AC9); after inserting a
verified deadline with a `body`-bearing source ref, `/api/today` returns it in the
`promises` lane with the body stripped. The route test (TestClient) returns 200 +
correct shape with the key and 401/403 without. Live `/api/today` curl is the
POST_DEPLOY_AC after merge.

**7. What remains for the later UI tranche?**
`BAKER_DASHBOARD_V2_TODAY_UI_1` wires the first screen to `/api/today`;
`BAKER_DASHBOARD_V2_VERIFIER_1` populates `verified_items` (it is empty live now —
so `/api/today` correctly returns empty lanes, AC9, which is the expected valid
state until the verifier engine lands); `BAKER_DASHBOARD_V2_MATTER_ROOMS_1`. No
UI/model/writes were added here.

---

## Acceptance criteria

| AC | Status | Evidence |
|----|--------|----------|
| AC1 `GET /api/today` authenticated | PASS | route w/ `Depends(verify_api_key)`; thin delegate |
| AC2 only verified/ratified | PASS | `list_today_items` WHERE state IN(...); SQL-capture test |
| AC3 lanes allowlisted | PASS | `ITEM_TYPE_TO_LANE`; unknown→excluded |
| AC4 stable + sanitized card | PASS | 19-field card; recursive raw-key strip |
| AC5 no raw body leakage | PASS | sanitize tests + live body-strip |
| AC6 per-lane limit | PASS | default 5, clamp ≤20; limit test |
| AC7 morning-brief not rewritten | PASS | no edit to morning-brief/app.js; structural test |
| AC8 candidates cannot appear | PASS | 4-row state test |
| AC9 empty-state shape | PASS | empty-shape test + live empty path |
| AC10 no model/writes/migrations/UI | PASS | read-only; service makes no model call, no DDL, no writes |

---

## Gate

Builder self-test PASS (72 tests) → **G0 deputy-codex** (no raw/candidate bypass,
no dashboard rewrite) → **G1 deputy cross-lane** (static) → **G2 security-review**
(MANDATORY — authenticated route + DB read path) → **deputy merges**. Merge HELD
until all gates PASS. Post-deploy AC will be posted on live `/api/today` after
deploy.

Note: `verified_items` is empty in production (no verifier engine yet), so the
live endpoint will return empty-but-valid lanes — reported as correct, not a
failure.
