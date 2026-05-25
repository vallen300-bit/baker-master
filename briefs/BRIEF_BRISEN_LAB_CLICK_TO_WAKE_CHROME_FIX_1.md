---
brief_id: BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1
title: Dashboard click-to-wake fails silently in Chrome — replace window.location.href with anchor-click pattern
status: DISPATCHED
authored_by: cowork-ah1
authored_at: 2026-05-25
director_ratified: 2026-05-25 (cowork-ah1 chat — Director-observed live-Chrome reproduction)
target: b1
reply_target: cowork-ah1
expected_time: ~20min
complexity: Low
target_repo: brisen-lab (single PR)
depends_on: PR #34 (BRISEN_LAB_CLICK_TO_WAKE_1, merged) + PR #36 (BRISEN_LAB_WAKE_NUDGE_PIVOT_1, merged)
---

# BRIEF: BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1 — Replace `window.location.href` with anchor-click pattern for custom-scheme launch

### Surface contract

- Existing surface: badged card click in the dashboard fires `brisen-lab://wake/<alias>` → handler nudges/spawns. PR #34 wired the click handler. PR #36 made the handler nudge-first.
- Problem on Chrome: the click handler uses `window.location.href = "brisen-lab://..."` which Chrome (current versions) silently denies for custom URL schemes with the console error *"Not allowed to launch '...' because a user gesture is required"* — even from a trusted user click. Result: every card click on Director's Chrome does nothing visible. Director-observed reproduction this session.
- Scope of this fix: change the JS launch pattern only. Same DOM, same badge-gating, same shift-click escape hatch, same fallback to detail modal for unbadged clicks. No new HTTP route, no new visible UI element, no copy change.
- Why Surface contract block is real (not N/A): the click affordance on badged cards is a Director-visible behavior — currently broken, this brief restores it.

## Context

PR #34 shipped click-to-wake. PR #36 shipped nudge-first behavior. Verification this session showed:
- Handler app installed correctly (Launch Services binds `brisen-lab://` to `com.brisen.lab.wake`).
- Direct fire via `open 'brisen-lab://wake/<alias>'` from a Terminal works end-to-end (nudge fires + agent wakes).
- Direct fire via `osascript do script in <tab>` works.
- **Click on dashboard card does NOT reach the handler in Chrome.** Console error: `Not allowed to launch 'brisen-lab://wake/b3' because a user gesture is required.`

Root cause: Chrome (Chromium ~v100+) treats `window.location.href = "<custom-scheme>://..."` as a programmatic navigation and rejects it for external-protocol launches, even when called inside a click event handler. The browser's external-protocol policy requires the launch to originate from a "trusted user activation" surface, which Chrome recognizes for an `<a>` element click but NOT for a JS-set `location.href`.

Standard workaround: synthesize an `<a>` element with the custom-scheme href, programmatically click it, then remove it. The browser's user-activation tracker accepts the synthetic anchor click as a trusted launch because it inherits the activation context from the outer user click event.

## Estimated time: ~20min
## Complexity: Low
## Prerequisites: PR #36 merged (it is — main @ `66109ce`).

---

## Fix/Feature 1: Replace `window.location.href` with anchor-click in card click handler

### Problem

`static/app.js` line 905 (post-PR #34 deploy, v=15 currently live):
```js
window.location.href = "brisen-lab://wake/" + encodeURIComponent(alias);
```

Chrome blocks this for custom schemes regardless of user gesture context. The line silently no-ops + Chrome logs the console error. The handler then hits `return;` and exits without triggering the wake handler. Result: dashboard click-to-wake is broken in Chrome.

### Current state

The relevant region of `static/app.js` (lines ~895-911):
```js
// BRISEN_LAB_CLICK_TO_WAKE_1 (Director-ratified 2026-05-24, cowork-ah1 bus #916)
const WAKEABLE_ALIASES = new Set(TERMINALS);
document.querySelectorAll(".card").forEach(c => {
  if (SYSTEM_CARDS.includes(c.dataset.alias)) return;
  c.addEventListener("click", (ev) => {
    const alias = c.dataset.alias;
    const hasBadge = !!(state.busBadge[alias] && state.busBadge[alias].unacked_count > 0);
    const wakeable = WAKEABLE_ALIASES.has(alias);
    if (hasBadge && wakeable && !ev.shiftKey) {
      window.location.href = "brisen-lab://wake/" + encodeURIComponent(alias);
      return;
    }
    state.detailAlias = alias;
    renderDetail();
  });
});
```

### Implementation

Replace the URL launch line + the comment immediately above it with the anchor-click pattern. New region (lines ~895-911):

```js
// BRISEN_LAB_CLICK_TO_WAKE_1 (Director-ratified 2026-05-24, cowork-ah1 bus #916)
// BRISEN_LAB_CLICK_TO_WAKE_CHROME_FIX_1 (2026-05-25): switched from
// window.location.href to anchor-click. Chrome blocks the former for custom
// URL schemes ("user gesture required" error) — synthesizing an <a> click
// inherits the outer click event's user-activation context and routes
// through Launch Services as the user-trusted external-protocol launch.
const WAKEABLE_ALIASES = new Set(TERMINALS);
document.querySelectorAll(".card").forEach(c => {
  if (SYSTEM_CARDS.includes(c.dataset.alias)) return;
  c.addEventListener("click", (ev) => {
    const alias = c.dataset.alias;
    const hasBadge = !!(state.busBadge[alias] && state.busBadge[alias].unacked_count > 0);
    const wakeable = WAKEABLE_ALIASES.has(alias);
    if (hasBadge && wakeable && !ev.shiftKey) {
      // Anchor-click pattern (Chrome custom-scheme compatibility).
      const a = document.createElement("a");
      a.href = "brisen-lab://wake/" + encodeURIComponent(alias);
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      a.remove();
      return;
    }
    state.detailAlias = alias;
    renderDetail();
  });
});
```

### Key constraints

- **Do NOT change `WAKEABLE_ALIASES`, `SYSTEM_CARDS`, `TERMINALS`, or `state.busBadge` reads** — those are correct; the only bug is the URL launch primitive.
- **Do NOT touch the wake handler app** (`tools/wake-handler/`) — it's confirmed working end-to-end.
- **Do NOT remove the badge-gating** (`hasBadge && wakeable && !ev.shiftKey`) — that's the affordance contract from PR #34.
- **Do NOT change `index.html`, `styles.css`, or any HTML structure** — DOM is identical; only the JS function body changes.
- **Keep the existing detail-modal fallback intact** — same `state.detailAlias = alias; renderDetail();` lines.
- **Append the anchor element to `document.body` then remove it inside the same synchronous call** — Chrome's user-activation tracker is synchronous; do NOT defer the `.remove()` via setTimeout or microtasks.

### Verification

1. Locally: `python -m http.server` from `static/` won't work (Render-served; verify in dev branch deploy).
2. Manual Chrome test (Director-observed reproduction):
   - Open `https://brisen-lab.onrender.com/` in Chrome.
   - Pick an agent with a badge visible on its card (or send a smoke message via `BAKER_ROLE=lead bus_post.sh <slug> "smoke" "smoke/test"` if none).
   - Open Chrome DevTools → Console.
   - Click the badged card.
   - Expected: no `"Not allowed to launch ..."` error in console; a Terminal opens (spawn) or `check bus` appears in the matching agent's running Claude prompt (nudge). Either is a PASS.
   - Negative: console error or no visible action → still broken.
3. Verify `/tmp/brisen-lab-wake-<fn>.command` file timestamp updates (when spawn fires) OR (when nudge fires + Apple Events grant present) the matching Terminal's Claude session receives `check bus`.
4. Safari regression check: open the same dashboard in Safari, repeat the click. Expected: still works (anchor-click is universally supported; original `window.location.href` also worked in Safari).
5. Cache-bust: bump `index.html` `app.js?v=15` → `app.js?v=16` so Director's browser picks up the new JS without a hard reload.

---

## Fix/Feature 2: Cache-bust bump in `index.html`

### Problem

Without bumping the `?v=` query param on `<script src="/static/app.js?v=15">`, browser caches will serve the old JS for an indeterminate window post-deploy. Director was on `v=15` this session.

### Implementation

In `static/index.html`, change `<script src="/static/app.js?v=15">` to `<script src="/static/app.js?v=16">`. One-line edit.

### Verification

After deploy, `curl -s https://brisen-lab.onrender.com/ | grep app.js` should show `app.js?v=16`. Director's browser will pick up the new JS on next normal navigation; hard reload not required.

---

## Files Modified

- `static/app.js` — replace `window.location.href = "brisen-lab://..."` with anchor-click. Add a short comment referencing this brief.
- `static/index.html` — bump `app.js?v=15` to `app.js?v=16`.

## Do NOT Touch

- `tools/wake-handler/*` — handler app is correct; the bug is in the dashboard JS.
- `static/styles.css` — no styling change.
- `bus.py`, `app.py`, `daemon/*`, server code generally — no server-side change.
- `WAKEABLE_ALIASES`, `SYSTEM_CARDS`, `TERMINALS` — unchanged.
- The detail-modal fallback path — unchanged.

## Quality Checkpoints

1. `grep -n "anchor-click\|a.click()" static/app.js` returns the new pattern.
2. `grep -c "window.location.href = \"brisen-lab" static/app.js` returns 0.
3. `grep "app.js?v=" static/index.html` shows `v=16`.
4. Director-observed click on a badged card in Chrome triggers nudge or spawn (verified by `/tmp/brisen-lab-wake-*.command` timestamp OR Claude session receiving `check bus`).
5. No new console errors in Chrome DevTools when clicking a badged card.
6. Detail modal still opens correctly on (a) unbadged-card clicks, (b) shift+click on badged cards.

## Gate chain (your trigger after ship)

- Gate-1 architecture: deputy (AH2)
- Gate-2 `/security-review`: deputy (AH2) — trivial JS DOM diff; brief review fine
- Gate-3 picker-architect: SKIP (no install, no symlink change)
- Gate-4 code-reviewer 2nd-pass: deputy (AH2)
- Gate-5 merge: cowork-ah1 will merge on PASS (lead is quiet on this thread; first-AH1-wins rule applies)

## Reply target

Post ship report bus to **cowork-ah1**.

## Director context

Director ran end-to-end smoke test on b3 + hag-filer this session. Direct fire of the URL via Terminal `open` command works perfectly. Dashboard click does nothing visible. Live-Chrome diagnostic in Director's browser tab confirmed the `"user gesture required"` block. Without this fix, the entire click-to-wake feature is dead-on-arrival in Chrome — Director would continue typing `check bus` manually into every agent's Terminal. PR #34 + PR #36 effectively don't deliver value on Director's primary browser until this lands.

## What NOT to do

- Do NOT widen the alias coverage; same 14 pickers as PR #34.
- Do NOT change the badge-gating condition.
- Do NOT add try/catch around the anchor.click(); if the launch is blocked again, the console error is the diagnostic signal we want.
- Do NOT ship without testing in Chrome directly (Safari-only confirmation is insufficient — Safari was never the broken case).
