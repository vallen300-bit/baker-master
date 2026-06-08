---
status: COMPLETE
completed: 2026-06-08 (merged PR #338, G3 PASS, POST_DEPLOY_AC PASS)
brief_id: DASHBOARD_COCKPIT_WAVE2A_FRONTEND_HEALTH_1
dispatch: DASHBOARD_COCKPIT_WAVE2A_FRONTEND_HEALTH_1
to: b3
from: cowork-ah1
dispatched_by: lead
reassigned_from: cowork-ah1
reassigned_at: 2026-06-08
dispatched_at: 2026-06-08
task_class: frontend health / robustness (silent-fail + dead-end surfaces)
gate_plan: G0 codex (brief) -> G1 functional -> G3 codex (code) -> merge. G2 NOT required (frontend-only, no auth/data change).
brief_path: briefs/BRIEF_DASHBOARD_COCKPIT_WAVE2A_FRONTEND_HEALTH_1.md
---

# B3 dispatch — DASHBOARD_COCKPIT_WAVE2A_FRONTEND_HEALTH_1

Full brief: `briefs/BRIEF_DASHBOARD_COCKPIT_WAVE2A_FRONTEND_HEALTH_1.md` — read it in full.

**Frontend-only robustness pass. No backend/route/schema change. G2 not required.** Three
fixes, all in `outputs/static/app.js` + `index.html` cache-bust:

- **Fix 1 (P2):** ~21 fire-and-forget mutation clicks (complete/dismiss/mark-done/cancel/
  acknowledge/resolve/snooze) fail silently. ENUMERATE the full set first (grep recipe in
  brief), wrap each with await + `res.ok` check + ONE shared visible-error helper + revert
  the optimistic UI on failure. Ship report MUST list the full count + line numbers
  (fail-loud, do not silently cap).
- **Fix 2:** Document button opens bare Dropbox root when `source_path` missing
  (`app.js:~8343`) — guard it, show "source link unavailable", no dead-end tab.
- **Fix 3:** Presentations iframe blank-page on cold/down brisen-docs (`app.js:~8940`/
  `:8974`) — add loading affordance + ~8s timeout/onerror fallback message + retry button.

**DEFERRED (do NOT build):** mobile `md()` citation/table parity; Cortex nav-home /
discoverability — both follow-up briefs.

**Gates:** G0 codex (brief) -> G1 functional (exercise a mutation failure path under
DevTools Offline; confirm visible error + no false-success) -> G3 codex (code) -> merge.

Report back to `lead` (orchestration reassigned to lead 2026-06-08). Ship report = literal
output (grep counts, test/console), not "by inspection".
