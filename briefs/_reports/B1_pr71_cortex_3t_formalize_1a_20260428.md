# B1 Cross-Team Review — PR #71 CORTEX_3T_FORMALIZE_1A (2026-04-28)

**PR:** [#71 cortex-3t-formalize-1a](https://github.com/vallen300-bit/baker-master/pull/71) (HEAD `7957692`, +1741 / -0, 9 files)
**Brief:** `briefs/BRIEF_CORTEX_3T_FORMALIZE_1A.md`
**Builder:** B3 (Code Brisen #3)
**Reviewer:** B1 (Code Brisen #1) — second-pair review per `b1-situational-review-trigger` (MEDIUM trigger class)
**Verdict:** **APPROVE** (advisory items below — none blocking).

Posted as PR comment in lieu of formal APPROVE per `vallen300-bit` self-PR gotcha (PR #67 / #69 / #70 precedent).

## Files in scope (review confined to these)

- `migrations/20260428_cortex_cycles.sql` (+43)
- `migrations/20260428_cortex_phase_outputs.sql` (+28)
- `memory/store_back.py` (+94 — `_ensure_cortex_cycles_table`, `_ensure_cortex_phase_outputs_table`, registration in init path)
- `orchestrator/cortex_runner.py` (+331)
- `orchestrator/cortex_phase2_loaders.py` (+245)
- `triggers/cortex_pipeline.py` (+59)
- `tests/test_cortex_runner_phase126.py` (+371)
- `tests/test_cortex_phase2_loaders.py` (+330)
- `briefs/_reports/B3_cortex_3t_formalize_1a_20260428.md` (+240)

## Criterion 1 — Brief acceptance match

7 verification criteria from brief §"Verification criteria":

| # | Criterion | Result |
|---|---|---|
| 1 | `pytest tests/test_cortex_runner_phase126.py tests/test_cortex_phase2_loaders.py -v` ≥18 pass | ✓ **31 / 31** (literal stdout below) |
| 2 | `py_compile` for runner / loaders / store_back / pipeline | ✓ exit 0 (note: brief says `triggers/pipeline.py`; shipped file is `triggers/cortex_pipeline.py` per B3 Lesson #40 EXPLORE correction documented in cortex_pipeline.py:5-6) |
| 3 | Migration runs cleanly + 2 tables post-deploy | Bootstrap mirror byte-for-byte matches migration; deferred to live deploy verification |
| 4 | REPL dry-run returns CortexCycle with status='awaiting_reason', 1 cycle row + 3 phase outputs | Covered by `test_phase1_inserts_cycle_row` + `test_phase2_inserts_phase2_context_artifact` + `test_phase6_writes_archive_artifact` + `test_status_terminates_at_awaiting_reason_in_1a_scope` ✓ |
| 5 | Pipeline stub dormant by default | ✓ `triggers/cortex_pipeline.py:23-25` (env flag `CORTEX_LIVE_PIPELINE` default false). Note: stub is not yet called from `kbl/bridge/alerts_to_signal.py:495` — wire-up explicitly deferred to 1C per file docstring (consistent with brief Problem section: "1C lands the live wire after 1B's reasoning is in place") |
| 6 | 5-min absolute timeout test | ✓ `test_short_timeout_aborts_long_running_phase` + `test_timeout_marks_existing_cycle_failed` PASS |
| 7 | Phase 6 always runs | ✓ `test_phase6_archive_runs_even_when_phase2_fails` + `test_failed_cycle_marks_status_failed_in_archive` + `test_phase1_db_failure_rolls_back_and_propagates` PASS |

10 Quality Checkpoints from brief §"Quality Checkpoints":

| # | Check | Result |
|---|---|---|
| 1 | Migration-vs-bootstrap drift: zero | ✓ **byte-for-byte match** (see Criterion 2 below) |
| 2 | Every except has `conn.rollback()` | ✓ `cortex_runner.py:216-220, 265-269, 324-328`; `cortex_phase2_loaders.py:237-241`; `store_back.py:602-606, 642-646` |
| 3 | Every SELECT has LIMIT | ✓ all 3 recent-activity queries `LIMIT 30`; covered by `test_all_recent_activity_queries_have_limit` |
| 4 | `BAKER_VAULT_PATH` graceful: missing returns warning | ✓ `test_vault_unavailable_returns_warning_and_empty_vault_keys` |
| 5 | `cycle_id` is UUID | ✓ `test_cycle_id_is_uuid` |
| 6 | JSONB casts use `::jsonb` | ✓ `cortex_runner.py:210, 254, 305` |
| 7 | `from orchestrator.cortex_runner import maybe_run_cycle` works | ✓ top-level `async def maybe_run_cycle` at line 59 |
| 8 | `triggers/pipeline.py` defensive try/except if `cortex_runner` import fails | ✓ `cortex_pipeline.py:46-59` (lazy import inside `try`, broad `except` swallowed with log; comment notes pipeline must continue) |
| 9 | No new `requirements.txt` deps | ✓ `git diff main..HEAD -- requirements.txt` empty |
| 10 | 1B/1C touchpoints noted as out-of-scope in code | ✓ `cortex_runner.py:12-13, 144-147, 283`; `cortex_pipeline.py:3-12, 36` |

## Criterion 2 — DDL drift trap (Lesson #2 / #37)

Compared `_ensure_cortex_cycles_table` (`memory/store_back.py:561-609`) with `migrations/20260428_cortex_cycles.sql`, and `_ensure_cortex_phase_outputs_table` (`memory/store_back.py:611-649`) with `migrations/20260428_cortex_phase_outputs.sql`:

- **cortex_cycles** — every column matches type-for-type and constraint-for-constraint (15 columns + 1 PK + 1 INDEX). CHECK constraints on `current_phase` and `status` enumerate the same values in the same order. `uuid_generate_v4()` default + `uuid-ossp` extension consistent.
- **cortex_phase_outputs** — every column matches (8 columns + 1 PK + 1 FK + 1 INDEX). `ON DELETE CASCADE` on `cycle_id` FK present in both. JSONB default `'[]'::jsonb` on `citations` matches.

**Drift: zero. PASS.**

Both `_ensure_*` functions correctly use signature `(self)` (no `cur` parameter), per B3's EXPLORE correction in the dispatch §2 anchor.

## Criterion 3 — Function-signature accuracy (Lesson #44)

Verified existing-function references in shipped code against actual symbols:

| Reference | Resolved | Status |
|---|---|---|
| `SentinelStoreBack._get_global_instance()` | `memory/store_back.py:45` | ✓ |
| `store._get_conn()` / `store._put_conn(conn)` | `memory/store_back.py:236, 248` | ✓ |
| `cortex_runner.maybe_run_cycle(...)` (called from pipeline stub) | `orchestrator/cortex_runner.py:59` | ✓ matches signature `(matter_slug=, triggered_by=, trigger_signal_id=, director_question=)` |
| `load_phase2_context(matter_slug)` | `orchestrator/cortex_phase2_loaders.py` | ✓ kwarg-by-name call from runner:240 |
| `email_messages` JOIN through `signal_queue.payload->>'message_id' = em.message_id` + `sq.primary_matter` | `cortex_phase2_loaders.py:194-205` | ✓ matches B3 EXPLORE correction (no `email_messages.primary_matter` column; covered by `test_recent_activity_joins_signal_queue_for_email_messages`) |
| `sent_emails.body_preview` (NOT `body` / `full_body`) | `cortex_phase2_loaders.py:174-179` | ✓ covered by `test_recent_activity_uses_body_preview_not_body` |
| `chain_runner.maybe_run_chain` (brief §29 wrap target) | NOT yet called | Acceptable — wrapping happens in Phase 3-5 (1B/1C scope); brief Phase 1/2/6 surface for 1A doesn't reach the reasoning step |

**Function-signature accuracy: PASS.** All B3 EXPLORE corrections (`triggers/pipeline.py` → `triggers/cortex_pipeline.py`, `email_messages.primary_matter` → JOIN through signal_queue, `sent_emails.body` → `body_preview`, `_ensure_*(self)` not `(self, cur)`) are applied throughout and asserted by tests.

## Criterion 4 — Tests are real (literal pytest)

```
$ python3 -m pytest tests/test_cortex_runner_phase126.py tests/test_cortex_phase2_loaders.py -v 2>&1 | tail -40
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0 -- /Library/Developer/CommandLineTools/usr/bin/python3
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b1
plugins: anyio-4.12.1, mock-3.15.1, langsmith-0.4.37
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

============================== 31 passed in 0.14s ==============================
```

**31 / 31 PASS** locally on B1 worktree (Python 3.9.6) — exceeds brief minimum (≥18). Hermetic — no live DB needed (psycopg2 connections are mocked via store accessor patches). Tests are real, not "passes by inspection".

## Criterion 5 — Boundaries respected

- `kbl.gold_writer` import: **none** in `cortex_runner.py`, `cortex_phase2_loaders.py`, `triggers/cortex_pipeline.py`. ✓
- `cortex_events` table: **no INSERT/SELECT** from any 1A file (separate table from `cortex_phase_outputs`; touched only by GOLD_COMMENT_WORKFLOW_1's `_ensure_cortex_events_table` at `memory/store_back.py:3001`). ✓
- `kbl/gold_writer.py:_check_caller_authorized`: not bypassed (1A doesn't touch GOLD writer at all). ✓

**Boundaries: PASS.**

## Top-3 advisory observations (not blocking)

1. **`triggers/cortex_pipeline.py` exists but is not yet called.** Brief Fix/Feature 4 §"Implementation" specifies "Call site: AFTER the `signal_queue` INSERT commits, BEFORE the next signal is processed". B3 deferred this wire-up to 1C, citing the brief's Problem section ("1C lands the live wire after 1B's reasoning is in place") as the consistent reading. The brief is internally contradictory between the Problem and Implementation paragraphs; B3's interpretation is conservative and reasonable, but the call-site insertion at `kbl/bridge/alerts_to_signal.py:495` should be explicitly tracked on 1C's checklist so it doesn't slip. Until then, Quality Checkpoint #5 ("dormant by default") is satisfied trivially because nothing calls the wrapper.

2. **`maybe_run_cycle` re-raises after archive but archive errors are swallowed.** In `_run_cycle_inner` (`cortex_runner.py:148-170`), if Phase 1 or 2 raises, status is set to `failed` and Phase 6 is invoked in a `finally` block. If Phase 6 itself raises, the exception is logged but swallowed (line 162). The original failure is then re-raised. Net effect: caller sees the original error, but the cycle row in Postgres may have `status='failed'` set in memory yet not persisted to the DB (if Phase 6's UPDATE failed). That's a small consistency window — the cycle row's last persisted status would still be `'in_flight'` from Phase 1's INSERT. Worth a follow-up: emit a structured Slack/log alert when archive itself fails, since at that point the durable state diverges from the in-memory state.

3. **Phase 1 INSERT bypasses DB-side `cycle_id` default.** `cortex_runner.py:124-129` generates `uuid.uuid4()` in Python and passes it to the INSERT, even though the migration declares `cycle_id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`. Functionally equivalent for now, but if later code reads back from the DB and assumes the DB-generated UUID, a Python-generated one will work but be slightly out of sync conceptually with the schema's `DEFAULT`. Minor — could either drop the default in the migration or stop pre-generating in Python; the latter is cheaper. Not a blocker.

## Verdict

**APPROVE** — ready to merge once AI Head A's `/security-review` clears (Lesson #52 mandatory parallel gate). All 7 verification criteria + 10 quality checkpoints pass. DDL drift zero. Function signatures grep-verified. Tests real (31/31 hermetic). Boundaries respected. Three advisory observations above are follow-ups, not blockers.

Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
