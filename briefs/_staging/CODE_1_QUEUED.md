# CODE_1_QUEUED — B1: PR #64 BRANCH_HYGIENE_1 second-pair review — 2026-04-26

**Dispatcher:** AI Head B (Build-reviewer)
**Trigger:** PR #65 DEADLINE_EXTRACTOR_QUALITY_1 merge-or-mailbox-flip (whichever comes first)
**Purpose:** Second-pair-of-eyes review per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`
**Why B1:** PR #64 touches **DB migration** (`migrations/20260426_branch_hygiene_log.sql` + bootstrap) AND **external API** (GitHub branch deletion via `gh api`). Both are trigger classes in the situational-review rule. B3's "LOW trigger class → AI Head solo merge" claim is process-incorrect; AI Head B disagrees and routes for B1 review.

---

## §2 pre-dispatch busy-check (deferred)

CODE_1_PENDING.md currently holds dispatch for PR #65 (still in flight pending Director Triaga tick + AI Head merge). On either of:
- PR #65 merged → `printf 'COMPLETE — PR #65 merged <sha>' > briefs/_tasks/CODE_1_PENDING.md`
- PR #65 declared idle (Director ticks Triaga and we re-dispatch sequentially)

…AI Head B will overwrite `briefs/_tasks/CODE_1_PENDING.md` with the body below.

---

## Body for CODE_1_PENDING.md (paste verbatim when promoting):

```
# CODE_1_PENDING — B1: PR #64 BRANCH_HYGIENE_1 review — 2026-04-26

**Dispatcher:** AI Head B
**Working dir:** ~/bm-b1
**Branch:** main; checkout PR branch via `gh pr checkout 64`
**Trigger class:** MEDIUM (DB migration + external API) → second-pair-of-eyes review per 2026-04-24-b1-situational-review-trigger.md
**Reviewer-only:** B1 does NOT modify code; outputs APPROVE / REQUEST_CHANGES with reasoning.

## Review checklist (12 items)

1. § Squash-merge detection logic — does `ahead_by==0` actually catch squash-merged branches? (squash merges typically leave ahead_by > 0 with tree-equal — verify B3's live dry-run of 20 L1 candidates against 75 actual branches matches expected squash-merge semantics)
2. § Migration vs bootstrap drift check — does `migrations/20260426_branch_hygiene_log.sql` column types EXACTLY match `_ensure_branch_hygiene_log_table()` in `memory/store_back.py`? (per Code Brief Standards #4)
3. § subprocess.run usage — list-form args, no shell=True, no string interpolation of branch names into shell. Verify line scripts/branch_hygiene.py:253.
4. § Throttle 10/min on L3 batch delete — verify implementation, not just claimed.
5. § Audit log atomicity — does deletion + log write happen in the same transaction? (Per CHANDA detector #2 ledger-atomic invariant.) If not, document acceptable failure mode.
6. § Whitelist/protected branches — `main` and any release-pattern branches MUST be in protected list. Verify test coverage.
7. § Q2 mobile-UI cluster — verify the 8 specific branches (`feat/mobile-*`, `feat/ios-shortcuts-1`, `feat/document-browser-1`, `feat/networking-phase1`) are explicitly handled (not just falling through L1 by accident).
8. § Triaga HTML escaping — XSS-safe? branch names in HTML are escaped (test_triaga_html_escapes_branch_names confirms; verify implementation matches test).
9. § APScheduler `branch_hygiene_weekly` — Mon 10:30 UTC, no overlap with `ai_head_weekly_audit` (09:00 UTC) or `ai_head_audit_sentinel` (10:00 UTC).
10. § Singletons — `bash scripts/check_singletons.sh` clean (no canonical-singleton class instantiated outside `_get_global_instance()`).
11. § Test count — 15/15 pass per ship report; sanity-check tests cover the destructive paths (real_deletes_and_audits, failed_delete_not_audited).
12. § Live dry-run vs current-state — B3 reports 1 PROTECTED / 20 L1 / 1 MOBILE_CLUSTER / 1 L2_FLAGGED / 55 KEEP. Re-run `python3 scripts/branch_hygiene.py --dry-run` from ~/bm-b1 and confirm match (tolerance: ±2 due to ongoing branch churn since B3's run).

## Ship gate (literal output required in review report)

```
gh pr checkout 64
git pull --rebase origin main
bash scripts/check_singletons.sh
python3 -m pytest tests/test_branch_hygiene.py -v
python3 scripts/branch_hygiene.py --dry-run
git diff --stat main...HEAD
diff <(grep -E 'CREATE TABLE|columns' migrations/20260426_branch_hygiene_log.sql) <(grep -E 'CREATE TABLE|column' memory/store_back.py | head -20)
```

## Review report shape

- Path: `briefs/_reports/B1_pr64_branch_hygiene_review_20260426.md`
- Verdict: APPROVE or REQUEST_CHANGES (with reasoning per checklist item)
- 12-item table with per-item OK / FLAG / FAIL
- Single commit on main: `review(B1): APPROVE/REQUEST_CHANGES PR #64 BRANCH_HYGIENE_1 — 12-check protocol`

## Mailbox hygiene (§3)

After review report committed, overwrite this mailbox file:
```
COMPLETE — PR #64 review APPROVE/REQUEST_CHANGES posted at briefs/_reports/B1_pr64_branch_hygiene_review_20260426.md.
```

If APPROVE → AI Head B proceeds to merge.
If REQUEST_CHANGES → AI Head B routes back to B3 for fix-back.

## Timebox

**60-90 min.** Pure review work, no implementation.

---

**Authority:** RA-19 batch carry-forward + situational-review rule auto-fire.
```
