# LAB_V2_LOOPS_PANEL_V2_1 — LOOPS view v2: persistent facet bar + categorized subpanel + Sortie card

dispatched_by: lead (2026-07-24, Director-ratified: Mock v2 "all good" + naming rulings + "make it live. Add the loop number 3")
repo: brisen-lab (bm-b2-brisen-lab checkout) · branch: b2/lab-v2-loops-panel-v2-1
visual spec (Director-approved): /Users/dimitry/Desktop/01_AO_WORKING/Loops-Panel-V2-Mock-v2.html (designer Mock v2, receipt wiki/_fleet/design-reviews/2026-07-24-loops-panel-v2-mock-v2.md)

## Context

Lab V2 LOOPS view (brisen-lab, /v2#view=loops). Current structure: 6 loop cards
(5 on main + Sortie parked on lead/loops-sortie-card-install-1 @7de2afd), each
card carrying its OWN facet row; subpanel = flat list + All row (PR #179 shape).
Director walked the Mock v2 and ratified it live with two category renames.
Related merges tonight: naming convention @5a0f835 (NBSP tokens), meeting-cycle
board embed @9472768. /v2 routes are server-side no-cache; /static/ is cacheable.

## Context Contract

- IN: static/v2/loops.html, static/v2/loops.js, static/v2/shell.js (loops seed +
  hydrateLoopsSubpanel), static/v2/shell.css (facet-bar + group styles),
  static/loops/sortie-loop.html (vendored, from parked branch), tests named below.
- OUT (do not read/modify): skills subpanel, cockpit, server routes, bus code,
  other views, the vendored diagram HTML internals.
- Truth sources: Mock v2 file (layout), parked branch @7de2afd (sortie card),
  main @5a0f835 (current state).

## Task class

production-implementation (Director-facing UI, brisen-lab static shell) — full
gate chain applies.

## Problem

LOOPS view today: per-card facet rows + flat subpanel list. Director ruled: facet
choices move to ONE persistent top bar (constant while the loop below switches);
subpanel groups loops by category (collapsible caret groups, SKILLS grammar).
Sortie card (built + gated on parked branch) joins on the NEW layout.

## Director rulings (verbatim authority, 2026-07-24 chat)

1. Persistent top facet bar: "loops change, but the horizontal options of what to choose stay the same all the time."
2. Category names SHORT, no Loops-suffix mismatch: **Business** (was Matter/Meta Loops) · **Research** · **Operations** · **Building** (was Delivery).
3. "Make it live. Add the loop number 3." — production GO for both.

## Category → loop mapping

- **Business**: Loop 1 · Working Set, Loop 2 · Meeting Cycle, Loop 3 · Sortie
- **Research**: Research Loop
- **Operations**: Airport Loop
- **Building**: Build Loop
- "All" row stays on top (grid entry), DEFAULT_SLUG unchanged.

## Sources

- Mock v2 file above = visual truth for layout/spacing/active states (underline-active persistent tabs; caret category groups). Lab shell.css tokens, both themes.
- Sortie card content + vendored diagram: parked branch `lead/loops-sortie-card-install-1` @7de2afd4aaffde91415cbcf058ceeb1aa66ea736 (card 6 markup + static/loops/sortie-loop.html + shell.js seed row + test count reconciles). Cherry-pick or re-apply — your call; card must be re-seated on the new layout (per-card facet-row is REPLACED by the global bar).
- Loop naming: NBSP inside "Loop N" tokens (U+00A0 raw in HTML,   in shell.js) — preserve exactly (merged @5a0f835).

## Files modified (expected)

- static/v2/loops.html — facet rows removed per-card → one facet bar; card 6 added
- static/v2/loops.js — facet-bar controller (persist selection across loop switch); board wiring unchanged
- static/v2/shell.js — loops seed grouped (Business/Research/Operations/Building) + sortie-loop row; hydrateLoopsSubpanel group rendering
- static/v2/shell.css — facet bar (sticky, underline-active) + caret group styles
- static/loops/sortie-loop.html — vendored from parked branch (byte-identical)
- tests/test_v2_nav_skeleton.py, tests/test_v2_loops_route.py, tests/test_v2_hashnav.js — reshaped assertions
- No other files. Any extra file = name it in the receipt with why.

## Verification

1. `python3 -m pytest tests/test_v2_loops_route.py tests/test_v2_nav_skeleton.py tests/test_v2_shell_route.py tests/test_v2_skills_route.py -q` → green.
2. `node tests/test_v2_hashnav.js` → 25/25 (plus your new groups).
3. Browser check (real render): facet selection persists across loop switch; group collapse/expand; Sortie board mounts (pre-validate fetch 2xx); deep-link #view=loops&loop=sortie-loop lands highlighted; both themes; console 0.
4. `git ls-remote origin b2/lab-v2-loops-panel-v2-1` sha in receipt.

## Done rubric / done-state class

done-state: BUILT-AND-SELF-VERIFIED (builder verify ≠ gate — Lesson #131b).
DONE = all 7 AC receipt-enumerated SHIPPED + suite green + browser check evidence
+ ls-remote sha. NOT done on compile-clean alone.

## Gate plan

lead codex-gates the delta (cite repo+branch+sha, base = current main tip —
rebase first if main moved) → lead merges via bm-lead-brisen-lab → Render deploy
→ designer post-deploy embedded QA (verify-dashboard-render on live surface) →
Director eyeball. POST_DEPLOY_AC_VERDICT on the bus after live checks.

## Acceptance criteria

1. ONE sticky facet bar at top of LOOPS view: Description / Diagram / Agents involved / Prompt / Output. Selected facet PERSISTS when switching loops (the core Director ask). Underline-active treatment per mock.
2. Subpanel: All row + 4 collapsible caret groups named exactly Business / Research / Operations / Building with the mapping above; group expand-state survives loop switches within a session; active-row highlight still tracks hash.
3. Loop 3 · Sortie card LIVE with its REAL animated board (villa-gabbiano board pattern: pre-validate fetch → iframe mount — NOT the mock's placeholder frame), board file at /static/loops/sortie-loop.html.
4. Existing behaviors preserved: grid/All collapse mode + gen-guard unmount, deep-links (#view=loops&loop=<slug>), Loop 2 animated board, NBSP tokens, both themes, no console errors.
5. hydrateLoopsSubpanel (shell.js) + fallback seed reshaped for groups — seed must include sortie-loop; hashnav derive unaffected for unknown slugs.
6. Tests: update test_v2_nav_skeleton.py / test_v2_loops_route.py / test_v2_hashnav.js for the new structure (facet-bar singleton, group counts, board count 4, seed slugs incl sortie); FULL v2 suite green + hashnav green. Cache-bust loops.js + shell.js + shell.css as touched.
7. Receipt: enumerate every AC SHIPPED/DROPPED-BECAUSE (no silent skips — Lesson #135); include `git ls-remote` head sha; cite repo+branch+sha for the codex gate (NEVER bare PR number — Lesson #134); verify branch base = current main tip BEFORE gate ask (Lesson #133).

## Out of scope

Do NOT redesign other views; do NOT touch skills subpanel; do NOT alter the vendored diagram HTML files; no server/route changes (/v2 no-cache already live).

## Flow

Build → self-verify (run suite + browser check) → receipt to lead on bus → lead codex-gates (delta, repo+branch+sha) → lead merges via bm-lead-brisen-lab → deploy → designer post-deploy embedded QA → Director eyeball.
