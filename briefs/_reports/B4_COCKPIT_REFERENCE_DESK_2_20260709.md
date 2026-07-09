# B4 Ship Report — COCKPIT_REFERENCE_DESK_2

- **Brief:** `briefs/BRIEF_COCKPIT_REFERENCE_DESK_2.md` @df0a04fd
- **Dispatch:** bus #7545 (from `lead`)
- **Branch:** `b4/cockpit-reference-desk-2` @ `d6d6334b`
- **PR:** #494 → base `main`
- **Date:** 2026-07-09
- **Task class:** production-facing UI+backend, Tier-B. No migrations, no env-var changes, no external sends. No `/security-review` (no auth/key-surface change).

## Files modified
- `outputs/static/index.html` — landing-grid block removed (Fix 1)
- `triggers/sentinel_health.py` — RETIRED_SOURCES + `_RETIRED_WATERMARK_MAP` + `_STALE_AFTER_HOURS` (Fixes 2, 3)
- `triggers/calendar_trigger.py` — `should_skip_poll("calendar")` guard (Fix 2)
- `triggers/fireflies_trigger.py` — liveness reporting (Fix 4)
- `tests/test_sentinel_staleness.py` — extended (Fixes 2, 3)
- `tests/test_fireflies_liveness.py` — new (Fix 4)
- `tests/test_retire_dead_evok_sentinels.py` — reconciled for the ratified retirement expansion (Fix 2)

## Quality Checkpoints (Done rubric — one line each)

1. **Compile / syntax — PASS.** `py_compile` clean on `sentinel_health.py`, `calendar_trigger.py`, `fireflies_trigger.py`; `node --check outputs/static/app.js` OK (unchanged).
2. **Full pytest, zero new failures vs clean main — PASS.** junit failing-id set diff (CRD_1 method): branch bad = 307, clean `origin/main` bad = 307, **NEW failures = 0**. The 307 are pre-existing env/collection failures (missing deps, live-PG) identical on both. Branch adds 12 passing tests (4251 passed vs 4239 on main).
3. **Landing-grid greps = 0 + reconciliation — PASS.** `id="gridTravel"` / `gridCritical` / `gridMeetings` / `gridDeadlines` / `class="landing-grid"` all count 0. Test reconciliation: `grep -rn` over `tests/` found **no test asserting the landing-grid ids** → nothing to invert for Fix 1. (Fix 2 did require reconciling `test_retire_dead_evok_sentinels.py` — see below.)
4. **Post-deploy `/api/sentinel-health` — PASS** (verified live 2026-07-09 ~08:0xZ). 7 retired sources `{browser,calendar,slack,initiative_engine,obligation_generator,fireflies,fireflies_backfill}` all `disabled`; `ao_pm_lint`/`movie_am_lint`/`waha_restart` all `healthy`; residual `stale` set = empty. (34 total sentinels; broader `disabled` list also includes pre-existing exchange*/todoist/whoop — out of CRD_2 scope.)
5. **Post-deploy DOM check — PASS (DOM subtraction); console/render partial.** `gridTravel`/`gridCritical`/`gridMeetings`/`gridDeadlines` + `.landing-grid` all absent in **served HTML AND live rendered DOM**. Honest caveat: the "no console errors / priorities+attention render" positive check is not fully verifiable in an unauthenticated headless browser — the SPA renders only a skeleton without a stored Baker key (body ~468 chars), and the observed console errors (`net::ERR_FAILED` + a 404 on auth-gated API calls, plus a pre-existing `apple-mobile-web-app-capable` meta deprecation warning) are auth-gated, **not** landing-grid regressions.
6. **Post-deploy no lingering STALE-DATA alerts for fireflies/slack — PASS.** Brief's alerts SQL (`status IN ('pending','acknowledged')`, `title ILIKE '%stale%'` + fireflies/slack) returned **0 rows** — `clear_retired_source_alerts()` did its job. No hand-deletes.
7. **`POST_DEPLOY_AC_VERDICT` on bus — POSTED** (post-deploy-ac-bus-gate) to `lead` cc `deputy`, topic `post-deploy-ac/cockpit-reference-desk-2`, threaded on #7555. `ac_result: PASS`, `done_state: DONE`.

## Fix-by-fix notes

- **Fix 1:** deleted the `.landing-grid` block; left the CRD_2 tombstone comment. No `app.js`/`style.css` edit → `?v=` stays 85/133, no cache-bust churn. `viewTravel`/`viewPromised` view divs + `_criticalQuickAdd`/`_meetingQuickAdd` retained.
- **Fix 2:** 7 sources added to the frozenset control point + watermark map (only slack/fireflies map to a named `_WATERMARK_MAX_AGE` key). Evok 3 + their watermarks untouched. `should_skip_poll("calendar")` guard added at the top of `check_calendar_and_prep`.
- **Fix 3:** 192h thresholds added; `_STALE_AFTER_HOURS_DEFAULT` and existing entries untouched.
- **Fix 4 — HONEST CAVEAT:** liveness fix is **latent, unit-verified only**. In prod `check_new_transcripts` never reaches the fixed lines because (a) fireflies is now retired → `should_skip_poll("fireflies")` returns first, AND (b) the fireflies scan job is env-gated off (`FIREFLIES_SCAN_ENABLED=false`, Plaud-only cutover PR #341) so it isn't even registered. Per the brief's REVIEW NOTE: I do **not** claim "poller runs every 2h" — it does not run in prod today. The fix ships to close the blind-spot bug class so un-retiring fireflies later cannot resurrect it. Tests patch `should_skip_poll`→False to exercise the paths; a third test asserts the real retired short-circuit (nothing touches the sentinel) to document current honest state.

## Test reconciliation reported
- `test_retire_dead_evok_sentinels.py`: `test_retired_set_is_exactly_the_three_evok_sources` → split into `test_evok_sources_remain_retired` (subset guarantee kept) + `test_retired_set_is_exactly_evok_plus_crd2` (exact new ratified set). `LIVE_WATERMARK_SOURCES` lost `slack`+`fireflies` (now retired), fixing `test_no_live_watermark_source_is_retired`.
- `test_sentinel_staleness.py`: `test_stacks_after_retirement` live-source example moved `calendar`→`clickup` (calendar is now retired → would normalize to `disabled`).

## Gate plan / next
codex G3 → lead merge → Render auto-deploy → B4 runs checkpoints 4-6 → `POST_DEPLOY_AC_VERDICT` on bus → AH1 spot-verify. **Chained follow-on:** AO_FLIGHT_RELATIONSHIP_1 (bus #7550) is queued to B4 explicitly *after* CRD_2 merges (shared `index.html` — sequenced to avoid conflict).
