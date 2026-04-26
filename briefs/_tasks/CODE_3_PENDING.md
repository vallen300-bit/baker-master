# CODE_3_PENDING — B3: AMEX_RECURRING_DEADLINE_1 — 2026-04-26

**Dispatcher:** AI Head B (Build-reviewer, M2 lane)
**Working dir:** `~/bm-b3`
**Branch:** `amex-recurring-deadline-1` (create from main; B3 worktree on stale `gold-comment-workflow-1` post-merge — `git checkout main && git pull -q` first)
**Brief:** `briefs/BRIEF_AMEX_RECURRING_DEADLINE_1.md` (**AMENDED 2026-04-26 PM** post-EXPLORE pass — see Authority chain footer)
**Status:** OPEN
**Trigger class:** **MEDIUM** (DB migration on `deadlines` + cross-capability state writes via 3 completion-path call-site mods) → **B1 second-pair-of-eyes review required pre-merge** per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`. Builder ≠ B1.

---

## §2 pre-dispatch busy-check

- **Mailbox prior:** COMPLETE — PR #66 GOLD merged 95d99f3. Idle ✓
- **Branch state:** B3 worktree on stale `gold-comment-workflow-1`; `git checkout main && git pull -q` resolves.
- **Other B-codes:** B1 idle (post-PR #66 review). B2 → WIKI_LINT_1. B5 → CHANDA rewrite. No overlap.
- **Lesson #47/§2 amendment candidate (review-already-in-flight):** N/A — this is a build dispatch, not review.
- **Brief amendment (2026-04-26 PM):** initial AMEX brief (commit `820fa9a`) had 3 defects surfaced via post-PR-#66 EXPLORE pass. Amendment lands wrong-integration-points fix (actual API: `complete_deadline` line 796 / `dismiss_deadline` line 774 / `confirm_deadline` line 816 + 2 raw UPDATE paths in `clickup_trigger.py:535` + `models/deadlines.py:387`); `python-dateutil` requirements.txt addition; auto-dismiss race-window fix (`AND recurrence IS NULL` exclusion).

**Dispatch authorisation:** Director RA-21 2026-04-26 PM "Q2 RESOLVED: anchor_date = 3rd of every month" + default-fallback ("Your 3 question — you default. I skip") + RA-21 reroute ("M2 = your natural lane").

## Brief route (charter §6A)

`/write-brief` 6-step protocol applied retroactively via amendment (Rule 0 compliant). Brief at `briefs/BRIEF_AMEX_RECURRING_DEADLINE_1.md`.

## Action

Read brief end-to-end (especially §3 Architecture amendment + §5 Code Brief Standards 1-10 + §10 Amendment H invocation-path audit). Implement:

1. Schema migration: `deadlines` + 4 new columns (`recurrence`, `recurrence_anchor_date`, `recurrence_count`, `parent_deadline_id`)
2. `compute_next_due()` helper in `deadline_manager.py` using `dateutil.relativedelta` (handle Feb edge cases / leap year)
3. **`_maybe_respawn_recurring(deadline_id)` helper** — idempotent (checks for existing child with same anchor before creating); cap respawn rate 1/day per parent; alert Director on cap hit
4. **Wire ALL 3 completion paths to call helper** (Amendment H critical):
   - `complete_deadline()` line 796 — direct call
   - `triggers/clickup_trigger.py:535` raw UPDATE — inline call after UPDATE
   - `models/deadlines.py:387` raw UPDATE — inline call after UPDATE
5. Auto-dismiss paths skip recurring (`_auto_dismiss_overdue_deadlines` line 672 + `_auto_dismiss_soft_deadlines` line 706): add `AND recurrence IS NULL` to WHERE
6. Dismiss UX: `dismiss_deadline` for recurring asks "this instance only or stop recurrence?" (default: this instance only)
7. `requirements.txt`: add `python-dateutil`
8. Migration `migrations/20260426_amex_recurrence.sql` + matching `_ensure_*` bootstrap in `memory/store_back.py` (mirror pattern from `_ensure_ai_head_audits_table` line 511 — `_get_conn()` + `cur.close()`)
9. Acceptance test: AmEx (#1438) → `recurrence='monthly'`, `recurrence_anchor_date='2026-05-03'`; verify spawn after `complete_deadline` call
10. Tests: `tests/test_deadline_recurrence.py` (≥10 cases: 4 recurrence types × edge cases (Feb / leap year / end-of-month) + idempotency + cap-rate + parent-link + 3-path Amendment H verification)

**Out of scope** (per brief §6): Calendar integration / cron expressions / holiday adjustments / max-count.

## Ship gate (literal output required)

```bash
cd ~/bm-b3 && git checkout main && git pull -q
git checkout -b amex-recurring-deadline-1
# ... implement ...
bash scripts/check_singletons.sh                          # OK: No singleton violations
python3 -c "import dateutil.relativedelta; print('dateutil OK')"  # post-requirements.txt update + pip install
pytest tests/test_deadline_recurrence.py -v               # ≥10 cases, all green
pytest tests/ 2>&1 | tail -3                              # full suite no regressions
# Migration-vs-bootstrap drift (Standard #4):
diff <(grep -A 8 "ALTER TABLE deadlines" migrations/20260426_amex_recurrence.sql | sort) \
     <(grep -A 8 "ALTER TABLE deadlines\|ADD COLUMN.*recurrence" memory/store_back.py | sort)
# Amendment H verification (3 paths wired):
grep -nE "_maybe_respawn_recurring" orchestrator/deadline_manager.py triggers/clickup_trigger.py models/deadlines.py
# expect: ≥1 match in each file
# Auto-dismiss exclusion verification:
grep -B2 -A6 "_auto_dismiss_overdue_deadlines\|_auto_dismiss_soft_deadlines" orchestrator/deadline_manager.py | grep -E "recurrence IS NULL"
# expect: ≥2 matches (both auto-dismiss functions)
git diff --name-only main...HEAD
git diff --stat
```

**No "by inspection"** (per `feedback_no_ship_by_inspection.md`).

## Ship-report shape

- **Path:** `briefs/_reports/B3_amex_recurring_deadline_1_20260426.md`
- **Contents:** all literal outputs above + acceptance test result on AmEx #1438 (record before/after rows) + Amendment H 3-path wire verification + auto-dismiss exclusion verification.
- **PR title:** `AMEX_RECURRING_DEADLINE_1: recurrence on deadlines + 3-path respawn wiring + auto-dismiss exclusion`
- **Branch:** `amex-recurring-deadline-1`

## After PR open

PR will be opened against `main`. **Do NOT auto-merge** — trigger-class MEDIUM requires B1 review. B1 dispatch fires from AI Head B once B3 ship-report posted.

## Mailbox hygiene (§3)

After PR merged (post B1 APPROVE), overwrite this file:
```
COMPLETE — AMEX_RECURRING_DEADLINE_1 merged as <commit-sha> on 2026-04-2X by AI Head B (B1 review APPROVE). §3 hygiene per b-code-dispatch-coordination.
```

## Timebox

**~5–7h.** Migration + helper + 3-path wiring + auto-dismiss fix + dependency add + 10+ tests + acceptance test on real AmEx row.

---

**Dispatch timestamp:** 2026-04-26 ~22:30 UTC
**Authority chain:** Director RA-21 2026-04-26 PM Q2 resolution + default-fallback → RA-19 spec → AI Head B `/write-brief` retroactive amendment (post-PR-#66 EXPLORE) → B3 build → B1 review (situational-review trigger) → AI Head B merge.
