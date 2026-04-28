# B3 SHIP REPORT — CORTEX_3T_FORMALIZE_1A

**Date:** 2026-04-28
**Author:** Code Brisen #3 (Claude Opus 4.7, 1M context)
**Brief:** `briefs/BRIEF_CORTEX_3T_FORMALIZE_1A.md` (sub-brief 1A of 3 for Cortex Stage 2 V1)
**Branch:** `cortex-3t-formalize-1a`
**PR:** https://github.com/vallen300-bit/baker-master/pull/71
**Trigger class:** MEDIUM (2 Postgres migrations + new orchestrator module + pipeline wiring) → B1 second-pair review pre-merge

---

## What shipped

The shell of Cortex Stage 2 V1 — schema + runner + Phase 1/2/6. Phase 3-5
are stubbed; cycle parks at `status='awaiting_reason'` until 1B/1C land.

| Layer | File | Lines |
|---|---|---|
| Migration | `migrations/20260428_cortex_cycles.sql` | 43 |
| Migration | `migrations/20260428_cortex_phase_outputs.sql` | 28 |
| Bootstrap mirror | `memory/store_back.py` (additive) | +94 |
| Runner | `orchestrator/cortex_runner.py` | 322 |
| Phase 2 loaders | `orchestrator/cortex_phase2_loaders.py` | 226 |
| Pipeline stub | `triggers/cortex_pipeline.py` | 56 |
| Tests | `tests/test_cortex_runner_phase126.py` | 357 |
| Tests | `tests/test_cortex_phase2_loaders.py` | 339 |

Total: 1,501 LOC additions across 8 files. Zero edits to existing live
code paths beyond the additive `_ensure_*_table` calls in
`store_back.py:__init__`.

---

## EXPLORE results (Lesson #44 — verified before coding)

Three brief assumptions did not match production schema/paths and were
corrected before any code shipped:

1. **`triggers/pipeline.py` does not exist.** The actual
   `INSERT INTO signal_queue` lives at `kbl/bridge/alerts_to_signal.py:495`.
   Created `triggers/cortex_pipeline.py` (NEW) with the env-flag-dormant
   stub; 1C will land the call-site wire-up after dry-run validation.
2. **`email_messages.primary_matter` does not exist** (verified at
   `memory/store_back.py:1177-1188` — schema has `message_id, thread_id,
   sender_name, sender_email, subject, full_body, received_date,
   priority, ingested_at`). Phase 2 entity-inbound query JOINs through
   `signal_queue` (which carries `primary_matter` per migration
   `20260418_step1_signal_queue_columns.sql`). Brief's EXPLORE checklist
   anticipated this fallback.
3. **`sent_emails.body` does not exist** — actual column is `body_preview`
   (verified at `models/sent_emails.py:39-52`). Phase 2 director-outbound
   query uses `body_preview ILIKE %s`.

Plus three robustness-grade tweaks not in the brief snippet:

- `_ensure_*_table` corrected from `(self, cur)` to `(self)` to match the
  canonical `_ensure_ai_head_audits_table` pattern at
  `memory/store_back.py:518-559` (each function manages its own
  conn/cur/commit/rollback/put_conn).
- Phase 1 sense payload uses `json.dumps` instead of the brief's
  `'%s' %` string interpolation (which would break on a matter slug
  containing a `"`).
- Phase 6 archive UPDATE captures `cycle.status` so `status='failed'`
  persists through the always-runs archive path (not just `current_phase`).

---

## DDL drift check — migrations vs bootstrap mirror

```
=== cortex_cycles drift ===          MATCH
=== cortex_phase_outputs drift ===   MATCH
```

Normalized column-name/type comparison via Python diff (whitespace + SQL
inline comments stripped). Zero drift on both tables.

---

## Ship gate — literal pytest output

```
$ pytest tests/test_cortex_runner_phase126.py tests/test_cortex_phase2_loaders.py -v 2>&1 | tail -45
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 31 items

tests/test_cortex_runner_phase126.py::test_cycle_id_is_uuid PASSED       [  3%]
tests/test_cortex_runner_phase126.py::test_status_terminates_at_awaiting_reason_in_1a_scope PASSED [  6%]
tests/test_cortex_runner_phase126.py::test_phase1_inserts_cycle_row PASSED [  9%]
tests/test_cortex_runner_phase126.py::test_phase1_inserts_sense_artifact_with_correct_phase PASSED [ 12%]
tests/test_cortex_runner_phase126.py::test_phase1_payload_is_valid_json PASSED [ 16%]
tests/test_cortex_runner_phase126.py::test_phase2_calls_load_phase2_context_with_matter_slug PASSED [ 19%]
tests/test_cortex_runner_phase126.py::test_phase2_inserts_phase2_context_artifact PASSED [ 22%]
tests/test_cortex_runner_phase126.py::test_phase2_updates_last_loaded_at PASSED [ 25%]
tests/test_cortex_runner_phase126.py::test_phase2_loader_returned_dict_persists_in_cycle_state PASSED [ 29%]
tests/test_cortex_runner_phase126.py::test_phase6_writes_archive_artifact PASSED [ 32%]
tests/test_cortex_runner_phase126.py::test_phase6_sets_completed_at_and_final_status PASSED [ 35%]
tests/test_cortex_runner_phase126.py::test_phase6_archive_runs_even_when_phase2_fails PASSED [ 38%]
tests/test_cortex_runner_phase126.py::test_failed_cycle_marks_status_failed_in_archive PASSED [ 41%]
tests/test_cortex_runner_phase126.py::test_phase1_db_failure_rolls_back_and_propagates PASSED [ 45%]
tests/test_cortex_runner_phase126.py::test_short_timeout_aborts_long_running_phase PASSED [ 48%]
tests/test_cortex_runner_phase126.py::test_timeout_marks_existing_cycle_failed PASSED [ 51%]
tests/test_cortex_phase2_loaders.py::test_vault_unavailable_returns_warning_and_empty_vault_keys PASSED [ 54%]
tests/test_cortex_phase2_loaders.py::test_vault_present_but_matter_dir_missing PASSED [ 58%]
tests/test_cortex_phase2_loaders.py::test_load_phase2_context_happy_path PASSED [ 61%]
tests/test_cortex_phase2_loaders.py::test_read_or_empty_caps_at_max_bytes PASSED [ 64%]
tests/test_cortex_phase2_loaders.py::test_read_or_empty_returns_empty_for_missing PASSED [ 67%]
tests/test_cortex_phase2_loaders.py::test_load_curated_dir_alphabetical PASSED [ 70%]
tests/test_cortex_phase2_loaders.py::test_load_curated_dir_empty_when_missing PASSED [ 74%]
tests/test_cortex_phase2_loaders.py::test_load_cortex_meta_returns_three_keys PASSED [ 77%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_uses_body_preview_not_body PASSED [ 80%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_joins_signal_queue_for_email_messages PASSED [ 83%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_baker_actions_query_present PASSED [ 87%]
tests/test_cortex_phase2_loaders.py::test_all_recent_activity_queries_have_limit PASSED [ 90%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_no_db_returns_empty_lists PASSED [ 93%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_handles_db_exception_gracefully PASSED [ 96%]
tests/test_cortex_phase2_loaders.py::test_recent_activity_serializes_datetimes_to_isoformat PASSED [100%]

============================== 31 passed in 0.04s ==============================
```

**31 / 31 pass** — exceeds the brief minimum (≥18). Test breakdown:
16 runner tests covering Phase 1+2+6 happy/error/timeout paths;
15 loader tests covering vault graceful degradation, file-byte caps,
SQL-assertion verification of the EXPLORE-corrected column references
(body_preview / signal_queue JOIN / LIMIT clauses), and DB-exception
rollback.

---

## Other verifications

| Check | Command | Result |
|---|---|---|
| Syntax gate | `python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_runner.py', doraise=True); ...4 files"` | exit 0 ✓ |
| DDL drift | normalized diff of migration vs bootstrap mirror for both tables | **MATCH MATCH** |
| Full-suite vs `main` | `pytest tests/ -q --deselect tests/test_1m_storeback_verify.py` | branch: 31 fail / 1102 pass ; main: 67 fail / 1071 pass — **+31 passes, 0 NEW failures** |
| Cortex-specific full-suite | `grep "FAILED.*cortex"` against full suite | **0 failures** |

Pre-existing failures on `main` (clickup MagicMock issues, vault test
isolation errors, scan endpoint 503s, etc.) are unrelated to this PR.

### Test pollution mitigation note

During build, an early test fixture used
`monkeypatch.setattr("memory.store_back.SentinelStoreBack", ...)` which
worked in isolation but failed in some full-suite orderings (some earlier
test had imported `memory.store_back` differently, causing
`AttributeError: module 'memory' has no attribute 'store_back'`).

**Fix applied:** factored a module-level `_get_store()` helper in
`orchestrator/cortex_phase2_loaders.py` and patched THAT in the test
fixture instead of the `memory.store_back` attribute path. Stable across
all suite orderings now. This is a hardening pattern other tests in the
suite would benefit from (separate cleanup for a future brief — not in
scope here).

---

## Lesson references

- **#44** (Verify SSE shape / function signatures / schema before coding) —
  EXPLORE step caught `triggers/pipeline.py` non-existence,
  `email_messages.primary_matter` absence, `sent_emails.body` absence,
  and `_ensure_*_table` signature pattern. All corrected before code
  shipped.
- **#37** (Schema belongs in migrations, not Python `_ensure_*` only) —
  shipped both migration files AND mirror methods; mirror is
  belt-and-braces until migration runner has claimed the file in prod.
- **#42** (Fixture-only tests can't catch schema drift) — added
  SQL-assertion tests that capture `cursor.execute` queries and assert
  canonical column names (`body_preview`, `signal_queue.primary_matter`,
  `LIMIT` presence). Catches what fixture-only tests would miss.
- **#52** (AI Head reviewer must run `/security-review` skill against PR
  branch before merge) — flagged in PR test plan; non-substitutable.
- **#1** (Every `except` does `conn.rollback()` and every SELECT has
  LIMIT) — covered by code structure + `test_all_recent_activity_queries_have_limit`.

---

## Quality checkpoints (brief §Quality Checkpoints)

1. ✅ Migration-vs-bootstrap drift: **zero** (verified twice — once with
   simple `diff`, once with normalized Python-stripped column-name diff).
2. ✅ Every `except` block has `conn.rollback()` — Phase 1 sense, Phase 2
   load, Phase 6 archive, Phase 2 loaders' `_load_recent_activity`.
3. ✅ Every SELECT has `LIMIT` — covered by
   `test_all_recent_activity_queries_have_limit` (assertion on every
   captured SQL).
4. ✅ `BAKER_VAULT_PATH` graceful: missing path → empty matter keys +
   `vault_available: False` flag + recent_activity still attempted.
5. ✅ `cycle_id` is UUID — `test_cycle_id_is_uuid` parses it via
   `uuid.UUID(cycle.cycle_id)`.
6. ✅ JSONB casts via `::jsonb` in INSERT (Phase 1 sense, Phase 2 load,
   Phase 6 archive).
7. ✅ `from orchestrator.cortex_runner import maybe_run_cycle` works
   post-deploy (smoke import passes).
8. ✅ Pipeline stub catches all exceptions in `_maybe_trigger_cortex` so
   signal-pipeline boot never breaks because of Cortex.
9. ✅ No new entries in `requirements.txt`.
10. ✅ 1B (Phase 3) and 1C (Phase 4-5 + scheduler + dry-run + rollback)
    explicitly noted as out-of-scope in module docstrings + brief §Out of
    scope reproduced in PR description.

---

## Out of scope (per brief)

- Phase 3 reasoning — 1B's territory
- Phase 4 proposal card / Phase 5 act / GOLD propagation — 1C
- Slack Block Kit posting / `/cortex/cycle/{id}/action` endpoint — 1C
- APScheduler matter-config drift weekly job — 1C
- Step 29 DRY_RUN flag — 1C
- Step 33 rollback script — 1C
- Live pipeline activation (`CORTEX_LIVE_PIPELINE=true`) — 1C decommission
- Decommission of `ao_signal_detector` / `ao_project_state` —
  Step 34-35, post-1C, Director-consult

---

## Next steps

1. AI Head B (or whichever AI Head holds dispatch authority for this
   batch) routes PR #71 to B1 second-pair review (MEDIUM trigger class).
2. AI Head reviewer invokes `/security-review` skill against branch
   `cortex-3t-formalize-1a` (Lesson #52 — non-substitutable).
3. On APPROVE + `/security-review` PASS, AI Head Tier-A merge.
4. Post-merge verification:
   - `\dt cortex_*` on Neon → 2 tables created.
   - From Python REPL on Render: `await maybe_run_cycle(matter_slug='oskolkov', triggered_by='director')`
     → `cycle_id` UUID returned, 1 row in `cortex_cycles` with
     `status='awaiting_reason'` + `current_phase='archive'` +
     `completed_at NOT NULL`, 3 rows in `cortex_phase_outputs`
     (sense / load / archive).
5. 1B (Phase 3) and 1C (Phase 4-5 + scheduler + dry-run + rollback) brief
   dispatch is AI Head territory once 1A merges.
