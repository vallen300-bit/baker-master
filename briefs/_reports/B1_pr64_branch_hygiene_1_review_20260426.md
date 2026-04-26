# B1 Review Report — PR #64 BRANCH_HYGIENE_1

**Date:** 2026-04-26
**Reviewer:** B1
**Builder:** B3 (`branch-hygiene-1` branch)
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/64
**Brief:** `briefs/BRIEF_BRANCH_HYGIENE_1.md`
**Trigger class:** LOW (Director override held merge until B1 APPROVE)
**Verdict:** **APPROVE** — 11/11 checks green.

---

## Verdict

All 11 review checks pass. AI Head A may merge per Director Tier B
(`gh pr merge 64 --squash`). One non-blocking note on stale-branch math
in check #9 (branch was cut from main before
DEADLINE_EXTRACTOR_QUALITY_1 merged); rebase-on-merge resolves it.

---

## #1. Scope lock — exactly 7 files ✓

```
$ git diff --name-only main...HEAD
briefs/_reports/B3_branch_hygiene_1_20260426.md
briefs/_reports/branch_hygiene_triaga_20260426.html
memory/store_back.py
migrations/20260426_branch_hygiene_log.sql
scripts/branch_hygiene.py
tests/test_branch_hygiene.py
triggers/embedded_scheduler.py
```

Exact 7-file match against the brief's expected list. No auth / secrets / out-of-scope module touched.

## #2. Python syntax on 4 Python files ✓

```
$ for f in scripts/branch_hygiene.py tests/test_branch_hygiene.py memory/store_back.py triggers/embedded_scheduler.py; do
    python3 -c "import py_compile; py_compile.compile('$f', doraise=True)"
  done
All 4 files clean.
```

## #3. Migration vs bootstrap drift ✓

Both create `branch_hygiene_log` with column-for-column-identical schema:

```sql
-- migration (migrations/20260426_branch_hygiene_log.sql)
CREATE TABLE IF NOT EXISTS branch_hygiene_log (
    id              BIGSERIAL PRIMARY KEY,
    branch_name     TEXT        NOT NULL,
    last_commit_sha TEXT        NOT NULL,
    deleted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    layer           TEXT        NOT NULL,
    reason          TEXT        NOT NULL DEFAULT '',
    age_days        INT         NOT NULL DEFAULT 0,
    actor           TEXT        NOT NULL DEFAULT 'branch_hygiene'
);
```

```python
# bootstrap (memory/store_back.py::_ensure_branch_hygiene_log_table)
CREATE TABLE IF NOT EXISTS branch_hygiene_log (
    id              BIGSERIAL PRIMARY KEY,
    branch_name     TEXT        NOT NULL,
    last_commit_sha TEXT        NOT NULL,
    deleted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    layer           TEXT        NOT NULL,
    reason          TEXT        NOT NULL DEFAULT '',
    age_days        INT         NOT NULL DEFAULT 0,
    actor           TEXT        NOT NULL DEFAULT 'branch_hygiene'
)
```

All 8 columns identical types + nullability + defaults. 3 indexes
(`idx_branch_hygiene_log_deleted_at|_layer|_branch_name`) match. Bootstrap
wraps DB ops in try/except + rollback + finally per python-backend rule.

## #4. PROTECTED branch preservation ✓

```python
# scripts/branch_hygiene.py:52
DEFAULT_PROTECT_PATTERNS = ("main", "master", "release/*")

# scripts/branch_hygiene.py:207
if branch.matches_any(protect_patterns):
    return ("PROTECTED", "matches protect pattern")
if branch.name == base:
    return ("PROTECTED", f"base branch {base!r}")
```

`PROTECTED` returns BEFORE the `compare_to_base()` call and BEFORE any
deletion-layer classification. `branch.name == base` adds belt-and-braces
for the configured base even if the patterns are overridden via CLI. Test
coverage: `test_classify_protected_main`,
`test_classify_protected_release_pattern`.

## #5. L1 ahead_by==0 logic correctness ✓

```python
# scripts/branch_hygiene.py:213-216
cmp = compare_to_base(repo, base, branch.name)
ahead = cmp.get("ahead_by", -1)
if ahead == 0:
    return ("L1", f"squash-merged (ahead_by=0, status={cmp.get('status')})")
```

L1 fires only when GitHub `compare` API returns `ahead_by == 0` (i.e. every
commit on the branch is already on `main`). Defensive default `-1` if API
returns nothing → never zero → never classified L1. **No commit-message
heuristic, no fuzzy "looks merged" matching** — only the deterministic
GitHub-side signal.

## #6. Mobile cluster Q2 whitelist ✓

```python
# scripts/branch_hygiene.py:55-60
MOBILE_UI_CLUSTER = (
    "feat/mobile-*",
    "feat/ios-shortcuts-1",
    "feat/document-browser-1",
    "feat/networking-phase1",
)
```

Exactly 4 patterns, exact match to brief §Q2. No extras, none missing. Used
in `classify()` at line 218 with `branch.matches_any(mobile_cluster)`.

## #7. L3 throttle (10/min) ✓

```python
# scripts/branch_hygiene.py:51 + :377-391
DELETIONS_PER_MINUTE = 10
...
def execute_deletions(rows, *, repo, layer, dry_run,
                     throttle_per_minute: int = DELETIONS_PER_MINUTE, …):
    interval = 60.0 / max(throttle_per_minute, 1)
    for b, reason in rows:
        if dry_run: continue
        ...
        if not dry_run:
            time.sleep(interval)
```

`run_l3_batch()` routes through `execute_deletions()` (line 419), so the
6-second-per-deletion throttle applies uniformly to L1, MOBILE, and L3 paths.
Mechanism: `time.sleep(60.0 / 10) = 6.0s` between non-dry-run deletions.

## #8. Audit-log fire-and-forget ✓

```python
# scripts/branch_hygiene.py:235-279
def log_deletion(branch, layer, reason, actor="branch_hygiene", *, store=None) -> bool:
    """Insert a row into branch_hygiene_log. Best-effort; non-fatal."""
    ...
    try:
        cur.execute("INSERT INTO branch_hygiene_log (...)", (...))
        conn.commit()
        return True
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning("audit log insert failed for %s: %s", branch.name, e)
        return False
    finally:
        store._put_conn(conn)
```

Wired in `execute_deletions()` (auditor lambda, line 375) covering L1 +
MOBILE_CLUSTER + L3, and explicit call for L2_FLAGGED at line 513 (since
L2 rows are flagged not deleted). All four layers log; failures rollback +
log warning + return False — never raise.

## #9. 15 tests pass + regression delta ✓ (with note)

```
$ pytest tests/test_branch_hygiene.py -v
collected 15 items
[15 PASSED rows]
============================== 15 passed in 0.46s ==============================
```

Full-suite numbers:

| | failures | passes | skipped | errors | collected |
|---|---|---|---|---|---|
| main (today)               | 30 | 930 | 27 | 31 | 1018 |
| `branch-hygiene-1`         | 30 | 932 | 27 | 31 | 1020 |

**Failures held at 30 — 0 new failures.**

The pass delta is +2 not +15 because `branch-hygiene-1` was cut from main
**before** DEADLINE_EXTRACTOR_QUALITY_1 (PR #65) merged. Branch is missing
13 tests from `tests/test_deadline_extractor_quality.py` that exist on
main. Mathematically: +15 (new branch_hygiene tests) − 13 (deadline tests
absent on this branch) = +2 net.

This is a **stale-branch artifact, not a regression**. A rebase-on-merge
will pick up both test files and the count will be the expected +15.

Identified test name diff (`comm -23` / `comm -13`):
- New on branch: 15 × `tests/test_branch_hygiene.py::test_*` (all PASS)
- On main but not branch: 13 × `tests/test_deadline_extractor_quality.py::test_*`

## #10. APScheduler `branch_hygiene_weekly` Mon 10:30 UTC ✓

```python
# triggers/embedded_scheduler.py:285-323
def _run_branch_hygiene_weekly():
    try:
        from scripts.branch_hygiene import run_classification, execute_deletions, ...
        buckets = run_classification(...)
        execute_deletions(...)
        logger.info("branch_hygiene_weekly: L1=%d MOBILE=%d L2_FLAGGED=%d KEEP=%d", ...)
    except Exception as e:
        logger.warning("branch_hygiene_weekly failed (non-fatal): %s", e)

scheduler.add_job(
    _run_branch_hygiene_weekly,
    CronTrigger(day_of_week="mon", hour=10, minute=30, timezone="UTC"),
    id="branch_hygiene_weekly", name="branch_hygiene_weekly",
    coalesce=True, max_instances=1, replace_existing=True,
)
```

Mon 10:30 UTC ✓; full body wrapped in try/except (non-fatal warning on
failure) so scheduler never crashes. `coalesce=True, max_instances=1,
replace_existing=True` — sane scheduler hygiene. **Brief does not specify
a feature flag** so the cron runs unconditionally as registered (consistent
with brief — no flag-gate check warranted).

## #11. Singleton check ✓

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

---

## Recommendation

**APPROVE.** All 11 checks green. Single note for AI Head A: PR #64
should be merged via `gh pr merge 64 --squash` per Director Tier B; the
squash-merge will rebase the branch's L1 logic onto current main (which
includes the new deadline filter). After merge, both
`tests/test_branch_hygiene.py` and `tests/test_deadline_extractor_quality.py`
will coexist on main with no overlap.

Suggest also: AI Head A run `python3 scripts/branch_hygiene.py --dry-run`
once post-merge to dry-validate the live branch list before letting the
Mon 10:30 UTC cron fire on real data the next Monday.

## Mailbox hygiene

Per dispatch §3, after AI Head A merges PR #64, the `CODE_1_PENDING.md`
mailbox should be overwritten to:
`COMPLETE — PR #64 BRANCH_HYGIENE_1 merged as <commit-sha> on 2026-04-26
by AI Head A. B1 review APPROVED 11/11 — see briefs/_reports/B1_pr64_branch_hygiene_1_review_20260426.md.`
