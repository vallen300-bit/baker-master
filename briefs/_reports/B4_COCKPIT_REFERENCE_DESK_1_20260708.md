# B4 Ship Report — COCKPIT_REFERENCE_DESK_1

- **Brief:** `briefs/BRIEF_COCKPIT_REFERENCE_DESK_1.md` (Director-ratified 2026-07-08)
- **Dispatch:** bus #7492, from `lead`
- **Branch:** `b4/cockpit-reference-desk` → **PR #493** (base `main`)
- **Commit:** `bd3f8556`
- **Gate:** codex G3 `gate/cockpit-reference-desk-g3`; lead merges.
- **Task class:** production-facing UI+backend, Tier-B. Harness V2 done-rubric answered per-checkpoint below.

## What shipped (4 fixes, subtraction + honesty badges only)

- **Fix 1 nav shrink** — removed People/Ideas/Media nav sections, Travel + Presentations tabs, stale Cortex landing card; added `ARRIVALS BOARD ↗` → `/arrivals`; guarded 5 boot loaders (no dead fetches); cache-bust v84→85 / v132→133. View `<div>`s + app.js code retained (deep-link reachable).
- **Fix 2 honest staleness** — `_apply_staleness` read-time overlay in `triggers/sentinel_health.py` (no table write); `get_all_sentinel_health` → `_apply_staleness(_apply_retirement(rows))`; dashboard summary + SPA render `stale`/`disabled`.
- **Fix 3 numbers** — `fire_count` shares one `_live_fire_where` predicate with `top_fires`; new `scripts/cockpit_shrink_cleanup.py` one-off (preserves tier-1/action_required/is_critical).
- **Fix 4 latency + as-of** — 60s in-process morning-brief payload cache; per-section cold-timing log; `as_of` on morning-brief + matters-summary, rendered "as of HH:MM".

## Quality Checkpoints (done rubric — each answered)

1. **Compile** — `py_compile` clean: `outputs/dashboard.py`, `triggers/sentinel_health.py`, `scripts/cockpit_shrink_cleanup.py`. ✅ `node --check outputs/static/app.js` clean. ✅
2. **Tests** — `pytest tests/test_sentinel_staleness.py -v` → **10 passed**. Full suite: **zero new failures vs clean main** — junit diff of failing-id sets empty; 307 pre-existing env failures (`ModuleNotFoundError: No module named 'mcp'`, DB-less integration, flaky collection) identical in both. Baseline 4864 tests/307 fail; mine 4874 tests/307 fail (+10 = my new file, all pass). ✅
3. **Sidebar clean / ARRIVALS / no console errors** — ⏳ POST-DEPLOY. Static-source pre-checks green: `grep -c 'data-tab="travel"'`=0, `presentations`=0, `ARRIVALS`=1. Browser DOM + console check pending Render deploy.
4. **`/api/sentinel-health` stale** — ⏳ POST-DEPLOY. Overlay unit-proven (30-day row → `stale`; `down` stays `down`; retired stays `disabled`). Live browser+calendar=`stale` + nonzero `stale` bucket pending deploy.
5. **Morning brief warm <2s / fire_count ≈ fires / as-of** — ⏳ POST-DEPLOY. 60s cache (warm-hit returns cached payload); fire_count now shares top_fires predicate; as_of field present (grep=4). Live `curl -w '%{time_total}'` ×3 pending deploy.
6. **Cleanup script before/after counts; no protected rows touched** — ⏳ **NOT RUN against prod.** Script is compile-clean + dry-run default; WHERE clauses exclude tier-1 / action_required / is_critical. **I do not have prod DB access from this session** — running the 660-row mutation is a deliberate operator step (lead or authorized run post-merge: `python3 scripts/cockpit_shrink_cleanup.py --dry-run` then `--run`).
7. **List stale sources on first deploy** — ⏳ POST-DEPLOY. Requires live `/api/sentinel-health`; browser + calendar are the known-silent pair from the audit; full list to follow post-deploy for the retire-vs-fix decision.
8. **POST_DEPLOY_AC_VERDICT** — ⏳ POST-DEPLOY (post-deploy-ac-bus-gate convention), after Render deploy of the merge.

## Notes / fail-loud

- **Test reconciliation:** `test_dashboard_cortex_ratify::test_pending_tab_button_in_static_index_html` asserted the Cortex Pending tab exists in index.html — Fix 1 (ratified) removes the whole Cortex card, so I inverted the test to guard the ratified removal. Backend `/api/cortex/cycles/pending` + all `_cortexPending*` JS helpers are preserved (their tests still pass) so the card can be re-added unchanged.
- **Fix 4 scope call:** the brief's Diagnose gate says instrument first, "fix what the timings prove — do not guess." I shipped the deterministic wins (60s cache = warm <2s, as-of, section timing) but did **not** blind-refactor the shared-cursor DB fan-out into `asyncio.gather` — that needs a connection-per-thread refactor and should follow the prod cold-timing logs (`morning-brief cold timing (s): {...}` at INFO). Flagging so a timing-gated follow-up can be scoped from real data.
- **`brisen-lab/`** untracked embedded repo in the worktree is not mine — left untracked, not committed.
