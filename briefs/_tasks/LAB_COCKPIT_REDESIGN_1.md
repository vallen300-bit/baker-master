# LAB_COCKPIT_REDESIGN_1 — Director-ratified cockpit v2 (layout + wishlist)

- dispatcher: lead · seat: B1 · date: 2026-07-17
- status: PENDING
- binding contracts (committed this repo):
  - `scripts/cockpit_static/director_layout_contract.json` — Director FINAL layout (mock v3 export 2026-07-17T13:26Z): 6 sections, 43 cards, positions + order. Source of truth for plates/grouping — REPLACES the Control-Room mirror as grouping source in `generate_cockpit_layout.py`.
  - `COCKPIT_REDESIGN_MOCK_V3.html` — visual register preview Director reviewed.
  - Director final comments (this brief §D).
- prior art: PR #585/#586/#587 arc; scope v1.3.2 @46d8134f still governs controller/proxy/auth invariants — this brief changes PAGE + layout-generation only, plus the two controller additions in D4/D6.

## Context

Cockpit v1 arc (PR #585/#586/#587) is merged + live on :7800 (43 cards). Director drove the mock loop today (mock v2 → his layout export → mock v3 → FINAL export + verbal comments in chat) and ratified this redesign. Grouping source moves from Control-Room mirror to his committed contract file. Harness V2 blocks below.

**Context Contract (read before build):** `scripts/cockpit_static/director_layout_contract.json` · `COCKPIT_REDESIGN_MOCK_V3.html` · `scripts/generate_cockpit_layout.py` · `scripts/cockpit_static/{cockpit.js,cockpit.css,index.html,glance_state.js}` · `scripts/cockpit_controller.py` · Lab register reference: brisen-lab `app.js` + CSS (card sizing/shadow) · scope v1.3.2 @46d8134f (§5/§7 invariants) · bus #12055 (context-band contract) · this brief. Nothing else required.

**Task class:** medium-feature (UI + generator rebind + 2 controller verbs; no schema/infra).

## Problem

Cockpit page ships with Control-Room-mirror grouping and v1 card visuals. Director ratified a full redesign: his own 6-section layout, denser cards, Lab-register visuals, context visibility, Lab-parity bus glance, and wake-on-open.

## Deliverables

**D1 — Layout rebind.** Generator reads `director_layout_contract.json` for plate labels, order, card membership + in-plate order (sort: row-band y±40 then x — same rule as the mock export). Contract supplies display_name (codex-arch ruling #12246 — Director's shortened labels are binding); registry/manifest supply runtime/driveable/ports. `--strict`: every active seat must appear exactly once; fail loud on drift between contract and registry (new seat activated later → trailing "Unassigned" plate + stderr report, never silent).

**D2 — Card visuals (REVISED per Director correction 2026-07-17 ~13:45Z).** Drop the AG pill entirely. Card geometry: LANDSCAPE — WIDER than today AND lower height (Director final wording: "they should be longer, but not so high"); vertical screen economy is the goal. Lab-style drop shadow so cards lift. Text MUCH brighter — card names + all cockpit lettering step up toward white (still AA on the dark fills). Names one line. Cowork/APP cards: SAME dimensions as terminal cards, recessed/inner-shadow kept, APP marker kept.

**D3 — Plate shading.** Each of the 6 plates gets a slightly different grade of near-black background (subtle stepped ladder, same hue family) so sections read apart at a glance. Keep text contrast AA.

**D4 — Context band on card face (RE-CONFIRMED by Director 2026-07-17 ~13:50Z — mock-v3 rendition ratified as "perfect").** Thin fill-line at card bottom exactly as in COCKPIT_REDESIGN_MOCK_V3.html: 3px bar, green→amber→red gradient by fill, tiny label. Data: `context_pct` via controller (forge telemetry, null-safe → bar hidden; coordinate with #12055, do not block on it). Approximate acceptable. The bar must NOT materially raise card height (it fits the landscape geometry).

**D5 — Lab-parity bus glance.** Card face: unacked count + oldest-age (exists) + AMBER card state when unacked>0 and seat not WORKING (match Lab semantics Director uses today). Terminal panel: on open, list that seat's unacked bus messages — id + topic + age (controller proxies the Lab per-seat unacked query; read-only). Goal: Director can retire Production/Lab view for daily driving.

**D6 — Wake-on-open.** When Director opens a driveable seat that has unacked>0 AND glance ≠ WORKING: controller auto-sends one line into its tmux — `check bus #<oldest-unacked-id> <topic>` + Enter (bus-ID nudge convention, Director-ratified 2026-07-17). Guards: never when WORKING; never for needs_go seats (GO flow owns those); 10-min per-seat dedupe; audit-log every send. This is a new controller verb — same origin/auth guards as start/go.

**E — Director eyeball corrections on PR 1 (verbatim intent, 2026-07-17 ~17:15 local — BINDING, fold into PR 2):**

- **E1 — App-card background contrast.** "The background difference of the agents living in the app is not visible enough… has to be more visible." Make APP-resident cards a clearly different background from terminal cards — the background IS the app/terminal distinction now.
- **E2 — Shadows.** "Cards don't have shadows. In production and lab they have shadows so they stand out." Current shadow reads flat on the deployed page — strengthen to visibly match the Lab/production lift.
- **E3 — Remove kind word.** Remove the word "terminal" from the card face (screen economy). With E1, background color replaces the kind label; drop the APP text marker too (supersedes D2 "APP marker kept").
- **E4 — Remove "up".** Remove the word "up" at the top of the card. Other states (working / needs-go / down / offline) keep their affordances.
- **E6 — No state words at all (Director addition 2026-07-17 ~17:30 local).** "You can also remove session down… I won't have time to read. I would like to measure what's going on predominantly by the layout and the color of the card." Remove the state TEXT row entirely ("session down", "up", etc.). State is carried by color + affordance only: dimmed + Start button = down; bright = running; amber = unread bus; green tint + GO = needs GO; red = terminal offline. Words on the card face: name, slug, unread badge/age, buttons — nothing else. (Supersedes the E4 wording: not just "up" — ALL state words go.)
- **E5 — Height recompute.** With kind + "up" rows gone, recompute the LOWEST uniform card height that fits the crowded state (same method as #12268; flex-shrink guard + geometry/contrast test sweeps stay green, floors unchanged).

Start-button note (NOT a defect, no change): Start renders only on DOWN driveable seats by design — up seats need no Start, app seats cannot be started. Explained to Director.

## Files Modified

- `scripts/generate_cockpit_layout.py` — grouping source → contract file; kind/badge logic unchanged; stale comment fix.
- `scripts/cockpit_static/cockpit_layout.json` — regenerated.
- `scripts/cockpit_static/cockpit.css` — card geometry, shadows, plate grade ladder, cowork recess at full size, context-band styles.
- `scripts/cockpit_static/cockpit.js` — AG pill removal, amber state, panel unacked list, context band render, wake-on-open call.
- `scripts/cockpit_static/glance_state.js` — amber-state predicate (pure, dual-export, tested).
- `scripts/cockpit_controller.py` — `context_pct` + per-seat unacked list in `/api/agents` (or side endpoint), wake verb w/ guards + audit.
- `tests/test_cockpit_layout.py`, `tests/test_cockpit_controller.py`, new `tests/test_cockpit_wake.py` + amber/context predicate tests.

## Verification

Literal, not compile-clean (Lesson #8): pytest cockpit suite green; `node --check` both JS; `--strict` regen 43/43 vs contract; live :7800 DOM assertions for AC-1..AC-6 after deploy; wake-on-open exercised against a REAL seat with a planted unacked message + audit-log line shown; Lab-vs-cockpit unacked spot-check on 3 seats same-minute. Screenshots to `briefs/_reports/_assets/`.

## Quality Checkpoints / Acceptance criteria

- AC-1: live :7800 renders exactly the contract layout (6 plates, 43 cards, order).
- AC-2: no AG pills; landscape cards (wider, lower) w/ shadow; MUCH brighter lettering; cowork = same size, recessed; plates visibly graded.
- AC-7 (E1-E5): no "terminal"/"APP" kind words, no "up" word; app cards visibly distinct by background alone at arm's length; shadows visibly lift like Lab; uniform height re-minimized; geometry+contrast sweeps green.
- AC-3: context bar on card face per mock v3 (3px fill line); hidden when `context_pct` null; never blocks render; no material height cost.
- AC-4: unacked seat shows amber + count; panel lists message ids/topics; matches Lab numbers for the same seat at the same moment (spot-check 3 seats).
- AC-5: wake-on-open fires exactly once per guard window, correct text, audited; does NOT fire on WORKING or needs_go seats.
- AC-6: all #585-#587 invariants hold (GO gating via goAffordanceVisible untouched, ttyd error card, telemetry banner, no innerHTML, --strict passes).

## Done rubric / done-state + Gate plan

**Done-state class:** live-verified (deployed :7800 + Director eyeball), not merge-done. DONE = all AC live-proven + POST_DEPLOY_AC_VERDICT v1 posted on `post-deploy-ac/lab-cockpit-redesign-1` + Director eyeball GOOD. Anything skipped → say so in the verdict (fail loud), no silent scope drops.

**Gate plan:**

codex gate → codex-arch UI critique (against contract + mock v3 + Lab register) → lead line-read → lead merge → b1 deploys from merged main → Director eyeball = final.

## Notes

- One coherent arc, no piecemeal merges; split into ≤3 PRs only if review size demands, each gated.
- Fold the stale generator comment (~line 190) here as promised (#12228).
- BEN marker conflict stays parked (#12102). Phase-2 fleet cutover is a SEPARATE arc — untouched by this brief.
