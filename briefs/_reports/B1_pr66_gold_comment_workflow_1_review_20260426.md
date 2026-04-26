# B1 Review Report — PR #66 GOLD_COMMENT_WORKFLOW_1

**Date:** 2026-04-26
**Reviewer:** B1
**Builder:** B3 (`gold-comment-workflow-1` branch, commits `1c88201` + `19408b8`)
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/66
**Brief:** `briefs/BRIEF_GOLD_COMMENT_WORKFLOW_1.md`
**Trigger class:** MEDIUM (DB migration + cross-capability state writes)
**Verdict:** **APPROVE — 13/13 checks green.**

---

## #1. Scope lock — exactly 13 files ✓

```
$ git diff --name-only main...HEAD
briefs/_reports/B3_gold_comment_workflow_1_20260426.md
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

13 files exact match. No auth/secrets module touched. No `kbl/gold_drain.py`
or `kbl/loop.py` modifications (DISTINCT lanes preserved). No vault paths
inside the PR (vault siblings committed separately as `894d86e`).

## #2. Python syntax on all .py files ✓

```
$ for f in $(git diff --name-only main...HEAD | grep '\.py$'); do
    python3 -c "import py_compile; py_compile.compile('$f', doraise=True)"
  done
All .py files clean.
```

## #3. Migration ↔ bootstrap drift ✓

Column-by-column extraction (balanced-paren parser) of both
`gold_audits` and `gold_write_failures`:

```
=== gold_audits ===
 migration:                                bootstrap:
   id SERIAL PRIMARY KEY                     id SERIAL PRIMARY KEY
   ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW() ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
   issues_count INT NOT NULL DEFAULT 0       issues_count INT NOT NULL DEFAULT 0
   payload_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb  payload_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb
 MATCH: True

=== gold_write_failures ===
 migration:                                bootstrap:
   id SERIAL PRIMARY KEY                     id SERIAL PRIMARY KEY
   attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()  attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
   target_path TEXT NOT NULL                 target_path TEXT NOT NULL
   error TEXT NOT NULL                       error TEXT NOT NULL
   caller_stack TEXT                         caller_stack TEXT
   payload_jsonb JSONB DEFAULT '{}'::jsonb   payload_jsonb JSONB DEFAULT '{}'::jsonb
 MATCH: True
```

Both indexes (`idx_gold_audits_ran_at`, `idx_gold_write_failures_attempted_at`)
match column-for-column. Naïve `diff` is non-empty only because of Python
indentation + trailing semicolons inside triple-quoted strings — both
ignored per the brief's "modulo whitespace" rule.

## #4. id SERIAL not BIGSERIAL ✓

```python
# memory/store_back.py:567 (gold_audits)
id            SERIAL PRIMARY KEY,
# memory/store_back.py:601 (gold_write_failures)
id            SERIAL PRIMARY KEY,
```

Both tables use `SERIAL`, mirroring the `ai_head_audits` precedent at
`memory/store_back.py:511`.

## #5. `_get_conn()` + `cur.close()` pattern ✓

```python
# Both _ensure_gold_audits_table and _ensure_gold_write_failures_table:
conn = self._get_conn()
if not conn:
    return
try:
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS …""")
    cur.execute("CREATE INDEX IF NOT EXISTS …")
    conn.commit()
    cur.close()
except Exception as e:
    try:
        conn.rollback()
    except Exception:
        pass
    logger.warning(f"Could not ensure …: {e}")
finally:
    self._put_conn(conn)
```

Matches the `ai_head_audits` pattern. `conn.rollback()` in except per the
python-backend rule. `_put_conn()` in finally returns conn to pool.

## #6. Caller-stack guard ✓

```python
# kbl/gold_writer.py:33-56
class CallerNotAuthorized(GoldWriteError): ...

def _check_caller_authorized() -> None:
    """Reject if any frame in the calling stack belongs to cortex_*."""
    for frame in inspect.stack():
        mod = frame.frame.f_globals.get("__name__", "") or ""
        if mod.startswith("cortex_") or mod.startswith("kbl.cortex"):
            raise CallerNotAuthorized(
                f"gold_writer.append rejected — caller {mod!r} must use gold_proposer"
            )
```

Walks `inspect.stack()`, reads `frame.frame.f_globals["__name__"]`
(the module the caller was DEFINED in), rejects `cortex_*` and
`kbl.cortex*`. Test pattern at `tests/test_gold_writer.py:80-104`
uses `types.FunctionType` rebind to put a test caller into a fake
`cortex_test_caller` module without polluting any production frame, plus
try/finally cleanup of `sys.modules`. Sane and isolated.

## #7. Slack DM uses canonical helper ✓

```
$ grep -nE "_safe_post_dm|push_to_director|slack_push" \
    orchestrator/gold_audit_job.py kbl/gold_writer.py
orchestrator/gold_audit_job.py:10:     triggers.ai_head_audit._safe_post_dm helper.
orchestrator/gold_audit_job.py:82:        from triggers.ai_head_audit import _safe_post_dm
orchestrator/gold_audit_job.py:83:        _safe_post_dm(summary)
```

Only `_safe_post_dm` from `triggers.ai_head_audit`. Zero references to the
phantom `push_to_director` / `slack_push`. Wrapped in try/except so a
Slack failure logs a warning but doesn't fail the audit job.

## #8. APScheduler `gold_audit_sentinel` Mon 09:30 UTC ✓

```python
# triggers/embedded_scheduler.py:730-747
_gold_audit_enabled = _os.environ.get("GOLD_AUDIT_ENABLED", "true").lower()
if _gold_audit_enabled not in ("false", "0", "no", "off"):
    from orchestrator.gold_audit_job import _gold_audit_sentinel_job
    scheduler.add_job(
        _gold_audit_sentinel_job,
        CronTrigger(day_of_week="mon", hour=9, minute=30, timezone="UTC"),
        id="gold_audit_sentinel",
        name="Gold corpus weekly audit (Monday 09:30 UTC)",
        coalesce=True, max_instances=1, replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Registered: gold_audit_sentinel (Mon 09:30 UTC)")
else:
    logger.info("Skipped: gold_audit_sentinel (GOLD_AUDIT_ENABLED=false)")
```

```python
# orchestrator/gold_audit_job.py:24-37
def _gold_audit_sentinel_job() -> None:
    try:
        ...
        report = gold_parser.emit_audit_report(vault)
        _persist(report)
        if report.get("issues_count", 0) > 0:
            _push_slack_dm(report)
    except Exception as e:
        logger.error("gold_audit_sentinel_job failed: %s", e, exc_info=True)
```

- Mon 09:30 UTC ✓ (slot between `ai_head_weekly_audit` 09:00 + `ai_head_audit_sentinel` 10:00 — no collision per brief)
- `GOLD_AUDIT_ENABLED` kill-switch with default `true` ✓
- Job body wrapped in try/except logging error with `exc_info=True` (non-fatal) ✓
- `coalesce=True, max_instances=1, replace_existing=True, misfire_grace_time=3600` ✓

## #9. 36/36 tests + regression delta ✓

```
$ pytest tests/test_gold_writer.py tests/test_gold_proposer.py \
    tests/test_gold_drift_detector.py tests/test_gold_parser.py
collected 36 items

tests/test_gold_writer.py .........                              [ 25%]
tests/test_gold_proposer.py .......                              [ 44%]
tests/test_gold_drift_detector.py ..............                 [ 83%]
tests/test_gold_parser.py ......                                 [100%]

============================== 36 passed in 0.10s ==============================
```

Full-suite delta vs current main (with `--ignore=tests/test_tier_normalization.py`
because of pre-existing collection error):

| | failures | passes | skipped | errors |
|---|---|---|---|---|
| main (today)               | 30 | 945 | 27 | 31 |
| `gold-comment-workflow-1`  | 30 | 981 | 27 | 31 |
| **delta**                  | **+0** | **+36** | **+0** | **+0** |

Exactly **+36 passes, 0 new failures**, matching B3 ship-report claim.

## #10. Singletons ✓

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

## #11. DV_ONLY relaxation safe ✓

```python
# kbl/gold_writer.py:119-131 (renderer hard-appends DV.)
def _render_entry(entry: GoldEntry) -> str:
    quote = entry.ratification_quote.strip()
    if not quote.rstrip().endswith("DV."):
        quote = f"{quote.rstrip()} DV."
    return ( "## …\n\n**Ratification:** {quote}\n\n…" )
```

```python
# kbl/gold_drift_detector.py:68-72 (validator relaxes DV_ONLY by design)
# DV_ONLY at validate_entry is belt-and-braces only: gold_writer's
# renderer auto-appends "DV." when missing, so the file written is
# always DV-tagged. We DO NOT flag a quote lacking DV. here — that
# would block legitimate writer.append() calls. The audit_all path
# catches manual file writes that bypass the renderer.
```

```python
# kbl/gold_drift_detector.py:181-185 (audit_file STILL flags DV_ONLY)
DriftIssue(
    "DV_ONLY",
    f"ratified entry missing DV. initials: {header[:80]}",
    str(path),
)
```

Defense-in-depth confirmed:
1. Caller-stack guard (`_check_caller_authorized`) rejects cortex callers.
2. Renderer (`_render_entry`) hard-appends `DV.` on every programmatic write.
3. `audit_file()` flags `DV_ONLY` on the file system — catches any manual
   edit / bypass route. So the validator-time relaxation closes the loop
   without dropping the safety net.

## #12. Backfill — 0 issues against canonical entries ✓

```
$ BAKER_VAULT_PATH=$HOME/baker-vault python3 -c "
from kbl import gold_drift_detector
from pathlib import Path
issues = gold_drift_detector.audit_all(Path.home() / 'baker-vault')
print(f'issues: {len(issues)}')"
issues: 0
```

Confirms B3 ship-report claim. Existing 2 entries in
`_ops/director-gold-global.md` are clean.

## #13. Vault sibling alignment ✓

```
$ cd ~/baker-vault && git log --oneline -3
894d86e vault-sibling(GOLD_COMMENT_WORKFLOW_1): commit-msg hook + canonical process doc
68c45c6 ai-head SKILL Rule 0.5 + LONGTERM: wake-paste MANDATORY on every B-code dispatch
c8ecd7d people.yml v3 → v4: …

$ git config --get core.hooksPath
.githooks

$ ls -la .githooks/
commit-msg -> gold_drift_check.sh   (symlink)
gold_drift_check.sh                 (rwxr-xr-x, 2406 bytes)

$ ls _ops/processes/gold-comment-workflow.md
-rw-r--r-- 5580 bytes
```

All 3 sibling files (script + symlink + process doc) committed in
`894d86e`. `core.hooksPath = .githooks` is active on the Director's clone.
Per CHANDA #9, the Mac Mini single-writer doesn't write Gold paths so
no hook activation needed there.

---

## Verdict

**APPROVE.** All 13 checks green. AI Head B may merge per Director Tier B
trigger-class clearance:

```
gh pr merge 66 --squash --delete-branch
```

After merge, mailbox `briefs/_tasks/CODE_1_PENDING.md` should be flipped
to `COMPLETE — PR #66 GOLD_COMMENT_WORKFLOW_1 merged as <sha> on
2026-04-26 by AI Head B. B1 review APPROVED 13/13 — see
briefs/_reports/B1_pr66_gold_comment_workflow_1_review_20260426.md.`

## One observation (non-blocking)

The brief's drift check #3 specifies `MUST be empty (modulo whitespace)`
— the trivial `diff` produces output because of Python indentation +
trailing semicolons. Future Code Brief Standards rev could prefer a
column-set comparator (or a lint script) over raw `diff`, since the
current heuristic produces false alarms on every Python-bootstrapped
table. Documenting here for next migration brief.

## Authority chain

Director RA-21 "Proceed with Gold Comment" → RA-21 spec (vault `e3465ab`)
→ AI Head B `/write-brief` Rule 0 brief → B3 build (PR #66, commits
`1c88201` + `19408b8`) → B1 review (this report) → AI Head B merge
(post-APPROVE).
