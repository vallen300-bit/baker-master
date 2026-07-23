# BRIEF: LAB_V2_BRAND_LIVE_BADGE_TOGGLE_RESTYLE_1 — unified brand title, sidebar live line, toggle relocation, cockpit badge collision fix

## Context

Director screenshot + three rulings, 2026-07-23 ~17:55Z, /v2 AGENTS view with terminal side-panel open:

1. **Green health line collides with FLEET COCKPIT title.** The cockpit page's `#sync-note` ("Live · 28 with terminal / 42 seats") renders beside the `<h1>` (`baker-master/scripts/cockpit_static/index.html:40-42`, `.summary-title-row` at `cockpit.css:267`); when the terminal panel opens, the cockpit iframe narrows and the green text overlays "FLEET COCKPIT". Not acceptable at any width.
2. **Brand row reads as two names.** Sidebar shows `BRISEN` (15px/700) over `LAB · v2` (10px muted) — `brisen-lab/static/v2/index.html:22-25`. Director: "Brisen should have Lab in the same format so it creates one title." → ONE unified wordmark.
3. **Live line moves under the unified title** — Director: "even better than bottom left corner." Theme-toggle placement redesign delegated to lead → design below.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director reads fleet liveness at a glance under one unified brand title, and switches color theme from the sidebar bottom.
2. **Backend route:** none new. Cockpit embed already served via `/cockpit/*` bridge (`brisen-lab/app.py:3092-3117`, `COCKPIT_EMBED_ENABLED`-gated); shell probe `GET /api/cockpit/config` (`static/v2/shell.js:146`) unchanged.
3. **Endpoint contract:** no new HTTP calls. Data crosses via same-origin `postMessage` from the pre-mounted `#cockpit-frame` (`shell.js:477-479`); listener validates `event.origin === location.origin` AND `event.data.type === "cockpit-health"`.
4. **State location:** health object already computed in `renderSummary()` (`baker-master/scripts/cockpit_static/cockpit.js:214-240`); deployed copy `~/Library/Application Support/baker/cockpit/static/`. Shell renders a read-only mirror.
5. **UI repo (= state repo):** split is deliberate — brisen-lab `static/v2/` restyles the sidebar it owns; baker-master `scripts/cockpit_static/` restyles the cockpit DOM it owns; only a message crosses.
6. **Director surface preference:** ratified in-message 2026-07-23 — live line under unified sidebar title; toggle placement delegated to lead → sidebar bottom, icon-only.
7. **Gate-1+2 reviewer instruction:** "Reviewers MUST load the URL with exact query string + confirm non-error response. Code-shape review is necessary but not sufficient."

## Estimated time: ~2.5h
## Complexity: Medium
## Prerequisites: none (builds on brisen-lab main @f9f92e9 shell v14; baker-master main @2666ff15)

## Harness V2

- **Context Contract:** inputs = Director's 3 rulings (screenshot 2026-07-23) + the verified file/line map in the Surface contract; outputs = restyled `static/v2` sidebar (brisen-lab branch) + restyled `scripts/cockpit_static` (baker-master branch), receipts with repo+branch+sha each. Builder reads ONLY the files listed under Files Modified + their tests; no repo-wide exploration needed.
- **Task class:** production UI implementation, two-repo, no schema/API surface change.
- **Done rubric (done-state class: gated-merge):** all 5 Quality Checkpoints pass in builder's own Chrome verification + touched test suites green + codex seat gate PASS on both diffs → lead merges + resyncs deployed cockpit copy + Director eyeball. Builder-verified alone ≠ done (Lesson #131).
- **Gate plan:** codex delta gate per repo diff (cite repo+branch+sha, never PR numbers — #15295 wrong-repo trap); reviewer must run the narrow-width collision probe + offline fail-soft, not code-shape only.

## Baker Agent Vault Rails
Relevant: verification-surfaces (Chrome render checks both surfaces), bus-and-lanes (receipts per repo).
Ignored: loop-runner, memory-and-lessons, skills-and-playbooks — no loop/memory/skill content touched.

---

## Fix 1 (brisen-lab): unified brand + live line + toggle relocation

### Problem
Brand reads as two names; no liveness at shell level; toggle crowds the wordmark (Director flagged 07-22 "tight vs BRISEN wordmark").

### Current State
- `static/v2/index.html:21-31`: `.sidebar-brand` row = `.brand-id` (`.brand-mark` "BRISEN" + `.brand-sub` "LAB · v2") + `#theme-toggle` button.
- `static/v2/shell.css:83-97` brand styles; `:272-294` toggle chip styles (moved into brand row by LAB_V2_HEADER_UNIFORMITY_1, PR #176).
- `static/v2/shell.js:477-479` pre-registers `#cockpit-frame` (same-origin `/cockpit/*` src).

### Engineering Craft Gates
- Diagnose: N/A this fix — no bug, restyle per ruling (collision diagnosed in Fix 2).
- Prototype: N/A — design Director-ratified in-message; toggle placement lead-ratified here.
- TDD: applies — extend `tests/test_v2_nav_skeleton.py` (brand markup asserts) + `tests/test_v2_theme_toggle.py` (toggle now sidebar-bottom) + new source-assert test that the shell listener checks `event.origin` before consuming messages. Write the brand/toggle asserts first, then restyle.

### Implementation
1. Brand row → one line, one format: `BRISEN LAB` — both words same size/weight/tracking (use current `.brand-mark` 15px/700/.12em for both). Keep tiny muted `v2` suffix (`.brand-sub` demoted to inline suffix). One visual title.
2. Under it, add `<div class="brand-live" id="brand-live" hidden></div>` — small green line, `.feed-dead` red variant, mirroring cockpit `.summary-status` semantics (green dot ::before optional but keep it subtle). Reserve slot height in CSS so appearance does not shift the nav (no layout jump).
3. `shell.js`: add a `message` listener — accept only `event.origin === location.origin` && `event.data && event.data.type === "cockpit-health"`; render `"Live · " + driveable + " with terminal / " + total + " seats"` (append `" · telemetry source degraded"` when `degraded`), red text form on `live === false`, and `hidden = true` when no message yet or malformed. Use `textContent` only (XSS rule — no innerHTML).
4. Toggle: move `#theme-toggle` out of the brand row to the sidebar BOTTOM, pinned (sidebar is flex-column — `margin-top: auto` wrapper). Icon-only sun/moon glyph (text glyph fine, e.g. ☾/☀ via CSS content or JS label swap), keep `aria-label`, same click handler + persistence.
5. Bump static asset versions per existing `?v=N` convention (shell.js currently v14 in `index.html` — bump to v15; bump shell.css similarly).

### Key Constraints
- Do NOT touch subpanel/LOOPS/cards work just merged (PR #177-#180 surfaces) beyond the sidebar brand block.
- Fail-soft: no cockpit message ever → line stays hidden; zero console errors; existing "Cockpit offline" banner logic (`shell.js:134-146`) unchanged.
- No new endpoints, no polling loops in the shell.

## Fix 2 (baker-master): cockpit badge collision + postMessage emit

### Problem
`#sync-note` beside the h1 overlays "FLEET COCKPIT" when the iframe narrows (Director screenshot). Repro: load cockpit page at ≤~700px width (or open the /v2 terminal side-panel) and observe overlap.

### Current State
- `scripts/cockpit_static/index.html:37-46`: `.summary-title-row` = `<h1>FLEET COCKPIT</h1>` + `<span class="summary-status" id="sync-note">`.
- `scripts/cockpit_static/cockpit.css:267` `.summary-title-row { display:flex; flex-wrap:wrap; gap:13px }`; `.summary-status` at `:276-288` (green `--needs-go`, `.is-warn` amber, `.feed-dead` red), `white-space: nowrap`.
- `scripts/cockpit_static/cockpit.js:214-240` `renderSummary(labOk, health)` computes the exact display string in all three states.

### Engineering Craft Gates
- Diagnose: applies — feedback loop = Chrome at narrow width (≤700px + 320px floor). First step: reproduce the overlap, identify the actual mechanism (flex-wrap should wrap — suspect an ancestor min-width/transform or deployed-copy drift), fix at root, prove with the same narrow-width probe. If deployed-copy drift explains the screenshot, note it in the receipt — the source fix still ships.
- Prototype: N/A — target layout ratified (stacked line).
- TDD: applies — cockpit static has no test harness; verification = live probes below + a source-assert (grep-style) test in brisen-lab is NOT appropriate cross-repo → state probe results in receipt instead (honest seam: static JS, no runner).

### Implementation
1. Restructure: `#sync-note` moves OUT of `.summary-title-row` to its own line directly UNDER the h1 (above the `<p>` descriptor). No overlap possible at any width; keep all three color states.
2. When embedded (`window.parent !== window`): hide the in-cockpit line (the Lab sidebar now carries it — no duplication). Standalone (127.0.0.1:7800): line shows stacked.
3. In `renderSummary()`, after existing DOM writes, emit `try { if (window.parent !== window) window.parent.postMessage({type:"cockpit-health", live: ..., driveable: ..., total: ..., degraded: labOk === false}, location.origin); } catch (e) {}` — every call, all three branches (no-probe branch emits `{type, live: null}` so the shell keeps the line hidden). Never let the emit break standalone rendering.
4. Bump cockpit static asset version per its existing convention.

### Key Constraints
- Do NOT touch `cockpit_controller.py`, layout JSON contracts, or `glance_state.js`.
- Do NOT resync `~/Library/Application Support/baker/cockpit/` yourself — lead does the deployed-copy resync post-merge (note it in your receipt).

### Verification
- Chrome: /v2 AGENTS with terminal panel open at 1440px and narrow — no overlap down to 320px iframe width; sidebar line matches cockpit numbers; both themes.
- Chrome: standalone cockpit — stacked line, three states (green / degraded text / feed-dead red).
- Kill cockpit (or bridge) → sidebar line hidden, no console errors.
- brisen-lab: touched pytest + `node tests/test_v2_hashnav.js` green; `py_compile`/`node --check` clean.

---

## Files Modified
- `brisen-lab/static/v2/index.html` — brand unification, live-line slot, toggle relocation, `?v=` bumps
- `brisen-lab/static/v2/shell.css` — brand/live-line/toggle-bottom styles
- `brisen-lab/static/v2/shell.js` — origin-validated `message` listener
- `brisen-lab/tests/test_v2_nav_skeleton.py`, `tests/test_v2_theme_toggle.py` — updated asserts + listener source-assert
- `baker-master/scripts/cockpit_static/index.html`, `cockpit.css`, `cockpit.js` — stacked badge, embed-hide, postMessage emit

## Do NOT Touch
- `brisen-lab/app.py` — no route changes (HEAD/no-cache work just merged @f9f92e9)
- `baker-master/scripts/cockpit_static/cockpit_layout.json`, `director_layout_contract.json` — layout contracts, lead/Director-owned
- `~/Library/Application Support/baker/cockpit/` — deployed copy, lead resyncs
- LOOPS/subpanel/card CSS from PR #177-#180

## Quality Checkpoints
1. Narrow-width overlap repro BEFORE the fix, gone AFTER (state mechanism found in receipt).
2. One-format `BRISEN LAB` title + live line beneath, both themes, no layout jump on line appearance.
3. Toggle at sidebar bottom: works, persists, keyboard-focusable, aria-label intact.
4. Fail-soft offline path clean (line hidden, zero console errors).
5. Receipts cite repo+branch+sha per repo (ls-remote confirmed) — NEVER bare PR numbers.

## Verification SQL
N/A — static frontend only, no DB surface.
