---
brief_id: LAB_COCKPIT_REDESIGN_1 (PR 2)
attempt: 1
branch: b1/cockpit-redesign-pr2
dispatched_by: lead (bus #12281)
report_topic: gates/cockpit-redesign-pr2
gate: codex delta + codex-arch full UI critique -> lead line-read -> merge -> deploy -> Director eyeball
---

# LAB_COCKPIT_REDESIGN_1 PR 2 — checkpoint

Brief: briefs/_tasks/LAB_COCKPIT_REDESIGN_1.md @857fb900. PR 1 merged @4fdf3058 + deployed.
Contract/layout/manifest already on main (43/43). New branch off main @4fdf3058.

## Scope (one PR, AC-1..AC-7, no piecemeal merges; commit incrementally on branch)
- E1 app-card bg clearly distinct (bg IS the app/terminal distinction) [cockpit.css]
- E2 visibly stronger Lab shadows [cockpit.css]
- E3 remove 'terminal' + 'APP' kind words (keep SERVICE/HEADLESS badge) [cockpit.js]
- E4 remove 'up' word (plain up-idle -> dot only; keep working/needs-go/down/offline text) [cockpit.js]
- E5 recompute lowest uniform height after E3/E4 row removals (method of #12268; keep flex-shrink guard + geometry/contrast sweeps green, 4.5:1) [cockpit.css + geometry test]
- D4 context band on card face: 3px green->amber->red fill by context_pct, tiny label, null-safe hidden, no material height cost [cockpit.js + cockpit.css; controller context_pct]
- D5 Lab-parity glance: amber card state when unacked>0 & not WORKING [glance_state.js pure predicate + cockpit.js]; panel unacked list on open (id+topic+age) [cockpit_controller.py proxy + cockpit.js]
- D6 wake-on-open: controller verb, opens driveable + unacked>0 + glance!=WORKING -> tmux `check bus #<oldest-id> <topic>`+Enter; guards: never WORKING, never needs_go, 10-min per-seat dedupe, audit-log every send; same origin/auth as start/go [cockpit_controller.py + cockpit.js openTerm]

## Progress
- [x] E1-E5 (page-side) — commit on branch, verified scratch 114px uniform
- [x] D4 context band UI (null-safe) — 3px bar, cardbottom, verified
- [ ] D5 amber predicate (glance_state.js) + amber class (cockpit.js)
- [ ] D5 controller unacked-list endpoint + panel render
- [ ] D6 controller wake verb + audit + openTerm call
- [ ] tests: geometry/contrast sweeps green, new test_cockpit_wake.py + amber/context predicate tests
- [ ] verify live :7800 AC-1..AC-7 post-merge; screenshots

## Next concrete step
D5/D6 next: glance_state.js amber predicate + cockpit.js amber class; cockpit_controller.py context_pct + per-seat unacked list + wake verb (guards+audit); cockpit.js panel unacked list + wake-on-open call in openTerm; test_cockpit_wake.py + amber/context predicate tests.
