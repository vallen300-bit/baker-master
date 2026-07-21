# BRIEF: COCKPIT_AGENTS_VIEW_DIRECTOR_PASS_1 — Director walkthrough fixes on the cockpit agents grid + context-refresh button

## Context
Director eyeballed the Lab /v2 AGENTS view (which renders the cockpit grid, served
from `scripts/cockpit_static/` in this repo via the local controller / in-Lab bridge)
on 2026-07-21 and gave 6 rulings. Items here are the 5 cockpit-side ones plus one NEW
feature he asked for in the same pass (context-refresh button). Lab /v2-side items
(sidebar width, SOON column, skills bar, loops sub-views) are a SEPARATE brief
(LAB_V2_DIRECTOR_PASS_1, brisen-lab repo) — do not touch brisen-lab from this brief.

Verified current state (origin/main @42d77a63):
- `scripts/cockpit_static/index.html:59` header row is
  `<span></span><span>Agent / identity</span><span>Inbox</span><span>Context window</span><span>Session</span>`
- `scripts/cockpit_static/index.html:44` subtitle `<p>Every terminal, app seat, desk, and service in one scan surface.</p>`
- Start button render: `scripts/cockpit_static/cockpit.js:698-700` (`.rbtn.start`, onclick `doStart`), `doStart` at `cockpit.js:1071-1075`
- GO send path (controller): `scripts/cockpit_controller.py:1056-1064` `send_go()` → `tmux send-keys -t <slug> Enter`
- Literal+CR send pattern (reuse for /clear): `scripts/cockpit_controller.py:1382-1390` (`send-keys -l <text>` then `send-keys Enter`); settle-gap discipline documented at `cockpit_controller.py:95-103` (WAKE_COMPOSER_SUBMIT_FIX_1).

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director realigns/reads the agents grid (Fixes 1-5, existing surface, no new click destinations) and clicks a per-seat ⟳ button to clear that agent's context without opening the terminal (Feature 6).
2. **Backend route:** Fixes 1-5: none new — existing `POST /api/sessions/{slug}/go` and `/start` untouched (verified `scripts/cockpit_controller.py:1056-1064`). Feature 6: NEW `POST /api/sessions/{slug}/refresh_context` in `baker-master/scripts/cockpit_controller.py`, modeled byte-for-byte on `send_go(settings, entry)`'s tmux argv pattern.
3. **Endpoint contract:** path param `slug` (registry slug, driveable only); no query params; no body; same-origin Basic-auth session (identical to `/go`); responses `{ok:true, sent:"/clear", slug}` / 404 unknown / 409 session down or app seat.
4. **State location:** tmux session per seat, local Mac (controller-owned); no Postgres surface.
5. **UI repo (= state repo):** baker-master `scripts/cockpit_static/` — surface: cockpit grid (local :7800 + in-Lab bridge embed).
6. **Director surface preference:** ratified 2026-07-21 — Director named this exact surface himself ("a button I can click in the Agents View ... cockpit") in the walkthrough.
7. **Gate-1+2 reviewer instruction:** "Reviewers MUST load the URL with exact query string + confirm non-error response. Code-shape review is necessary but not sufficient." (Concretely: `curl -X POST -u <cockpit-basic-auth> http://127.0.0.1:7800/api/sessions/<up-seat>/refresh_context` → 200; against a down seat → 409; unknown slug → 404.)

## Estimated time: ~2-3h
## Complexity: Medium (one new controller endpoint + CSS/markup surgery)
## Prerequisites: none — main @42d77a63 or later

## Harness V2
- **Context Contract:** builder needs ONLY: this brief, `scripts/cockpit_static/{index.html,cockpit.js,cockpit.css}`, `scripts/cockpit_controller.py` (send_go + literal/cr helper + settle-gap constant), `tests/test_cockpit_card_geometry.py`, `tests/test_cockpit_controller.py`, runbook `.claude/how-to/lab-cockpit.md`. No bus reads, no vault, no DB.
- **Task class:** production UI + local-controller feature (Tier-A merge path; no Render deploy — local controller reinstall by lead).
- **Done rubric / done-state class:** DONE = all 6 fixes implemented, full cockpit test files green, codex gate PASS, branch pushed + completion report; NOT done at compile-clean (Lesson #8). Done-state: PR-ready (lead merges + resyncs static/controller + Director eyeball).
- **Gate plan:** independent codex gate (bus seat `codex`) on the branch before merge; reviewer instructions block below is binding on the gate.

## Baker Agent Vault Rails
Relevant: build-command-center (cockpit runbook `.claude/how-to/lab-cockpit.md`), verification-surfaces (post-merge resync + eyeball).
Ignore: bus-and-lanes, loop-runner, memory-and-lessons (no bus/schema/memory changes).

---

## Fix 1 (Director item 1): Context-window column header symmetric with cell content

### Problem
Header "Context window" is visually narrower than the bar+percent content beneath;
Director wants header start/finish to coincide with the row values' start/finish.

### Current State
Header row `index.html:59` and per-row grid cells in `cockpit.js` (ctx cell built
around `cockpit.js:671`, class names `ctxCell`/`ctxbar`/`ctxfill`/`ctxlbl`).
Grid column templates live in `scripts/cockpit_static/cockpit.css` — find the
`grid-template-columns` used by BOTH the header row and data rows.

### Engineering Craft Gates
- Diagnose: N/A — visual alignment, no bug loop.
- Prototype: N/A — deterministic CSS fix.
- TDD/verification: applies — extend `tests/test_cockpit_card_geometry.py` with a lock asserting header and row share one `grid-template-columns` definition (single source, no duplicated diverging template).

### Implementation
1. Make header and data rows consume the SAME grid template (one CSS custom property, e.g. `--agents-grid-cols`, applied to both) so widths cannot diverge.
2. Remove any per-header width/padding that shrinks the "Context window" span relative to the ctx cell; header text left edge must align with bar left edge, right edge with the percent label's right edge (same padding box).

### Key Constraints
Do not change bar semantics/colors (severity-by-value, COCKPIT_LAYOUT_REARRANGE_1) or the live-refresh logic just merged (@a39c0a57).

### Verification
Open http://127.0.0.1:7800/ — header "Context window" flush with bar+percent block at multiple window widths (resize check).

---

## Fix 2 (Director item 2): Move Inbox column between Context window and Session

### Problem
Director: "Inbox looks odd in this place" — wants order Agent/identity → Context window → Inbox → Session.

### Current State
Order today (index.html:59): control, Agent/identity, Inbox, Context window, Session. Data-row cell append order in cockpit.js mirrors it.

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A.
- TDD/verification: applies — geometry test asserts header label order `Agent / identity, Context window, Inbox, Session`.

### Implementation
Reorder header spans in index.html:59 AND the cell append order in the cockpit.js row builder AND the shared grid template columns (Fix 1's custom property). Inbox stays narrow (age-only badge, COCKPIT_INBOX_AGE_ONLY merged @a39c0a57 — do not regress age-only rendering).

---

## Fix 3 (Director item 4): Remove the Start button from cards

### Problem
Director: "I probably don't need the button start" — he starts seats from the terminal.

### Current State
`cockpit.js:698-700` renders `▶ Start` on driveable+down rows; `doStart` at `cockpit.js:1071`; toast "press Start first" at `cockpit.js:770`.

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A.
- TDD/verification: applies — geometry/behavior test asserts no `.rbtn.start` in rendered card DOM.

### Implementation
1. Remove the Start-button branch from the D3 control-cell render (down seats show their status chip instead — keep the "session down" visual state).
2. KEEP `doStart` + `POST /api/sessions/<slug>/start` endpoint intact (used by `cockpit_migrate.sh` path and possible re-add) — UI removal only.
3. Update the `cockpit.js:770` guard: GO on a down seat should toast "seat is down — start it in the terminal" (no longer references a Start button).

### Key Constraints
Do NOT remove the GO ⏎ button — Director uses it. Do not touch controller start endpoint.

---

## Fix 4 (Director item 5): Agent/identity header aligned with agent cells

### Problem
"Agent identity" header not aligned with the agent names beneath — must share left edge.

### Implementation
Same mechanism as Fix 1 — once header/rows share one grid template + padding box, assert the identity header span has identical `padding-left` to the identity cell. Include in the shared-template geometry test.

---

## Fix 5 (Director item 6): Remove the subtitle explanation line

### Problem
`index.html:44` "Every terminal, app seat, desk, and service in one scan surface." — takes space, adds nothing (Director ruling). Space reserved for future use.

### Implementation
Remove the `<p>` (keep the containing header block so the slot is easy to repopulate later; leave an HTML comment `<!-- reserved: future header line, same font slot -->`).

---

## Feature 6 (Director NEW ask): per-seat context-refresh button

### Problem
Director wants a one-click button on a seat card that clears the agent's context
("prompt /new … maybe the refresh button … anything that sends a message to the
terminal that would refresh the context") without going to the terminal.

### Design (locked by AH1)
- Claude Code's context-reset command is `/clear` — send that (NOT `/new`, which is not a Claude Code CLI command).
- New controller endpoint `POST /api/sessions/<slug>/refresh_context`, driveable seats only, 404 unknown slug, 409 if session down. Sends via the EXISTING literal+cr pattern (`cockpit_controller.py:1382-1390`): `send-keys -l "/clear"`, settle gap (reuse WAKE_COMPOSER_SUBMIT_FIX_1 gap constant), `send-keys Enter`. Audit-log the action like GO is logged.
- UI: small `⟳` button on the card control cell (up seats only), tooltip "Refresh context (/clear)". MUST be two-step: first click arms (button shows "sure?" state ~3s), second click fires — a context wipe is destructive-ish; no accidental single-click wipes. No browser confirm() dialog (breaks the same-origin iframe flow).
- Toast result "context refreshed → <slug>" / error passthrough.

### Engineering Craft Gates
- Diagnose: N/A (new feature).
- Prototype: N/A — interaction is simple; two-step arm pattern already exists in fleet UIs (GO precedent).
- TDD/verification: applies — controller test: refresh_context on up seat issues exactly [send-keys -l "/clear", settle, send-keys Enter] (mock tmux argv capture, follow existing send_go test pattern); down seat → 409; unknown → 404. UI: geometry test asserts ⟳ renders only on up+driveable rows.

### Key Constraints
- NEVER auto-fire on load or poll. Click-armed only.
- Do not send to app-claude (APP) seats — no tmux session.
- `/clear` goes to lead's own seat too — fine; Director's choice at click time.

---

## Gate-1 + Gate-2 reviewer instructions
Reviewers MUST load the URL referenced in the acceptance criteria (or `curl` it with
the exact query string the frontend will send) and confirm a non-error response.
Code-shape review (XSS-safe, syntactically valid HTML/JS) is necessary but NOT
sufficient. For this brief: exercise `POST /api/sessions/<slug>/refresh_context`
against an up seat (200 + argv proof), a down seat (409), an unknown slug (404),
and confirm the grid renders with the new column order + no Start button.

## Files Modified
- `scripts/cockpit_static/index.html` — header order, subtitle removal
- `scripts/cockpit_static/cockpit.js` — cell order, Start removal, ⟳ button, toast text
- `scripts/cockpit_static/cockpit.css` — shared grid template custom property
- `scripts/cockpit_controller.py` — refresh_context endpoint
- `tests/test_cockpit_card_geometry.py` — order/alignment/no-start/⟳ locks
- `tests/test_cockpit_controller.py` — refresh_context endpoint tests

## Do NOT Touch
- `scripts/cockpit_static/glance_state.js` — production Lab semantics, unrelated
- `cockpit_layout.json` — generated artifact, no regeneration needed (no membership change)
- Wake/nudge paths in `cockpit_controller.py` — reuse the literal+cr helper, do not modify it
- brisen-lab repo — separate brief

## Quality Checkpoints
1. All existing cockpit tests still pass (`pytest tests/test_cockpit_controller.py tests/test_cockpit_card_geometry.py`).
2. Header/cells share ONE grid template (grep proves single definition).
3. Start button gone; GO button intact; down-seat toast updated.
4. ⟳ two-step arm works; endpoint refuses down/unknown/app seats.
5. Static resync note in completion report: merge → rsync `scripts/cockpit_static/` → `~/Library/Application Support/baker/cockpit/static/`; controller change requires `bash scripts/install_cockpit_controller.sh` + launchd kickstart (lead runs this on merge).

## Verification SQL
N/A — no DB surface. Live verification = Director eyeball at http://127.0.0.1:7800/ and via Lab /v2 AGENTS embed.
