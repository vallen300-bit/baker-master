# B2 SHIP REPORT — AO_DASHBOARD_LIVE_WIRING

- **Dispatched by:** lead (#7132, references deputy #7130)
- **Date:** 2026-07-08
- **Branch:** `b2/ao-dashboard-live-wiring`
- **Commit:** `1de73c0b`
- **PR:** #487
- **Task class:** small-fix-production (data-only)

## What shipped
`orchestrator/flight_dashboards/AO-OSK-001.json` — a new `FLIGHT_DASHBOARD_PACKET v2`
desk snapshot so `/flight/AO-OSK-001` serves 200 (was 404 on the missing JSON; route +
flag already live in prod). Mirrors `BB-AUK-001.json` shape exactly. **No code changed —
data file only.**

## Content (transposed, not invented)
All 7 desk cards transposed from the curated Page-v4 source
(`baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/AO-OSK-001/dashboard-v1.html`):
header · decide_now (EUR 100K reconciliation, CONCEDE✓/HOLD) · money_kpis (5) ·
ball_in_court (5) · top_risks (5) · what_changed (5) · communications (4 humans,
honest-empty research).

## Key decision — `suspected_flight=""` (Option B, lead #7139/#7145)
The ticketing bridge tags every ticket with one global `suspected_flight`
(`aukera-annaberg-financing` via `_flight_name()`), so binding AO's dashboard to it would
put BB-AUK's 179 Lilienmatt tickets on AO's CEO surface. Rejected as misleading on the
honest-content contract. §4 live strip therefore renders **honest zeros** (matches the
source's deliberate honest-zeros). The zeros-explanation note lives data-only in a
`what_changed` row (refs bus #7127/#7107). AO check-in id=601 visibility + an
at-the-§4-strip note fold into the follow-up `AIRPORT_TICKET_PER_FLIGHT_TAG_1` code brief
(lead-authored).

## Fail-loud (both adjudicated by lead)
1. `suspected_flight` binding — the dispatch's "show the checked-in AO ticket" vs
   "transpose don't invent (honest zeros)" conflict → lead ruled Option B.
2. §4 card note needs code (the strip renderer is machine-only, no snapshot field) →
   lead ruled place it in a desk card, data-only.

## Verification
- `build_flight_dashboard` + `render_dashboard_html` render clean; §4 = 0/0/0/0 honest
  zeros (no fabrication, no "ledger unavailable"); note + bus refs + EUR 100K decision
  all present.
- `pytest tests/test_flight_dashboard.py` → **12 passed** (renderer untouched).

## Done rubric
`/flight/AO-OSK-001 → 200` · §4 strip live + honest zeros · note present · desk content
parity vs source.

## Gate plan
PR #487 → deputy G2 content-parity → lead merge → post-deploy AC4 probe
(`POST_DEPLOY_AC_VERDICT`).
