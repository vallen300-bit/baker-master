# BRIEF: COCKPIT_REFERENCE_DESK_1 — Shrink old cockpit to reference desk + honest staleness

## Context

Director ratified 2026-07-08 (cowork-ah1 session, audit artifact:
`~/Vallen Dropbox/Dimitry vallen/_01_INBOX_FROM_CLAUDE/2026-07-08-ah1-baker-cockpit-audit.html`):
the arrivals board is the daily front door; the old CEO cockpit SPA at `baker-master.onrender.com/`
becomes the **reference desk** — search, documents, question desks, matters, AO, engine-room views.
Everything else is retired from the nav. Root defect to fix: the health surface shows "healthy" for
sentinels that silently stopped (browser last success 2026-04-27, calendar 2026-05-29) because status
is derived ONLY from `consecutive_failures` (`triggers/sentinel_health.py` `_status_for_failures`,
~line 116). Silence must look different from health.

Audit evidence (all pulled live 2026-07-08 18:30–18:45 UTC):
- `/api/dashboard/morning-brief`: 12.0s response; `fire_count: 436` vs `critical_items: 1`; `narrative: ""`.
- 660 `alerts` rows status='pending' (16,356 dismissed); 13 `deadlines` status='active' already past due.
- Empty-but-200 endpoints: `/api/ideas` `[]`, `/api/trips` `{"trips":[]}`, `/api/networking/contacts` 0,
  `/api/rss/articles` 0 (last article 2026-05-01), people issues last update 2026-04-07, cortex last cycle 2026-05-20.

## Estimated time: ~5h
## Complexity: Medium
## Prerequisites: none (single deployable; no migration files needed)

## Baker Agent Vault Rails
Relevant: build-command-center (Harness V2 brief discipline), verification-surfaces (post-deploy AC verdict).
Ignored intentionally: bus-and-lanes (no bus code touched), loop-runner, memory-and-lessons (lesson append only if something goes wrong).

### Surface contract
- **Surface:** old CEO cockpit SPA only — `outputs/static/index.html`, `outputs/static/app.js`,
  `outputs/static/style.css`, plus its backing endpoints in `outputs/dashboard.py` and
  `triggers/sentinel_health.py`.
- **Register:** existing cockpit visual register. This brief is SUBTRACTION + honesty badges only —
  no redesign, no new panels, no color-system changes.
- **Keep in nav:** Brisen Lab ↗, Projects / Operations / Inbox (matters sections), AO Dashboard,
  Ask Baker, Ask Specialist, Client PM, Search, Documents, Templates Gallery ↗, Dossiers,
  Work in progress, AI Hotel ↗, AI Hotel Lab ↗, System, Baker Data, KBL Pipeline.
- **Remove from nav:** Ideas section, Media section, People section, Travel tab, Presentations tab.
- **Add to nav:** one top-level link `ARRIVALS BOARD ↗` → `/arrivals` (placed directly under the
  Brisen Lab link; plain `<a>`, same styling class as the Brisen Lab external link).
- **Landing (Morning Brief) stays** but slimmed per Fix 3/4. Mobile surface (`mobile.html`/`mobile.js`)
  untouched this pass.
- **New status vocabulary:** `stale` (red/amber pill, text "no data since <date>") joins
  healthy/degraded/down/unknown/disabled on the System console and health strip.

---

## Fix 1: Nav shrink (frontend subtraction)

### Problem
Five nav surfaces render empty or frozen data and erode trust (see Context evidence).

### Current State
- Sidebar sections + tabs in `outputs/static/index.html` (~lines 36–160): grep anchors
  `id="navIdeas"` / `Ideas`, `id="navMedia"` / `Media`, `id="navPeople"` / `People`,
  `data-tab="travel"`, `data-tab="presentations"`.
- Loaders in `outputs/static/app.js`: `loadIdeas` (~8600), media category counts (~2208),
  people issues summary (~2246), `loadTravel` (~7017), presentations manifest fetch (~9474).
  Line numbers are approximate — grep for the function names.

### Engineering Craft Gates
- Diagnose: N/A — subtraction, no bug being chased.
- Prototype: N/A — no design uncertainty; Director ratified the keep/remove list.
- TDD/verification: applies — DOM-level check post-deploy (see Verification); no unit seam for static HTML.

### Implementation
1. In `index.html`: delete (do not just `display:none`) the five nav blocks listed in the Surface
   contract. Leave the underlying view `<div>`s and app.js view code in place — views stay reachable
   by deep link, they just lose their buttons. Do NOT delete `TAB_VIEW_MAP` entries.
2. In `app.js`: guard the five loaders so no dead fetches fire on boot. Pattern: at the top of each
   loader `if (!document.querySelector('[data-tab="travel"]')) return;` (adjust selector per section).
   The dynamic-section builders (Ideas/Media/People) are called from the sidebar populate path after
   `matters-summary` — remove those three call sites instead of guarding inside, whichever is smaller.
3. Add the `ARRIVALS BOARD ↗` link (Surface contract). `/arrivals` handles its own PIN — no key logic
   in the SPA.
4. Landing page: remove the Cortex feed card markup (`index.html` ~266–282) and its loader call —
   last cycle 2026-05-20; it returns when Cortex trial data justifies it.
5. Cache bust: bump BOTH `style.css?v=84`→`?v=85` and `app.js?v=132`→`?v=133` in `index.html`
   (iOS PWA requirement).

### Key Constraints
- Do NOT touch `orchestrator/` (arrivals board, flight dashboards, cockpit serve layer).
- Do NOT remove backend endpoints for retired sections — read surface only shrinks; APIs stay
  (MCP + other consumers may use them).
- Do NOT touch the three orphaned views (Fires/Tags/Browser monitor) — already unreachable; leave as-is.

### Verification
After deploy: `curl -s https://baker-master.onrender.com/ | grep -c 'data-tab="travel"'` → 0;
same for presentations; `grep -c 'ARRIVALS'` → ≥1. Browser check: sidebar shows no Ideas/Media/People/
Travel/Presentations; no console errors on load (F12).

---

## Fix 2: Honest staleness on the health surface (root-cause fix)

### Problem
`sentinel_health.status` is written from `consecutive_failures` only. A sentinel that silently stops
never fails → stays "healthy" forever. Browser: last success 2026-04-27, calendar: 2026-05-29 — both
green today. This is the single defect that makes the whole dashboard untrustworthy.

### Current State
- `triggers/sentinel_health.py::_status_for_failures` (~116) — failures-only mapping.
- `get_all_sentinel_health()` (~632) — reads `sentinel_health` rows, applies `_apply_retirement`
  (read-time transform, ~52) which normalizes `RETIRED_SOURCES` to `disabled`. This read-time-overlay
  pattern is the one to extend.
- A watermark staleness checker already exists (`check_stale_watermarks`, ~523, with `_WATERMARK_MAX_AGE`
  per-source max ages) but only fires alerts — it never changes displayed status.
- `outputs/dashboard.py::get_sentinel_health` (~4471) builds `summary = {"healthy":0,"degraded":0,"down":0,"unknown":0}`.

### Engineering Craft Gates
- Diagnose: applies — feedback loop = unit test on the overlay function with a synthetic old
  `last_success_at`; live probe = `/api/sentinel-health` must show browser/calendar as `stale`.
- Prototype: N/A — pattern already exists in the codebase (`_apply_retirement`).
- TDD/verification: applies — write the overlay unit test FIRST (new `tests/test_sentinel_staleness.py`),
  then implement.

### Implementation
1. In `triggers/sentinel_health.py`, add module-level config + read-time overlay (after `_apply_retirement`):

```python
# COCKPIT_REFERENCE_DESK_1: a sentinel that silently stops must not show healthy.
# Read-time overlay (no write), same pattern as _apply_retirement. Hours before a
# quiet source flips to 'stale'; default covers anything unlisted.
_STALE_AFTER_HOURS_DEFAULT = 48
_STALE_AFTER_HOURS = {
    "email": 6,
    "graph_mail": 6,
    "whatsapp": 24,
    "clickup": 30,
    "todoist": 48,
    "calendar": 48,
    "rss": 72,
    "browser": 168,
}

def _apply_staleness(rows: list) -> list:
    now = datetime.now(timezone.utc)
    for r in rows:
        if r.get("status") in ("disabled", "down"):
            continue  # retirement and hard-down outrank staleness
        ls = r.get("last_success_at")
        if ls is None:
            continue  # 'unknown' handled by existing logic
        if ls.tzinfo is None:
            ls = ls.replace(tzinfo=timezone.utc)
        max_h = _STALE_AFTER_HOURS.get(r.get("source"), _STALE_AFTER_HOURS_DEFAULT)
        if (now - ls).total_seconds() / 3600 > max_h:
            r["status"] = "stale"
    return rows
```

2. In `get_all_sentinel_health()` change the return line to
   `return _apply_staleness(_apply_retirement(rows))`.
3. In `outputs/dashboard.py::get_sentinel_health` (~4481) add `"stale": 0` and `"disabled": 0` to the
   `summary` dict literal (unexpected statuses currently fall into `unknown` — make both explicit).
4. Frontend (`app.js` System console + landing health strip): render `stale` as a red/amber state with
   text `no data since <last_success date>`; `disabled` renders grey. Grep for where `healthy`/`down`
   pill classes are assigned.
5. Do NOT auto-retire browser/calendar/rss/todoist. Whether each dead feed is fixed or formally
   retired (via `RETIRED_SOURCES`) is a separate AH decision — this brief only makes the truth visible.
   List every source that shows `stale` on first deploy in the ship report.

### Key Constraints
- Read-time transform only — never write `stale` into the `sentinel_health` table.
- Do not change `_status_for_failures`, alert firing, or `check_stale_watermarks` behavior.
- Threshold map is module-level constant — no env vars, no DB config.

### Verification
Unit: new test constructs rows with `last_success_at = now - 30 days` → expects `stale`; row with
`status='down'` stays `down`; retired source stays `disabled`.
Live: `curl -s -H "X-Baker-Key: $KEY" .../api/sentinel-health | python3 -c "..."` → `browser` and
`calendar` report `stale`, summary has a nonzero `stale` bucket.

---

## Fix 3: Numbers cleanup — landing counts must mean something

### Problem
Landing claims `fire_count: 436` while showing 5 top fires and 1 critical item; 660 pending alerts
sit untriaged; 13 "active" deadlines are already past due. Alarm fatigue = zero information.

### Current State
- `outputs/dashboard.py::/api/dashboard/morning-brief` (~5818) computes `fire_count` — read the
  actual query before changing it.
- `alerts` columns (verified via information_schema 2026-07-08): id, tier, title, body, action_required,
  status, acknowledged_at, resolved_at, created_at, snoozed_until, source, source_id, matter_slug, exit_reason, …
- `deadlines` columns (verified): id, description, due_date, status, is_critical, matter_slug, priority, …

### Engineering Craft Gates
- Diagnose: applies — before/after counts via the Verification SQL below.
- Prototype: N/A.
- TDD/verification: applies — fire_count contract test if a seam exists; otherwise live probe (state why in ship report).

### Implementation
1. **One-off data cleanup** — run against prod via a `scripts/` one-shot (NOT a schema migration;
   pattern: `scripts/` folder one-off with `if __name__ == "__main__"`), inside a transaction,
   printing affected counts before commit:

```sql
-- Expire stale pending alerts. Preserves tier-1 and action-required rows (user-flagged data
-- must survive auto-cleanup — Lesson: auto-dismiss killed Director-flagged items once already).
UPDATE alerts
   SET status = 'expired',
       exit_reason = 'cockpit_shrink_bulk_expire_20260708'
 WHERE status = 'pending'
   AND created_at < now() - interval '14 days'
   AND tier > 1
   AND (action_required IS NOT TRUE);

-- Expire past-due 'active' deadlines, preserving critical-flagged ones.
UPDATE deadlines
   SET status = 'expired'
 WHERE status = 'active'
   AND due_date < now() - interval '2 days'
   AND (is_critical IS NOT TRUE);
```

2. **fire_count contract**: change the morning-brief `fire_count` to count ONLY what the fires
   surface actually treats as live fires — pending, not snoozed (`snoozed_until IS NULL OR
   snoozed_until < now()`), `tier <= 2`, created within 30 days. Read the `top_fires` query in the
   same function and reuse its WHERE clause so the number and the list can never diverge again.
   Add `LIMIT` to any unbounded query you touch; `conn.rollback()` in every except block.

### Key Constraints
- Cleanup script must NOT touch alerts with `action_required = TRUE` or `tier = 1`, nor deadlines
  with `is_critical = TRUE`.
- No recurring auto-expiry job in this brief — one-off only; recurring hygiene is a follow-up decision.

### Verification SQL
```sql
SELECT status, COUNT(*) FROM alerts GROUP BY status LIMIT 10;          -- pending should drop ~660 → double digits
SELECT COUNT(*) FROM deadlines WHERE status='active' AND due_date < now() LIMIT 1;  -- → ≤ handful, all is_critical
```
Live: morning-brief JSON `fire_count` within same order of magnitude as rendered fires list.

---

## Fix 4: Landing latency + as-of stamps

### Problem
`/api/dashboard/morning-brief` takes ~12s (measured 11.95s, 2026-07-08). First screen = blank wait.
No panel says when its data was fetched.

### Current State
Endpoint at `outputs/dashboard.py` ~5818 aggregates many sequential queries. Read it before changing.

### Engineering Craft Gates
- Diagnose: applies — FIRST add per-section timing (log dict of section→ms at INFO), deploy or run
  locally against prod DB, identify the top offenders. Ranked hypotheses: (1) sequential fan-out of
  10+ queries, (2) one pathological query on a big table (alerts 18k / email 163k rows), (3) a slow
  external call inside the request path. Fix what the timings prove — do not guess.
- Prototype: N/A.
- TDD/verification: applies — live probe: 3× `curl -w '%{time_total}'`, p95 < 2s.

### Implementation
1. Add timing instrumentation, identify offenders.
2. Then, as the timings dictate: run independent reads concurrently (`asyncio.gather` over
   `asyncio.to_thread(...)` for sync store calls), add `asyncio.wait_for` timeouts (3s) with graceful
   degradation per section (EWS pattern already in codebase), and add an in-process 60s cache of the
   full payload (module-level `{"ts": ..., "payload": ...}`; no cross-instance coordination needed).
3. Add `"as_of": <utc iso now>` top-level field to morning-brief and matters-summary responses;
   render it in the SPA as a small "as of HH:MM" stamp on the landing header and matters header.

### Key Constraints
- Graceful degradation, not hard failure: a slow section returns its empty shape + `"timed_out": true`.
- Do not change response schema keys the SPA already reads — add only.

### Verification
`for i in 1 2 3; do curl -s -o /dev/null -w '%{time_total}\n' -H "X-Baker-Key: $KEY" .../api/dashboard/morning-brief; done`
→ all < 2s (second and third calls may hit cache; first cold call < 4s acceptable if timings prove
cold DB pool). Landing shows "as of" stamp.

---

## Files Modified
- `outputs/static/index.html` — nav subtraction, ARRIVALS link, cache-bust bumps
- `outputs/static/app.js` — loader guards, stale/disabled rendering, as-of stamps
- `outputs/static/style.css` — only if a `stale` pill class is needed
- `outputs/dashboard.py` — sentinel-health summary buckets, fire_count contract, morning-brief timing/concurrency/cache/as_of
- `triggers/sentinel_health.py` — `_STALE_AFTER_HOURS` + `_apply_staleness`
- `tests/test_sentinel_staleness.py` — NEW
- `scripts/cockpit_shrink_cleanup.py` — NEW one-off (Fix 3)

## Do NOT Touch
- `orchestrator/*` — arrivals board / flight dashboards / cockpit serve are the new lane, out of scope
- `outputs/static/mobile.html`, `mobile.js` — mobile pass is a separate brief
- `migrations/*` — no schema change in this brief
- Backend endpoints of retired sections — nav-only retirement
- `templates/arrivals_board_template.html` — vault-owned register

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` + same for `triggers/sentinel_health.py`.
2. `pytest tests/test_sentinel_staleness.py -v` green; full `pytest` no new failures.
3. Post-deploy: sidebar clean (no 5 retired sections), ARRIVALS link works, no JS console errors.
4. `/api/sentinel-health`: browser + calendar = `stale`; summary has `stale` + `disabled` buckets.
5. Morning brief < 2s warm, fire_count ≈ rendered fires, as-of stamp visible.
6. Cleanup script printed before/after counts; no `is_critical`/`action_required`/tier-1 rows touched.
7. Ship report lists every source showing `stale` on first deploy (input to retire-vs-fix decision).
8. POST_DEPLOY_AC_VERDICT v1 posted to bus (post-deploy-ac-bus-gate convention).

## Harness V2
- **Task class:** production-facing UI+backend change, Tier-B lane (Director-ratified direction 2026-07-08).
- **Context contract:** this brief + the audit artifact are self-contained; no other session context required.
- **Done rubric:** all 8 Quality Checkpoints answered individually in the ship report — "tests pass" alone is not done.
- **Gate plan:** codex review (G0-style static pass) on the PR before merge; AH merges on PASS-WITH-NITS; post-deploy AC verdict on bus.
