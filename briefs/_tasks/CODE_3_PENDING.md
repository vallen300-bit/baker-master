---
dispatch: DASHBOARD_MUTATION_FAILSAFE_1
to: b3
from: cowork-ah1
dispatched_by: cowork-ah1
status: PENDING
dispatched_at: 2026-06-02T15:30:00Z
authored: 2026-06-02
brief_path: briefs/BRIEF_DASHBOARD_MUTATION_FAILSAFE_1.md
target_repo: baker-master
estimated_time: ~2.5h
complexity: Medium
brief_version: v2 — codex-arch G0 PASS (#1643); 3 folds applied + label typo fixed
codex_pre_review: PASS (codex-arch #1643) — JSON-error success gate, async/await enumeration, body-bearing endpoint contract all confirmed
reply_to: cowork-ah1
ship_topic: ship/dashboard-mutation-failsafe-1
anchor_chat: Director 2026-06-02 "go" — dashboard tune-up Wave 2 (cockpit audit). b1/b2/b4 busy; b3 free post-merge. NO collision with b1/b4 dashboard work — they are brisen-lab static/app.js; THIS is baker-master outputs/static/app.js.
---

### Surface contract: see brief — full 6-check block in BRIEF_DASHBOARD_MUTATION_FAILSAFE_1.md Context section (codex-arch G0 PASS #1643).

# b3 dispatch — DASHBOARD_MUTATION_FAILSAFE_1

Read `briefs/BRIEF_DASHBOARD_MUTATION_FAILSAFE_1.md` end-to-end before any code. **Target repo: baker-master** (your `~/bm-b3` baker-master clone). This is the **Baker Cockpit** frontend `outputs/static/app.js` — NOT the brisen-lab bus dashboard (different repo; b1/b4 are working brisen-lab's `static/app.js`, zero overlap with you).

Brief cleared **codex-arch G0 = PASS** (#1643, 2026-06-02); all 3 folds + the label typo are already in the brief. No further pre-write review required.

**Why this exists:** cockpit audit Wave 2 — ~21 mutation action buttons (complete/dismiss/done/resolve/snooze/postpone) are fire-and-forget `bakerFetch().then()`/`await` chains. Two bugs: silent failure (no error path) AND false success (optimistic UI applied without checking `resp.ok`, so a 500/401 — or a 200+`{error}` — makes the card vanish as if done).

**Scope (3 fixes, frontend-only):**
- **Fix 1:** `_showToast(msg, type)` — add a red `error` variant (backward-compatible; default unchanged). app.js:2999.
- **Fix 2:** add the centralized `_mutate(url, opts, onOk, onErr)` helper near `bakerFetch` (app.js:25): awaits, requires `resp.ok`, then guarded `resp.clone().json()` — treats `{error}` as failure (red toast + onErr), runs `onOk(resp, data)` only on confirmed success.
- **Fix 3:** migrate the ~21 action-button sites ONE AT A TIME (lessons: batch JS migration = bugs) — BOTH `.then` and `await` styles; optimistic UI moves into `onOk`. Seed list + the async/await offenders (resolveAlert, dismissAlert, confirmBrowserAction, cancelBrowserAction) are in the brief. PRESERVE the existing `d.error` behavior of `_triagePromoteCritical`/`_triageAddToPromised`/`_criticalQuickAdd`. PRESERVE body-bearing mutations (e.g. `+1 Week` sends `{due_date}`).

**Constraints:** scope to user-facing ACTION buttons, not all ~70 mutation calls. Bump `index.html` `?v=N` cache-bust.

**Gates:** G1 (cowork-ah1 fold) → G3 (deputy). **G2 `/security-review` NOT required** (frontend error-handling only; codex-arch concurred). Verification MUST include the failed-mutation behavior (offline / 500 / 200+`{error}`) on desktop + iPhone PWA — card stays + red toast, no false success.

**Ship:** open PR on `baker-master`; bus-post `ship/dashboard-mutation-failsafe-1` to `cowork-ah1`. **Do NOT merge** (AH gate). Answer the done-rubric in the ship report (task class = frontend reliability; terminal state = failed-mutation no longer false-succeeds, verified live).
