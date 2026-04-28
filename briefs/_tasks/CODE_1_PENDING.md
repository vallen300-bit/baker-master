---
status: OPEN
brief: review_pr_74
trigger_class: MEDIUM
dispatched_at: 2026-04-28T08:12:00Z
dispatched_by: ai-head-a
review_target_pr: 74
review_target_brief: briefs/BRIEF_CORTEX_3T_FORMALIZE_1C.md
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
autopoll_eligible: false
---

# CODE_1_PENDING — B1: SECOND-PAIR REVIEW PR #74 (CORTEX_3T_FORMALIZE_1C) — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b1`
**PR to review:** [#74 cortex-3t-formalize-1c](https://github.com/vallen300-bit/baker-master/pull/74) (HEAD `10b4e4a`, +2958/-20, 21 files)
**Brief:** [`briefs/BRIEF_CORTEX_3T_FORMALIZE_1C.md`](../BRIEF_CORTEX_3T_FORMALIZE_1C.md) — read **Amendment A1 + A2** at top
**Trigger class:** MEDIUM (new endpoint + Slack interactive + APScheduler + cross-capability state writes + decommission rollback) → B1 second-pair-review per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`
**Builder:** B3 (cannot self-review per b1-builder-can't-review-own-work; B1 = independent reviewer)

## §2 pre-dispatch busy-check (AI Head A verified)

- **B1 mailbox prior state:** COMPLETE — PR #72 second-pair review APPROVE shipped (`bed8626`). IDLE.
- **Other B-codes:** B2 idle post-recovery; B3 just shipped PR #74; §3 hygiene pending post-merge.
- **Lesson #50 review-in-flight pre-check:** `gh pr view 74 --json reviewDecision` empty; no `briefs/_reports/B1_pr74*` exists; CLEAN.

## What you're reviewing

PR #74 ships sub-brief 1C of 3 (final piece, Cortex Stage 2 V1). Per B3 ship report:
- 5 new modules: Phase 4 proposal / Phase 5 act / drift audit / rollback / cortex_runner phase4-wire test
- Endpoint `POST /cortex/cycle/{id}/action` added to `dashboard.py`
- APScheduler `_matter_config_drift_weekly_job` registered
- **Amendment A2 wired** at `kbl/bridge/alerts_to_signal.py:495` + `triggers/cortex_pipeline.maybe_dispatch` (env flag `CORTEX_PIPELINE_ENABLED`, default OFF until DRY_RUN passes)
- Rollback script `scripts/cortex_rollback_v1.sh` committed
- 82 new tests pass + 5 skipped (Py 3.9 PEP-604 chain — clean on CI 3.10+); full cortex+bridge regression 181 pass, 5 skipped in 0.91s
- **Amendment A1 honored** (`gold_proposer.propose(ProposedGoldEntry)`, NOT `gold_writer.append`)

## B1 review checklist (7 criteria — 5 standard + 2 amendment-specific)

1. **Brief acceptance match** — every line item in `BRIEF_CORTEX_3T_FORMALIZE_1C.md` §"Verification criteria" + §"Quality Checkpoints" verified against shipped code. Flag any missing.
2. **EXPLORE corrections accuracy (Lesson #44)** — verify any EXPLORE corrections B3 surfaces in the ship report grep-verify against actual code. B3's EXPLORE pass is the anchor.
3. **Tests are real, not "passes by inspection" (Lesson #47)** — run literal `pytest tests/test_cortex_phase4_proposal.py tests/test_cortex_phase5_act.py tests/test_cortex_action_endpoint.py tests/test_alerts_to_signal_cortex_dispatch.py tests/test_cortex_rollback.py -v 2>&1 | tail -50` AND full regression `pytest tests/test_cortex_*.py tests/test_alerts_to_signal*.py -v 2>&1 | tail -10` in your worktree; paste literal stdout into review report. 82 new pass + 5 skipped + 181 total green required per B3's claim.
4. **Slack signature verification — DEFERRAL ACCEPTED 2026-04-28T08:25Z** — Director-ratified deferral after AI Head A `/security-review`: `POST /cortex/cycle/{id}/action` ships **internal-only** (gated by `Depends(verify_api_key)` / X-Baker-Key static header). Slack-signed `/slack/interactivity` proxy with HMAC-SHA256 + timestamp ≤5min + constant-time compare + response_url pass-through is parked as separate follow-up brief (`_ops/ideas/2026-04-28-cortex-slack-interactivity-proxy.md`). **Verify only that the X-Baker-Key gate is in place and that no cortex_* module bypasses `verify_api_key`.** Do NOT flag missing Slack HMAC as REQUEST_CHANGES — it's accepted scope deferral.
5. **Boundaries respected** — `gold_writer.append` NOT called from any cortex_* module (Amendment A1). `gold_proposer.propose(ProposedGoldEntry)` IS the only cortex-side GOLD write path. cycle_id linkage via `ProposedGoldEntry.cortex_cycle_id` field. Caller-authorized guard (`kbl/gold_writer.py:_check_caller_authorized`) NOT touched.

## Amendment-specific checks (additional 2 criteria)

6. **Amendment A1 (gold_proposer not gold_writer)** — grep all 1C files for `gold_writer.append`; expected count: 0. grep for `gold_proposer.propose`; expected: ≥1. Flag if any cortex_* module imports `kbl.gold_writer` (other than for type-checking imports).
7. **Amendment A2 (alerts_to_signal:495 callsite)** — verify `triggers/cortex_pipeline.maybe_dispatch(signal_id, matter_slug)` called AFTER the `signal_queue` INSERT commits at `kbl/bridge/alerts_to_signal.py:495`. Verify try/except wrap (dispatch failure must NOT block INSERT). Verify env flag gating on `CORTEX_PIPELINE_ENABLED` (default false). Verify 2 minimum tests in `tests/test_alerts_to_signal_cortex_dispatch.py` (flag-off no-op, flag-on dispatch failure no-block).

## Output: review report at `briefs/_reports/B1_pr74_cortex_3t_formalize_1c_20260428.md`

Then post verdict on PR via `gh pr comment 74 --body "<verdict>"` (formal APPROVE blocked by self-PR rule per #67/#69/#70/#71/#72 precedent — comment is the gate).

## Parallel work this window

- AI Head A runs `/security-review` skill on PR #74 (Lesson #52 mandatory). Slack signature verification + new endpoint = security-sensitive surface; A will scrutinize hard.
- AI Head B doing structural-design cross-lane pass alongside (3 reviewers > 2 on highest-stakes ship in V1).
- All 3 verdicts (B1 + AI Head A + AI Head B) gate the merge. AI Head A merges Tier-A on all-clear.

## NOT in scope

- Refactor of Phase 3a/3c through canonical Anthropic helper — parked at `_ops/ideas/2026-04-28-cortex-anthropic-helper-canonical-refactor.md` (post-V1).
- Structured-extra logging upgrade — parked at `_ops/ideas/2026-04-28-cortex-archive-failure-alerting.md` (post-V1).
- cycle_id single-source-of-truth cleanup — parked at `_ops/ideas/2026-04-28-cortex-cycle-id-generation-cleanup.md` (post-V1).

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
