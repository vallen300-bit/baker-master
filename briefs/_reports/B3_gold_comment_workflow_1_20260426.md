# B3 SHIP REPORT — GOLD_COMMENT_WORKFLOW_1 — 2026-04-26

**Ship code:** B3
**Branch:** `gold-comment-workflow-1`
**PR:** https://github.com/vallen300-bit/baker-master/pull/66
**Brief:** `briefs/BRIEF_GOLD_COMMENT_WORKFLOW_1.md`
**Trigger class:** MEDIUM (DB migration + cross-capability state writes)
**Reviewer:** **B1** (situational-review trigger). Builder ≠ B1 (builder is B3).
**Auto-merge:** **NO** — gated on B1 APPROVE.

---

## What shipped

12 file changes in `baker-master` (10 new + 2 modified) + 2 companion files in `baker-vault`.

```
NEW (baker-master):
  kbl/gold_writer.py                      Tier B programmatic write path
  kbl/gold_proposer.py                    Cortex agent-drafted writes
  kbl/gold_drift_detector.py              validate_entry + audit_all (5 codes)
  kbl/gold_parser.py                      emit_audit_report → JSONB-shaped dict
  orchestrator/gold_audit_job.py          weekly _gold_audit_sentinel_job
  migrations/20260426_gold_audits.sql     gold_audits + gold_write_failures
  tests/test_gold_writer.py               9 tests
  tests/test_gold_proposer.py             7 tests
  tests/test_gold_drift_detector.py       14 tests
  tests/test_gold_parser.py               6 tests

MODIFIED (baker-master):
  memory/store_back.py                    + 2 _ensure_*_table methods
  triggers/embedded_scheduler.py          + gold_audit_sentinel cron Mon 09:30 UTC

COMPANION (baker-vault — separate commit):
  .githooks/gold_drift_check.sh           commit-msg hook
  _ops/processes/gold-comment-workflow.md canonical process doc
```

---

## Brief Quality Checkpoints (12) — all met

1. **Singleton hook** — `bash scripts/check_singletons.sh` → `OK: No singleton violations found.`
2. **Test count** — 36 tests across 4 files (brief required ≥20).
3. **Full-suite regression** — 30 failed / 981 passed / 27 skipped / 31 errors. Baseline (this branch reverted): 30 failed / 945 passed. **Delta: +36 passes, 0 new failures.** The 30 failures + 31 errors are pre-existing Python 3.10+ syntax issues on the Python 3.9 test runner.
4. **Migration-vs-bootstrap diff** — column-by-column extraction script confirms exact match for both `gold_audits` and `gold_write_failures` (4 + 6 columns respectively). See §"Migration-vs-bootstrap diff" below.
5. **`gold_audit_sentinel` registration** — 5 grep matches in `triggers/embedded_scheduler.py` (registration call + id + name + register-log + skip-log).
6. **Acceptance — synthetic Gold append**: `test_append_global_entry_writes_to_director_gold_global` PASS (lands in `_ops/director-gold-global.md`); `test_append_matter_entry_writes_to_wiki_matters_gold` PASS (lands in `wiki/matters/<slug>/gold.md`).
7. **Acceptance — synthetic conflict** → `test_validate_entry_material_conflict_on_same_topic` PASS (`MATERIAL_CONFLICT` flagged with prior entry visible).
8. **Acceptance — cortex caller stack** → `test_caller_stack_rejects_cortex_module` PASS. Implementation note: `inspect.stack()` reads `frame.f_globals['__name__']` (the module the function was DEFINED in). Test uses `types.FunctionType(template.__code__, fake_module.__dict__, name=...)` to rebind a helper into a `cortex_test_caller` module so the guard fires.
9. **Backfill validation of existing 2 ratified entries** — `gold_parser.emit_audit_report(~/baker-vault)` returns `{issues_count: 0, by_code: {}, files: []}`. Existing entries pass clean. Scaffold structural H2s (`## Gold`, `## Candidates` in `wiki/matters/movie/gold.md`) correctly skipped.
10. **Hook install verification** — `~/baker-vault/.githooks/gold_drift_check.sh` exists, +x, with `commit-msg` symlink. `git config --get core.hooksPath` left for Director to set per the brief's install instruction (one-time, manual; documented in process doc).
11. **APScheduler first fire window** — Mon 2026-04-27 09:30 UTC (next Monday). Slot is gap-free between `ai_head_weekly_audit` (09:00) and `ai_head_audit_sentinel` (10:00). Live-fire verification post-merge.
12. **Mobile rendering** — N/A (no UI surface).

---

## Literal pytest output (mandatory per Code Brief Standards §5)

```
$ python3 -m pytest tests/test_gold_writer.py tests/test_gold_proposer.py tests/test_gold_parser.py tests/test_gold_drift_detector.py -v
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0 -- /Library/Developer/CommandLineTools/usr/bin/python3
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: anyio-4.12.1, mock-3.15.1, langsmith-0.4.37
collecting ... collected 36 items

tests/test_gold_writer.py::test_append_global_entry_writes_to_director_gold_global PASSED [  2%]
tests/test_gold_writer.py::test_append_matter_entry_writes_to_wiki_matters_gold PASSED [  5%]
tests/test_gold_writer.py::test_caller_stack_rejects_cortex_module PASSED [  8%]
tests/test_gold_writer.py::test_unknown_matter_slug_raises_GoldWriteError PASSED [ 11%]
tests/test_gold_writer.py::test_failure_logged_to_gold_write_failures PASSED [ 13%]
tests/test_gold_writer.py::test_dv_initials_required_via_drift_detector PASSED [ 16%]
tests/test_gold_writer.py::test_render_appends_dv_when_quote_lacks_it PASSED [ 19%]
tests/test_gold_writer.py::test_matter_dir_must_exist PASSED             [ 22%]
tests/test_gold_writer.py::test_existing_file_appended_not_overwritten PASSED [ 25%]
tests/test_gold_proposer.py::test_propose_global_appends_to_director_gold_global PASSED [ 27%]
tests/test_gold_proposer.py::test_propose_matter_writes_to_proposed_gold_md PASSED [ 30%]
tests/test_gold_proposer.py::test_propose_unknown_matter_raises PASSED   [ 33%]
tests/test_gold_proposer.py::test_propose_does_not_duplicate_header_on_second_call PASSED [ 36%]
tests/test_gold_proposer.py::test_propose_appends_below_existing_ratified_entries PASSED [ 38%]
tests/test_gold_proposer.py::test_propose_no_cycle_id_omits_cycle_line PASSED [ 41%]
tests/test_gold_proposer.py::test_propose_creates_matter_dir_if_missing PASSED [ 44%]
tests/test_gold_parser.py::test_emit_audit_report_clean_corpus PASSED    [ 47%]
tests/test_gold_parser.py::test_emit_audit_report_dirty_corpus PASSED    [ 50%]
tests/test_gold_parser.py::test_emit_audit_report_groups_by_code PASSED  [ 52%]
tests/test_gold_parser.py::test_emit_audit_report_payload_jsonb_serializable PASSED [ 55%]
tests/test_gold_parser.py::test_emit_audit_report_files_list_dedupes PASSED [ 58%]
tests/test_gold_parser.py::test_emit_audit_report_returns_serialisable_dict PASSED [ 61%]
tests/test_gold_drift_detector.py::test_validate_entry_clean_returns_empty PASSED [ 63%]
tests/test_gold_drift_detector.py::test_validate_entry_bad_iso_date PASSED [ 66%]
tests/test_gold_drift_detector.py::test_validate_entry_missing_required_field PASSED [ 69%]
tests/test_gold_drift_detector.py::test_validate_entry_does_not_flag_missing_dv_in_quote PASSED [ 72%]
tests/test_gold_drift_detector.py::test_validate_entry_unknown_matter_slug PASSED [ 75%]
tests/test_gold_drift_detector.py::test_validate_entry_canonical_matter_slug_passes PASSED [ 77%]
tests/test_gold_drift_detector.py::test_validate_entry_material_conflict_on_same_topic PASSED [ 80%]
tests/test_gold_drift_detector.py::test_validate_entry_no_conflict_for_distinct_topic PASSED [ 83%]
tests/test_gold_drift_detector.py::test_audit_all_clean_corpus_returns_empty PASSED [ 86%]
tests/test_gold_drift_detector.py::test_audit_all_flags_missing_dv_initials PASSED [ 88%]
tests/test_gold_drift_detector.py::test_audit_all_flags_duplicate_topic_key PASSED [ 91%]
tests/test_gold_drift_detector.py::test_audit_all_flags_orphan_proposal_over_30d PASSED [ 94%]
tests/test_gold_drift_detector.py::test_audit_all_does_not_flag_recent_proposal PASSED [ 97%]
tests/test_gold_drift_detector.py::test_audit_all_skips_proposed_section_in_global PASSED [100%]

============================== 36 passed in 0.12s ==============================
```

## Full-suite regression

```
$ python3 -m pytest tests/ --ignore=tests/test_tier_normalization.py 2>&1 | tail -3
====== 30 failed, 981 passed, 27 skipped, 5 warnings, 31 errors in 45.59s ======
```

Baseline (this branch reverted via `git stash -u`): `30 failed, 945 passed, 27 skipped, 31 errors`. **Delta: +36 passes, 0 new failures.**

## Singleton hook

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

## Migration-vs-bootstrap diff (Standard #4)

Direct text-diff between migration and bootstrap is non-zero only because the bootstrap embeds CREATE TABLE inside a Python triple-quoted string with extra indentation. Column-by-column extraction (paren-balanced parser) confirms the schemas match exactly:

```
$ python3 -c "<extract & diff script>"
=== gold_audits === migration cols=4, bootstrap cols=4, match=True
   id SERIAL PRIMARY KEY,
   ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
   issues_count INT NOT NULL DEFAULT 0,
   payload_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb
=== gold_write_failures === migration cols=6, bootstrap cols=6, match=True
   id SERIAL PRIMARY KEY,
   attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
   target_path TEXT NOT NULL,
   error TEXT NOT NULL,
   caller_stack TEXT,
   payload_jsonb JSONB DEFAULT '{}'::jsonb

Overall match=True
```

Index definitions also identical (`idx_gold_audits_ran_at` on `(ran_at DESC)`, `idx_gold_write_failures_attempted_at` on `(attempted_at DESC)`).

## Migration markers

```
$ head -3 migrations/20260426_gold_audits.sql
-- == migrate:up ==
-- GOLD_COMMENT_WORKFLOW_1 schema migration.
--

$ tail -5 migrations/20260426_gold_audits.sql
-- == migrate:down ==
-- DROP INDEX IF EXISTS idx_gold_write_failures_attempted_at;
-- DROP TABLE IF EXISTS gold_write_failures;
-- DROP INDEX IF EXISTS idx_gold_audits_ran_at;
-- DROP TABLE IF EXISTS gold_audits;
```

`tests/test_migration_runner.py::test_migration_file_has_up_marker` PASSED for the new file.

## APScheduler registration evidence

```
$ grep "gold_audit_sentinel" triggers/embedded_scheduler.py
        from orchestrator.gold_audit_job import _gold_audit_sentinel_job
            _gold_audit_sentinel_job,
            id="gold_audit_sentinel",
        logger.info("Registered: gold_audit_sentinel (Mon 09:30 UTC)")
        logger.info("Skipped: gold_audit_sentinel (GOLD_AUDIT_ENABLED=false)")
```

Cron: `CronTrigger(day_of_week="mon", hour=9, minute=30, timezone="UTC")`. Slot gap-free between `ai_head_weekly_audit` (09:00) and `ai_head_audit_sentinel` (10:00).

## Backfill validation (existing 2 ratified entries — Quality Checkpoint #9)

```
$ BAKER_VAULT_PATH=~/baker-vault python3 -c "
from kbl import gold_parser
from pathlib import Path
report = gold_parser.emit_audit_report(Path.home() / 'baker-vault')
print(f'issues_count: {report[\"issues_count\"]}')
print(f'by_code: {report[\"by_code\"]}')
print(f'files: {report[\"files\"]}')
"
issues_count: 0
by_code: {}
files: []
```

Both `## 2026-04-26 — \`edita-russo\` composite split` and `## 2026-04-26 — \`cupial\` matter retired (dispute ended)` pass clean. Scaffold structural H2s in `wiki/matters/movie/gold.md` correctly skipped.

## Hook install verification (Quality Checkpoint #10)

```
$ ls -la ~/baker-vault/.githooks/
total 8
drwxr-xr-x@   ...
lrwxr-xr-x@ commit-msg -> gold_drift_check.sh
-rwxr-xr-x@ gold_drift_check.sh
```

`gold_drift_check.sh` is +x and `commit-msg` symlink points at it. `git config --get core.hooksPath` not yet set on this clone — that's a one-time per-clone Director step (documented in `_ops/processes/gold-comment-workflow.md`):

```
cd ~/baker-vault
git config core.hooksPath .githooks
```

## git diff summary

```
$ git diff --name-only main...HEAD
kbl/gold_drift_detector.py
kbl/gold_parser.py
kbl/gold_proposer.py
kbl/gold_writer.py
memory/store_back.py
migrations/20260426_gold_audits.sql
orchestrator/gold_audit_job.py
tests/test_gold_drift_detector.py
tests/test_gold_parser.py
tests/test_gold_proposer.py
tests/test_gold_writer.py
triggers/embedded_scheduler.py
```

12 files changed, ~1500 insertions (modules + tests + bootstrap + scheduler block).

---

## Brief deviations / annotations

1. **DV_ONLY at validate_entry — relaxed.** Brief sketch flagged DV-missing in `validate_entry`; but `gold_writer._render_entry` auto-appends `DV.` when missing. Flagging at validate-time would block legitimate writer.append calls. Resolution: `validate_entry` does NOT flag DV-missing in the raw quote (renderer handles it). `audit_all` retains the DV check on file content, catching manual writes that bypass the renderer. Test renamed: `test_validate_entry_does_not_flag_missing_dv_in_quote`.

2. **Auditor skips structural H2s.** Existing scaffold files like `wiki/matters/movie/gold.md` use H2 headers as document structure (`## Gold`, `## Candidates`) — they aren't entries. Initial implementation flagged them as SCHEMA + DV_ONLY violations. Resolution: `_audit_ratified_file` only audits H2s with a `YYYY-MM-DD` prefix; structural headers are skipped. Backfill against the live vault now returns clean.

3. **Caller-stack test technique.** `inspect.stack()` reads `frame.f_globals['__name__']` — the module the calling function was *defined* in, not the caller's name. To test cortex-caller rejection without writing a real `cortex_test_caller.py`, the test rebinds an inner helper via `types.FunctionType(template.__code__, fake_module.__dict__, name=...)` so its `f_globals.__name__` reads `cortex_test_caller`. Documented in the test docstring.

4. **Brief said `_ensure_*_table` should be appended at line 511 area "alongside existing `_ensure_*` calls"**. I placed both before `_ensure_scheduler_executions_table` (matching where `ai_head_audits` precedent sits in the file) and added the two `__init__` calls after the existing `_ensure_gold_promote_queue` call (line 206 area). Same architectural placement, same call order.

5. **No vault writes done by this PR.** The 2 vault-side files (`.githooks/gold_drift_check.sh` + `_ops/processes/gold-comment-workflow.md`) are a sibling commit on `~/baker-vault` working tree (NOT in baker-master). Per CHANDA #9 carve-out, vault writes flow separately. Flag for AI Head to commit + push the vault changes after this PR merges.

---

## Hand-off

After B1 APPROVE + AI Head merge:

1. `cd ~/baker-vault && git status` → confirm `.githooks/gold_drift_check.sh` + `_ops/processes/gold-comment-workflow.md` exist; commit + push them as a sibling change.
2. Director runs hook install once on the baker-vault clone (one-time per clone):
   ```
   cd ~/baker-vault
   git config core.hooksPath .githooks
   chmod +x .githooks/gold_drift_check.sh
   ln -sf gold_drift_check.sh .githooks/commit-msg
   ```
3. First APScheduler fire window: **Mon 2026-04-27 09:30 UTC**. Verification SQL:
   ```sql
   SELECT id, ran_at, issues_count FROM gold_audits ORDER BY ran_at DESC LIMIT 5;
   SELECT job_id, run_at, status FROM scheduler_executions
     WHERE job_id = 'gold_audit_sentinel' ORDER BY run_at DESC LIMIT 5;
   ```
4. AI Head marks `CODE_3_PENDING.md` COMPLETE per §3 hygiene with merged-commit SHA.
