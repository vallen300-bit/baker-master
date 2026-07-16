# LAB_COCKPIT_PAGE_1 — cockpit page + controller (Cockpit BRIEF B)

- **Status:** DRAFT — dispatch gated on (a) Director card-behavior confirm, (b) codex-arch re-G0 PASS on SCOPE_LAB_TERMINAL_COCKPIT_1 v1.1 (@f37fc5dd), (c) BRIEF A merged + B3 pilot green
- **Parent scope (binding):** `briefs/SCOPE_LAB_TERMINAL_COCKPIT_1.md` **v1.2 @0b199b4f** — §5, §6c, §7, §8 P1, §9, §11. Scope wins on conflict; flag, don't improvise.
- **v1.2 additions (Director-ratified, MUST ship in v1):** production Lab glance colors on cards (blue-flash NEW / amber WORKING / dim IDLE, via controller proxy of Lab state); plate grouping (Control Tower / Verification / Builders / Specialists / Matter Desks / Ground System, registry-generated, verify vs live Control Room); GO button on panel + card face → `POST /api/sessions/{slug}/go` sends Enter only.
- **Dispatcher:** lead. **Builder:** b-code (assigned at dispatch). **Gate:** codex cross-vendor PR review → lead merge.
- **Repo:** baker-master.

## Context

Cockpit arc BRIEF B of 2 — the Director-facing page on top of BRIEF A's tmux substrate. Card contract = Director-confirmed mock + v1.2 Director rulings (colors/plates/GO).

**Context Contract (Harness V2):** builder reads ONLY: parent scope §5/§6c/§7/§8/§9/§11 (v1.2), `COCKPIT_CARD_BEHAVIOR_MOCK.html`, brisen-lab `static/glance_state.js` + `static/app.js` (glance/badge semantics + Lab CSS tokens), BRIEF A's launch manifest + ledger interfaces. No vault libraries, no matter context.
**Task class:** production UI + local controller (Director-facing register; ui-surface-prebrief applies — surface named: Cockpit, pattern: Lab fleet grid).
**Done rubric / done-state:** all ACs live on this Mac against real tmux seats; done-state = merged + pilot seats (B3, Brisen Desk) fully driveable from the page + POST_DEPLOY_AC_VERDICT posted.
**Gate plan:** G1 self-test → codex cross-vendor PR review + cross-vendor UI critique → lead line-read + merge → Director eyeball on pilot cards.

## Problem (1-liner)

Director needs one Lab-look screen: card grid of all terminal agents, click a card → the real typeable terminal in-page, Esc back to grid, Start button on stopped seats, live Lab glance colors, plate grouping, one-click GO.

## Files Modified (expected)

- NEW controller (Python, single file preferred) + NEW static cockpit page/assets
- NEW launchd plist for controller (generated)
- NO edits to brisen-lab repo, dashboard.py, registry, or BRIEF A scripts (interface-consume only).

## Verification

Live-flow proofs (Lesson #8): every AC exercised against real tmux sessions on this Mac; screenshots of plate grid + open terminal + GO click in ship report.

## Deliverables

1. **Python controller** (scope §6c — codex-arch pick; NOT bare http.server, NOT Caddy): launchd-managed, 127.0.0.1-only, serves the static page AND exactly two API routes: `GET /api/agents` (cards + live state from manifest + `tmux ls`), `POST /api/sessions/{slug}/start` (manifest-allowlisted). No stop/kill verbs in v1.
2. **Cockpit page:** manifest-driven card grid, Lab visual tokens (dark register, card bevel, AG badge, group headers Orchestrators/Builders/Desks/Specialists, B1–B4 adjacent fixed order); card states up/dimmed+Start/error; click → on-demand iframe to that seat's ttyd (codex-arch pick — no custom xterm.js client); Esc/✕ closes. Interaction contract = `COCKPIT_CARD_BEHAVIOR_MOCK.html` (Director-facing mock; keep behavior identical unless Director corrected it — check dispatch note).
3. **App-claude seats:** status-only cards (12), visibly marked, no iframe.
4. **Auth + origin** (scope §6c): shared Basic-auth credential (0600, `~/Library/Application Support/baker/cockpit/`) on ttyd + controller; controller rejects non-`127.0.0.1:<port>` Origin/Host.
5. **Runbook + how-to entry** (`.claude/how-to/` one-liner + body per index contract).

## Quality Checkpoints / Acceptance criteria (live — Lesson #8)

Scope §8 AC 2, 5 verbatim, PLUS:
- AC-B1: `GET /api/agents` returns exactly the manifest's eligible seats + correct up/down state (verified against `tmux ls`).
- AC-B2: Start on a downed pilot seat brings it up via manifest cmd; card flips live without page reload.
- AC-B3: kill controller + all ttyd → native Terminal windows unaffected (scope failure-mode proof).
- AC-B4: unknown slug to the start route → 404, no shell execution (allowlist proof).

## Out of scope

Render-Lab embedding (P2). Remote access/Tailscale. tmux/migration machinery (BRIEF A). Bus/dashboard.py changes. New model usage.

## Report

Ship report to `briefs/_reports/`, bus post to lead with PR ref; POST_DEPLOY_AC_VERDICT after merge + live check on pilot seats.
