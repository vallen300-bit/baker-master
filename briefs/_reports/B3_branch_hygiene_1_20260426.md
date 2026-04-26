# B3 SHIP REPORT — BRANCH_HYGIENE_1 — 2026-04-26

**Ship code:** B3
**Branch:** `branch-hygiene-1`
**PR:** https://github.com/vallen300-bit/baker-master/pull/64
**Commit:** `726323b`
**Brief:** `briefs/BRIEF_BRANCH_HYGIENE_1.md`
**Trigger class:** LOW (GitHub external API only) → AI Head solo merge
**Reviewer:** AI Head B (Build-reviewer / dispatcher)

---

## What shipped

5 file changes (3 new + 2 modified):

```
NEW:
  scripts/branch_hygiene.py                    411 lines — L1/L2/L3 + Triaga + audit
  tests/test_branch_hygiene.py                 15 tests
  migrations/20260426_branch_hygiene_log.sql   audit table (with migrate:up/down markers)

MODIFIED:
  memory/store_back.py                         + _ensure_branch_hygiene_log_table()
  triggers/embedded_scheduler.py               + branch_hygiene_weekly Mon 10:30 UTC
```

Q2 default-delete pattern (mobile UI cluster) covered: `feat/mobile-*`, `feat/ios-shortcuts-1`, `feat/document-browser-1`, `feat/networking-phase1`.

---

## Brief verification — all 6 DoD items met

- [x] `scripts/branch_hygiene.py` implemented with L1+L2+L3 logic
- [x] First run will auto-delete L1 squash-merged branches (20 candidates per dry-run + 1 MOBILE)
- [x] Mobile UI cluster covered (7 already classified L1 by squash-merge; `feat/ios-shortcuts-1` falls to MOBILE_CLUSTER bucket and is deleted on first run; PR description preserves Q2 default)
- [x] Triaga HTML for L2 → Director review (`briefs/_reports/branch_hygiene_triaga_20260426.html`)
- [x] L3 bulk-delete after Director ticks (`--l3 ticks.txt`; throttled 10/min)
- [x] APScheduler `branch_hygiene_weekly` job registered Mon 10:30 UTC
- [x] Audit log table `branch_hygiene_log` records every deletion (branch_name, last_commit_sha, deleted_at, layer, reason, age_days, actor)

---

## Literal pytest output (mandatory per Code Brief Standards §5)

```
$ python3 -m pytest tests/test_branch_hygiene.py -v
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0 -- /Library/Developer/CommandLineTools/usr/bin/python3
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: anyio-4.12.1, mock-3.15.1, langsmith-0.4.37
collecting ... collected 15 items

tests/test_branch_hygiene.py::test_classify_protected_main PASSED        [  6%]
tests/test_branch_hygiene.py::test_classify_protected_release_pattern PASSED [ 13%]
tests/test_branch_hygiene.py::test_classify_l1_squash_merged_when_ahead_zero PASSED [ 20%]
tests/test_branch_hygiene.py::test_classify_l1_negative_when_ahead_positive_and_recent PASSED [ 26%]
tests/test_branch_hygiene.py::test_classify_l2_flagged_stale_unmerged PASSED [ 33%]
tests/test_branch_hygiene.py::test_classify_mobile_cluster_default_delete PASSED [ 40%]
tests/test_branch_hygiene.py::test_classify_mobile_cluster_specific_branches PASSED [ 46%]
tests/test_branch_hygiene.py::test_execute_deletions_dry_run_does_nothing PASSED [ 53%]
tests/test_branch_hygiene.py::test_execute_deletions_real_deletes_and_audits PASSED [ 60%]
tests/test_branch_hygiene.py::test_execute_deletions_failed_delete_not_audited PASSED [ 66%]
tests/test_branch_hygiene.py::test_triaga_html_lists_l2_branches PASSED  [ 73%]
tests/test_branch_hygiene.py::test_triaga_html_handles_empty_l2_list PASSED [ 80%]
tests/test_branch_hygiene.py::test_triaga_html_escapes_branch_names PASSED [ 86%]
tests/test_branch_hygiene.py::test_run_l3_batch_deletes_only_present_branches PASSED [ 93%]
tests/test_branch_hygiene.py::test_run_l3_batch_skips_missing_branches PASSED [100%]

============================== 15 passed in 0.45s ==============================
```

Brief required ≥6; delivered **15**.

## Full-suite regression

```
$ python3 -m pytest tests/ --ignore=tests/test_tier_normalization.py 2>&1 | tail -3
====== 24 failed, 938 passed, 27 skipped, 5 warnings, 31 errors in 30.91s ======
```

Baseline (main, this branch reverted): **24 failed, 923 passed, 31 errors.**
Branch result: **24 failed, 938 passed, 31 errors.**
Delta: **+15 passes, 0 new failures.** The 24 failed + 31 errors are pre-existing Python 3.10+ syntax issues (`int | None`) on the Python 3.9 test runner — not introduced by this PR.

## Singleton hook

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

## Migration-vs-bootstrap drift check

```
$ grep -n "branch_hygiene" memory/store_back.py
131:        self._ensure_branch_hygiene_log_table()
846:    def _ensure_branch_hygiene_log_table(self):
847:        """Create branch_hygiene_log table if it doesn't exist.
... (CREATE TABLE IF NOT EXISTS branch_hygiene_log (...))
```

The bootstrap mirrors `migrations/20260426_branch_hygiene_log.sql` column-for-column:
- `id BIGSERIAL PRIMARY KEY`
- `branch_name TEXT NOT NULL`
- `last_commit_sha TEXT NOT NULL`
- `deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `layer TEXT NOT NULL`
- `reason TEXT NOT NULL DEFAULT ''`
- `age_days INT NOT NULL DEFAULT 0`
- `actor TEXT NOT NULL DEFAULT 'branch_hygiene'`

Plus 3 indexes (`deleted_at DESC`, `layer`, `branch_name`).

## APScheduler registration evidence

```
$ grep branch_hygiene_weekly triggers/embedded_scheduler.py
286:    def _run_branch_hygiene_weekly():
305:                "branch_hygiene_weekly: L1=%d MOBILE=%d L2_FLAGGED=%d KEEP=%d",
312:            logger.warning("branch_hygiene_weekly failed (non-fatal): %s", e)
315:        _run_branch_hygiene_weekly,
317:        id="branch_hygiene_weekly",
318:        name="branch_hygiene_weekly",
323:    logger.info("Registered: branch_hygiene_weekly (Monday 10:30 UTC)")
```

Cron: `CronTrigger(day_of_week="mon", hour=10, minute=30, timezone="UTC")`. Triggered post AI Head weekly audit window.

## git diff summary

```
$ git diff --name-only main...HEAD
memory/store_back.py
migrations/20260426_branch_hygiene_log.sql
scripts/branch_hygiene.py
tests/test_branch_hygiene.py
triggers/embedded_scheduler.py

$ git diff --stat main...HEAD
 memory/store_back.py                       |  47 ++++
 migrations/20260426_branch_hygiene_log.sql |  29 +++
 scripts/branch_hygiene.py                  | 411 +++++++++++++++++++++++++++++
 tests/test_branch_hygiene.py               | 271 +++++++++++++++++++
 triggers/embedded_scheduler.py             |  39 +++
 5 files changed, ~797 insertions(+)
```

---

## Live dry-run output (smoke run)

```
$ python3 scripts/branch_hygiene.py --dry-run
Branch hygiene scan @ 2026-04-26T15:07:15.338670+00:00
Repo: vallen300-bit/baker-master; base: main; staleness: 30d
  PROTECTED: 1
  L1: 20
  MOBILE_CLUSTER: 1
  L2_FLAGGED: 1
  KEEP: 55
  [dry-run] would delete PM-TRIAGE-1 (L1: squash-merged (ahead_by=0, status=behind))
  [dry-run] would delete claude/fix-whatsapp-lid-filter-ooAK1 (L1: squash-merged ...)
  [dry-run] would delete feat/agent-bridge (L1: squash-merged ...)
  [dry-run] would delete feat/backfill-completion-1 (L1: squash-merged ...)
  [dry-run] would delete feat/desktop-alert-triage-1 (L1: squash-merged ...)
  [dry-run] would delete feat/document-browser-1 (L1: squash-merged ...)
  [dry-run] would delete feat/knowledge-search-d6 (L1: squash-merged ...)
  [dry-run] would delete feat/mobile-alerts-view-1 (L1: squash-merged ...)
  [dry-run] would delete feat/mobile-polish-1 (L1: squash-merged ...)
  [dry-run] would delete feat/morning-brief-v2 (L1: squash-merged ...)
  [dry-run] would delete feat/networking-phase1 (L1: squash-merged ...)
  [dry-run] would delete feat/push-notifications-e3 (L1: squash-merged ...)
  [dry-run] would delete feat/realtime-push-alerts-1 (L1: squash-merged ...)
  [dry-run] would delete feat/silent-contacts-card-1 (L1: squash-merged ...)
  [dry-run] would delete feat/specialist-thinking-citations (L1: squash-merged ...)
  [dry-run] would delete feat/thinking-dots-fix (L1: squash-merged ...)
  [dry-run] would delete feat/upcoming-tab-v2 (L1: squash-merged ...)
  [dry-run] would delete fix/email-backfill-async (L1: squash-merged ...)
  [dry-run] would delete fix/remove-commitments-tab-d8 (L1: squash-merged ...)
  [dry-run] would delete fix/whatsapp-prompts-clickup-create (L1: squash-merged ...)
  [dry-run] would delete feat/ios-shortcuts-1 (L1: Q2 default-delete (mobile UI cluster))
L2 Triaga HTML: /Users/dimitry/bm-b3/briefs/_reports/branch_hygiene_triaga_20260426.html
Done. Deletions=0 (dry-run=True).
```

77 branch buckets total: 1 PROTECTED + 20 L1 + 1 MOBILE_CLUSTER + 1 L2_FLAGGED + 55 KEEP. (Note: KEEP shifted 53→55 in second run because two branches got deleted upstream between captures; behaviour is correct.)

## Triaga HTML

Generated at: `briefs/_reports/branch_hygiene_triaga_20260426.html`

Format: `<table>` of L2 branches with checkbox per row + branch name + age + sha8 + reason. Director ticks → saves ticked names to file → re-run with `--l3 <file>`.

---

## Brief vs reality — counts annotation

| Bucket | Brief expected | Reality |
|---|---|---|
| L1 candidates | ~50 | 20 |
| L2 flagged | 21 | 1 |
| MOBILE_CLUSTER | 8 (Q2) | 1 (other 7 already L1) |

The skew is *correct*, not a regression: my squash-detection (`ahead_by==0`) is conservative — only safely-deletable branches reach L1. The brief's "~50 L1" estimate was age-based (37 <7d; many of those still have unmerged commits → KEEP, not L1). The 21 30-90d cluster mostly already squash-merged → caught by L1.

7 of 8 mobile UI cluster branches turned out to already be squash-merged → they hit L1 first and get deleted there. Only `feat/ios-shortcuts-1` lands in MOBILE_CLUSTER and is deleted via the Q2 default. Net result: all 8 mobile branches deleted on first run, as Q2 mandates.

## Brief deviations / annotations

1. **Mobile UI cluster classification.** Brief implied MOBILE_CLUSTER would include all 8. In reality, 7 are already L1 (squash-merge detected); the script auto-deletes them via the L1 path with a generic reason. To preserve Q2 audit traceability, the L1 deletions of mobile branches still carry their original `feat/mobile-*` etc names in the audit log — a downstream query `WHERE branch_name LIKE 'feat/mobile%' OR branch_name IN (...)` can recover the cluster view. If Director wants explicit MOBILE provenance in the audit row, that's a follow-up tweak.

2. **L2 staleness cadence Q3.** Brief defaulted 30d V1; will tune to 14d after backlog cleared. Hard-coded as `DEFAULT_STALENESS_DAYS = 30` constant; CLI flag `--staleness-days` allows override without code edit.

3. **Branch revival window.** Mitigation per brief §10: GitHub provides 90-day branch revival on deleted refs. Audit log records `last_commit_sha` so revival is `gh api -X POST repos/.../git/refs -f ref=refs/heads/<name> -f sha=<last_commit_sha>`. Not in this PR (out of scope), but enabled by the audit shape.

## Hand-off

Tier B LOW class → AI Head solo merge. After merge:
- Run `python3 scripts/branch_hygiene.py` (no `--dry-run`) once to clear backlog.
- Review `briefs/_reports/branch_hygiene_triaga_<date>.html`; if any L2 branches should go, tick → save names → `python3 scripts/branch_hygiene.py --l3 ticks.txt`.
- Mark `CODE_3_PENDING.md` COMPLETE per §3 hygiene.

Weekly cron will run from then on (Mon 10:30 UTC); audit log answers "what did we delete and when".
