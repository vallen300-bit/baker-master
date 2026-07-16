# Checkpoint — LAB_COCKPIT_PAGE_1 (Cockpit BRIEF B-2, page UI)

- attempt: 1
- seat: B1
- branch: b1/lab-cockpit-page (this checkpoint) — successor claims by the attempt-bump commit here
- status: DISPATCHED, NOT STARTED — handed to a fresh seat (prior B1 seat carried the full BRIEF A arc; context-band rollover at a clean brief boundary)
- dispatch: lead #12149 (acked). BRIEF A verdict #12145 accepted.
- brief: briefs/_tasks/LAB_COCKPIT_PAGE_1.md @2b55d251
- binding scope: SCOPE_LAB_TERMINAL_COCKPIT_1 v1.3 @2b7f18e4 §5/§7/§8 P1 B-2/§9/§11 (dispatch cited v1.3.2 @46d8134f)

## Gate condition MET (do not re-litigate)
B-1 controller merged + POST_DEPLOY_AC PASS (#12148). Live backend on http://127.0.0.1:7800, shared Basic auth:
GET / · GET /api/agents · POST /api/sessions/<slug>/start · POST /api/sessions/<slug>/go · GET /term/<slug>/ · WS /term/<slug>/ws.
CREDENTIAL: Director changed it to a simple local pair — READ from the credential file (~/Library/Application Support/baker/cockpit/credentials), NEVER hardcode.

## What's left (the whole brief — nothing built yet)
1. Cockpit static page (dropped into B-1 controller static dir): manifest-driven card grid via GET /api/agents; Lab dark tokens (bevel, AG badge, group headers); plate grouping (Control Tower/Verification/Builders/Specialists/Matter Desks/Ground System, registry-generated, B1-B4 adjacent fixed order); card states up / dimmed+Start / error; glance colors with NEEDS_GO ABOVE WORKING precedence; click card -> on-demand iframe to /term/<slug>/ (same-origin, no custom xterm client); Esc/✕ closes.
2. App-claude seats: status-only cards (12), visibly marked, no iframe.
3. GO button (panel + card face) -> POST /api/sessions/{slug}/go, visible 200 feedback.
4. Runbook + .claude/how-to/ entry (index one-liner + body).
- Context badge: ship FLAG OFF (Lab slice LAB_CONTEXT_BAND_EXPOSURE_1 not live). NEVER derive context from session age.

## Context Contract — read ONLY these
- parent scope §5/§7/§8/§9/§11 (v1.3)
- COCKPIT_CARD_BEHAVIOR_MOCK.html (interaction contract — keep behavior identical unless Director corrected; check dispatch note)
- brisen-lab static/glance_state.js + static/app.js (glance/badge semantics + Lab CSS tokens)
- B-1 ship report URL list (#12148) + scripts/cockpit_controller.py routes on main
- NO vault libs, NO matter context.

## ACs (live, Lesson #8)
scope §8 AC 2 + AC 5 verbatim, PLUS AC-U1 fresh-browser grid->open B3->keystroke->GO with ≤1 cred prompt; AC-U2 Start flips card live no reload; AC-U3 kill controller+ttyd -> native windows unaffected; AC-U4 NEEDS_GO+WORKING renders NEEDS_GO; AC-U5 (badge only) fresh/stale/missing rows.

## Out of scope
Controller/backend changes (B-1), Render-Lab embed (permanently out §11.5), Tailscale, tmux/migration (BRIEF A), bus/dashboard.py, new model usage.

## Gates
codex cross-vendor PR review + cross-vendor UI critique -> lead line-read + merge -> Director eyeball on pilot cards.

## Next concrete step (successor)
Read the Context-Contract files (mock + glance_state.js + app.js + controller routes), confirm /api/agents shape live (curl with cred from file), then scaffold the static page into the controller's static dir. Pilot cards to drive: B3 (up) + Brisen Desk. Start behavior-mock-faithful; do not invent interactions.

## BRIEF A (prior arc) — DONE, for reference
Merged main @10dd3bec (PR #582 + regression #584). B3 sandbox live: tmux b3 UP, ttyd 127.0.0.1:7608 /term/b3/, ledger migrated. Scripts: generate_cockpit_manifest.py, fleet_terminals.sh, cockpit_migrate.sh, install_cockpit_ttyd.sh, cockpit_rollback.sh. AC verdict #12145 accepted.
