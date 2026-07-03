# BRIEF: BRISEN_LAB_DASHBOARD_UI_FIXLIST_3_DEFECTS_1

**Target repo:** `brisen-lab` (github.com/vallen300-bit/brisen-lab) — NOT baker-master.
Work in your brisen-lab checkout (`~/bm-b1/brisen-lab` or `~/bm-b1-brisen-lab`); `git pull` first.
**Dispatched by:** AH1 (lead) 2026-07-03 · **Source:** cowork-ah1 bus #5207, Director GO'd.
**Recommended effort:** medium-high (origin-gate logic is security-adjacent; UI parts trivial).

## Problem
Three verified defects on the live Brisen Lab dashboard (brisen-lab.onrender.com), same
auth/origin family as the known ack-403. All Director-facing.

## Defect 1 — Wake indicator permanently stuck on "…" (PRIMARY)
- **Symptom:** header "Autonomous wakes:" button shows "…" in every browser (`static/app.js` ~line 1466).
- **Root cause (verified):** `GET /api/wake_health` returns `403 {"detail":"bad origin"}` even from
  the dashboard's own origin. Same-origin GET fetches send **no** `Origin` header, but the gate
  requires exact Origin equality → always 403 → `app.js` error path renders "…".
- **Fix:** on `GET /api/wake_health`, allow a **missing** Origin (treat as same-origin), or gate on
  `Referer`/host instead. **Keep `POST /api/autowake/master` strict** (state-changing — must stay
  origin-gated). Do not weaken any write endpoint.

## Defect 2 — Token-burn nav link dead
- **Symptom:** nav link hardcodes `href=http://127.0.0.1:3000` (`static/index.html` ~line 22) — dead
  from any machine not running that local service (i.e. every real client).
- **Fix:** point at the hosted burn surface, or hide/disable the link when unreachable. Your call on
  the cleaner of the two; prefer hosted URL if one exists, else hide.

## Defect 3 — Paused desks look neglected
- **Symptom:** `BRISEN_LAB_AUTOWAKE_DISABLED_SLUGS` containment is invisible in the UI;
  `baden-baden-desk` shows a large unread count with no "paused" state — reads as neglected, not
  intentionally suspended.
- **Fix:** card badge **"WAKE PAUSED"** when a slug is in the disabled list OR master is killed.
  Read this from `wake_health` (depends on Defect 1 being fixed first — `wake_health` must return
  the disabled-slug list + master state to the client).

## Constraints
- All three touch the same dashboard file family — one PR.
- Fault-tolerant: wrap the new server logic in try/except; a wake_health failure must degrade to a
  clear state, never crash the endpoint.
- Do not touch the wake **delivery** path (wake-listener / URL handler) — display/gate only.

## Sibling (check, don't assume)
cowork-ah1 flagged `/msg` inbox `reader_slug_mismatch` 403 as the same origin-gate family. If it
lives in this repo and the fix is the same shape, fold it in; if it's a different repo/mechanism,
leave it and note so in your report. Do not scope-creep beyond a same-shape one-liner.

## Acceptance criteria
1. `GET /api/wake_health` returns 200 from the dashboard origin (no Origin header) → indicator shows
   ENABLED/KILLED, never stuck "…".
2. `POST /api/autowake/master` still 403s on a bad/foreign Origin (write gate intact) — prove with a test.
3. Token-burn nav link resolves from a remote browser (or is hidden when unreachable).
4. A disabled slug (`baden-baden-desk`, currently in the disabled list) shows a "WAKE PAUSED" badge
   on its card; a non-disabled slug does not.
5. `wake_health` payload exposes master-state + disabled-slug list for the badge.

## Verify (exercise the flow — compile-clean ≠ done)
- Curl `GET /api/wake_health` with NO Origin header → expect 200 + master/disabled fields.
- Curl `POST /api/autowake/master` with a foreign Origin → expect 403.
- Load the dashboard, confirm indicator resolves and bb-desk shows WAKE PAUSED.
- Report back on the bus to `lead` with the PR link + curl outputs.
