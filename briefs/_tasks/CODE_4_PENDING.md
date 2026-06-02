# CODE_4_PENDING — DASHBOARD_CARD_SIGNAL_POLISH_1

status: COMPLETE
completed: 2026-06-02 PM3 — PR #59 merged b97eda0; G1 lead static + G2 /security-review scan-clear; b4 post-deploy AC #1649 machine-verified PASS (B1 instant-extinguish, B2 regression, endpoint auth, turn-stop-hook, frontend 6/6+8/8); Director visual AC PASS (blue NEW pulse + fast extinguish confirmed live).
dispatched: 2026-06-02 PM3 (aihead1-lead)
dispatched_by: lead
brief_source: ~/baker-vault/_ops/briefs/BRIEF_DASHBOARD_CARD_SIGNAL_POLISH_1.md
codex_g0: PASS-WITH-NOTES (#1645) — proceed; 5 fold-notes below
gate_plan: G0 codex DONE → G1 lead static → G2 /security-review REQUIRED (Part B touches X-Forge-Key DB-writing endpoint) → lead merge → Part B live-verify (turn-stop-hook on-disk + watched-session restart, Director visual judge)

## CODEX G0 FOLD-NOTES (#1645) — apply these
1. Part B: use `bus.WORKING_FRESH_THRESHOLD_S + 5` in app.py (app.py:23 already imports bus — no circular import). Do NOT hardcode 125.
2. Extend `tests/test_card_glance_working_toggle.js` to assert BOTH `glance-working` iff WORKING and `glance-new` iff NEW, incl. mutual exclusion.
3. Update stale comments still saying the dot is the single signal (app.js:352-354, styles.css:306-308) — A+C make dot + whole-card glow the work-state signals.
4. Part A rides Part B's narrow /security-review (G2 required: Part B touches X-Forge-Key DB-writing endpoint). Part C frontend-only, covered same PR.
5. turn-stop POST: synchronous `curl --max-time 1 >/dev/null 2>&1 || true` acceptable; background/nohup optional. NEVER log FORGE_KEY; hook must exit 0.

Evidence anchors codex verified: main=2f016fc (use ~/bm-b4-brisen-lab, ignore stale b4 feature clone); app.js:365-371 toggles glance-working; glance_state.js:15-18 WORKING>NEW; app.py:318-359 /api/heartbeat UPDATE-only; bus.py:67-71 WORKING_FRESH_THRESHOLD_S=120; bus.py:1216-1225 is_working; styles.css:290-293 left-edge + 483-486 mappings; app.js:114-123 DONE dot depends on cardState==="green"; turn-stop-hook.sh:8-13 clears active/<sid>.

---

# BRIEF — DASHBOARD_CARD_SIGNAL_POLISH_1 — instant extinguish + whole-card "received" highlight

**Repo:** brisen-lab (frontend + `/api/heartbeat`) + `~/forge-agent/turn-stop-hook.sh` (on-disk) · **Task class:** production implementation (dashboard UI + telemetry) · **Author:** AH1 (lead) · **Date:** 2026-06-02
**Harness-V2:** full (production-facing). Context Contract + done rubric below.

### Surface contract: user-visible dashboard cards at brisen-lab.onrender.com. Director is the visual judge. Two independent, independently-revertible parts.

## Context

Director live-tested the working/received signals 2026-06-02 and gave two fixes:
- **#2 — extinguish lag:** amber takes ~2 min to clear after a b-code finishes (the 120s freshness window). "Too long… distracts me. Why can't it be the same time when he finished?" → make amber go dark the instant the task ends.
- **#3 — "received" is invisible:** when an agent receives a task it shows a small white dot — "too small, I cannot notice it." → restore the WHOLE-CARD highlight for the received/NEW state (like the old data-pending chrome, but brighter), keeping the dot.

(WORKING whole-card amber already ships — `DASHBOARD_WHOLE_CARD_WORKING_GLOW_1` PR #58. This brief adds the matching NEW whole-card highlight + makes the extinguish instant.)

### Context Contract
- **Router:** b4 — owns the card frontend (`DASHBOARD_CARD_WORKSTATE_CLARITY_1` #55) + the heartbeat/`/api/heartbeat` (#56) + turn-gating. Single best owner for both parts.
- **Problem Evidence:** Director chat 2026-06-02 (#2 + #3 above); current `renderCard` toggles only `glance-working`; `.state-dot-pending` is a small white pulsing dot; `/api/heartbeat` only refreshes `last_seen_at=NOW()`; `is_working` = `last_seen_at` ≤ `WORKING_FRESH_THRESHOLD_S` (120s) so extinguish lags the window.
- **Current State:** `static/app.js` renderCard (post-#58): `const glance = computeGlanceState(alias); card.classList.toggle("glance-working", glance==="WORKING"); card.appendChild(renderStateDot(alias, glance))`. `static/styles.css` has `.card.glance-working` + `.state-dot-pending`. `app.py` `POST /api/heartbeat` = UPDATE-only `last_seen_at=NOW()`. `~/forge-agent/turn-stop-hook.sh` = self-gate + `rm -f active/<sid>` + exit 0.
- **Stable Paths:** `static/app.js`, `static/styles.css`, `static/index.html` (cache-bust), `app.py` (`/api/heartbeat`), `~/forge-agent/turn-stop-hook.sh`, `tests/`.

---

## Part A (frontend) — whole-card highlight on NEW ("task received")

### Implementation
- `static/app.js` renderCard: alongside the existing working toggle, add `card.classList.toggle("glance-new", glance === "NEW")`. (Reuse the single `glance` already computed; do not recompute.)
- `static/styles.css`: add `.card.glance-new` = a bright, **noticeable whole-card highlight** distinct from amber — bright blue, pulsing, so a glance across the room catches it:
```css
/* NEW — whole card pulses bright blue when a task is received but not yet
   started. Distinct from WORKING amber. Director: "make the whole card light
   up — I can't notice the small white dot." */
.card.glance-new {
  border-color: #2f81f7;
  box-shadow: 0 0 0 1px #2f81f7, 0 0 16px rgba(47, 129, 247, 0.45);
  background: rgba(47, 129, 247, 0.09);
  animation: card-new-pulse 1.4s ease-in-out infinite;
}
@keyframes card-new-pulse {
  0%, 100% { box-shadow: 0 0 0 1px #2f81f7, 0 0 10px rgba(47,129,247,0.30); }
  50%      { box-shadow: 0 0 0 1px #2f81f7, 0 0 22px rgba(47,129,247,0.60); }
}
```
- Keep the dot (Director wants both signals). WORKING amber unchanged. DONE/IDLE/UNKNOWN → no whole-card glow.
- Cache-bust changed assets (`styles.css?v=N+1`, `app.js?v=N+1`).
- Precedence note: a card is NEW only when not WORKING (resolver already returns WORKING over NEW), so `glance-new` and `glance-working` are mutually exclusive — fine to toggle both off the one `glance`.

### Part A Acceptance
- A1: a card with an unacked task (glance NEW) shows the whole-card blue pulse + the dot; WORKING shows amber (unchanged); DONE/IDLE = no glow.
- A2: `node tests/test_glance_state_resolver.js` still 8/8 (resolver untouched); extend `test_card_glance_working_toggle.js` (or a sibling) to assert `glance-new` toggles iff glance==="NEW".

---

## Part B (backend + hook) — instant extinguish on task-end

### Implementation
- `app.py` `POST /api/heartbeat`: accept an OPTIONAL `idle` boolean in the body. When `idle` is true, backdate instead of refresh:
  `UPDATE forge_sessions SET last_seen_at = NOW() - make_interval(secs => %s) WHERE session_uuid = %s` with secs = `WORKING_FRESH_THRESHOLD_S + 5` (pull the threshold from the same source of truth; do not hardcode 125 — import/derive). Default (`idle` absent/false) = existing `NOW()` behavior, byte-for-byte. Keep auth/freeze/alias-validation/UPDATE-only/no-broadcast exactly as today.
- `~/forge-agent/turn-stop-hook.sh`: after `rm -f active/<sid>`, fire-and-forget POST `/api/heartbeat` with `{"session_uuid":<sid>,"terminal_alias":$FORGE_TERMINAL,"idle":true}` (short timeout, never logs FORGE_KEY, exit 0). This stales `last_seen_at` immediately → `is_working=false` on the next dashboard poll (~seconds), not ~2 min.
- Net behavior: turn ends → flag cleared (ticker stops) AND last_seen_at backdated → amber extinguishes within one dashboard refresh.

### Part B Acceptance
- B1: `POST /api/heartbeat {idle:true}` for a fresh session → `is_working=false` immediately on `/api/v2/terminals` (vs still-true without idle). Literal test.
- B2: default heartbeat (no `idle`) still refreshes → `is_working=true` (regression — unchanged).
- B3: same auth/freeze/alias/UPDATE-only/no-broadcast invariants as the existing endpoint (the #56 tests stay green).
- B4 (live): a b-code finishing a turn (window open) greys **within one dashboard poll cycle (~seconds), not ~2 min** — Director visual judge.

---

## Part C (frontend) — retire the legacy colored left-edge (Director "glitch": b2/b3 left edge amber)

### Problem
The card left edge is `border-left: 4px solid var(--card-edge)` colored by `data-card-state` (styles.css ~483-486): `yellow→#d29922` (= the SAME amber as WORKING), `red→#f85149`, `green→#2ea043`, `grey→#30363d`. `cardState()` returns "yellow" for an open PR or a building-on-a-feature-branch mailbox. b2/b3 show amber left edges from a **stale snapshot** — their `forge_snapshot_push` daemon has been dead ~3 days, so the edge reflects days-old PR/branch state, in the same amber as the live working signal. Director reads it as a glitch (color collision + stale data).

### Implementation
- **Retire the left-edge COLOR.** Remove the `data-card-state` → `--card-edge` color mappings (styles.css ~483-486) so the left border is always the neutral `var(--border)`. The dot + whole-card glow (NEW blue / WORKING amber / DONE green) are now the only work-state colors — the legacy colored edge is redundant + collision-prone.
- **KEEP** `cardState()` the function and the `data-card-state` attribute — the dot's DONE state depends on `isDoneGreen = cardState(snap) === "green"`, and the attribute stays as debug instrumentation. ONLY the colored border is retired.
- Cache-bust (shared with Part A bump).

### Part C Acceptance
- C1: b2/b3 (and all cards) show a neutral left edge regardless of `data-card-state`; no amber/yellow/red/green left border anywhere.
- C2: the DONE-green dot still works (cardState function intact); resolver tests still green.
- Note (separate follow-up, NOT in scope): the dead `forge_snapshot_push` daemon for b2/b3 (~3 days stale) is a telemetry degradation like the agent.py tailer — retiring the colored edge makes it moot for this signal; reviving the snapshot daemon is its own brief.

## Files Modified
- `static/app.js` — `glance-new` toggle.
- `static/styles.css` — Part C: remove `data-card-state` color mappings (neutral left edge).
- `static/styles.css` — `.card.glance-new` + keyframe; cache-bust.
- `static/index.html` — cache-bust bump.
- `app.py` — `/api/heartbeat` optional `idle` backdate branch.
- `~/forge-agent/turn-stop-hook.sh` — POST idle:true on Stop.
- `tests/` — Part A toggle test + Part B idle-endpoint tests.

## Do NOT Touch
- `static/glance_state.js` resolver, `renderStateDot`/the dot, `.card.glance-working` (amber).
- The default `/api/heartbeat` refresh path (additive `idle` branch only).
- `WORKING_FRESH_THRESHOLD_S` value, `turn-start-hook.sh`, the ticker gate.

## Quality Checkpoints
1. NEW = whole-card bright-blue pulse + dot; mutually exclusive with WORKING amber; DONE/IDLE dark.
2. `idle:true` backdates last_seen_at past the threshold → instant grey; default path unchanged (#56 tests green).
3. Threshold derived from the single source of truth, not hardcoded.
4. turn-stop POST is fire-and-forget, never logs FORGE_KEY, exit 0.
5. Cache-bust every changed static asset.

## Gate Plan
- G0 codex (brief, then PR) · G1 lead static · **G2 /security-review REQUIRED** (Part B touches the X-Forge-Key DB-writing endpoint — narrow but mandatory on Tier-A; Part A frontend confirm-narrow) · G3 architect N/A. Lead merges on green; Part B needs the turn-stop-hook edit applied on-disk + a watched-session restart to live-verify.

## Done rubric / done-state terminal class
- **Task class:** production implementation (UI + telemetry).
- **Done-state:** DONE only at live AC — A1 (whole-card NEW pulse visible) + B4 (extinguish within ~seconds of task-end), Director visual-confirmed, + cache-bust live. "Tests pass" alone ≠ done.

## Notes for reviewer (codex)
- Confirm `idle` backdate is the cleanest instant-extinguish vs a separate endpoint (reuses heartbeat auth/freeze/validation; smaller surface).
- Confirm `glance-new` + `glance-working` mutual exclusivity holds via the resolver priority.
- Rule whether Part A (frontend-only) needs its own narrow /security-review or rides Part B's.
- Confirm the turn-stop POST can't block the agent's turn (fire-and-forget, short timeout).
