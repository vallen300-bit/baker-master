# LAB_V2_LOOPS_CARD_COLLAPSE_1 — LOOPS page: compact card grid → click opens the working view

**Lane:** b2 — BUILDER (codex seat/CLI gates; lead merges).
**Repo:** brisen-lab. **Task class:** production UI implementation (Director-facing, frontend-only).
**Dispatcher:** lead (Director order 2026-07-23 morning, verbatim intent below). Report to lead.

## Context

Director, on the live /v2 LOOPS page today: the page opens as one big brochure
window per loop ("the bigger window … is too big. It's with more loops. I have
to be able to see placeholders' cards. Click on the card, and today's view opens
up. Then I work with the loop inside that view."). Current page renders every
loop-card fully expanded (all fields server-rendered, board collapsed behind a
toggle). Wanted inversion: **default = compact placeholder cards (grid); click =
that loop's WORKING view opens (board mounted = today's state), brochure fields
become secondary facets.**

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** open a loop's working view from a compact named card and work with the loop inside it (select/expand state change + lazy board mount).
2. **Backend route:** `GET /v2/loops` at `brisen-lab/app.py:2231` — `def v2_loops(): return _v2_page("loops.html")` (no params, no-cache headers per LAB_V2_SKILLS_STICKY_BAR_1). Boards: existing StaticFiles mount serves `/static/loops/*.html`.
3. **Endpoint contract:** plain GET, no query params, no auth beyond the Lab shell's existing gate; board URLs are pre-validated client-side with `fetch()` before iframe insert (Lesson #130 pattern — keep it).
4. **State location:** server-rendered cards in `static/v2/loops.html` + static boards `static/loops/villa-gabbiano.html` (research-loop board host, loops.html:196) and `static/loops/lilienmatt-aukera-financing.html` (airport-loop, loops.html:233); build-loop card at loops.html:242. All in brisen-lab.
5. **UI repo (= state repo):** brisen-lab — surface: Lab /v2 LOOPS page.
6. **Director surface preference:** specified by Director himself 2026-07-23 (cards in Lab V2 LOOPS page — the request IS the surface ruling).
7. **Gate-1+2 reviewer instruction:** "Reviewers MUST load /v2/loops in a browser (and via the /v2 shell iframe), click each card, and confirm the working view renders with a non-error board or the description fallback. Code-shape review is necessary but not sufficient."

## Problem

`static/v2/loops.html` renders each `.loop-card` with ALL description fields
visible and stacked full-width; `static/v2/loops.js` only isolates a card on
selection (`is-hidden` on the others) and lazy-mounts the board behind a manual
toggle. There is no compact overview state; with more loops coming the page is
unusable as a picker.

## Implementation sketch (builder owns final shape)

1. **Collapsed default:** render cards as a responsive compact grid (name +
   one-line hook + "board / no board yet" hint). All `.field` content stays in
   the DOM (server-rendered, JS-off readable) but hidden in collapsed state via
   CSS class — do NOT delete or restructure the field markup:
   `shell.js hydrateLoopsSubpanel()` (shell.js:313-334) fetches /v2/loops and
   PARSES these cards for the sidebar subpanel — keep `data-loop`, headings, and
   field structure parseable (verify hydration still yields the same groups).
2. **Click card → working view:** existing isolation mechanism expands the
   clicked card full-pane, others hide, `← All loops` returns to the grid.
   In expanded state the BOARD auto-mounts (today's view) as primary content —
   keep the pre-validate `fetch()` → 2xx → iframe insert pattern (Lesson #130);
   non-2xx renders "Board unavailable." Facet bar (Description · Diagram ·
   Agents Involved · Prompt · Output) stays available; a loop with NO board
   opens on the Description facet instead (never a blank pane).
3. **Deep links preserved:** `#loop=<slug>` (+ `facet`) via hashnav.js opens
   directly in expanded state; grid state = no loop param. Back control clears
   the param (existing parent-hash fallback at loops.js:177 unchanged).
4. **No new endpoints, no board rewrites** (boards stay byte-untouched), no
   innerHTML for dynamic text (textContent discipline), asset cache-bust if the
   shell versions these files.

## Files Modified

- `static/v2/loops.html` — CSS + collapsed-state classes (markup structure preserved for subpanel parser).
- `static/v2/loops.js` — grid/expand state machine, board auto-mount on expand.
- NOTHING else. Do NOT touch `app.py`, boards under `static/loops/`, `shell.js`, `hashnav.js` (consume, don't modify — if hashnav needs a change, stop and report).

## Acceptance criteria

1. /v2/loops default = compact card grid; no board iframes mounted, no brochure walls.
2. Click any card → that loop's working view: board rendered (or Description fallback), other cards hidden, `← All loops` visible.
3. Deep link `#loop=build-loop` opens expanded directly; back returns to grid; shell sidebar LOOPS subpanel still hydrates identically (compare group list pre/post).
4. JS-off: page still readable (server-rendered fields visible — collapsed styling may degrade, content must not vanish).
5. Zero console errors in both themes; works inside the /v2 shell iframe and standalone.

## Verification

- Browser probe: load /v2/loops standalone + inside /v2 shell; click all 3 cards; hash deep-link test; JS-off render check; console clean.
- Existing loops tests green; extend the LAB_UNIFY_P3 test(s) for the collapsed-default + auto-mount-on-expand behavior.
- Ship receipt: branch, sha, `git ls-remote` line, probe results.

## Done rubric / gate plan

- **Done-state class:** merged + Render deploy + live AC in Director's Chrome (lead/cowork-ah1 runs live check; Director eyeballs final).
- **Gate plan:** codex gate (seat or CLI lane, lead routes) BEFORE merge; reviewer must execute the Surface-contract §7 browser instruction. Lead merges on PASS → Render deploy → live AC → report to Director.
