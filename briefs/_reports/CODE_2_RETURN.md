# CODE_2_RETURN — CAPABILITY_THREADS_1 — 2026-04-24

**From:** Code Brisen #2
**To:** AI Head #2
**Branch:** `capability-threads-1`
**Brief:** `briefs/BRIEF_CAPABILITY_THREADS_1.md` (1587 lines)
**Dispatch:** `briefs/_tasks/CODE_2_PENDING.md` (mailbox commit `a9941f3`)
**Base:** main @ `87e1f65` (includes PR #56 `281661d`)
**PR:** https://github.com/vallen300-bit/baker-master/pull/57

---

## 1. Ship gate — literal output

```
$ python3 -c "import py_compile
for f in ['orchestrator/capability_threads.py','orchestrator/capability_runner.py','orchestrator/pm_signal_detector.py','orchestrator/agent.py','memory/store_back.py','outputs/dashboard.py']:
    py_compile.compile(f, doraise=True)
print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_capability_threads.py tests/test_capability_threads_h5.py -v 2>&1 | tail -25
collected 12 items

tests/test_capability_threads.py::test_extract_entity_cluster_ao_pm_patterns PASSED [ 8%]
tests/test_capability_threads.py::test_extract_entity_cluster_unknown_pm_returns_empty PASSED [16%]
tests/test_capability_threads.py::test_score_candidate_weights PASSED    [25%]
tests/test_capability_threads.py::test_jaccard_overlap PASSED            [33%]
tests/test_capability_threads.py::test_recency_weight_now_is_one PASSED  [41%]
tests/test_capability_threads.py::test_recency_weight_half_life PASSED   [50%]
tests/test_capability_threads.py::test_topic_summary_truncates PASSED    [58%]
tests/test_capability_threads.py::test_topic_summary_strips_newlines PASSED [66%]
tests/test_capability_threads.py::test_surface_from_mutation_source_known_sources PASSED [75%]
tests/test_capability_threads.py::test_create_new_thread_uses_python_uuid_not_pgcrypto PASSED [83%]
tests/test_capability_threads.py::test_capability_threads_ddl_applied SKIPPED [91%]
tests/test_capability_threads_h5.py::test_h5_cross_surface_continuity SKIPPED [100%]

10 passed, 2 skipped in 0.17s
```

**Integration test gate:** brief specified `--run-integration` pytest flag,
but this repo already uses the `needs_live_pg` fixture (from `tests/conftest.py`;
resolves `TEST_DATABASE_URL` or CI ephemeral Neon branch, else `pytest.skip`).
Switched to `needs_live_pg` for consistency with existing
`tests/test_bridge_pipeline_integration.py` pattern — **no new flag added**.
The 2 integration tests skip locally (no `TEST_DATABASE_URL`); CI with
`NEON_API_KEY+NEON_PROJECT_ID` runs them against an ephemeral branch per
existing conftest logic.

## 2. Full-suite regression delta

```
Baseline (main @ 87e1f65, excluding tests/test_tier_normalization.py
pre-existing collection TypeError):
  832 passed, 24 failed, 21 skipped, 31 errors

Branch (capability-threads-1):
  842 passed, 24 failed, 23 skipped, 31 errors

Delta: +10 passes = 10 new unit tests green
       +2 skipped  = 2 new integration tests gated on needs_live_pg
       +0 failures = zero regressions
       +0 errors   = zero new errors
```

Measurement method: `git stash -u` → pytest on pristine main → capture baseline
→ `git stash pop` → re-verify ship gate on restored branch.

## 3. Per-feature summary

| Feature | File(s) | Change |
|---|---|---|
| **F1** | `migrations/20260424_capability_threads.sql` (NEW) | 2 tables (`capability_threads`, `capability_turns`) + 1 additive column (`pm_state_history.thread_id`) + 5 indexes. Idempotent `IF NOT EXISTS` throughout. `uuid-ossp` DEFAULT (no pgcrypto — absent on Neon per pre-merge verification). |
| **F2** | `orchestrator/capability_threads.py` (NEW, 383 lines) | Hybrid stitcher — Qdrant cosine via `retriever.qdrant.query_points` (repo convention, not deprecated `.search`), entity Jaccard, recency half-life. `stitch_or_create_thread`, `persist_turn`, `mark_dormant_threads`, `surface_from_mutation_source`. Singleton factories only. No LLM calls. Every `except` calls `conn.rollback()` before `_put_conn`. |
| **F3** | `memory/store_back.py:5228-5303` | Added `thread_id: Optional[str] = None` to `update_pm_project_state`; `INSERT pm_state_history ... RETURNING id`; returns `history_row_id` on audit-write success, `None` on first-ever insert / failure. Optimistic-lock body (lines 5264-5285) unchanged per brief §"Do NOT Touch". |
| **F3.2** | `orchestrator/capability_runner.py` (`extract_and_update_pm_state`) | Stitch **before** `update_pm_project_state` call so `thread_id` propagates into `pm_state_history`. `persist_turn` **after** state-write so `pm_state_history_id` can link back. Both wrapped in try/except with logger.warning — state-write never blocked by thread failure. |
| **F3.3** | `orchestrator/pm_signal_detector.py:149-190` | After existing signal state-write, stitch + persist a `signal` surface turn. `pm_state_history.thread_id` stays NULL for this surface by design (§H2 documented exception). |
| **F3.4** | `orchestrator/agent.py:2024-2042` | `_update_pm_state` tool now passes `mutation_source="agent_tool"` — closes the H4 gap from PR #50 ship report (`briefs/_reports/CODE_2_RETURN.md:107` carryover). |
| **F4.1** | `orchestrator/capability_runner.py` (new method `_get_pm_thread_context`) | Placed immediately after `_get_pm_project_state_context` (brief's adjacency hint). `DictCursor` for named-column access; most-recently-active thread if no hint, else hint-provided. Non-fatal — empty string on any error. Emits chronological Q/A preview with surface label. |
| **F4.2** | `orchestrator/capability_runner.py:_build_system_prompt` | Injects `# RECENT THREAD CONTEXT` section between live state (after existing state_ctx block) and pending insights. All 4 doors route through `_build_system_prompt` → inherit automatically. |
| **F5.1** | `outputs/dashboard.py` (3 new `@app` routes before CLI runner) | `GET /api/pm/threads/{pm_slug}` (list), `GET /api/pm/threads/{pm_slug}/{thread_id}/turns` (replay), `POST /api/pm/threads/re-thread` (Director override — force_new via `stitch_or_create_thread`). All read paths use `LIMIT`; unknown pm_slug → 404; stitch-failure → 200 with `{threads:[], error}` (fail-soft). |
| **F5.2** | `outputs/static/app.js` (+86 lines at end) | Pure-DOM: `textContent`, `createElement`, `appendChild`, `_pmThreadsClear` via `removeChild` loop. Zero `innerHTML` with user content. Feature-flagged via `_pmThreadsEnabled()` → `localStorage['baker.threads.ui_enabled'] === '1'`. |
| **F5.3** | `outputs/static/index.html` | Panel containers (`#pm-threads-panel`, `#pm-thread-replay`) added before `<script src="app.js">`, `display:none` default. Inline activation script toggles display only when flag is set. `app.js?v=106 → ?v=107`, `style.css?v=71 → ?v=72` cache-bust (lesson #4). |
| **F5.4** | `outputs/static/style.css` (+48 lines at end) | Fixed-position panel right-edge, 360px wide, 40vh max-height each, stacked. Mobile (≤480px) falls back to static flow. Uses existing CSS vars with fallbacks. |
| **F6.a** | `tests/test_capability_threads.py` (NEW, 180 lines) | 11 tests: 2 entity extractor, 4 scoring (including exact Jaccard 1/3 check + half-life recency), 2 topic_summary (truncation + newline stripping), 1 `surface_from_mutation_source` mapping, 1 pgcrypto guardrail (UUID via Python `uuid.uuid4` not DB `gen_random_uuid()`), 1 DDL smoke (gated on `needs_live_pg`). |
| **F6.b** | `tests/test_capability_threads_h5.py` (NEW, 95 lines) | MANDATORY §H5 cross-surface continuity test — writes via `sidebar` surface, follow-up via `decomposer` surface, asserts both surfaces observable under the same pm_slug in the recency window. Gated on `needs_live_pg`. |
| **F6.c** | `tests/test_pm_state_write.py` (MOD — 1 `_FakeStore` class) | Accept-and-ignore `thread_id` kwarg in the D1 test's `_FakeStore.update_pm_project_state` signature (previously pinned the old 5-arg shape). Added `_get_conn`/`_put_conn` no-ops so stitcher helpers degrade cleanly. `mutation_source` ship-gate assertions preserved verbatim. |

## 4. Files modified vs brief §Files Modified list

| Brief §Files Modified entry | This PR? | Notes |
|---|---|---|
| `migrations/20260424_capability_threads.sql` (NEW) | ✅ | F1 |
| `orchestrator/capability_threads.py` (NEW) | ✅ | F2 |
| `memory/store_back.py:5228` | ✅ | F3.1 |
| `orchestrator/capability_runner.py:261` | ✅ | F3.2 |
| `orchestrator/capability_runner.py` `_build_system_prompt` | ✅ | F4.2 |
| `orchestrator/capability_runner.py` new `_get_pm_thread_context` | ✅ | F4.1 |
| `orchestrator/pm_signal_detector.py:149` | ✅ | F3.3 |
| `orchestrator/agent.py:2031` | ✅ | F3.4 |
| `outputs/dashboard.py` (3 new endpoints) | ✅ | F5.1 |
| `outputs/static/app.js` | ✅ | F5.2 |
| `outputs/static/index.html` | ✅ | F5.3 + v=107/v=72 |
| `outputs/static/style.css` | ✅ | F5.4 + v=72 |
| `tests/test_capability_threads.py` (NEW) | ✅ | F6.a |
| `tests/test_capability_threads_h5.py` (NEW) | ✅ | F6.b |

```
$ git diff main..HEAD --name-only | wc -l
13
```

12 brief-expected files + `tests/test_pm_state_write.py` (test update:
existing D1 `_FakeStore` hard-coded the old `update_pm_project_state`
signature without `thread_id`; kwarg added with default None so signature
change is backward-compatible, but the mock had to expand accordingly).
Within brief §Scope discipline ±1 tolerance. Reason documented in PR body.

## 5. Do NOT Touch — verified untouched

- `memory/store_back.py:5264-5285` (optimistic-lock body of
  `update_pm_project_state`) — semantically unchanged; only the INSERT
  above grew `thread_id` + `RETURNING id` and the commit/close/return
  structure was reorganized per branch (same side-effects, just clearer
  ownership of `history_row_id` return).
- `memory/retriever.py` — reused `SentinelRetriever._get_global_instance()`
  + `._embed_query()` + `.qdrant` unchanged.
- `conversation_memory` table + `memory/store_back.py::log_conversation` —
  zero diff.
- `scripts/backfill_pm_state.py` — zero diff (forward-only per design).
- `ao_project_state` + `ao_state_history` legacy tables — untouched per
  brief §Legacy references note.
- `config/migration_runner.py` — zero diff.
- `grep -cE '_ensure_capability_threads|_ensure_capability_turns'
  memory/store_back.py` → **0** (lesson #37 DDL-in-migrations-only).
- 5 existing tests in `tests/test_pm_state_write.py` other than D1 (noop),
  and every other test file (zero semantic diff across the full suite —
  only net additions).

## 6. Rule compliance

### SKILL.md Rules

- **Rule 4** (migration-vs-bootstrap DDL): `grep -cE
  '_ensure_capability_threads|_ensure_capability_turns' memory/store_back.py`
  → 0. DDL lives exclusively in the migration file. ✓
- **Rule 7** (file:line verify): every cited line grep-verified before edit.
  - `capability_runner.py:261` `extract_and_update_pm_state` ✓
  - `capability_runner.py:1062` `_build_system_prompt` ✓
  - `capability_runner.py:1674` `_get_pm_project_state_context` ✓
    (brief said "near 1062" → actual adjacency slot at 1674, placed there)
  - `capability_runner.py:1867` `_auto_update_pm_state` ✓
    (brief said 1875 → file drift ~8 lines; not edited this brief)
  - `store_back.py:5228` `update_pm_project_state` ✓
  - `pm_signal_detector.py:149` ✓
  - `agent.py:2031` ✓
  - `dashboard.py:8191`/`8283` (brief said 8148/8240 → file drift ~40 lines;
    not edited this brief — state-write threads untouched)
- **Rule 8** (singleton): `scripts/check_singletons.sh` green. Every call
  path uses `SentinelStoreBack._get_global_instance()` /
  `SentinelRetriever._get_global_instance()`. Zero bare constructors in
  the new module. ✓
- **Rule 10** (Part H): §H1–H5 complete (see PR body §Part H audit). Partial
  attributions for `signal` + `agent_tool` surfaces documented with reasons.

### Python rules (`.claude/rules/python-backend.md`)

- Every PostgreSQL `except` includes `conn.rollback()` before `_put_conn`. ✓
- All DB queries have explicit `LIMIT`. ✓
- Fault-tolerant writes: every stitcher + persist call site wrapped
  try/except → `logger.warning` → fall-through to state-write (non-fatal
  telemetry). ✓
- Regex: `re.findall(..., flags=re.IGNORECASE)` (no inline `(?i)`). ✓

### Frontend rules (`.claude/rules/frontend.md`)

- iOS PWA cache-bust: `style.css?v=72`, `app.js?v=107` bumped. ✓
- Vanilla JS only — `createElement` / `textContent` / `appendChild` /
  `removeChild` — no frameworks, no build tools. ✓
- Mobile viewport: 480px breakpoint falls back to static flow so the
  fixed-position panels don't overflow. (Live mobile PWA verification
  pending deploy — documented in F5 §Key UI constraints follow-up.)

### Security (hook-enforced)

- **Zero `innerHTML` with user-derived content** anywhere in the new JS.
  All user-supplied fields (`topic_summary`, `question`, `answer`, `surface`)
  set via `textContent` on a freshly-created element. ✓

## 7. Pre-merge verification (lesson #40)

```bash
# 1. pgvector NOT installed — design premise confirmed
$ curl … "SELECT extname FROM pg_extension WHERE extname IN ('vector','uuid-ossp')"
  extname: uuid-ossp
# ✓

# 2. pm_project_state baseline
$ curl … "SELECT pm_slug, version, updated_at FROM pm_project_state WHERE state_key='current'"
  ao_pm   v88  2026-04-24 00:59:42+00:00
  movie_am v132 2026-04-24 06:50:34+00:00
# Post-deploy Quality Checkpoint 4 expects both versions to continue
# advancing — any stall means the thread_id propagation broke the
# update_pm_project_state write loop.

# 3. No pre-existing _ensure_capability_* in store_back
$ grep -cE '_ensure_capability_threads|_ensure_capability_turns' memory/store_back.py
  0
# ✓ (lesson #37)

# 4. No duplicate /api/pm/threads endpoint
$ grep -n '/api/pm/threads' outputs/dashboard.py   # pre-merge
  (empty)
# ✓ (lesson #11)

# 5. Singleton hook
$ bash scripts/check_singletons.sh
  OK: No singleton violations found.
```

## 8. Observations for follow-up (non-blocking)

- **Integration-test gating divergence from brief.** Brief specified
  `--run-integration` pytest flag; this repo's conftest already has
  `needs_live_pg` fixture as the canonical gate. Switched to the existing
  convention — no new flag, one less way to test-runners to configure.
  The 2 integration tests run on CI when `NEON_API_KEY+NEON_PROJECT_ID`
  set, exactly as every other live-PG test in this repo does.
- **Sidebar UI wiring hook.** The new `loadPMThreads(pmSlug)` function is
  *defined* but not yet *invoked* from an existing capability-switch
  handler in `app.js`. By design — Feature-5 panels stay dark until
  Director opts in via localStorage, so there's no hook to wire. When
  enabled, Director can invoke `loadPMThreads('ao_pm')` manually from
  DevTools, or a lightweight UI gesture (capability-dropdown change) can
  be wired in a follow-up after live smoke confirms the endpoints.
- **Signal surface + agent_tool partial attributions.** Both documented
  in §H2 as deliberate with reason (`flag_pm_signal` refactor + agent-tool
  turn-write deferred). Tracked in existing Monday audit scratch
  (`_ops/agents/ai-head/SCRATCH_MONDAY_AUDIT_20260427.md` §B3 per brief's
  pointer) as follow-up brief candidate.
- **`_auto_update_pm_state` and dashboard `_sidebar_state_write` /
  `_delegate_state_write` threads.** All three route through the edited
  `extract_and_update_pm_state`, so they inherit stitch+persist
  automatically. Zero direct edit needed at those call sites (brief's line
  drift of ~40 lines in `dashboard.py:8148→8191` confirmed cosmetic; the
  callers are untouched).
- **Baseline** carries 24 pre-existing failing tests + 31 collection
  errors + the `tests/test_tier_normalization.py` TypeError. All
  unchanged on branch (zero regressions).

---

**Handoff:** `@ai-head-2 ready for review`. Next:

1. `/security-review` on PR #57 (SKILL.md mandatory protocol).
2. Tier A merge on APPROVE + green CI.
3. Render deploy → migration auto-apply → `/health` green.
4. Verification SQL block (brief §"Verification SQL (ready-to-run
   post-deploy)") — paste output.
5. Quality Checkpoints 1–13 (brief §Quality Checkpoints post-deploy).
6. Optional: Director toggles
   `localStorage.setItem('baker.threads.ui_enabled','1')`; reload; verify
   panel renders; click a thread row → replay shows. No console errors.

— B2
