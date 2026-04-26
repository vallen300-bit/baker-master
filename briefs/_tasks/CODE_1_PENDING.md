# CODE_1_PENDING — B1: REVIEW PR #66 GOLD_COMMENT_WORKFLOW_1 — 2026-04-26

**Dispatcher:** AI Head B (Build-reviewer, M2 lane)
**Working dir:** `~/bm-b1`
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/66
**Branch under review:** `gold-comment-workflow-1` (built by B3, commits `1c88201` + `19408b8`)
**Brief:** `briefs/BRIEF_GOLD_COMMENT_WORKFLOW_1.md`
**Status:** OPEN — peer review (B1 cannot review own work; B3 was builder, B1 is reviewer)
**Trigger class:** **MEDIUM** (DB migration + cross-capability state writes) per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`. AI Head B holds merge until B1 APPROVE.

---

## §3 hygiene retroactive

Prior CODE_1_PENDING was B1's PR #64 BRANCH_HYGIENE_1 review → APPROVE → merged `676803e` 2026-04-26 by AI Head A. This dispatch overwrites the COMPLETE state.

## §2 pre-dispatch busy-check

- **Mailbox prior:** COMPLETE — PR #64 review APPROVE 11/11. Idle ✓
- **Branch state:** `gh pr checkout 66` resolves any stale state.
- **Other B-codes:** B2 → WIKI_LINT_1. B3 → idle (just shipped PR #66; AMEX queued at `_staging/CODE_3_QUEUED.md` awaiting PR #66 merge). B5 → CHANDA rewrite.
- **Dispatch authorisation:** Director RA-21 2026-04-26 PM "Proceed with Gold Comment" + situational-review rule auto-fire (medium trigger-class).

---

## Your review job — 13 checks

### 1. Scope lock — file count + paths

```bash
cd ~/bm-b1 && git fetch && gh pr checkout 66 && git pull -q
git diff --name-only main...HEAD
```

Expect at minimum:
```
briefs/_reports/B3_gold_comment_workflow_1_20260426.md (or similar)
kbl/gold_writer.py
kbl/gold_proposer.py
kbl/gold_drift_detector.py
kbl/gold_parser.py
orchestrator/gold_audit_job.py
memory/store_back.py                       (modified — bootstraps added)
migrations/20260426_gold_audits.sql
triggers/embedded_scheduler.py             (modified — gold_audit_sentinel registered)
tests/test_gold_writer.py
tests/test_gold_proposer.py
tests/test_gold_drift_detector.py
tests/test_gold_parser.py
```

Reject if: any auth/secrets module touched, or any kbl/gold_drain.py / kbl/loop.py modification (DISTINCT lanes per brief §"Existing landscape"), or vault paths inside the PR (vault siblings committed separately as `894d86e` baker-vault).

### 2. Python syntax on all new + modified Python files

```bash
for f in $(git diff --name-only main...HEAD | grep '\.py$'); do
  python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" || { echo "FAIL: $f"; exit 1; }
done && echo "All .py files clean."
```

### 3. Migration-vs-bootstrap drift check (Code Brief Standard #4)

```bash
diff <(grep -A 10 "CREATE TABLE.*gold_audits" migrations/20260426_gold_audits.sql) \
     <(grep -A 10 "CREATE TABLE.*gold_audits" memory/store_back.py)
diff <(grep -A 10 "CREATE TABLE.*gold_write_failures" migrations/20260426_gold_audits.sql) \
     <(grep -A 10 "CREATE TABLE.*gold_write_failures" memory/store_back.py)
```

Both diffs MUST be empty (modulo whitespace). **Any type mismatch = REJECT** per `feedback_migration_bootstrap_drift.md`.

### 4. Schema verification — id SERIAL not BIGSERIAL

Brief specified `id SERIAL PRIMARY KEY` (mirroring `ai_head_audits` precedent at `memory/store_back.py:511`). Verify:

```bash
grep -A 6 "_ensure_gold_audits_table\|_ensure_gold_write_failures_table" memory/store_back.py | grep -E "SERIAL|BIGSERIAL"
```

Expect: `SERIAL`. Reject if `BIGSERIAL`.

### 5. Bootstrap pattern matches `ai_head_audits` precedent

Brief specified `_get_conn()` + `cur.close()` pattern (NOT context manager `with self.get_conn() as conn`). Verify:

```bash
grep -B1 -A 25 "_ensure_gold_audits_table\|_ensure_gold_write_failures_table" memory/store_back.py | head -60
```

Expect: `conn = self._get_conn()` + `cur.close()` style. Reject if context-manager style mismatches sibling pattern.

### 6. Caller-stack guard in gold_writer

Brief specified `_check_caller_authorized()` rejects callers in `cortex_*` or `kbl.cortex*` namespace.

```bash
grep -B 2 -A 10 "_check_caller_authorized\|CallerNotAuthorized" kbl/gold_writer.py | head -30
```

Expect: `inspect.stack()` walk + `__name__` startswith check + raises `CallerNotAuthorized`. B3 noted "types.FunctionType rebind for cortex-caller test" — verify the test pattern is sane (test should mock a cortex-named caller without breaking the inspect machinery for production paths).

### 7. Slack DM uses canonical helper

Brief specified `triggers.ai_head_audit._safe_post_dm` (NOT phantom `triggers.slack_push.push_to_director`). Verify:

```bash
grep -nE "_safe_post_dm|push_to_director|slack_push" orchestrator/gold_audit_job.py kbl/gold_writer.py
```

Expect: `_safe_post_dm` only. Reject if any reference to phantom `push_to_director`.

### 8. APScheduler `gold_audit_sentinel` Mon 09:30 UTC

```bash
grep -B 2 -A 10 "gold_audit_sentinel\|_gold_audit_sentinel_job" triggers/embedded_scheduler.py | head -25
```

Expect: registered job, Mon 09:30 UTC, `GOLD_AUDIT_ENABLED` kill-switch, try/except in job body. Slot is 09:30 UTC — between `ai_head_weekly_audit` (09:00) and `ai_head_audit_sentinel` (10:00); no collision.

### 9. 36/36 tests pass + regression delta

```bash
pytest tests/test_gold_writer.py tests/test_gold_proposer.py tests/test_gold_drift_detector.py tests/test_gold_parser.py -v 2>&1 | tail -20
pytest tests/ 2>&1 | tail -3
```

Expect `36 passed` for the 4 new files; full suite `+36 passes, 0 new failures` per B3 report.

### 10. Singleton check

```bash
bash scripts/check_singletons.sh
```

Expect: `OK: No singleton violations found.` (per Code Brief Standard #8)

### 11. DV_ONLY validation deviation

B3 noted "DV_ONLY relaxed at validate-time (renderer auto-appends)". Verify the relaxation is at `validate_entry()` only and the renderer (`_render_entry`) hard-appends `DV.`:

```bash
grep -B 2 -A 8 "_render_entry\|DV\." kbl/gold_writer.py | head -30
grep -B 2 -A 6 "DV_ONLY" kbl/gold_drift_detector.py | head -20
```

Expect: renderer always appends ` DV.`; validator does not block on missing DV (since renderer guarantees it). Acceptable deviation if defense-in-depth: caller-stack guard + renderer enforcement covers the surface.

### 12. Backfill validation of existing 2 entries

B3 ship-report claims `gold_drift_detector.audit_all(~/baker-vault)` returns `issues_count: 0` against the existing 2 entries in `_ops/director-gold-global.md`. Re-run from B1 worktree:

```bash
BAKER_VAULT_PATH=~/baker-vault python3 -c "
from kbl import gold_drift_detector
from pathlib import Path
issues = gold_drift_detector.audit_all(Path('$HOME/baker-vault'))
print(f'issues: {len(issues)}')
for i in issues[:5]:
    print(f'  [{i.code}] {i.message}')
"
```

Expect: `issues: 0`. Reject if any issues against canonical entries.

### 13. Vault sibling alignment

B3 staged `.githooks/gold_drift_check.sh` + `.githooks/commit-msg` + `_ops/processes/gold-comment-workflow.md` on baker-vault working tree. AI Head B committed sibling as `894d86e` 2026-04-26. Verify:

```bash
cd ~/baker-vault && git log --oneline -3
ls -la .githooks/
git config --get core.hooksPath
```

Expect: latest commit `894d86e` (or descendant) lands the 3 sibling files; `core.hooksPath = .githooks` activated. Note: hook activation only on Director's clone here; Mac Mini still runs without hook (CHANDA #9 single-writer; Mac Mini doesn't write Gold paths).

---

## If 13/13 green

Post APPROVE on PR #66 (`gh pr review 66 --approve`). AI Head B merges per autonomy charter §4 + Tier B trigger-class clearance (`gh pr merge 66 --squash --delete-branch`). §3 hygiene mark this mailbox COMPLETE post-merge.

## If any check fails

`gh pr review 66 --request-changes` with specific list. Route back to B3 for fix-back. Do NOT merge.

## Ship report

`briefs/_reports/B1_pr66_gold_comment_workflow_1_review_20260426.md` — include all 13 check outputs literal. PR comment summary linking to ship report.

---

## Trigger class note

GOLD_COMMENT_WORKFLOW_1 is **MEDIUM** trigger class (DB migration + cross-capability state writes — `gold_proposer` is the contract surface for future Cortex M2). Situational-review rule auto-fires per `2026-04-24-b1-situational-review-trigger.md`. AI Head solo-merge would be a process violation here. Hold merge until B1 APPROVE.

## Timebox

**~30–45 min.** 13 checks, mostly mechanical. Brief is comprehensive; deviations are pre-annotated (5 listed in B3 ship report — review for rationale).

---

**Dispatch timestamp:** 2026-04-26 ~22:55 UTC
**Authority chain:** Director RA-21 "Proceed with Gold Comment" → RA-21 spec (vault `e3465ab`) → AI Head B `/write-brief` Rule 0 brief → B3 build (PR #66, commits `1c88201`+`19408b8`) → B1 review (this dispatch) → AI Head B merge (post-APPROVE).
