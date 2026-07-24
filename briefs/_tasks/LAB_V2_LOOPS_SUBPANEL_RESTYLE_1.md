# LAB_V2_LOOPS_SUBPANEL_RESTYLE_1 — LOOPS subpanel visual restyle to Mock v3

dispatched_by: lead (2026-07-24, Director order "sort out the proper view … does not look like prof design" + Mock v3 ratified "all good")
repo: brisen-lab (bm-b2-brisen-lab checkout) · branch: b2/lab-v2-loops-subpanel-restyle-1
visual spec (Director-ratified): /Users/dimitry/Desktop/01_AO_WORKING/Loops-Subpanel-V3.html (designer Mock v3; receipt wiki/_fleet/design-reviews/2026-07-24-loops-subpanel-v3.md)
model note: this build runs as the Sonnet pilot (lead call — mechanical restyle class, full gate chain unchanged)

## Context

LOOPS panel v2 merged @c280de7 + live (designer QA PASS 6/6 #15560). Director
rejected the SUBPANEL visual register on live eyeball. Designer Mock v3 fixes 5
diagnosed defects; layout/behavior (groups, persistence, routing) is NOT in scope
— this is a VISUAL-ONLY restyle of the left subpanel.

## Context Contract

- IN: static/v2/shell.css (subpanel/facet group styles), static/v2/shell.js
  (hydrateLoopsSubpanel markup ONLY if class/structure hooks are needed),
  tests/test_v2_nav_skeleton.py + tests/test_v2_hashnav.js (assertion updates only).
- OUT: loops.html cards, loops.js, boards, facet bar behavior, skills view,
  server routes, all other views.
- Truth: Mock v3 file above. SKILLS-view sidebar = the Lab's one sidebar grammar.

## Task class

production-implementation (Director-facing UI) — full gate chain.

## Problem

Live subpanel visual register rejected by Director ("does not look like prof
design"): outlined 'All' box reads as a search field, heavy uppercase headers,
floated count circles, decorative dots, inconsistent indent + row wrap.

## Files Modified

- static/v2/shell.css — subpanel group/row/count/'All' styles (main work)
- static/v2/shell.js — hydrateLoopsSubpanel markup hooks ONLY if needed
- tests/test_v2_nav_skeleton.py, tests/test_v2_hashnav.js — assertion updates only
- No other files. Extra file = name it in the receipt with why.

## Acceptance criteria (the 5 ratified fixes; Mock v3 = truth; both themes)

1. 'All' row: plain nav row (soft-fill + accent when selected, SKILLS grammar) — kill the outlined search-field look.
2. Group headers: Title Case, no uppercase tracking.
3. Counts: plain muted number tight after the label ('Business 3') — kill floated gray circles.
4. Green per-row dots: dropped.
5. One indent step; caret aligned; 'Loop 2 · Meeting Cycle' fits one line (badge space reclaimed). NBSP tokens preserved.

## Verification

1. `python3 -m pytest tests/test_v2_loops_route.py tests/test_v2_nav_skeleton.py tests/test_v2_shell_route.py tests/test_v2_skills_route.py -q` green.
2. `node tests/test_v2_hashnav.js` green.
3. Browser check vs Mock v3 side-by-side, BOTH themes; group collapse/expand + active-row highlight + facet persistence unregressed; console 0.
4. Cache-bust every touched asset. `git ls-remote` sha in receipt.

## Done rubric / done-state class

done-state: BUILT-AND-SELF-VERIFIED (builder verify ≠ gate — Lesson #131b).
Receipt enumerates each of the 5 fixes SHIPPED (no silent skips — Lesson #135);
cite repo+branch+sha (Lesson #134); verify base = current main tip (Lesson #133).

## Gate plan

lead codex-gates delta (repo+branch+sha) → lead merges via bm-lead-brisen-lab →
Render deploy → designer post-deploy QA vs Mock v3 → Director eyeball →
POST_DEPLOY_AC_VERDICT.

## Out of scope

No layout/behavior changes; no other views; no renames (Business/Building are
Director-ratified, keep); no vendored board edits.
