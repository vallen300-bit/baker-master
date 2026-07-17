# Checkpoint — LAB_COCKPIT_PAGE_1 (Cockpit BRIEF B-2, page UI)

- attempt: 2
- seat: B1
- branch: b1/lab-cockpit-page (this checkpoint) — successor claims by the attempt-bump commit here
- status: IN PROGRESS (attempt 2 claimed 2026-07-17) — building the cockpit page; env grounded (controller live :7800, b3 tmux+ttyd pilot up, /api/agents shape confirmed)

## Attempt-2 grounding + decisions (recorded for successor/review)
- MOCK ABSENT: COCKPIT_CARD_BEHAVIOR_MOCK.html is not on this machine (git history, bm-b1, baker-vault, Desktop/baker-code all clean). Dispatch #12149 carries no mock correction. NOT treated as a blocker: scope §5 Target UX specifies the full interaction contract in prose, and §6.5 names the *live Lab page* as the design source (present at brisen-lab/static/). Building to scope §5 + live Lab CSS tokens + live Control Room. Flagged to lead.
- GROUPING: registry (agent_registry.yml) has NO class/group fields (§5.1 "generated from registry class/role fields" is literally unsatisfiable). Authoritative source per §5.1 = "mirror the live Control Room, verify at build". Decision: build-time generator (scripts/generate_cockpit_layout.py) mirrors live Lab CONTROL_GROUPS (brisen-lab/static/app.js) — the 6 plates in Control Room order — reconciled against the registry (display names, runtime → driveable vs app-claude) + launch manifest (ports). Emits generated cockpit_layout.json (provenance SHAs, no hand-kept list in the page). Card set = 26 driveable (/api/agents) + 12 app-claude status-only.
- /api/agents fields: slug, alias, port, session_up, is_working, has_telemetry, needs_go, unacked_count, oldest_unacked_age_sec, unacked_topics.
- Static deploy target: ~/Library/Application Support/baker/cockpit/static (COCKPIT_STATIC_DIR); repo source scripts/cockpit_static/; installer wired to copy it.
- CREDENTIAL is 9 bytes at ~/Library/Application Support/baker/cockpit/credentials — read at runtime, never hardcode.
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

## Progress (attempt 2 — build COMPLETE, live ACs GREEN)
Built: scripts/cockpit_static/{index.html,cockpit.css,cockpit.js,glance_state.js,cockpit_layout.json}
+ scripts/generate_cockpit_layout.py (layout generator, mirrors live CONTROL_GROUPS)
+ install_cockpit_controller.sh static-staging + .claude/how-to/lab-cockpit.md (runbook) + INDEX line
+ tests/test_cockpit_layout.py (5 passed; existing cockpit suite 18 passed, no regression).
Mock pulled from main @b44a7132 (merged) — behavior aligned to it. Live smoke on Chrome:
AC-2/AC-U1 open B3 → real terminal in-page + keystroke reached brisen-desk tmux (probe verified+cleared)
+ GO → POST /go 200; AC-U2 brisen-desk Start button flipped card down→up live no reload;
AC-U3 killed controller+b3 ttyd → tmux survived, launchd relaunch <1s, GET/ 200;
AC-U4 live DOM needs_go+working → glance-needs-go (working suppressed); AC-U5 N/A (badge flag off);
§8 AC-5 loopback-only. Pilots b3+brisen-desk migrated in ledger. Screenshot: briefs/_reports/_assets/B1_cockpit_grid_20260717.png.

## Fix pass 1 (2026-07-17) — codex-arch UI critique #12171 FAIL, 4 blockers cleared
Dispatch lead #12172 (acked). Commit 3a3b84e1 on b1/lab-cockpit-page (no amend). Fix-done posted #12173 → gates/lab-cockpit-page-pr-585.
- B1 slug on card face (cockpit.js .slug line, §5.2).
- B2 GO gated on row.needs_go===true (was every up seat).
- B3 ttyd-down error card — controller /api/agents adds per-seat ttyd_up (probe_ttyd async loopback TCP, concurrent, injectable ttyd_prober param); renderer red 'terminal offline', not openable.
- B4 Lab outage visible — LabGlance.last_ok → /api/agents lab_glance_ok; renderer amber 'telemetry offline' banner + dashed 'no telemetry' UNKNOWN (glanceClass returns glance-unknown for null row / UNKNOWN).
- Nits folded: header 'N driveable / M seats'; down-seat Start un-dimmed.
- Tests 24 passed (test_cockpit_controller incl. new probe_ttyd + lab_glance_ok; layout/serve/manifest). Live-verified all 4 states + outage banner on a throwaway controller (alt port + fake manifest/Lab); screenshots briefs/_reports/_assets/B1_cockpit_fixpass{,_outage}_20260717.png. Live :7800 untouched.

## Next concrete step (successor)
Wait on codex-arch re-critique + codex delta gate on gates/lab-cockpit-page-pr-585. On PASS → lead merge → deploy (install_cockpit_controller.sh restages static + restarts :7800) → POST_DEPLOY_AC_VERDICT v1 on pilot seats (b3, brisen-desk) to lead. On re-FAIL → address on NEW commits, re-post fix-done. Do NOT redeploy :7800 pre-merge.

## BRIEF A (prior arc) — DONE, for reference
Merged main @10dd3bec (PR #582 + regression #584). B3 sandbox live: tmux b3 UP, ttyd 127.0.0.1:7608 /term/b3/, ledger migrated. Scripts: generate_cockpit_manifest.py, fleet_terminals.sh, cockpit_migrate.sh, install_cockpit_ttyd.sh, cockpit_rollback.sh. AC verdict #12145 accepted.
