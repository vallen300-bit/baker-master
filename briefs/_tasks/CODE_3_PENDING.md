# CODE_3_PENDING — B3: BRANCH_HYGIENE_1 — 2026-04-26

**Dispatcher:** AI Head B (Build-reviewer)
**Working dir:** `~/bm-b3`
**Branch:** `branch-hygiene-1` (create from main)
**Brief:** `briefs/BRIEF_BRANCH_HYGIENE_1.md`
**Status:** OPEN — supersedes prior HOLD (PLAUD_SENTINEL_1 redundant per lesson #47)
**Trigger class:** LOW (touches GitHub external API but no auth/DB-migration/secrets/financial) → AI Head solo merge

---

## §2 pre-dispatch busy-check

- **Mailbox prior:** `HOLD — PLAUD_SENTINEL_1 redundant against shipped sentinel`. Worker free; mailbox cleared by this dispatch.
- **Branch state:** main; `git checkout main && git pull` first. (Worker may have stale `plaud-sentinel-1` checkout — discard.)
- **Other B-codes:** B1 → DEADLINE_EXTRACTOR_QUALITY_1 in flight (no overlap). B2 → WIKI_LINT_1 (no overlap). B5 → CHANDA rewrite (no overlap).
- **Lesson #47 redundancy check:** branch-hygiene script — no shipped equivalent; spec confirms 75 stale branches.

**Dispatch authorisation:** Director default-fallback 2026-04-26 ("Your 3 question — you default. I skip") + Cat 7 close "C" ratification. Q2 default = **delete the 8-branch mobile UI cluster.**

## Brief route (charter §6A)

`/write-brief` 6 steps applied. Brief at `briefs/BRIEF_BRANCH_HYGIENE_1.md`. Q1/Q2/Q3 defaulted (see brief §4).

## Action

Read brief end-to-end. Implement `scripts/branch_hygiene.py` with L1+L2+L3 logic + audit log + APScheduler weekly job registration.

First-run priority: clear backlog of ~50 squash-merged branches via L1 + flag 21 L2 candidates + delete 8 mobile-UI cluster (Q2 default = delete: `feat/mobile-*`, `feat/ios-shortcuts-1`, `feat/document-browser-1`, `feat/networking-phase1`).

Triaga HTML for L2 candidates → Director review pre-L3 batch delete.

## Ship gate (literal output required)

```
pytest tests/test_branch_hygiene.py -v
# ≥6 tests: L1 squash detection + L2 staleness flag + L3 delete (mocked) + whitelist (main + protected) + log row creation
pytest tests/ 2>&1 | tail -3
bash scripts/check_singletons.sh
python3 scripts/branch_hygiene.py --dry-run
# expect: ~50 L1 candidates / 21 L2 flagged / 0 actual deletions in dry-run
git diff --name-only main...HEAD
git diff --stat
```

**No "by inspection"** (per `feedback_no_ship_by_inspection.md`).

## Ship-report shape

- **Path:** `briefs/_reports/B3_branch_hygiene_1_20260426.md`
- **Contents:** all literal outputs above + dry-run output + Triaga HTML link + APScheduler job registration evidence (`grep branch_hygiene_weekly triggers/embedded_scheduler.py`).
- **PR title:** `BRANCH_HYGIENE_1: auto-prune stale branches L1/L2/L3 + audit log + weekly cron`
- **Branch:** `branch-hygiene-1`

## Mailbox hygiene (§3)

After PR merged, overwrite this file:
```
COMPLETE — BRANCH_HYGIENE_1 merged as <commit-sha> on 2026-04-26 by AI Head B. §3 hygiene per b-code-dispatch-coordination.
```

## Timebox

**~3–4h.** Includes script + tests + audit-log table + APScheduler job + Triaga HTML.

## Out of scope (explicit)

- NO local-clone branch cleanup (Director's local concern)
- NO worktree cleanup (`Desktop/baker-code/00_WORKTREES.md` separate)
- NO PR auto-close on stale branch (orthogonal)
- NO physical deletion of 30–90d cluster beyond mobile UI without Director Triaga tick

---

**Dispatch timestamp:** 2026-04-26 ~07:00 UTC.
**Authority chain:** Director default-fallback → RA-19 spec → AI Head B brief promotion + dispatch → B3 execution.
