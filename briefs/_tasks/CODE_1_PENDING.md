# CODE_1_PENDING — B1: REVIEW PR #64 BRANCH_HYGIENE_1 — 2026-04-26

**Dispatcher:** AI Head A (Build-lead)
**Working dir:** `~/bm-b1`
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/64
**Branch under review:** `branch-hygiene-1` (built by B3)
**Brief:** `briefs/BRIEF_BRANCH_HYGIENE_1.md` (per AI Head B dispatch)
**Status:** OPEN — peer review (B1 cannot review own work; B3 was builder, B1 is reviewer)
**Trigger class:** LOW per BRANCH_HYGIENE_1 brief (GitHub external API only; no auth/DB-migration/secrets/financial). **Director override:** Hold merge until B1 APPROVE per Director Tier B 2026-04-26 ("Hold #64 merge until B1 APPROVE").

---

**§3 hygiene retroactive:** prior CODE_1_PENDING was B1's DEADLINE_EXTRACTOR_QUALITY_1 build → shipped as PR #65 → merged 2026-04-26 as `29907ea` (AI Head A auto-merge per Director Tier B "merge PR #65 immediately"). Mailbox marked complete here implicitly via overwrite.

**§2 pre-dispatch busy-check:** B1 builder-frees on PR #65 merge (just landed). Branch state: B1 worktree on `deadline-extractor-quality-1` post-merge — checkout main + pull resolves. No file overlap with this review (just reading).

**Dispatch authorisation:** Director 2026-04-26: *"Tick on L1 harvest list... Merge PR #65 immediately. Dispatch B1 review of PR #64. Hold #64 merge until B1 APPROVE."*

---

## Your review job — 11 checks

### 1. Scope lock — exactly 7 files

```bash
cd ~/bm-b1 && git fetch && git checkout branch-hygiene-1 && git pull -q
git diff --name-only main...HEAD
```

Expect exactly:
```
briefs/_reports/B3_branch_hygiene_1_20260426.md
briefs/_reports/branch_hygiene_triaga_20260426.html
memory/store_back.py
migrations/20260426_branch_hygiene_log.sql
scripts/branch_hygiene.py
tests/test_branch_hygiene.py
triggers/embedded_scheduler.py
```

**Reject if:** any file outside this list, or any auth/secrets module touched.

### 2. Python syntax on 4 Python files

```bash
for f in scripts/branch_hygiene.py tests/test_branch_hygiene.py memory/store_back.py triggers/embedded_scheduler.py; do
  python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" || { echo "FAIL: $f"; exit 1; }
done && echo "All 4 files clean."
```

### 3. Migration-vs-bootstrap drift check (LONGTERM.md feedback rule)

Brief and ship report claim column-for-column match between migration and bootstrap. **Verify yourself:**

```bash
# Migration columns
grep -A 20 "CREATE TABLE.*branch_hygiene_log" migrations/20260426_branch_hygiene_log.sql

# Bootstrap columns
grep -A 30 "_ensure_branch_hygiene_log_table" memory/store_back.py
```

Both must show: `id BIGSERIAL PK`, `branch_name TEXT NOT NULL`, `last_commit_sha TEXT NOT NULL`, `deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`, `layer TEXT NOT NULL`, `reason TEXT NOT NULL DEFAULT ''`, `age_days INT NOT NULL DEFAULT 0`, `actor TEXT NOT NULL DEFAULT 'branch_hygiene'`. **Any type mismatch = REJECT** per `feedback_migration_bootstrap_drift.md`.

### 4. PROTECTED branch preservation

Reject if `main` / `master` / `release/*` could ever be deleted. Verify guard:

```bash
grep -nB2 -A8 "PROTECTED\|protected_patterns\|protect_branch" scripts/branch_hygiene.py | head -40
```

Expect explicit pattern match + test coverage. Hard-fail at every layer.

### 5. L1 ahead_by==0 logic correctness

L1 auto-delete is the riskiest path. Verify:

```bash
grep -nB2 -A10 "ahead_by\|squash" scripts/branch_hygiene.py | head -30
```

Expect: deletion only when `ahead_by == 0` (every commit on branch already on base). NO heuristic squash-detection (e.g., commit-msg matching) — only the safe deterministic signal.

### 6. Mobile cluster Q2 whitelist exact match

Brief specifies 4 patterns: `feat/mobile-*`, `feat/ios-shortcuts-1`, `feat/document-browser-1`, `feat/networking-phase1`.

```bash
grep -nB2 -A5 "MOBILE_CLUSTER\|mobile.*cluster\|ios-shortcuts" scripts/branch_hygiene.py | head -20
```

Expect exact 4 patterns. Reject if any extras or missing.

### 7. L3 throttle (10/min)

L3 batch-delete reads from a tickfile. Throttle prevents GitHub API rate-limit hit.

```bash
grep -nB2 -A5 "throttle\|rate.*limit\|10.*min\|sleep\|time\.sleep" scripts/branch_hygiene.py | head -15
```

Expect: explicit sleep / throttle on L3 path. Document the exact mechanism in your review note.

### 8. Audit-log fire-and-forget

Every L1/L2/MOBILE/L3 action MUST write to `branch_hygiene_log`. Reject if any path skips logging.

```bash
grep -nB1 -A3 "INSERT INTO branch_hygiene_log\|_audit\|log_branch_action" scripts/branch_hygiene.py | head -25
```

Expect: log calls in L1, L2_FLAGGED, MOBILE_CLUSTER, L3 paths. Try/except around each (failure should NOT block the deletion).

### 9. 15 tests pass + regression delta

```bash
pytest tests/test_branch_hygiene.py -v 2>&1 | tail -15
pytest tests/ 2>&1 | tail -3
```

Expect `15 passed` for the new file; full suite +15 passes vs main, 0 new failures.

### 10. APScheduler `branch_hygiene_weekly` Mon 10:30 UTC

```bash
grep -B2 -A8 "branch_hygiene_weekly" triggers/embedded_scheduler.py
```

Expect: registered job, Mon 10:30 UTC, behind whatever flag the brief specified, try/except in job body so failure doesn't crash scheduler.

### 11. Singleton check

```bash
bash scripts/check_singletons.sh
```

Expect: `OK: No singleton violations found.`

---

## If 11/11 green

Post APPROVE on PR #64. AI Head A merges per Director Tier B (`gh pr merge 64 --squash`). §3 hygiene mark this mailbox COMPLETE post-merge.

## If any check fails

`gh pr review 64 --request-changes` with specific list. Route back to B3 for fix. Do NOT merge.

## Ship report

`briefs/_reports/B1_pr64_branch_hygiene_1_review_20260426.md` — include all 11 check outputs literal.

---

## Trigger class note (Director override on default)

Brief classified BRANCH_HYGIENE_1 as **LOW** (GitHub external API only; AI Head solo-merge per autonomy charter §4). Director explicitly overrode with "Hold merge until B1 APPROVE" — likely because branch deletion is destructive (irreversible without git fsck) and warrants peer review even at LOW class. Per autonomy charter §4 Director prerogative. No appeal needed.

## Timebox

**~25–35 min.** 11 checks, mostly mechanical.
