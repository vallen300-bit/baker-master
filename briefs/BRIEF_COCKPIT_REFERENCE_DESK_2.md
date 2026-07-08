# BRIEF: COCKPIT_REFERENCE_DESK_2 — landing-grid removal + sentinel retire set + weekly thresholds + fireflies liveness honesty

## Context

Follow-up to COCKPIT_REFERENCE_DESK_1 (PR #493, merged 2026-07-08, live). Two inputs:

1. **Director directive 2026-07-09** (cowork-ah1 session): remove the 4 landing-grid cards — Travel, Critical, Promised To Do, Meetings — "he can never allocate them properly." The cards aggregate misclassified data and are noise, not signal.
2. **AH1 retire-vs-fix ruling** (bus #7525, ADOPTED by lead #7527) on the stale sources surfaced by CRD_1's honest-staleness overlay, **updated by live evidence gathered 2026-07-09**: the Fireflies account itself recorded its last meeting 2026-05-19 (live Fireflies API probe returned zero transcripts after that date; Plaud is the active transcript path, latest ingest 2026-07-08). Fireflies is therefore **account-idle, not pipeline-broken** → it moves from the FIX list to the RETIRE list, plus a small liveness-reporting fix so this ambiguity can never recur.

Everything here is subtraction + honesty, same doctrine as CRD_1. No new features.

## Estimated time: ~2.5h
## Complexity: Low-Medium
## Prerequisites: none (main @ 6169f45c or later)

## Baker Agent Vault Rails

Relevant: **standing-contract** (Director-facing surface honesty), **verification-surfaces** (sentinel-health is a verification surface; changes must keep it truthful).
Ignored (out of scope): bus-and-lanes, skills-and-playbooks, memory-and-lessons, loop-runner — no bus/skill/memory mechanics change here.

## Harness V2

- **Task class:** production-facing UI+backend, **Tier-B** (same class as CRD_1). No migrations, no env-var changes, no external sends.
- **Context Contract:** worker needs exactly — (1) this brief; (2) repo at main ≥ `6169f45c`; (3) prod read access for post-deploy checks: `X-Baker-Key` header (Render env `BAKER_API_KEY` — never commit) against `baker-master.onrender.com`; (4) bus posting as own seat for the verdict. NOT needed / do not pull: baker-vault wikis, Cortex configs, Fireflies API credentials (diagnosis already done — evidence embedded above), Director chat history.
- **Done rubric:** every Quality Checkpoint below answered individually in the ship report — pass / fail / ⏳ POST-DEPLOY / N-A with reason. "Compile-clean" alone ≠ done (Lesson #8). Fix 4 is explicitly **unit-verifiable only** while fireflies is retired — the ship report must say so, not claim live proof.
- **Done-state class:** DEPLOYED + post-deploy AC verified — done only when the merge is live on Render, checkpoints 4-6 pass against prod, and `POST_DEPLOY_AC_VERDICT` is on the bus (post-deploy-ac-bus-gate).
- **Gate plan:** lead reviews brief → commit to main → dispatch (b-seat) → PR → **codex G3** → lead merges → Render auto-deploy → worker runs post-deploy checkpoints → verdict on bus → AH1 spot-verifies. No /security-review needed (Tier-B, no auth/key-surface change; the separate scoped-key hardening brief owns that lane).

---

## Fix 1: Remove the 4 landing-grid cards (Travel / Critical / Promised To Do / Meetings)

### Problem
Director-directed removal 2026-07-09. The cards mis-bucket items (audit 2026-07-08 + Director confirmation). CRD_1 removed Travel from the NAV but its landing grid cell remained.

### Current State
`outputs/static/index.html` (main @6169f45c): a single self-contained block

```html
<div class="landing-grid">
    ... 4 × <div class="grid-cell"> ...
</div>
```

starting at the line `<div class="landing-grid">` (~line 201) and ending at its matching `</div>` (~line 241), immediately before the comment `<!-- COCKPIT_REFERENCE_DESK_1: Cortex Intent Feed card removed ... -->`. The 4 cells contain ids: `gridTravel`/`gridTravelCount`, `gridCritical`/`gridCriticalCount` (+ button `_criticalQuickAdd()`), `gridDeadlines`/`gridDeadlinesCount` (labelled "Promised To Do"), `gridMeetings`/`gridMeetingsCount` (+ button `_meetingQuickAdd()`).

`outputs/static/app.js` `loadMorningBrief()` populates each cell **behind an element-existence guard** (`var gridTravel = document.getElementById('gridTravel'); if (gridTravel) {...}` — same pattern for the other three, ~lines 1101-1330). Removing the HTML cells is therefore safe without touching app.js.

### Engineering Craft Gates
- Diagnose: N/A — ratified removal, not a bug.
- Prototype: N/A — no design uncertainty; deleting a block.
- TDD/verification: applies — grep-level asserts + browser DOM check (below). First check: `grep -c 'id="gridTravel"' outputs/static/index.html` = 0 after edit.

### Surface contract
- **Surface:** old cockpit SPA landing view (`viewMorningBrief`), engine-room/reference register (Pattern C) — NOT a Director-canonical Pattern E flight dashboard; design-v2 flight rules do not apply.
- **Change:** delete the entire `.landing-grid` block (4 cards). Nothing else on the landing view moves: TODAY'S PRIORITIES block above it stays; the Cortex-removal comment, silent-contacts warning, and attention/fires elements below it stay.
- **Reachability after change:** Travel/Promised deep-link views (`viewTravel`, `viewPromised`) remain in the DOM and via `FUNCTIONAL_TABS` deep-links — unchanged CRD_1 doctrine (removal = nav/landing subtraction, not code deletion).
- **Verify:** browser DOM after deploy — 4 ids absent, zero console errors, landing renders priorities + attention content normally.

### Implementation
1. In `outputs/static/index.html`, delete from the line `<div class="landing-grid">` through its closing `</div>` (the block whose cells contain `gridTravel`, `gridCritical`, `gridDeadlines`, `gridMeetings`). Leave a one-line tombstone comment in its place:
```html
<!-- COCKPIT_REFERENCE_DESK_2: landing grid (Travel / Critical / Promised To Do / Meetings) removed — Director directive 2026-07-09; cards mis-bucketed items. View divs + guarded JS loaders retained. -->
```
2. Do NOT edit `outputs/static/app.js` — the four render blocks are element-guarded and become no-ops. Do NOT edit `outputs/static/style.css` — `.landing-grid` CSS becomes unused (harmless).
3. No cache-bust bump needed: neither `app.js` nor `style.css` changes (`?v=` stays 85/133). index.html is served fresh.

### Key Constraints
- Do not remove `viewTravel` / `viewPromised` view divs or any `_criticalQuickAdd` / `_meetingQuickAdd` JS function definitions — unused functions are harmless; deleting them risks breaking other call sites.
- Do not touch the TODAY'S PRIORITIES block or attention/fires rendering.
- **Test reconciliation:** `grep -rn "gridTravel\|gridCritical\|gridDeadlines\|gridMeetings\|landing-grid" tests/` — if any test asserts these exist in index.html, invert it to guard the ratified removal (same pattern as CRD_1's Cortex-tab test inversion). Report which tests were inverted.

### Verification
- `grep -c 'id="gridTravel"\|id="gridCritical"\|id="gridMeetings"\|class="landing-grid"' outputs/static/index.html` → 0 for each.
- `node --check outputs/static/app.js` (unchanged, but run anyway).
- Post-deploy browser check: landing loads, no console errors, 4 cards gone.

---

## Fix 2: Retire 7 dead/idle sentinel sources

### Problem
CRD_1's staleness overlay now honestly shows these as `stale`, but they are permanently dead or idle — displaying them as `stale` forever is noise. Ruling #7525 (adopted #7527) + fireflies evidence update:

| source | last success | why retire |
|---|---|---|
| `browser` | 2026-04-27 | 72d dead; browser-use path abandoned |
| `calendar` | 2026-05-29 | dead poller; any future calendar ingest rebuilds on Graph, not this |
| `slack` | 2026-05-20 | 49d dead; Slack read path is MCP now |
| `initiative_engine` | 2026-03-27 | 103d dead; superseded by Cortex |
| `obligation_generator` | 2026-03-29 | 101d dead; superseded |
| `fireflies` | 2026-06-09 | account idle — last real meeting 2026-05-19 (live API probe 2026-07-09); Plaud replaced it |
| `fireflies_backfill` | 2026-06-09 | rides with fireflies |

### Current State
`triggers/sentinel_health.py` — single control point (RETIRE_DEAD_EVOK_SENTINELS_1 pattern, verified 2026-07-09):
- `RETIRED_SOURCES = frozenset({"exchange", "exchange_sent", "exchange_calendar"})` (line ~33)
- `_RETIRED_WATERMARK_MAP` (line ~42) maps each retired source → its `trigger_watermarks` source name(s); feeds `RETIRED_WATERMARK_SOURCES` which `check_stale_watermarks()` (line ~568) skips.
- `_WATERMARK_MAX_AGE` (line ~479) named-source keys: `email_poll, fireflies, todoist, dropbox, slack, whatsapp_resync, exchange_poll, graph_mail` — of the retire set, only **`slack`** and **`fireflies`** appear → only they need watermark mappings.
- `should_skip_poll(source)` returns True for retired sources; `report_success`/`report_failure` no-op; `_apply_retirement` normalizes display to `disabled`.
- Poller hooks verified: `triggers/browser_trigger.py:47` and `triggers/slack_trigger.py:99` already call `should_skip_poll`. **`triggers/calendar_trigger.py` does NOT** — it only calls `report_success("calendar")` (line ~693); its poll entry function (find via `grep -n "report_success(\"calendar\")" triggers/calendar_trigger.py`, then locate the enclosing function's start ~line 576) needs a skip guard so retirement also stops the wasted poll attempts.

### Engineering Craft Gates
- Diagnose: applies (fireflies) — RESOLVED pre-brief. Hypotheses were (1) account idle, (2) env flag off, (3) silent fetch failures. Live Fireflies API probe 2026-07-09 (`fireflies_get_transcripts fromDate=2026-05-15` → single 05-19 transcript, already in PG; `meeting_transcripts` shows plaud ingesting through 07-08) proves (1). No further diagnosis needed.
- Prototype: N/A — established retirement mechanism, third use.
- TDD/verification: applies — extend the existing retirement/staleness tests before implementing (see Verification).

### Implementation
In `triggers/sentinel_health.py`:

```python
RETIRED_SOURCES = frozenset({
    # RETIRE_DEAD_EVOK_SENTINELS_1 — M365 cutover 2026-06-03:
    "exchange", "exchange_sent", "exchange_calendar",
    # COCKPIT_REFERENCE_DESK_2 — ruling bus #7525/#7527, Director-informed 2026-07-09.
    # Un-retire = delete the line here (+ its _RETIRED_WATERMARK_MAP entry if any).
    "browser",               # dead since 2026-04-27; browser-use path abandoned
    "calendar",              # dead since 2026-05-29; future calendar ingest = Graph rebuild
    "slack",                 # dead since 2026-05-20; Slack reads moved to MCP
    "initiative_engine",     # dead since 2026-03-27; superseded by Cortex
    "obligation_generator",  # dead since 2026-03-29; superseded
    "fireflies",             # account idle — last real meeting 2026-05-19; Plaud replaced it
    "fireflies_backfill",    # rides with fireflies
})
```

Extend `_RETIRED_WATERMARK_MAP` (existing dict — add keys, keep Evok entries):

```python
    "browser": (),
    "calendar": (),
    "slack": ("slack",),          # named key in _WATERMARK_MAX_AGE
    "initiative_engine": (),
    "obligation_generator": (),
    "fireflies": ("fireflies",),  # named key in _WATERMARK_MAX_AGE — stops the permanent 48h STALE-DATA alert
    "fireflies_backfill": (),
```

In `triggers/calendar_trigger.py`, at the top of the poll entry function (the one that ends in `report_success("calendar")`):

```python
    from triggers.sentinel_health import should_skip_poll
    if should_skip_poll("calendar"):
        return
```

### Key Constraints
- Do NOT delete any poller/trigger code — retirement is display + skip, reversible by removing one frozenset line.
- Do NOT touch the three Evok entries or their watermark mappings.
- `clear_retired_source_alerts()` already runs inside `check_stale_watermarks()` — it will clean any orphaned fired STALE-DATA alert for fireflies/slack automatically. Verify it fires post-deploy; do not hand-delete alerts.
- Fireflies un-retire path must stay documented in the frozenset comment (Director may resume Fireflies recording).

### Verification
- Extend `tests/test_sentinel_staleness.py` (10 existing tests from CRD_1): a row for each newly retired source with any status/last_success → `_apply_retirement` normalizes to `disabled`; `should_skip_poll("calendar") is True`; `RETIRED_WATERMARK_SOURCES` contains `"slack"` and `"fireflies"`.
- Post-deploy: see Verification SQL + curl below.

---

## Fix 3: Weekly-cadence staleness thresholds (kill 3 false positives)

### Problem
`_STALE_AFTER_HOURS_DEFAULT = 48` flags Sunday-weekly jobs as `stale` from Tuesday onward — 5 days of false alarm per week. Live 2026-07-09: `ao_pm_lint`, `movie_am_lint`, `waha_restart` all show `stale` with last success Sun 2026-07-05 — they are healthy.

### Current State
`triggers/sentinel_health.py` line ~76: `_STALE_AFTER_HOURS = {...}` per-source overrides (email 6, browser 168, etc.). Cadences verified in `triggers/embedded_scheduler.py`: `ao_pm_lint` Sun 06:00 UTC (line ~621 log), `movie_am_lint` Sun 06:05 (line ~1308 comment), `waha_restart` `CronTrigger(day_of_week="sun", hour=4)` (line ~572).

### Engineering Craft Gates
- Diagnose: applies — loop = unit test on `_apply_staleness` with a 3-day-old weekly row; root cause proven (48h default vs 168h cadence). Done pre-brief.
- Prototype: N/A. TDD: applies — test first: weekly source, last success 100h ago → stays `healthy`; 200h ago → `stale`.

### Implementation
Add to `_STALE_AFTER_HOURS`:

```python
    # COCKPIT_REFERENCE_DESK_2: Sunday-weekly jobs — 192h = 8 days, so one
    # fully-missed week flips stale, a normal week never does.
    "ao_pm_lint": 192,
    "movie_am_lint": 192,
    "waha_restart": 192,
```

### Key Constraints
Do not change `_STALE_AFTER_HOURS_DEFAULT` or any existing entry.

### Verification
Unit tests above + post-deploy: the 3 sources report `healthy` on `/api/sentinel-health` (before next Sunday; after a missed Sunday they must flip `stale`).

---

## Fix 4: Fireflies poller liveness honesty (latent-bug fix)

### Problem
`triggers/fireflies_trigger.py::check_new_transcripts` returns early WITHOUT reporting sentinel state on two paths, so "poller alive but no data" and "poller dead" are indistinguishable — this is exactly why fireflies' staleness was ambiguous until today's API probe:
- fetch failure (lines ~290-294): logs `fetch failed` then `return` — **no `report_failure`** → silent forever.
- empty result (lines ~296-298): `return` — **no `report_success`** → sentinel goes stale though the poller runs fine every 2h.

### Current State
`report_success("fireflies")` only fires at line ~443 after processing ≥1 new transcript. Sentinel row: 0 consecutive_failures, last_success 2026-06-09 — consistent with "runs fine, zero new data since backfill."

### Engineering Craft Gates
- Diagnose: applies — covered under Fix 2 (account idle proven). This fix removes the observability hole.
- Prototype: N/A. TDD: applies — mock `fetch_new_transcripts` to return `[]` / raise; assert `report_success` / `report_failure` called. Write these tests FIRST.

### Implementation
In `check_new_transcripts`:

```python
        try:
            new_transcripts = fetch_new_transcripts(watermark)
        except Exception as e:
            logger.error(f"Fireflies trigger: fetch failed: {e}")
            report_failure("fireflies", f"fetch failed: {e}")
            return

        if not new_transcripts:
            logger.info("Fireflies trigger: no new transcripts")
            report_success("fireflies")  # poller liveness ≠ data novelty
            return
```

(`report_success`/`report_failure` are already imported at the top of the function, line ~274.)

### Key Constraints
- NOTE: while `fireflies` is retired (Fix 2), `should_skip_poll` returns before these lines — the fix is **latent** until un-retire. Ship it anyway: it closes the bug class, and un-retiring must not resurrect the blind spot. Say exactly this in the ship report — do not claim live verification of this path.
- Do not touch the backfill function, watermark logic, or pipeline calls.

### Verification
Unit tests only (live path unreachable while retired — state this honestly). `pytest tests/test_fireflies_liveness.py -v` (new file) or extend the existing fireflies test file if one exists (`ls tests/ | grep -i firefl`).

---

## Files Modified
- `outputs/static/index.html` — landing-grid block removed (Fix 1)
- `triggers/sentinel_health.py` — RETIRED_SOURCES + watermark map + thresholds (Fixes 2, 3)
- `triggers/calendar_trigger.py` — should_skip_poll guard (Fix 2)
- `triggers/fireflies_trigger.py` — liveness reporting (Fix 4)
- `tests/test_sentinel_staleness.py` — extended (Fixes 2, 3)
- `tests/test_fireflies_liveness.py` — new (Fix 4)
- possibly: inverted landing-grid assertions in existing tests (Fix 1 reconciliation)

## Do NOT Touch
- `outputs/dashboard.py` — morning-brief payload keeps computing all sections; backend pruning is a separate latency decision gated on b4's cold-timing logs (CRD_1 ship-report note).
- `outputs/static/app.js` / `style.css` — element-guarded loaders and unused CSS stay; no cache-bust churn.
- `scripts/cockpit_shrink_cleanup.py` — already run in prod (671→35, lead 2026-07-08 21:03Z).
- Evok retirement entries; `_STALE_AFTER_HOURS_DEFAULT`; applied migrations; `tasks/lessons.md` existing entries.

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('triggers/sentinel_health.py', doraise=True)"` — ditto `calendar_trigger.py`, `fireflies_trigger.py`. `node --check outputs/static/app.js` (unchanged sanity).
2. New/extended tests pass; full `pytest` shows **zero new failures vs clean main** (junit failing-id set diff, CRD_1 method — 307 pre-existing env failures expected identical).
3. Landing-grid grep counts = 0 (Fix 1 Verification); test reconciliation reported.
4. Post-deploy `/api/sentinel-health`: the 7 new sources report `disabled`; `ao_pm_lint`/`movie_am_lint`/`waha_restart` report `healthy`; remaining `stale` set is empty (or listed + explained in ship report).
5. Post-deploy browser check: landing has no Travel/Critical/Promised/Meetings cards, no console errors, priorities + attention render.
6. Post-deploy: no STALE-DATA alert rows for fireflies/slack remain active (clear_retired_source_alerts did its job) — SQL below.
7. `POST_DEPLOY_AC_VERDICT` posted to bus per post-deploy-ac-bus-gate.

## Verification SQL
```sql
-- 7 retired sources normalized on the surface (API check is authoritative; DB rows stay untouched by design)
SELECT source, status, last_success_at::date
FROM sentinel_health
WHERE source IN ('browser','calendar','slack','initiative_engine',
                 'obligation_generator','fireflies','fireflies_backfill')
LIMIT 10;
-- (rows keep their stored status — 'disabled' appears only via the API overlay; both checks belong in the ship report)

-- no lingering stale-watermark alerts for retired sources
SELECT id, title, created_at::date
FROM alerts
WHERE status IN ('pending','acknowledged')  -- live statuses (verified 2026-07-09; there is no 'active')
  AND title ILIKE '%stale%' AND (title ILIKE '%fireflies%' OR title ILIKE '%slack%')
LIMIT 10;
```
```bash
# API surface: expect 7×disabled, 3×healthy weekly jobs, stale bucket ~empty
curl -s -H "X-Baker-Key: $BAKER_API_KEY" https://baker-master.onrender.com/api/sentinel-health
```
