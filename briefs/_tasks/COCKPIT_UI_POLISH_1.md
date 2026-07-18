# COCKPIT_UI_POLISH_1 — compact rows, universal ctx/Start, token entry page

**Priority:** P2 · **Worker:** b2 · **Dispatched:** 2026-07-18 (lead) · **Attempt:** 1
**Report topic:** `gates/cockpit-ui-polish-1`
**Director asks:** bus #12800 (card shape, ctx meter, Start) + #12796 (sidebar dead link) — ratified via cowork-ah1 relay 2026-07-18.

## Problem

Director cannot see the whole fleet on one screen (cards too tall), context
meters and Start controls appear only on some seats, and any device without the
access cookie hits a bare 404 instead of a code-entry screen (Lab sidebar
"Cockpit" link appears dead; cookie dies on browser close).

## Context

Cockpit page (`scripts/cockpit_static/`, served by `scripts/cockpit_controller.py`
locally at 127.0.0.1:7800, proxied to Brisen Lab at `/cockpit/*` via
COCKPIT_IN_LAB_BRIDGE_1) is live for the Director on laptop + phone. Three
Director-ratified UI defects + one access defect:

1. Cards too tall — fleet doesn't fit one screen. Wants thin Lab-list-style rows.
2. Context meter only on seats with telemetry — wants it on ALL cards (em-dash
   placeholder when `context_pct` is null).
3. Start button conditionally hidden — wants the state control uniformly present
   on every card.
4. Reaching `/cockpit/` without the access cookie = bare 404 ("page not found"
   from the Lab sidebar link; "does nothing" UX). No code-entry screen exists;
   cookie is session-only so it dies on browser close.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director scans the whole fleet on one screen, starts/opens
   any seat, and reaches the cockpit from any device by entering code once.
2. **Backend routes (verified by opening handlers):**
   - `GET /api/agents` — `scripts/cockpit_controller.py:821` `async def get_agents(request)` → `{"agents":[{slug, alias, port, session_up, ttyd_up, **GLANCE_FIELDS incl. context_pct, has_telemetry, needs_go, unacked_count}], "lab_glance_ok"}`.
   - `POST /api/sessions/{slug}/start` — `cockpit_controller.py:845` `start_session(slug, request)`; 502 on failure.
   - `POST /api/sessions/{slug}/go` — `cockpit_controller.py:853`.
   - Lab gate: `_cockpit_proxy` — `brisen-lab/app.py:2883` — flag-gated 404, then `cockpit_bridge.cockpit_access(req)` (X-Cockpit-Token header / `cockpit_token` cookie / one-time `?token=` that seeds cookie via `resp.set_cookie(... httponly, secure, samesite=strict)` — session-only today).
3. **Endpoint contract:** no query params on /api/agents; start/go take slug path
   param only; Lab auth = COCKPIT_ACCESS_TOKEN compare + existing rate-limit/lockout.
4. **State location:** seat state = cockpit_controller (manifest + tmux + Lab
   glance feed) in baker-master; access gate state = brisen-lab env + cookie.
5. **UI repo (= state repo):** cards → baker-master `scripts/cockpit_static/`;
   entry page → brisen-lab (it owns the gate). Split is the documented bridge
   contract (COCKPIT_IN_LAB_BRIDGE_1).
6. **Director surface preference:** ratified 2026-07-18 (#12800/#12796) — cockpit
   web page, thin rows "like my normal Brisen Lab list".
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load the URLs in the ACs
   (or curl with the exact query/cookie the frontend sends) and confirm
   non-error responses. Code-shape review is necessary but not sufficient.

## Deliverables

**D1 (baker-master `scripts/cockpit_static/`):** compact row layout — one thin
row per seat (Lab-list density), whole 43-seat fleet fits one laptop screen;
plate groupings survive as slim section headers.

**D2:** context meter rendered on EVERY row; `context_pct == null` → em-dash
placeholder (never blank, never hidden).

**D3:** state control on EVERY row: session down → `Start`; `needs_go` → `GO`;
else live status chip. Never conditionally absent.

**D4 (brisen-lab):** flag-ON + no/bad token → minimal code-entry page (input →
sets `cockpit_token` cookie, `max_age=30d`, httponly/secure/samesite=strict →
reload). Flag OFF stays bare 404 (posture unchanged). Existing rate-limit/
lockout untouched and still mandatory. Bad code on the entry page → same
lockout counter.

**D5:** cookie seeded via `?token=` also gets `max_age=30d` (today: session-only).

**D7 (brisen-lab — RATIFIED GOAL, #12806):** cockpit renders INSIDE the normal
Lab sidebar UI as a first-class view: sidebar "Cockpit" click switches the view
in-page (iframe embed of `/cockpit/` is acceptable v1), no new tab, no separate
"top-tab" shell. Hide the cockpit page's own top-tab header when embedded
(`window.__COCKPIT_BASE__` set = embed signal). Director acceptance: open normal
Lab → click sidebar Cockpit → grid opens there. One Lab, one page. AC7: literal
click-through screenshot.

**D8 (Director defect 2026-07-18 ~15:05Z):** working-state (amber) is FALSE for
seats that are visibly working — live probe showed `is_working:false` on every
seat incl. lead mid-task; `has_telemetry:false` on most. The Lab-glance
telemetry feed cannot be the sole source. Fix: controller derives a LOCAL
working signal — sample each seat's tmux pane (`capture-pane` hash delta over a
short window, force-redraw caveat from COMPOSER_RESIDUAL_DIAG report: stale
renders) and OR it with Lab telemetry. Card shows amber when either says
working. AC8: with a seat mid-build, its row is amber within ≤30s, and goes
quiet ≤60s after output stops.

**D9 (Director-RESOLVED design, #12858→#12864→#12871):** two card modes.
(1) tmux-backed: click opens terminal (unchanged). (2) App-resident (cowork-*,
codex-arch): click opens the BUS-MESSAGE PANEL — reuse the Lab "Production &
Lab" component verbatim (header `<name> [slug] messages`, sections
UNACKNOWLEDGED(n) / LAST MESSAGE / ACKNOWLEDGED(count), rows from-slug + topic +
msg-id + age, Copy button, close X) — bind-not-build, same data source. Plus
passive flash-on-new-message + unacked badge on App cards (mirror Production &
Lab). Requirement: zero dead clicks. AC9: App-card click opens the panel; new
bus message flashes the card.

**D6:** post-merge deploy note: sync `scripts/cockpit_static/` into
`~/Library/Application Support/baker/cockpit/static/` (installed copy the live
controller serves — see 2026-07-18 stale-copy incident) and verify via the Lab.

## Constraints

- Do NOT touch the wake/injection paths, ttyd terminal overlay internals, or
  `cockpit_mux.py` (byte-identical pair with brisen-lab).
- Do NOT weaken the gate: no token in page source, no logging of the code,
  lockout stays mandatory.
- Phone: rows must remain tappable (min 44px touch target) — Director uses
  Safari on iPhone.
- Mock references exist: `COCKPIT_LAYOUT_REARRANGE_MOCK_V3.html` (repo root) —
  density reference only, not binding.

## Files Modified

- baker-master: `scripts/cockpit_static/cockpit.css`, `scripts/cockpit_static/cockpit.js`, `scripts/cockpit_static/index.html` (D1-D3).
- brisen-lab: `app.py` (`_cockpit_proxy` no-token branch), `cockpit_bridge.py` (`cockpit_access` / cookie seeding), new entry-page template or inline HTML, tests (D4-D5).
- No other files; `cockpit_mux.py` pair and controller wake paths are out of scope.

## Harness V2

- **Context Contract:** everything the worker needs is in this brief + the two
  repos; no vault reads required. Live probe surface: 127.0.0.1:7800 (local) and
  brisen-lab.onrender.com/cockpit/ (needs access code — request from lead over
  the bus at AC time; do NOT hardcode it anywhere).
- **Task class:** production implementation, UI + auth-gate touch (Tier-A merge
  path, codex-gated).
- **Done rubric / done-state class:** post-deploy AC verdict on the bus
  (`post-deploy-ac-bus-gate` convention) on topic `gates/cockpit-ui-polish-1` —
  AC1-AC6 each PASS/FAIL, screenshots attached for AC1/AC2.
- **Gate plan:** codex bus-seat gate on both repo tips (pre-merge) →
  lead line-read + merge → installed-copy sync (AC6) → post-deploy AC verdict.

## Verification

- Run both repos' test suites; new gate-branch unit tests (AC5).
- Literal-flow probes, not compile-clean: load local page, load Lab page with
  cookie, no-cookie entry-page flow, wrong-code lockout (AC1-AC4).
- `diff -q` of installed copy vs repo static after sync (AC6).

## Quality Checkpoints / Acceptance criteria

- AC1: local page http://127.0.0.1:7800/ shows all seats as thin rows, one
  screen at 1440×900; every row has ctx meter (or em-dash) + state control.
- AC2: `curl -s -H "X-Cockpit-Token: <code>" https://brisen-lab.onrender.com/cockpit/api/agents`
  still 200; grid renders through the Lab (hard-reload, screenshot in report).
- AC3: no-cookie browser hit on `/cockpit/` with flag ON → entry page renders;
  correct code → grid; wrong code ×N → existing lockout fires. With flag OFF
  (staging toggle or unit test) → 404 unchanged.
- AC4: cookie from entry page AND from `?token=` carries Max-Age≈30d
  (assert header in test).
- AC5: existing tests green both repos; new unit tests for the entry-page gate
  branches (no-token/bad-token/good-token/flag-off).
- AC6: installed-copy sync executed + verified live (report the diff -q output).

## Gate

Codex gate (bus seat `codex`) on both repo tips before merge; report + screenshots
to `gates/cockpit-ui-polish-1`; lead merges.
