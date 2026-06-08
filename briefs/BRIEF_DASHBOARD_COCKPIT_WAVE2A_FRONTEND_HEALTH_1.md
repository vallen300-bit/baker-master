# BRIEF: DASHBOARD_COCKPIT_WAVE2A_FRONTEND_HEALTH_1 — Stop silent-fail mutations + dead-end document/presentation surfaces

## Context
The Baker Cockpit tune-up audit (2026-06-01, `tasks/dashboard-tuneup-audit.md`) found
that the Director's daily-use cockpit has several surfaces that **fail silently** — a
click looks like it worked but didn't, or a panel dead-ends with a blank screen and no
diagnostic. This brief is **Wave 2a (frontend-health subset)** — the genuinely-broken /
silent-fail surfaces only. It is **presentation/robustness only**: no schema, query, or
endpoint contract changes. Director directive 2026-06-08: Baker dashboard working
properly by tonight.

Scope is deliberately trimmed to ship tonight. Two audit Wave-2 items are **explicitly
deferred** to a follow-up (Cortex-discoverability nav home; mobile `md()` citation/table
parity) — they are enhancements/degraded-not-broken, not silent failures.

### Surface contract (ui-surface-prebrief skill, V1)
1. **User action:** (a) click any complete/dismiss/mark-done/cancel mutation button on the
   AO dashboard / deadlines / alerts panels; (b) open a document whose `source_path` is
   missing; (c) open the Presentations tab when the brisen-docs iframe target is down/cold.
2. **Backend routes:** NONE changed. This brief touches only `outputs/static/app.js`
   (frontend). The mutation endpoints themselves already exist and work; the bug is the
   frontend swallows their failures.
3. **Endpoint contracts:** unchanged. The mutation `fetch`/`bakerFetch` calls already
   target real routes; this brief adds error-handling around the existing calls.
4. **State location:** N/A — no state writes added or changed. Pure client-side error UX.
5. **UI repo (= state repo):** `baker-master` — `outputs/static/app.js` + `index.html`
   cache-bust. No cross-repo surface.
6. **Director surface preference:** N/A — hardens existing panels in place; no new
   Director-facing surface choice.
7. **Gate-1 reviewer instruction:** Reviewer MUST load the cockpit and exercise at least
   one mutation button (e.g. dismiss an alert) and confirm a failure path now shows a
   visible toast/inline error instead of a silent no-op. Code-shape review is necessary
   but NOT sufficient.

## Estimated time: ~2.5h
## Complexity: Low-Medium
## Prerequisites: none. All three fixes are independent and ship in one PR.

---

## Fix 1 (P2): 21 fire-and-forget mutation clicks fail silently on flaky network

### Problem
~21 mutation buttons (complete / dismiss / mark-done / cancel / acknowledge / resolve /
snooze) call their endpoint without awaiting or `.catch()`-ing the result. On a flaky
network or a 4xx/5xx the click is a **silent no-op** — the Director thinks an alert was
dismissed or a deadline completed when it wasn't.

### Current State
Audit located the fire-and-forget pattern at (non-exhaustive) `app.js:845, 2855, 3154,
3406, 6109` and ~16 more. The shape is a mutation `fetch(...)` / `bakerFetch(...)` whose
promise is neither awaited nor `.catch()`-handled, or whose `res.ok` is never checked.

### Implementation
1. **Enumerate the full set first.** Grep `app.js` for mutation calls that are not
   error-handled. Suggested sweep:
   ```bash
   grep -nE "bakerFetch\(|fetch\(" outputs/static/app.js | \
     grep -iE "complete|dismiss|mark|cancel|acknowledge|resolve|snooze|delete|promote|reschedule|assign|tag"
   ```
   Cross-check against the audit's listed line anchors. Produce the final list in the ship
   report (count + line numbers) — do NOT silently cap at a subset (fail-loud per
   `tasks/lessons.md`).
2. For each, wrap in a consistent pattern: `await` the call, check `res.ok`, and on
   failure surface a **visible** signal — reuse the existing toast/notification helper if
   one exists (grep for `showToast`/`notify`/`flash`); otherwise add a minimal inline
   error helper used by all of them. On failure the optimistic UI update must **revert**
   (e.g. the item should not disappear from the list if the dismiss failed).
3. Do not change what the buttons do on success — only add the failure branch.

### Key Constraints
- Use ONE shared error helper, not 21 bespoke handlers — kills drift (audit Top Risk:
  helper duplication). If a suitable helper exists, reuse it.
- Optimistic-UI reverts must not double-fire the render.
- No endpoint, payload, or method change.
- Cache-bust `?v=N` in `index.html`.

### Verification
- Pick 3 representative buttons (one alert, one deadline, one AO-card). With DevTools
  network throttled to Offline, click each → a visible error appears AND the item stays
  (no false "done"). Online → still works normally.
- Ship report lists the full count of call-sites hardened with line numbers.

---

## Fix 2 (P3->P2 for daily use): Document button dead-ends at bare Dropbox root when `source_path` missing

### Problem
`app.js:8343` — clicking a document whose `source_path` is missing opens the bare Dropbox
root (a dead-end), with no explanation. Looks broken.

### Current State
`outputs/static/app.js:~8343` builds a Dropbox URL from `source_path` without guarding the
empty/missing case.

### Implementation
Guard the missing/empty `source_path`: instead of opening the bare root, show a visible
inline message ("source link unavailable for this document") or disable the button with a
tooltip. Do not open a dead-end tab.

### Key Constraints
- Pure frontend guard. No backend lookup added.
- If `source_path` is present, behaviour is unchanged.
- Cache-bust `?v=N`.

### Verification
- Find/mocked a document row with empty `source_path` → button no longer opens bare
  Dropbox root; shows the unavailable cue.
- A document WITH `source_path` → opens correctly as before.

---

## Fix 3 (P2): Presentations iframe shows a blank page when brisen-docs is down/cold

### Problem
`app.js:8940, 8974` — the Presentations tab embeds a brisen-docs iframe. When that target
is down or cold-starting (Render free-tier spin-up), the user sees a blank white page with
no message.

### Current State
`outputs/static/app.js:~8940`/`:8974` sets the iframe `src` with no load-failure or
loading affordance.

### Implementation
1. Add a loading affordance (spinner / "Loading presentations…") shown until the iframe
   fires `load`.
2. Add an `onerror` / timeout fallback (e.g. if no `load` within ~8s): show an inline
   message ("Presentations service is waking up or unavailable — retry") with a retry
   button that re-sets the `src`.
3. Never leave a bare blank iframe with no affordance.

### Key Constraints
- iframe `load` event is the success signal; a timeout guards the cold-start/down case.
- Pure additive frontend. No backend change.
- Cache-bust `?v=N`.

### Verification
- Normal: Presentations tab shows the deck after a brief "Loading…" state.
- Point the iframe at an unreachable URL (temporary) → fallback message + retry button
  appears instead of a blank page. Revert.

---

## Files Modified
- `outputs/static/app.js` — Fix 1 (shared error helper + ~21 mutation call-sites),
  Fix 2 (source_path guard, :8343), Fix 3 (iframe loading + error fallback, :8940/:8974).
- `outputs/static/index.html` — `?v=N` cache-bust bump for `app.js`.

## Do NOT Touch
- Any backend handler, route, query, or schema — this is frontend-only.
- The success behaviour of any mutation button — only add the failure branch.
- Mobile `md()` citation/table parity (mobile.js) — DEFERRED to a follow-up brief.
- Cortex nav-home / discoverability — DEFERRED to a follow-up brief.
- `/api/dashboard/ao` auth dependency — Director-parked (Wave 1 Fix 1), out of scope.

## Quality Checkpoints
1. `node --check outputs/static/app.js` (or equivalent JS syntax check) clean.
2. Cockpit renders on desktop AND iPhone PWA (cache-bust verified).
3. At least 3 mutation buttons verified to show a visible error + revert under Offline.
4. Document missing-`source_path` and Presentations-down both show a cue, not a dead-end.
5. Ship report enumerates the FULL set of mutation call-sites hardened (count + lines).

## Gate-1 reviewer instructions
Reviewer MUST exercise at least one mutation button's failure path (DevTools Offline) and
confirm a visible error + no false-success state. Confirm the document and presentations
fallbacks render. G2 `/security-review` is NOT required (no auth/data-exposure change) but
G0 (codex brief review) + G1 (functional) + G3 (codex code review) apply.

---

## Deferred to Wave 2a-2 (follow-up brief, not tonight)
- Cortex stable discoverable home (nav tab / always-visible card) — audit Wave 2.
- Mobile `md()` divergence (citation badges + table styling) — audit Wave 2.
- These are enhancements / degraded-not-broken, intentionally out of the tonight envelope.
