# BAKER_OS_V2_FLIGHT_SNAPSHOT_BB_AUK_001_1

**Repo:** `baker-master` (base `main` @006c4aa) · **Worker:** b2 · **Dispatcher:** lead (AH1)
**Recommended effort:** medium (read-only assembly + one route; no writes, no state mutation)
**Origin:** D-30 (Director, 2026-07-04): flight dashboards start TODAY as read-only snapshots per D-24 (per-flight dashboard contract) + D-29 (two-surface model). Ledger: `baker-vault/_ops/build/baker-os-v2/04_working_brief/decision_action_log.md` §D-24/§D-29/§D-30.

## Context Contract

- **Task class:** production implementation, read-only surface, feature-flagged.
- **Pilot flight:** `BB-AUK-001` (Aukera financing Baden-Baden), desk `baden-baden-desk`.
- **Data sources (read-only):** `airport_tickets` (BB gate), `airport_outbound_events` (rows will start appearing from BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1, b4 in flight — handle 0-rows gracefully), project registry (`resolve_project_number` — gives matter_slug/desk/clickup_list_id), `models/` deadlines for the matter, `baker_actions` audit refs.
- **Surface:** new read-only route on the CEO Cockpit (`outputs/dashboard.py` app — be surgical, file is ~11.7k lines; a separate module imported by the app is preferred), e.g. `GET /flights/BB-AUK-001`. Auth: same `X-Baker-Key` model as existing cockpit routes... follow whatever the existing dashboard HTML routes do.
- **Sequencing rulings (do not relitigate):**
  - **D-24:** until the flight lifecycle store exists, dashboards are read-only snapshots assembled from available evidence; they must NOT claim authoritative live flight-state.
  - **D-29:** do NOT wire the `BB-AUK-001` mockup-v3 draft content (unratified, Director redesign pending). Layout minimal + clean; the D-24 FIELD LIST is the ratified content contract.
  - **D-23:** no flight-state mutation anywhere. Zero writes. This surface only reads.

## Problem

Director has no per-flight view. D-24 requires every active flight to have a Director-visible dashboard/snapshot; today BB-AUK-001 state lives scattered across tickets, ClickUp, and bus traffic.

## Tasks

### T1 — Snapshot assembler (pure read)
Module (e.g. `orchestrator/flight_snapshot.py`) building a snapshot dict for a project code, covering the D-24 field contract as far as evidence allows: outcome, deadline, current state (derived, labeled "derived from evidence"), next owner/action, blockers, condition precedents, evidence refs, human nudges, ClickUp refs, ticket/dispatch refs, returned-package status, history (recent events, newest first). Missing evidence ⇒ explicit "no data yet" per field, never invented values. All DB reads try/except; each source degrades independently.

### T2 — Route + render
`GET /flights/<project_code>` on the cockpit app: server-rendered static HTML (match cockpit's vanilla-JS/HTML idiom; muted McKinsey-style, no framework). Prominent banner: "READ-ONLY SNAPSHOT — assembled from evidence at <timestamp>; not authoritative flight state" (D-24 wording requirement). Unknown project code ⇒ 404. Feature flag env `FLIGHT_SNAPSHOT_ENABLED` (default false).

### T3 — Extensibility hooks (cheap now, needed for Control Tower)
Assembler is per-project-code generic (BB-AUK-001 just the pilot arg); an index route `GET /flights/` listing registered project codes with one-line state. NO Control Tower build (out of scope, D-29 Surface 2 later).

## Constraints
- ZERO writes to any table, any external system. Read-only or it doesn't ship.
- Surgical on `outputs/dashboard.py` — route registration only; logic lives in the new module. Re-run relevant tests after touching it (repo hard rule).
- No mockup-v3 content/layout reuse (unratified).
- Tests first: assembler unit tests with seeded/empty evidence (0 outbound rows MUST render cleanly — b4's drain may not have landed).

## Done rubric / Acceptance criteria
1. `GET /flights/BB-AUK-001` renders live: every D-24 field present (value or explicit "no data yet"), snapshot banner + timestamp visible.
2. 0-outbound-rows state renders cleanly (screenshot/curl proof before b4's drain lands = the natural test).
3. Flag off ⇒ 404/disabled; flag on ⇒ live. Unknown code ⇒ 404.
4. Zero write statements in the diff (grep-provable: no INSERT/UPDATE/DELETE/ClickUp client writes).
5. Existing dashboard tests green; new unit tests for assembler.
6. POST_DEPLOY_AC verdict on bus per `post-deploy-ac-bus-gate` (Render auto-deploys from main).

## Gate plan
1. pytest green. 2. Codex gate (lead routes; effort=medium — additive read-only). 3. POST_DEPLOY_AC on bus with live URL proof.

## Notes for worker
- Branch: `b2/flight-snapshot-bb-auk-001-1`. PR to `main`, ship report + gates to lead on bus.
- Coordinate nothing with b4 — his writer writes, you read; empty-safe rendering is your only coupling.
