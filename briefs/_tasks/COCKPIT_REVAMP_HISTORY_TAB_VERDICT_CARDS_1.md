# BRIEF: COCKPIT_REVAMP_HISTORY_TAB_VERDICT_CARDS_1 — Revamp items 8+9: Task-history view + gate-verdict pass/fail cards

## Context

Director walkthrough 2026-07-19 ratified 9 cockpit revamp items. Items 8+9 are the
last two before Lab unification may start:

- **Item 8 — Task history tab:** job rows with status, seat, duration, outcome.
- **Item 9 — Gate verdicts as pass/fail cards.** Director ruling: "Part of the
  history tab build" — one arc, this brief.

Living registry: `COCKPIT_REVAMP_STATUS_20260719.html` (repo root) — lead updates
it on ship; you do NOT edit it.

**Hard sequencing constraint:** ctx-bars (item 1, HEAD `030dc07b`) is in codex
re-gate now and touches `cockpit_controller.py` + `cockpit.js`. Do NOT branch
until lead posts the ctx-bars merge notice on the bus. Branch from the
`origin/main` tip that CONTAINS the ctx-bars merge. If you start and main does
not contain `030dc07b` merged, STOP and ask lead on the bus.

### Surface contract (ui-surface-prebrief skill, V1)

1. **User action:** Director clicks a new "History" sidebar entry to read recent
   fleet jobs (bus dispatch threads) as rows and gate verdicts as pass/fail
   cards; clicking a row expands its message trail preview.
2. **Backend route:** does not exist yet — this brief creates
   `GET /api/history` in `scripts/cockpit_controller.py` (FastAPI, port 7800,
   basic-auth middleware already covers all non-static routes). Existing
   pattern to copy: `GET /api/messages/{slug}` at
   `scripts/cockpit_controller.py:1963` backed by `load_message_previews()`
   at `:1826-1888` (Lab fetch + 10s TTL cache).
3. **Endpoint contract (upstream, verified):**
   `GET https://brisen-lab.onrender.com/msg/{slug}?limit=N` with header
   `X-Terminal-Key: <seat key>`; message fields used: `id`, `thread_id`,
   `topic`, `kind`, `from_terminal`, `to_terminals`, `body`, `created_at`,
   `acknowledged_at`. Known upstream gotchas: `unacked=true` param is IGNORED
   (judge by `acknowledged_at`); transient `{"detail":"bus_busy_retry"}` — treat
   as cache-serve, never crash the endpoint.
4. **State location:** Lab bus messages (remote, already-contracted fetch path
   via seat terminal keys the controller resolves today) — no new local
   persistence. UI repo = this repo (`bm-aihead1`), cockpit static.
5. **UI repo (= state-contract repo):** `bm-aihead1` cockpit — surface: local
   cockpit split-view shell at `http://127.0.0.1:7800/`.
6. **Director surface preference:** ratified 2026-07-19 walkthrough — "Task
   history tab" in the fleet cockpit. No re-ask needed.
7. **Gate-1+2 reviewer instruction:** Reviewers MUST curl
   `http://127.0.0.1:7800/api/history?limit=20` with basic auth and confirm a
   non-error JSON response with ≥1 job row, and load the History view in a
   browser. Code-shape review is necessary but NOT sufficient.

## Estimated time: ~4-6h
## Complexity: Medium
## Prerequisites: ctx-bars merge on main (lead bus notice); tmux/ttyd fleet local.

## Harness V2
- **Context Contract:** builder loads ONLY this brief + the anchor files it
  names (controller, cockpit_static, the two test files) — no vault libraries,
  no matter context.
- **Task class:** feature (local cockpit UI + one new read-only endpoint;
  no production Baker/Render surface).
- **Done rubric / done-state class:** machine-checkable — full cockpit pytest
  green incl. untouched no-blur AC + new pure-fn/route tests; live curl of
  `/api/history` returns job rows; POST_DEPLOY_AC_VERDICT posted on the bus
  before "shipped" (post-deploy-ac-bus-gate).
- **Gate plan:** independent codex gate on the exact pushed HEAD, routed via
  lead (no self-gating); lead runs merge, deploy, live AC.
  [2026-07-20 close-out: executed as specified — codex PASS-WITH-NOTES #14069
  @8b3616bf, merged @a37f8bcb, live AC 20 job rows, verdict #14073.]

## Baker Agent Vault Rails
Relevant: build-command-center (cockpit is a build surface), verification-surfaces
(codex gate on exact HEAD). Ignore: standing-contract, bus-and-lanes daemon code,
loop-runner, memory-and-lessons (no changes there).

---

## Feature 1 (item 8): `GET /api/history` + History sidebar view

### Problem
Cockpit shows live seat state only. No record of what jobs ran, who ran them,
how long they took, or how they ended. Director wants job rows: status, seat,
duration, outcome.

### Current State
- Controller: FastAPI, `scripts/cockpit_controller.py` (~2,444 lines). Routes:
  `/api/agents` (:1904), `/api/messages/{slug}` (:1963), session start/go/wake,
  ttyd websocket proxy. No history/job concept anywhere.
- Frontend: `scripts/cockpit_static/` — `index.html`, `cockpit.js` (IIFE,
  `boot()` ~:810), `cockpit.css`, `glance_state.js` (pure resolver),
  `cockpit_layout.json`. Sidebar built by `buildSidebar()` (~:630-720) with 8
  entries (ACTIVE, ALL, Pilots, Control Tower, Engineering, Support,
  Legal/Finance, Interns); poll loop `poll()` (~:202) hits `/api/agents` every
  4s (`POLL_MS = 4000`, :19).

### Engineering Craft Gates
- **Diagnose: N/A** — new feature, no bug to reproduce.
- **Prototype: N/A** — data shape is dictated by the Lab message schema already
  consumed by `load_message_previews()`; UI pattern copies the existing
  split-view/sidebar structure. No open design question.
- **TDD: applies.** Public seam #1: `build_history_jobs(messages: list) -> list`
  — a PURE function (module-level in `cockpit_controller.py`, no I/O) that
  groups raw message dicts into job rows. Write its tests FIRST from fixture
  message lists (below). Public seam #2: `GET /api/history` route test with the
  Lab fetch monkeypatched, following the style of
  `test_api_agents_requires_auth_and_maps_only_pinned_glance_fields()` in
  `tests/test_cockpit_controller.py`.

### Implementation

**1a. Pure grouping function** (controller, near `trim_message_preview` ~:250):

```python
VERDICT_PASS_RE = re.compile(r"\b(PASS(?:-WITH-NOTE(?:S)?)?|APPROVED?|LGTM)\b")
VERDICT_FAIL_RE = re.compile(r"\b(FAIL(?:ED)?|REQUEST[_ ]CHANGES|REJECTED|BLOCKED)\b")

def classify_verdict(body: str) -> str | None:
    """First 400 chars only; PASS wins only if no FAIL marker precedes it."""
    head = (body or "")[:400].upper()
    fail = VERDICT_FAIL_RE.search(head)
    ok = VERDICT_PASS_RE.search(head)
    if fail and (not ok or fail.start() < ok.start()):
        return "fail"
    if ok:
        return "pass"
    return None

def build_history_jobs(messages: list) -> list:
    """Group bus messages into job rows, newest first.

    Group key: thread_id if set, else (topic or 'untopiced-<id>').
    Row: {key, topic, seat (from_terminal of the LATEST non-lead msg, else
    lead), started_at (earliest created_at), ended_at (created_at of the
    latest verdict-classified msg, else None), duration_sec (ended-started,
    else None), status ('done' if verdict found else 'in-flight'),
    outcome ('pass'|'fail'|None), msg_ids (list), last_preview (≤160 chars)}.
    """
```

Implement exactly that contract. Sort rows by max `created_at` desc. Cap at
`limit`. Malformed rows (missing `created_at`) are skipped, never raised.

**1b. Route** (after `/api/messages/{slug}` ~:1963):

```python
@app.get("/api/history")
async def api_history(limit: int = 30):
    # Fetch lead's message stream from Lab (lead receives STARTED/verdict/
    # report traffic for every dispatch arc). Reuse the existing Lab-fetch +
    # terminal-key helper used by load_message_previews(), slug="lead",
    # upstream limit=min(200, limit*6). 10s TTL cache like message previews.
    # On Lab error/bus_busy: serve last cached result; if no cache, return
    # {"jobs": [], "stale": True} — NEVER 500.
```

All Lab calls wrapped in try/except (repo hard rule). No new persistence, no
Postgres.

**1c. Frontend — History view:**
- Add 9th sidebar entry `History` in `buildSidebar()` (`cockpit.js`).
- Selecting it swaps the middle column from the grid to a history list (same
  container, new render fn `renderHistory(jobs)`); grid views unaffected.
- Fetch `/api/history?limit=30` on view-enter and every 15s while the view is
  active (do NOT add it to the 4s `poll()` loop).
- Row layout: `[outcome dot] topic — seat — status — duration — age`, newest
  first. Duration formatted `Xm Ys`; in-flight rows show elapsed-since-start.
- Row click toggles an inline expansion showing `last_preview` + msg ids.
- Escape all message-derived text via `document.createTextNode` /
  `textContent` — NO innerHTML with bus content (XSS; helper `_escHtml` does
  NOT exist, don't invent it).
- CSS in `cockpit.css`; **no `backdrop-filter` anywhere** — hard AC test
  `test_grid_never_blurs_behind_an_open_card` (tests/test_cockpit_view_filter.py)
  must stay green.
- Bump the static cache-bust `?v=6 → ?v=7` in `index.html` for changed assets.

### Key Constraints
- Do NOT touch `/api/agents`, wake logic, `glance_state.js` resolver logic,
  D9 message panel, ttyd proxy.
- Do NOT add per-seat Lab fan-out (28 seats × fetch = rate-limit risk); lead
  stream only, single upstream call per refresh.
- Do NOT regenerate `cockpit_layout.json` — no card changes in this arc.

### Verification
- `pytest tests/ -k cockpit` — full suite green (232+ baseline, plus yours).
- Live: `curl -u <basic-auth> 'http://127.0.0.1:7800/api/history?limit=20'` →
  JSON with ≥1 job row naming a real recent topic (e.g. the ctx-bars arc).
- Browser: History entry renders rows; grid views unchanged; no blur.

---

## Feature 2 (item 9): Gate-verdict pass/fail cards

### Problem
Gate verdicts (codex PASS/FAIL) are buried in bus bodies. Director wants them
as pass/fail cards.

### Current State
No verdict concept exists ("verdict" greps zero hits in cockpit code).

### Engineering Craft Gates
- **Diagnose / Prototype: N/A** — same rationale as Feature 1.
- **TDD: applies** — `classify_verdict()` unit tests first: PASS,
  PASS-WITH-NOTE, REQUEST CHANGES, FAIL, "FAIL … then PASS" (fail wins),
  no-marker → None, empty/None body → None.

### Implementation
- Top strip of the History view: horizontal cards for the most recent ≤8 rows
  with `outcome != None`. Card: green `PASS` / red `FAIL` badge, topic, seat,
  ended-at age. Click scrolls to / expands the matching history row.
- Pure derivation from Feature 1's job rows — no extra endpoint, no extra
  fetch, no new state.

### Key Constraints
- Verdict classification lives ONLY in `classify_verdict()` (backend) — the
  frontend renders `outcome`, never re-parses bodies.
- Colors follow the ratified item-3 state-color language already in
  `cockpit.css` — reuse existing green/red tokens, don't invent new ones.

### Verification
- Unit tests above green.
- Browser: after any codex verdict lands on the bus, card appears within one
  15s refresh with correct pass/fail color.

---

## Files Modified
- `scripts/cockpit_controller.py` — `classify_verdict`, `build_history_jobs`, `GET /api/history`
- `scripts/cockpit_static/cockpit.js` — sidebar entry, `renderHistory`, verdict strip
- `scripts/cockpit_static/cockpit.css` — history + card styles
- `scripts/cockpit_static/index.html` — container hook + `?v=7` cache bust
- `tests/test_cockpit_history.py` — NEW: pure-fn + route + static-shape tests

## Do NOT Touch
- `scripts/generate_cockpit_layout.py` / `cockpit_layout.json` — no card changes
- `scripts/cockpit_static/glance_state.js` — resolver frozen this arc
- Wake/dedupe/audit code paths in the controller — live and gated separately
- `COCKPIT_REVAMP_STATUS_20260719.html` — lead-owned registry
- `tests/test_cockpit_view_filter.py` — must pass unmodified

## Gate-1 + Gate-2 reviewer instructions
Reviewers MUST curl `/api/history` with the exact query string the frontend
sends and confirm a non-error response, and load the History view live. Code-
shape review (XSS-safe, syntactically valid) is necessary but NOT sufficient.

## Quality Checkpoints
1. Branch only after lead's ctx-bars merge notice; base contains `030dc07b`.
2. Full cockpit pytest green, including untouched no-blur AC test.
3. `/api/history` never 500s — Lab-down path returns `{"jobs": [], "stale": true}`.
4. All bus-derived text rendered via textContent (XSS check).
5. Cache bust bumped; report exact pushed HEAD on the bus for the codex gate
   (gate goes to the `codex` bus seat via lead — do not self-gate).
6. Do NOT rsync App Support static or restart the controller — lead runs the
   deploy steps at merge time.

## Verification SQL
N/A — no database in this arc (controller is stateless; upstream is the Lab
HTTP API).
