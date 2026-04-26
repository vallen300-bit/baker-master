# CODE_3_PENDING — B3: GOLD_COMMENT_WORKFLOW_1 — 2026-04-26

**Dispatcher:** AI Head B (Build-reviewer, M2 lane)
**Working dir:** `~/bm-b3`
**Branch:** `gold-comment-workflow-1` (create from main; B3 worktree on stale `branch-hygiene-1` post-merge — checkout main + pull first)
**Brief:** `briefs/BRIEF_GOLD_COMMENT_WORKFLOW_1.md`
**Status:** OPEN
**Trigger class:** **MEDIUM** (DB migration + cross-capability state writes) → **B1 second-pair-of-eyes review required pre-merge** per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`. Builder ≠ B1 (you're B3 — confirmed eligible).

---

## §2 pre-dispatch busy-check (per `_ops/processes/b-code-dispatch-coordination.md`)

- **Mailbox prior:** `COMPLETE — BRANCH_HYGIENE_1 (B3 build) merged 676803e 2026-04-26`. Idle ✓
- **Branch state:** main + pull. B3 worktree may show stale `branch-hygiene-1` — `git checkout main && git pull -q` resolves.
- **Other B-codes:** B1 idle post-PR #64 review. B2 → WIKI_LINT_1 in flight (no overlap). B5 → CHANDA rewrite (no overlap).
- **Lesson #47 redundancy check:** verified existing `kbl/gold_drain.py` (WhatsApp queue drain — different lane), `kbl/loop.py:342 load_gold_context_by_matter` (Cortex Leg 1 read — different consumer), `_ensure_gold_promote_queue` (different table). No overlap with the 4 modules + audit job + hook this brief introduces.

**Dispatch authorisation:** Director RA-21 2026-04-26 PM "Proceed with Gold Comment". Q1–Q4 all RATIFIED (see brief §Context).

## Brief route (charter §6A)

`/write-brief` 6 steps applied (per SKILL Rule 0 mandatory). Brief at `briefs/BRIEF_GOLD_COMMENT_WORKFLOW_1.md`. EXPLORE phase verified `kbl/gold_drain.py` distinct lane; `_ai_head_weekly_audit_job` pattern at `triggers/embedded_scheduler.py:719` confirmed as APScheduler mirror; `_ensure_ai_head_audits_table` at `memory/store_back.py:511` confirmed as schema mirror (uses `_get_conn()` + `cur.close()`, NOT context manager); `_safe_post_dm` at `triggers/ai_head_audit.py:452` confirmed as canonical Slack DM helper.

## Action

Read brief end-to-end. Implement 7 components:

1. `kbl/gold_writer.py` — programmatic Tier B write path (caller-stack guard rejects cortex callers)
2. `kbl/gold_proposer.py` — Cortex agent-drafted proposed-gold writes (parallel module)
3. `kbl/gold_drift_detector.py` — pre-write `validate_entry()` + full-corpus `audit_all()`
4. `kbl/gold_parser.py` — read + audit aggregator (returns dict for `gold_audits.payload_jsonb`)
5. `migrations/20260426_gold_audits.sql` + matching `_ensure_gold_audits_table()` + `_ensure_gold_write_failures_table()` in `memory/store_back.py` (mirror exact pattern of `_ensure_ai_head_audits_table` at line 511)
6. `orchestrator/gold_audit_job.py` + scheduler registration in `triggers/embedded_scheduler.py` (Mon 09:30 UTC, `GOLD_AUDIT_ENABLED` kill-switch)
7. `baker-vault/.githooks/gold_drift_check.sh` — commit-msg-stage hook (NOT pre-commit; per `feedback_chanda_4_hook_stage_bug.md`)

Plus tests: `tests/test_gold_writer.py`, `test_gold_proposer.py`, `test_gold_parser.py`, `test_gold_drift_detector.py` (≥20 cases total per Quality Checkpoint #2).

Plus process doc: `baker-vault/_ops/processes/gold-comment-workflow.md` (canonical process; back-refs from cortex3t-roadmap.md + MEMORY.md + agent triplets resolve here once landed).

## Ship gate (literal output required)

```bash
cd ~/bm-b3 && git checkout main && git pull -q
git checkout -b gold-comment-workflow-1
# ... implement ...
bash scripts/check_singletons.sh                          # OK: No singleton violations
python3 -m pytest tests/test_gold_writer.py tests/test_gold_proposer.py tests/test_gold_parser.py tests/test_gold_drift_detector.py -v
# expect: ≥20 cases all passing
python3 -m pytest tests/ 2>&1 | tail -3
# expect: full-suite no regressions
# Migration-vs-bootstrap diff (Standard #4):
diff <(grep -A 10 "CREATE TABLE.*gold_audits" migrations/20260426_gold_audits.sql) \
     <(grep -A 10 "CREATE TABLE.*gold_audits" memory/store_back.py)
diff <(grep -A 10 "CREATE TABLE.*gold_write_failures" migrations/20260426_gold_audits.sql) \
     <(grep -A 10 "CREATE TABLE.*gold_write_failures" memory/store_back.py)
# Both diffs empty modulo whitespace
grep "gold_audit_sentinel" triggers/embedded_scheduler.py | head -5
# expect: ≥3 matches (registration + name + log)
git diff --name-only main...HEAD
git diff --stat
```

**No "by inspection"** (per `feedback_no_ship_by_inspection.md`).

## Ship-report shape

- **Path:** `briefs/_reports/B3_gold_comment_workflow_1_20260426.md`
- **Contents:** all literal outputs above + acceptance test results from §Quality Checkpoints (synthetic conflict + caller-stack rejection + DV-only check + backfill validation of existing 2 entries) + commit-msg hook install verification on baker-vault clone.
- **PR title:** `GOLD_COMMENT_WORKFLOW_1: 4 modules + audit sentinel + commit-msg hook (Hybrid C ratified)`
- **Branch:** `gold-comment-workflow-1`

## After PR open

PR will be opened against `main`. **Do NOT auto-merge** — trigger-class MEDIUM requires B1 review. B1 dispatch fires from AI Head B once B3 ship-report posted.

## Mailbox hygiene (§3)

After PR merged (post B1 APPROVE), overwrite this file:
```
COMPLETE — GOLD_COMMENT_WORKFLOW_1 merged as <commit-sha> on 2026-04-2X by AI Head B (B1 review APPROVE). §3 hygiene per b-code-dispatch-coordination.
```

## Timebox

**~6–8h.** 4 modules + 4 test files + migration + scheduler + hook + process doc. If approaching 10h, stop and flag — split-into-phases option exists (Phase 1: writer + drift + migration + tests; Phase 2: proposer + parser + audit job + hook).

## Out of scope (explicit)

- NO modifications to `kbl/gold_drain.py` (distinct lane)
- NO modifications to `kbl/loop.py:load_gold_context_by_matter` (different consumer)
- NO writes to existing `_ops/director-gold-global.md` content (validate via parser; never overwrite)
- NO `cortex_*` module changes (M2 not landed; gold_proposer prepares contract)
- NO LLM-assisted topic-key extraction (V2)
- NO auto-promotion of Proposed Gold (V2; Director hand-mediates)

---

**Dispatch timestamp:** 2026-04-26 ~16:00 UTC
**Authority chain:** Director RA-21 "Proceed with Gold Comment" → RA-21 spec (vault `e3465ab`) → AI Head B `/write-brief` skill draft (Rule 0 compliant) → B3 build → B1 review (situational-review trigger) → AI Head B merge.
