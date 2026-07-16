# LAB_COCKPIT_PAGE_1 — cockpit page UI (Cockpit BRIEF B-2)

- **Status:** DRAFT — dispatch gated on (a) BRIEF B-1 `LAB_COCKPIT_CONTROLLER_1` MERGED + its exact URLs returning non-error (codex-arch #12047 disposition), (b) BRIEF A B3 pilot green. UI ships LAST (ui-surface-prebrief).
- **Parent scope (binding):** `briefs/SCOPE_LAB_TERMINAL_COCKPIT_1.md` **v1.3 @2b7f18e4** — §5, §7, §8 P1 B-2, §9, §11. Scope wins on conflict; flag, don't improvise.
- **v1.2 additions (Director-ratified, MUST ship in v1):** production Lab glance colors on cards (blue-flash NEW / amber WORKING / dim IDLE — via B-1's `/api/agents` glance fields); **glance precedence includes NEEDS_GO ABOVE WORKING (codex-arch N4)** — match production Lab precedence exactly; plate grouping (Control Tower / Verification / Builders / Specialists / Matter Desks / Ground System, registry-generated, verify vs live Control Room); GO button on panel + card face → `POST /api/sessions/{slug}/go` (Enter only).
- **Context badge (OPTIONAL, feature-flagged):** context-remaining badge consumes the Lab-side slice `LAB_CONTEXT_BAND_EXPOSURE_1` ONLY after that slice is live (codex-arch #12055). NEVER derive context from session age — missing/stale ⇒ render "Context unknown"; session age may appear as a separate label. If the slice isn't live at dispatch, ship with the badge flag off; no blocking.
- **Dispatcher:** lead. **Builder:** b-code (assigned at dispatch). **Gate:** codex cross-vendor PR review + cross-vendor UI critique → lead line-read + merge → Director eyeball on pilot cards.
- **Repo:** baker-master.

## Context

Cockpit arc BRIEF B-2 of 3 — the Director-facing page on top of BRIEF A's tmux substrate and B-1's controller. Card contract = Director-confirmed mock + v1.2 Director rulings (colors/plates/GO). Backend already live: builder consumes B-1's URLs, builds NO backend.

**Context Contract (Harness V2):** builder reads ONLY: parent scope §5/§7/§8/§9/§11 (v1.3), `COCKPIT_CARD_BEHAVIOR_MOCK.html`, brisen-lab `static/glance_state.js` + `static/app.js` (glance/badge semantics + Lab CSS tokens), B-1's ship-report URL list. No vault libraries, no matter context.
**Task class:** production UI (Director-facing register; ui-surface-prebrief applies — surface named: Cockpit, pattern: Lab fleet grid).
**Done rubric / done-state:** all ACs live on this Mac against real tmux seats; done-state = merged + pilot seats (B3, Brisen Desk) fully driveable from the page + POST_DEPLOY_AC_VERDICT posted.

## Problem (1-liner)

Director needs one Lab-look screen: card grid of all terminal agents, click a card → the real typeable terminal in-page, Esc back to grid, Start button on stopped seats, live Lab glance colors, plate grouping, one-click GO.

## Files Modified (expected)

- NEW static cockpit page/assets, served by the B-1 controller (drop into its static dir).
- NO new backend routes, NO controller edits beyond static-asset wiring, NO edits to brisen-lab repo, dashboard.py, registry, or BRIEF A scripts (interface-consume only).

## Deliverables

1. **Cockpit page:** manifest-driven card grid via `GET /api/agents`; Lab visual tokens (dark register, card bevel, AG badge, group headers per v1.2 plates, B1–B4 adjacent fixed order); card states up/dimmed+Start/error; glance colors with NEEDS_GO above WORKING precedence; click → on-demand iframe to `/term/<slug>/` (same origin — codex-arch pick, no custom xterm.js client); Esc/✕ closes. Interaction contract = `COCKPIT_CARD_BEHAVIOR_MOCK.html` (keep behavior identical unless Director corrected it — check dispatch note).
2. **App-claude seats:** status-only cards (12), visibly marked, no iframe.
3. **GO button** on panel + card face → `POST /api/sessions/{slug}/go`; visible feedback on 200.
4. **Runbook + how-to entry** (`.claude/how-to/` one-liner + body per index contract).

## Quality Checkpoints / Acceptance criteria (live — Lesson #8)

Scope §8 AC 2, 5 verbatim, PLUS:
- AC-U1: full browser smoke in a FRESH browser profile — grid → open B3 → keystroke reaches real session → GO click delivers Enter — with at most ONE credential prompt (scope §6c AC).
- AC-U2: Start on a downed pilot seat flips the card live without page reload.
- AC-U3: kill controller + all ttyd → native Terminal windows unaffected (failure-mode proof).
- AC-U4: glance precedence proven: a seat that is both NEEDS_GO and WORKING renders NEEDS_GO.
- AC-U5 (only if badge flag on): context badge renders band/percent from the Lab slice; stale/missing ⇒ "Context unknown"; session age NEVER populates context (test all three rows: fresh, stale, missing).

## Out of scope

Controller/backend changes (B-1). Render-Lab embedding — PERMANENTLY out, local page is the locked v1 surface (scope §11.5; codex-arch N4 — P2 must not revive the PNA embed). Remote access/Tailscale. tmux/migration machinery (BRIEF A). Bus/dashboard.py changes. New model usage.

## Report

Ship report to `briefs/_reports/`, bus post to lead with PR ref + screenshots of plate grid, open terminal, GO click; POST_DEPLOY_AC_VERDICT after merge + live check on pilot seats.
