# BRIEF: ARRIVALS_BOARD_LIVE_1 — Wire the ratified Brisen Air ARRIVALS board to real flight state

## Context
Director ratified (2026-07-08, cowork-ah1 session) the Brisen Air ARRIVALS board UI
(`baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/arrivals-board-v6.html`)
and a 7-status flight vocabulary. Today the board is hand-seeded HTML. This brief wires it
to real state served from baker-master, same-origin, zero LLM calls (deterministic surface).

This is the "Control Tower roll-up" that `orchestrator/flight_snapshot.py` explicitly
deferred (D-29 note in `render_index_html`) and the first slice of the flight lifecycle
store (D-23). The read-only snapshot contract of `flight_snapshot.py` is NOT touched —
the board gets its own small pilot-written state table.

Status vocabulary (Director-ratified, exact strings, lifecycle order):
`CHECK-IN`, `ON TIME`, `HOLDING`, `DELAYED`, `FINAL APPROACH`, `LANDED`, `DIVERTED`.
Semantics: ARRIVES = next decisive event date (milestone / decision / landing).
FINAL APPROACH = decisive event ≤72h with a Director decision open. DELAYED must be
machine-derived when the arrives date passes — a pilot can never hide a slip.

## Estimated time: ~4-5h
## Complexity: Medium
## Prerequisites: none (project_registry + verify_api_key already live)

## Baker Agent Vault Rails
Relevant: verification-surfaces (new Director surface + probes), standing-contract
(two-surface seat rule extends: pilot upserts board state in the same ingest pass).
Ignored: bus-and-lanes (no bus changes), loop-runner, skills-and-playbooks (process-side
fold is lead's canon lane, not this brief), memory-and-lessons (Step 6 only).

## Harness V2

### Context Contract
Everything the builder needs is in this file — do not consult chat history or other
sessions. Verified-in-repo facts relied on: `verify_api_key` (`outputs/dashboard.py:188`),
`get_conn` (`kbl/db`), `project_registry` columns (`kbl/project_registry_store.py:59`),
no existing `/arrivals` route, `/flights` pattern at `outputs/dashboard.py:8353`.
Builder MUST verify in-repo before use (explicitly unverified here): the canonical
baker_actions audit helper name, template-loading pattern, import block for
`Body`/`HTTPException`, live-PG test fixture idiom. Frozen input: ratified template at
`baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/arrivals-board-v6.html`.

### Task class
Production implementation — new Director surface + DB migration + one authed write
endpoint. Merge tier: **Tier A** (new external write path) → /security-review mandatory
(Lesson #52), AH2 static review, full pytest + `bash scripts/check_singletons.sh`.

### Done rubric (done-state class: DEPLOYED_VERIFIED)
DONE only when, live on Render: (1) `GET /arrivals` returns 200 and one row per active
registry project; (2) `POST /api/flight-board/X` → 401/403 without key, 422 on bad
status, row upserted on good payload; (3) seeded past `arrives_on` + `ON TIME` renders
DELAYED on the live board; (4) full pytest green including `tests/test_arrivals_board.py`;
(5) all 7 Quality Checkpoints below pass. Merged-but-unverified is NOT done (Lesson #8).

### Gate plan
Pre-merge: AH2 static review → /security-review (Tier A) → pytest + singleton guard.
Post-deploy: live AC probes above → structured `POST_DEPLOY_AC_VERDICT` posted to the
bus per `post-deploy-ac-bus-gate` skill. Report routes to `lead`
(`dispatched_by: lead`, #7251); cowork-ah1 CC'd on the verdict topic `baker-os-v2/arrivals-board`.

### Surface contract
- Surface: `GET /arrivals` on baker-master (same origin as all Baker APIs; Director bookmarks it).
- Register: EXACT ratified v6 look — copy `arrivals-board-v6.html` CSS/flap-JS verbatim into a
  repo template; only the `<tbody>` rows become dynamic. No layout, palette, tile, or column
  changes. Columns: ARRIVES | FLIGHT NO | AIRLINE | DESTINATION | DESK | STATUS | UPDATED.
- Dark default + VIEW light toggle + REFRESH button + live clock: keep as-is from v6.
- Row click → `/flights/{project_code}` (existing same-origin snapshot page) until the
  Publisher pipeline serves Pattern-E cockpits; `cockpit_url` column exists for that later swap.
- Auto-refresh: `<meta http-equiv="refresh" content="120">` (flap animation replay is desired).
- Mobile: table scrolls horizontally inside the page (`overflow-x:auto` wrapper div — the ONE
  permitted addition to the template); no reflow of the one-line rows.

---

## Fix 1: Migration — `flight_board_state` (pilot-written lifecycle store, v1 slice)

### Problem
No authoritative flight status/arrives store exists (D-23 gap). Board needs one row per flight.

### Current State
`project_registry` (see `kbl/project_registry_store.py:59`) holds
`project_number TEXT UNIQUE, matter_slug, desk_owner, clickup_list_id, status`.
Airport evidence tables exist (`migrations/20260629_airport_tickets.sql`,
`20260701b_airport_outbound_events.sql`) but carry no ratified status vocabulary.

### Engineering Craft Gates
- Diagnose: N/A — new feature, no bug loop.
- Prototype: N/A — UI prototype already Director-ratified (arrivals-board v1→v6 iteration).
- TDD: applies — migration asserted via `information_schema.columns` in test (Fix 4).

### Implementation
New file `migrations/20260708a_flight_board_state.sql`:

```sql
-- ARRIVALS_BOARD_LIVE_1: pilot-written flight lifecycle state (D-23 first slice).
-- One row per registered flight. Pilots upsert in the same ingest pass as the
-- dashboard + ClickUp stamp (two-surface seat rule, Director-ratified 2026-07-08).
CREATE TABLE IF NOT EXISTS flight_board_state (
    project_code   TEXT PRIMARY KEY,
    status         TEXT NOT NULL DEFAULT 'CHECK-IN'
                   CHECK (status IN ('CHECK-IN','ON TIME','HOLDING','DELAYED',
                                     'FINAL APPROACH','LANDED','DIVERTED')),
    arrives_on     DATE,
    arrives_label  TEXT,
    airline        TEXT,
    destination    TEXT,
    cockpit_url    TEXT,
    page_version   TEXT,
    updated_by     TEXT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Key Constraints
- Do NOT edit any applied migration. New file only.
- No FK to project_registry (it is created lazily by its store; a hard FK would order-couple
  deploys). Join at read time.

### Verification
```sql
SELECT column_name FROM information_schema.columns
 WHERE table_name = 'flight_board_state' LIMIT 20;
```

---

## Fix 2: Pilot write path — `POST /api/flight-board/{project_code}`

### Problem
Pilots (desks) need one validated, audited way to set status/arrives. No raw_write free-typing.

### Current State
Write guard exists: `verify_api_key` at `outputs/dashboard.py:188`
(`async def verify_api_key(x_baker_key: str = Header(None, alias="X-Baker-Key"))`).

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A.
- TDD: applies — first test: POST with bad status → 422; good status → row upserted.

### Implementation
New module `orchestrator/arrivals_board.py` (keep dashboard.py additions thin):

```python
"""ARRIVALS_BOARD_LIVE_1 — flight board state store + ARRIVALS board render.

Pilot-written lifecycle state (D-23 slice 1) + Director ARRIVALS surface (D-29).
Render path is read-only; the ONLY write is upsert_board_state(), called from the
authed endpoint. Status vocabulary is Director-ratified 2026-07-08 — do not extend
without a ratified change.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

import psycopg2.extras

from kbl.db import get_conn

logger = logging.getLogger(__name__)

STATUSES = ["CHECK-IN", "ON TIME", "HOLDING", "DELAYED",
            "FINAL APPROACH", "LANDED", "DIVERTED"]
# Statuses the machine may display INSTEAD of the pilot's value when the
# arrives date has passed (a pilot can never hide a slip).
_OVERLAY_EXEMPT = {"LANDED", "DIVERTED", "DELAYED"}


def upsert_board_state(project_code: str, fields: dict, updated_by: str) -> dict:
    """Validated upsert of one flight's board row. Raises ValueError on bad input."""
    status = str(fields.get("status", "")).strip().upper()
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    arrives_on = fields.get("arrives_on")  # 'YYYY-MM-DD' or None
    if arrives_on is not None:
        arrives_on = date.fromisoformat(str(arrives_on))  # ValueError if malformed
    row = None
    with get_conn() as conn:
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO flight_board_state
                        (project_code, status, arrives_on, arrives_label, airline,
                         destination, cockpit_url, page_version, updated_by, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                    ON CONFLICT (project_code) DO UPDATE SET
                        status = EXCLUDED.status,
                        arrives_on = EXCLUDED.arrives_on,
                        arrives_label = COALESCE(EXCLUDED.arrives_label, flight_board_state.arrives_label),
                        airline = COALESCE(EXCLUDED.airline, flight_board_state.airline),
                        destination = COALESCE(EXCLUDED.destination, flight_board_state.destination),
                        cockpit_url = COALESCE(EXCLUDED.cockpit_url, flight_board_state.cockpit_url),
                        page_version = COALESCE(EXCLUDED.page_version, flight_board_state.page_version),
                        updated_by = EXCLUDED.updated_by,
                        updated_at = now()
                    RETURNING project_code, status, arrives_on, updated_by, updated_at
                    """,
                    (project_code.strip().upper(), status, arrives_on,
                     fields.get("arrives_label"), fields.get("airline"),
                     fields.get("destination"), fields.get("cockpit_url"),
                     fields.get("page_version"), updated_by),
                )
                row = dict(cur.fetchone())
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return row
```

In `outputs/dashboard.py` (check `grep -n "api/flight-board" outputs/dashboard.py` returns
nothing before adding — FastAPI first-match shadowing):

```python
@app.post("/api/flight-board/{project_code}", dependencies=[Depends(verify_api_key)])
async def flight_board_upsert(project_code: str, payload: dict = Body(...)):
    """ARRIVALS_BOARD_LIVE_1: pilot upsert of flight board state (audited)."""
    from orchestrator import arrivals_board
    try:
        row = arrivals_board.upsert_board_state(
            project_code, payload, updated_by=str(payload.get("updated_by") or "unknown"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        log_baker_action(action_type="flight_board_upsert", target=project_code,
                         details=row)
    except Exception:
        logger.warning("flight_board_upsert audit log failed", exc_info=True)
    return {"ok": True, "state": row}
```

**Builder MUST verify** the audit helper name before using it: `grep -n "def log_baker_action\|baker_actions" outputs/dashboard.py | head`. If the canonical audit write is a different helper (e.g. an insert into `baker_actions` via a store class), use that exact call instead — audit of ALL Baker writes is a repo invariant, but the helper name here is UNVERIFIED; do not invent one. Same for `Body` / `HTTPException` imports — check the file's import block (missing-import anti-pattern).

### Key Constraints
- Auth: `Depends(verify_api_key)` — pilots hold X-Baker-Key already. No new key tier.
- No bus posting, no ClickUp writes, no LLM calls anywhere in this brief.

### Verification
```sql
SELECT project_code, status, arrives_on, updated_by, updated_at
  FROM flight_board_state ORDER BY updated_at DESC LIMIT 10;
```

---

## Fix 3: Director surface — `GET /arrivals` (+ `GET /api/arrivals.json`)

### Problem
Board must render the ratified v6 register from live rows, same origin, no CORS, no key
in the page.

### Current State
No `/arrivals` route exists (`grep -n "arrivals" outputs/dashboard.py` → none, verified
2026-07-08). Pattern to follow: `/flights` index at `outputs/dashboard.py:8353-8369`
(HTMLResponse, try/except, degrade to empty).

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A (v6 IS the ratified prototype).
- TDD: applies — first test renders board HTML from fixture rows and asserts machine
  overlay + PENDING synthesis (see Fix 4).

### Implementation
1. Copy the ratified template into the repo:
   `cp baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/arrivals-board-v6.html outputs/templates/arrivals_board_template.html`
   Then in the copy: replace the four hardcoded `<tr>` blocks with a single `__ROWS__`
   token; replace `BOARD V6 · AS OF 8 JUL 2026` with `__STAMP__`; add
   `<meta http-equiv="refresh" content="120">` and the `overflow-x:auto` wrapper. NOTHING
   else changes. (If `outputs/templates/` does not exist, create it; check how other
   templates are loaded first: `grep -rn "templates" outputs/dashboard.py | head`.)
2. In `orchestrator/arrivals_board.py` add the read + render half:

```python
def list_board_rows() -> list[dict]:
    """All active flights: registry LEFT JOIN board state. Read-only, bounded, degrades."""
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT r.project_number, r.desk_owner, r.matter_slug,
                           s.status, s.arrives_on, s.arrives_label, s.airline,
                           s.destination, s.cockpit_url, s.page_version,
                           s.updated_by, s.updated_at
                      FROM project_registry r
                      LEFT JOIN flight_board_state s ON s.project_code = r.project_number
                     WHERE r.status = 'active'
                     ORDER BY r.project_number
                     LIMIT 200
                    """,
                    (),
                )
                return [dict(x) for x in cur.fetchall()]
    except Exception:
        logger.warning("list_board_rows failed", exc_info=True)
        return []


def effective_status(row: dict, today: Optional[date] = None) -> str:
    """Machine overlay: a past arrives date forces DELAYED unless landed/diverted.
    A registry row with no board state is CHECK-IN (counter open, no flight yet)."""
    status = (row.get("status") or "CHECK-IN").upper()
    today = today or datetime.now(timezone.utc).date()
    arrives = row.get("arrives_on")
    if arrives and status not in _OVERLAY_EXEMPT and arrives < today:
        return "DELAYED"
    return status
```

3. Row → flap-cell HTML: each cell rendered as the v6 `<div class="flap" data-flap="...">`
   markup (the template's own JS builds the tiles — server only supplies `data-flap`
   strings, html-escaped via `html.escape`). Rules:
   - ARRIVES: `arrives_on` as `10 JUL` format, else `—`.
   - FLIGHT NO: `project_number`; rows with no board state render `PENDING` + class
     `pending`, not clickable.
   - AIRLINE / DESTINATION: from board state; fall back `matter_slug` upper / `—`.
   - DESK: `desk_owner` upper.
   - STATUS: `effective_status()`; `FINAL APPROACH` gets `data-cls="inv"` + `blinkgrp`;
     `ON TIME` gets `data-cls="grn"`; others default amber.
   - UPDATED: `updated_at` as `8 JUL 10:49`, else `—`.
   - LANDED rows: drop from board once `updated_at` older than 7 days (filter in render).
   - Row click: `cockpit_url` if set else `/flights/{project_number}`.
4. Endpoints in `outputs/dashboard.py` (public read, mirror `/flights` — no key, no writes):

```python
@app.get("/arrivals", include_in_schema=False, response_class=HTMLResponse)
async def arrivals_board_page(request: Request):
    """ARRIVALS_BOARD_LIVE_1: Director ARRIVALS board (ratified v6 register)."""
    from orchestrator import arrivals_board
    try:
        rows = arrivals_board.list_board_rows()
    except Exception:
        logger.exception("arrivals_board_page failed")
        rows = []
    return HTMLResponse(arrivals_board.render_board_html(rows))


@app.get("/api/arrivals.json", include_in_schema=False)
async def arrivals_board_json():
    """Same rows as JSON — health/monitoring + future clients."""
    from orchestrator import arrivals_board
    rows = arrivals_board.list_board_rows()
    return {"count": len(rows),
            "rows": [{**r, "effective_status": arrivals_board.effective_status(r)}
                     for r in rows]}
```

### Key Constraints
- Zero writes on the render path (mirror flight_snapshot discipline).
- Do NOT modify `/flights` or `orchestrator/flight_snapshot.py`.
- All datetimes render in CET for the Director (match cockpit convention); timezone via
  `zoneinfo.ZoneInfo("Europe/Zurich")`, not a hand-rolled offset.
- Template fidelity: v6 CSS/JS byte-identical except `__ROWS__`, `__STAMP__`, meta-refresh,
  scroll wrapper.

### Verification
- Local: `python outputs/dashboard.py` → open `http://localhost:8080/arrivals` — board
  renders with real registry rows (BB-AUK-001 expected PENDING until a pilot posts state).
- `curl -s http://localhost:8080/api/arrivals.json | python3 -m json.tool` — rows + count.

---

## Fix 4: Tests (write FIRST for the behavior seams)

New file `tests/test_arrivals_board.py`:
1. `effective_status`: past `arrives_on` + `ON TIME` → `DELAYED`; past + `LANDED` stays
   `LANDED`; no state → `CHECK-IN`; today's date not delayed.
2. `upsert_board_state`: bad status raises ValueError; good payload returns row
   (live-PG test — follow existing `TEST_DATABASE_URL` auto-skip pattern; see other
   live-PG tests for the fixture idiom before writing).
3. `render_board_html`: fixture rows → HTML contains `data-flap="BB-AUK-001"`,
   `FINAL APPROACH` row carries `blinkgrp`, stateless row renders `PENDING`, LANDED row
   older than 7 days absent.
4. Endpoint smoke: `POST /api/flight-board/X` without key → 401/403; with key + bad
   status → 422.

Run: `pytest tests/test_arrivals_board.py -v` then full `pytest`.

---

## Files Modified
- `migrations/20260708a_flight_board_state.sql` — NEW
- `orchestrator/arrivals_board.py` — NEW
- `outputs/templates/arrivals_board_template.html` — NEW (copied from ratified v6)
- `outputs/dashboard.py` — 3 endpoints added (guarded, thin)
- `tests/test_arrivals_board.py` — NEW

## Do NOT Touch
- `orchestrator/flight_snapshot.py` — read-only snapshot contract (D-23/D-29) stays intact.
- `/flights` routes — existing surface, still linked from board rows.
- `kbl/project_registry_store.py` — registry semantics unchanged.
- Any applied migration.
- `baker-vault/…/arrivals-board-v6.html` — ratified original stays frozen in vault.

## Quality Checkpoints
1. `/arrivals` loads on Render after deploy; board shows every active registry flight.
2. Row with no pilot state shows PENDING / CHECK-IN — never invented status or date.
3. Pilot POST flips the row within one refresh (≤120s).
4. Past-date + ON TIME renders DELAYED (machine overlay proven live, not just in test).
5. Dark/light toggle + flap animation + one-line rows identical to ratified v6.
6. iPhone check: board scrolls horizontally, no wrapped rows.
7. `bash scripts/check_singletons.sh` passes; full `pytest` passes; compile-clean ≠ done —
   exercise the live flow (Lesson #8).

## Verification SQL
```sql
-- After pilots seed BB-AUK-001 + AO-OSK-001:
SELECT project_code, status, arrives_on, page_version, updated_by, updated_at
  FROM flight_board_state ORDER BY project_code LIMIT 10;
```

## Out of scope (explicit)
- Publisher-served Pattern-E cockpit pages (cockpit_url swap comes with that program).
- Bus/done-gate enforcement of the seat rule (lead's canon lane, #7150 thread).
- Any LLM-derived status inference — statuses are pilot-set + machine-overlaid only.
