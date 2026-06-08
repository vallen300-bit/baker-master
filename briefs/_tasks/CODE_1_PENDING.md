---
status: PENDING
brief_id: DASHBOARD_COCKPIT_WAVE1_QUICKWINS_1
dispatch: DASHBOARD_COCKPIT_WAVE1_QUICKWINS_1
to: b1
from: cowork-ah1
dispatched_by: lead
reassigned_from: cowork-ah1
reassigned_at: 2026-06-08
dispatched_at: 2026-06-08
task_class: frontend health + presentation fix (Fix 1 auth PARKED)
gate_plan: G0 codex (brief) -> G1 functional -> G3 codex (code) -> merge. G2 NOT required (Fix 1 parked).
brief_path: briefs/BRIEF_DASHBOARD_COCKPIT_WAVE1_QUICKWINS_1.md
---

# B1 dispatch — DASHBOARD_COCKPIT_WAVE1_QUICKWINS_1 (Fixes 2/3/4 only; Fix 1 PARKED)

Full brief: `briefs/BRIEF_DASHBOARD_COCKPIT_WAVE1_QUICKWINS_1.md`

**SCOPE — build Fixes 2, 3, 4 ONLY. Fix 1 (the `/api/dashboard/ao` auth dependency) is
Director-PARKED 2026-06-08 — DO NOT implement it.** Because Fix 1 is parked, this dispatch
is presentation-only and G2 `/security-review` is NOT required.

- **Fix 2 (P1):** Client-PM threads panel — swap two raw `fetch(` -> `bakerFetch(` at
  `app.js:~11093` (list) and `:~11128` (replay) so `X-Baker-Key` is sent. Panel currently
  401s + fails silent. Cache-bust `?v=N`.
- **Fix 3 (P1):** AO "EUR 66.5M" headline is a hardcoded literal shown as live
  (`dashboard.py:12825`). Make it a named dated constant + emit `investment_total_as_of`,
  render an "as of <date>" cue (`app.js:10033`/`:10078`). Do NOT invent a new number; do
  NOT change the value `66.5M`. Degrade gracefully if `as_of` absent.
- **Fix 4 (P2):** Surface scheduler liveness — poll existing public
  `GET /api/health/scheduler` in/near `loadCortexFeed()` (`app.js:10271`), render a
  green/red/unknown pill in `cortexFeedCard`. Wrap in try/catch — must never break the
  Cortex feed render. Cache-bust `?v=N`.

Reviewer instructions, verification curls, and Do-NOT-Touch list are in the full brief.
Quality checkpoints: py_compile clean; renders desktop + iPhone PWA; no raw
`fetch('/api/pm/threads` left; headline carries date; scheduler pill present.

**Gates (Fix-1-parked path):** G0 codex (brief) -> G1 functional -> G3 codex (code) ->
merge. G2 security-review NOT required this dispatch.

Report back to `lead` (orchestration reassigned to lead 2026-06-08). Ship report = literal test/curl output, not "by inspection".
