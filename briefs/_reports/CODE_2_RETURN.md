# CODE_2_RETURN — PM_SIDEBAR_STATE_WRITE_1 — 2026-04-23

**From:** Code Brisen #2
**To:** AI Head #2
**Branch:** `feature/pm-sidebar-state-write-1`
**Brief:** `briefs/BRIEF_PM_SIDEBAR_STATE_WRITE_1.md` (merge-base main `3c4f9db`)
**Merge-base main tip:** `3c4f9db`

---

## 8-check format

### 1. Ship gate — literal output

```
$ python3 -c "import py_compile; \
  py_compile.compile('orchestrator/capability_runner.py', doraise=True); \
  py_compile.compile('outputs/dashboard.py', doraise=True); \
  py_compile.compile('memory/store_back.py', doraise=True); \
  py_compile.compile('scripts/backfill_pm_state.py', doraise=True); \
  py_compile.compile('orchestrator/pm_signal_detector.py', doraise=True); \
  py_compile.compile('triggers/fireflies_trigger.py', doraise=True); \
  py_compile.compile('triggers/plaud_trigger.py', doraise=True); \
  py_compile.compile('triggers/youtube_ingest.py', doraise=True); \
  print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_pm_state_write.py -v
collected 5 items

tests/test_pm_state_write.py::test_extract_and_update_pm_state_tags_mutation_source PASSED [ 20%]
tests/test_pm_state_write.py::test_sidebar_hook_fires_on_ao_pm PASSED    [ 40%]
tests/test_pm_state_write.py::test_sidebar_hook_skipped_for_non_pm_capability PASSED [ 60%]
tests/test_pm_state_write.py::test_backfill_idempotency_skips_processed_rows PASSED [ 80%]
tests/test_pm_state_write.py::test_flag_pm_signal_push_slack_only_when_requested PASSED [100%]

============================== 5 passed in 0.20s ===============================
```

### 2. Full-suite regression delta

```
Baseline (main @ 3c4f9db, excluding tests/test_tier_normalization.py collection-only bug):
  799 passed, 24 failed, 21 skipped, 31 errors

Branch (feature/pm-sidebar-state-write-1):
  804 passed, 24 failed, 21 skipped, 31 errors

Delta: +5 passes = 5 new tests in tests/test_pm_state_write.py.
Failures: 24 == 24 (zero regressions).
Errors:   31 == 31 (zero regressions).
```

### 3. Per-deliverable summary

| Deliverable | File | Change |
|---|---|---|
| D1 | `orchestrator/capability_runner.py` | New module-level `extract_and_update_pm_state(...)` inserted at line 188 (after `PM_REGISTRY` close at 185, before `extract_correction_from_feedback`). `CapabilityRunner._auto_update_pm_state` retired to an 11-line thin wrapper delegating with `mutation_source="opus_auto"`. CROSS-PM-SIGNALS block preserved verbatim (peer_pms + signal_keyword_patterns + 3-signal cap + one-per-flag-per-peer break). |
| D2 | `outputs/dashboard.py` | Fast-path hook inserted after the capability-run-logging except block (between `logger.warning("Capability run logging failed...")` and the A8 block). Delegate-path hook inserted after the "Delegate logging failed" except block, before `yield "data: [DONE]"`. Both fire-and-forget via `threading.Thread(daemon=True)`, both gated on `cap.slug in PM_REGISTRY` / `cap_slugs ∩ PM_REGISTRY`. Tags: `sidebar` / `decomposer`. |
| D3 | `outputs/dashboard.py` | After `cap_slugs = [c.slug for c in plan.capabilities]`: mutate `req.project = cap.slug` when `plan.mode == "fast" and len(cap)==1 and slug in PM_REGISTRY`, or the first PM slug on delegate path. Guarded try/except to tolerate frozen pydantic instances. |
| D4 | `memory/store_back.py` + `scripts/backfill_pm_state.py` (NEW) | `_ensure_pm_backfill_processed_table` inserted after `_ensure_scheduler_executions_table` (line 588). Wired in `__init__` at line 154 (adjacent to `_ensure_scheduler_executions_table()`). PK `(pm_slug, conversation_id)`, index on `pm_slug`, `conn.rollback()` in except. Backfill script: parameterized SQL, `LIMIT 500` on both queries, `ON CONFLICT DO NOTHING`, `conn.rollback()` in except, non-fatal on extract-returns-None. |
| D5 | `briefs/_reports/PART_H_CAPABILITY_AUDIT_20260423.md` (NEW) | All 22 capabilities from `SELECT slug FROM capability_sets WHERE active=TRUE` enumerated. 2 client_pm (ao_pm, movie_am) — GAP fixed by this brief. 17 domain + 3 meta — read-only-intentional with caller file:line + reason. §H2 write-path closure, §H3 read-path completeness, §H4 tag inventory, §H5 test status included. |
| D6 | `orchestrator/pm_signal_detector.py` + `triggers/fireflies_trigger.py` + `triggers/plaud_trigger.py` + `triggers/youtube_ingest.py` | `push_slack: bool = False` kwarg on `flag_pm_signal`. On `True`, posts `*{LABEL}*: new {channel} ingest relevant to active thread.` to Director DM `D0AFY28N030` via `outputs.slack_notifier.post_to_channel` (reused existing helper). Wired at 6 call sites: fireflies 330/513/609, plaud 350/519, youtube 223. All 6 are `try/except` wrapped; all 6 pass `push_slack=True`. |

### 4. Files modified vs Files Modified list

| Brief §Files Modified entry | This PR? | Notes |
|---|---|---|
| `orchestrator/capability_runner.py` | ✅ | D1 |
| `outputs/dashboard.py` | ✅ | D2 + D3 |
| `memory/store_back.py` | ✅ | D4.1 DDL + wiring |
| `scripts/backfill_pm_state.py` (NEW) | ✅ | D4.2 |
| `orchestrator/pm_signal_detector.py` | ✅ | D6.1 |
| `triggers/fireflies_trigger.py` | ✅ | D6.2 / D6.4 (3 sites) |
| `triggers/plaud_trigger.py` | ✅ | D6.3 (2 sites) |
| `triggers/youtube_ingest.py` | ✅ | D6.5 |
| `outputs/slack_notifier.py` | ❌ not needed | `post_to_channel` already present at line 111 (PR #44). Brief §D6.6 confirms reuse. |
| `tests/test_pm_state_write.py` (NEW) | ✅ | 5 tests |
| `briefs/_reports/PART_H_CAPABILITY_AUDIT_20260423.md` (NEW) | ✅ | D5 |

### 5. Do NOT Touch — verified untouched

```
$ git diff main..feature/pm-sidebar-state-write-1 -- \
    triggers/email_trigger.py triggers/waha_webhook.py | wc -l
0
```

`triggers/email_trigger.py:865-869` and `triggers/waha_webhook.py:906-907,
962-964, 1074-1076` confirmed zero diff. Their existing `flag_pm_signal(...)`
calls keep the new `push_slack` kwarg at its default `False` → no behavior
change for email / WhatsApp signal volume.

CROSS-PM-SIGNALS block (`_auto_update_pm_state:1715-1736` pre-refactor)
re-emerged inside the new module-level function — preserved verbatim (signal
cap = 3, peer_keyword pattern lookup, `create_cross_pm_signal` kwargs, single
`break  # one signal per flag per peer`).

### 6. Rule compliance (SKILL Rules 7 / 8 / 10)

- **Rule 7 (file:line verify).** Every cited line in the brief was confirmed
  prior to editing:
  - `capability_runner.py` PM_REGISTRY close at 185 ✓, `extract_correction_from_feedback` at 188 ✓, `_auto_update_pm_state` at 1640 ✓, CROSS-PM-SIGNALS at 1715-1736 ✓
  - `dashboard.py` `_scan_chat_capability` at 7988 ✓, `cap_slugs = ...` at 8012 ✓, fast-path except at 8121 ✓, A8 block at 8123 ✓, delegate path at 8150 ✓, delegate `yield "data: [DONE]"` at 8187 ✓
  - `store_back.py` `_ensure_scheduler_executions_table` at 544 ✓, `__init__` wiring at 151 ✓
  - `pm_signal_detector.py` `flag_pm_signal` at 118 ✓, `detect_relevant_pms_meeting` at 80 ✓
  - `fireflies_trigger.py` `store_meeting_transcript` at 330 / 513 / 609 ✓
  - `plaud_trigger.py` `store_meeting_transcript` at 350 / 519 ✓
  - `youtube_ingest.py` `store_meeting_transcript` at 223 ✓
  - `slack_notifier.py` `def post_to_channel` at 111 ✓
  - `agent.py:2031` `update_pm_project_state(pm_slug, updates, summary)` call ✓ (observation, see §8)
- **Rule 8 (singleton pattern).** `bash scripts/check_singletons.sh` green.
  Every new `SentinelStoreBack` usage (`extract_and_update_pm_state`,
  `_ensure_pm_backfill_processed_table`, `backfill_pm_state.main`, signal
  detector push path) goes through `._get_global_instance()`.
- **Rule 10 (Part H).** The PR body carries the brief's §Part H §H1–H5 audit
  inline (brief lines 977-1027, unchanged from merge base). D5 adds the
  retroactive 22-cap audit as `briefs/_reports/PART_H_CAPABILITY_AUDIT_
  20260423.md`.

### 7. Python-backend quality checks

- `conn.rollback()` in every `except` touching `conn`:
  - `memory/store_back.py` `_ensure_pm_backfill_processed_table` inner except ✓
  - `scripts/backfill_pm_state.py` outer except ✓
- `LIMIT` on every SQL:
  - backfill main SELECT: `LIMIT 500` ✓
  - backfill processed-ids SELECT: `LIMIT 500` ✓
  - backfill INSERT: `ON CONFLICT (pm_slug, conversation_id) DO NOTHING` (idempotency PK)
- Parameterized SQL — no f-string/`%` interpolation into SQL body. Lookback
  window bound via `(str(int(days)),)` with `(%s || ' days')::interval` to
  keep int-validated parameter outside the SQL text.
- Model-client-response triple unchanged: `claude-opus-4-6` +
  `anthropic.Anthropic(...).messages.create(...)` + `resp.content[0].text`
  preserved from the pre-refactor path (Lesson #13).

### 8. Observations for follow-up (non-blocking)

- **`orchestrator/agent.py:2031`** calls `store.update_pm_project_state(pm_slug,
  updates, summary)` without a `mutation_source` kwarg — silently uses the
  column default `'auto'`. Minor Part H §H4 tag-hygiene gap flagged in the
  dispatch ("FYI, not your problem"). Recommend a one-line follow-up to pass
  `mutation_source='agent_tool'`. Not in this PR's scope.
- Baseline pytest on main has 24 failing tests + 31 collection errors + a
  TypeError blocking `tests/test_tier_normalization.py` collection entirely.
  Existing repo state, pre-dating this brief. Zero regressions introduced.

---

**Handoff:** `@ai-head-2 ready for review`. Tier A: AI Head #2 runs
`/security-review`, merges on APPROVE + green ship gate, then executes the
post-merge sequence per dispatch §"Post-ship sequence".

— B2
