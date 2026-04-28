---
status: COMPLETE
brief: briefs/BRIEF_CORTEX_3T_FORMALIZE_1C.md
trigger_class: MEDIUM
dispatched_at: 2026-04-28T07:55:00Z
dispatched_by: ai-head-a
prerequisite_pr: 72
prerequisite_state: MERGED 2026-04-28T07:50:48Z (squash 8757ef7)
claimed_at: 2026-04-28T08:00:00Z
claimed_by: b3
last_heartbeat: 2026-04-28T09:55:00Z
blocker_question: null
ship_report: briefs/_reports/B3_pr74_cortex_3t_formalize_1c_20260428.md
pr_number: 74
pr_url: https://github.com/vallen300-bit/baker-master/pull/74
pr_state: OPEN — awaiting B1 second-pair-review + AI Head A /security-review
autopoll_eligible: false
routing_note: re-routed to b3 from original b2 plan (b2 in flight on AI Head B's lane)
---

# CODE_3_PENDING — B3: CORTEX_3T_FORMALIZE_1C (Phase 4/5 + scheduler + dry-run + rollback) — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b3`
**Brief:** [`briefs/BRIEF_CORTEX_3T_FORMALIZE_1C.md`](../BRIEF_CORTEX_3T_FORMALIZE_1C.md) (914 lines, **Amendment A1 + A2 applied** — read both at top of brief)
**Branch:** `cortex-3t-formalize-1c` (cut from `main` post PR #72 merge `8757ef7`)
**Estimated time:** ~14h
**Trigger class:** MEDIUM (new endpoint + Slack interactive + APScheduler + cross-capability state writes + decommission rollback) → B1 second-pair-review pre-merge

## §2 pre-dispatch busy-check (AI Head A verified)

- **B3 mailbox prior state:** COMPLETE — PR #72 (CORTEX_3T_FORMALIZE_1B) merged `8757ef7` 2026-04-28T07:50:48Z. IDLE.
- **Other B-codes:**
  - B1: COMPLETE — PR #72 review APPROVE shipped (`bed8626` merged into main). IDLE.
  - B2: in flight on AI Head B's lane (Director-confirmed Claude App opened); hands-off.
- **Lesson #50 review-in-flight pre-check:** N/A (this is build, not review).

## Routing rationale (Director-accepted recommendation 2026-04-28T07:48Z)

Original session plan was 1C → b2. b2 indefinitely on AI Head B's lane per Director update. Re-routed 1C → b3:
- b3 has just-written context on Cortex internals (1A foundation + 1B reasoning) — exactly the layer 1C wires to.
- Zero idle time vs queueing for b2.
- b1 stays the independent reviewer regardless of builder.

## What you're building

Sub-brief 1C of 3 (Cortex Stage 2 V1) — the interface + ops layer. Six pieces:

1. **Phase 4 (propose)** — Slack Block Kit proposal card with 4 buttons (✅ ✏️ 🔄 ❌) + per-file Gold checkboxes (RA-23 Q2)
2. **`POST /cortex/cycle/{id}/action`** new endpoint — Slack interactivity webhook → button handlers (signature verification mandatory)
3. **Phase 5 (act)** — final-freshness check + execute structured_actions + GOLD via `kbl.gold_proposer.propose(ProposedGoldEntry)` (Amendment A1 — NOT `gold_writer.append`) + propagate curated files to wiki via Mac Mini SSH-mirror
4. **APScheduler `_matter_config_drift_weekly_job`** — Mon 11:00 UTC, mirrors `ai_head_weekly_audit_job`, flags configs not updated >30d
5. **DRY_RUN flag** — `CORTEX_DRY_RUN=true` → log-only first cycle (no Slack post, no GOLD, no propagation, no actions); `dry_run=true` on cycle row
6. **Rollback script** — `scripts/cortex_rollback_v1.sh` committed BEFORE any decommission of `ao_signal_detector` / `ao_project_state`. <5min RTO target.

**Plus Amendment A2 in-scope** (folded from PR #71 B1 review Obs #1, Director RA accepted):
- Wire `triggers/cortex_pipeline.maybe_dispatch(signal_id, matter_slug)` after the `signal_queue` INSERT commits at `kbl/bridge/alerts_to_signal.py:495`.
- Env-flag-gated: `CORTEX_PIPELINE_ENABLED=true` (default false until DRY_RUN passes).
- Try/except wrap: dispatch failures must NOT block `alerts_to_signal` write path.
- Add `tests/test_alerts_to_signal_cortex_dispatch.py` — 2 minimum tests (flag-off no-op, flag-on dispatch failure no-block).

## NOT in scope (PR #72 advisory observations — backlog)

B1's PR #72 review surfaced 3 advisory observations; **all 3 backlogged per Director RA expected** — do NOT fold into 1C scope:
1. Structured-extra logging upgrade (`logger.error(..., extra={cycle_id, phase, error_class})` vs current f-string) — folded into parked Slack alerting brief in vault `_ops/ideas/2026-04-28-cortex-archive-failure-alerting.md`. Don't touch in 1C.
2. Brief-language clarification (status vs current_phase QC#9 wording) — note-only, no code change. Don't touch in 1C.
3. 3a/3c bypass canonical Anthropic-helper layer — parked separately for post-V1 refactor brief. Don't touch in 1C.

## Files Modified (per brief §"Files Modified")

- `orchestrator/cortex_phase4_proposal.py` — new
- `orchestrator/cortex_phase5_act.py` — new
- `orchestrator/cortex_runner.py` — wire Phase 4/5 calls + Amendment A2 wire-up at alerts_to_signal.py
- `dashboard.py` (or new `endpoints/cortex_action.py`) — `POST /cortex/cycle/{id}/action`
- `kbl/bridge/alerts_to_signal.py` — Amendment A2 call-site wire
- `triggers/cortex_pipeline.py` — Amendment A2 dispatch logic
- `scripts/cortex_rollback_v1.sh` — new
- New scheduler job + tests

## Files NOT to Touch

Per brief §"Files NOT to touch" — `kbl/gold_writer.py` (caller-authorized boundary, defense-in-depth), 1B Phase 3 modules (cortex_phase3_*), 1A migrations + bootstrap, Phase 6 archive code, sentinel / dispatch coordination, 7 backlog-noted obs (see "NOT in scope" above).

## Ship gate (literal pytest mandatory — Lesson #47)

```bash
cd ~/bm-b3
pytest tests/test_cortex_phase4_proposal.py tests/test_cortex_phase5_act.py tests/test_cortex_action_endpoint.py tests/test_alerts_to_signal_cortex_dispatch.py tests/test_cortex_rollback.py -v 2>&1 | tail -50
pytest tests/test_cortex_*.py tests/test_alerts_to_signal*.py -v 2>&1 | tail -10  # full regression
```

Paste literal stdout into ship report. **All new tests must pass + 1A's 31/31 + 1B's 48/48 must still pass** (full cortex regression). NO "by inspection" (Lesson #47).

## /security-review (Lesson #52 mandatory)

After B1 approves your PR, AI Head A runs `/security-review` skill in parallel. Both verdicts (B1 + AI Head A) gate the merge. Trigger class MEDIUM = B1 second-pair-review per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`. **Note:** new endpoint + Slack signature verification = security-sensitive surface; A will scrutinize hard.

## Self-PR rule reminder

Same canonical pattern as PR #67/#69/#70/#71/#72: open PR, post `/security-review` verdict as PR comment (formal APPROVE blocked by self-PR rule), AI Head A Tier-A direct squash-merge after B1 + A both clear.

## Process

Per brief §"Process" + canonical PR pattern:
1. `git checkout main && git pull -q`
2. `git checkout -b cortex-3t-formalize-1c`
3. Build per Fix/Feature 1-6 + Amendment A2
4. Run literal pytest (new + regression), capture stdout
5. Push branch, open PR with title `CORTEX_3T_FORMALIZE_1C: Phase 4/5 + scheduler + dry-run + rollback`
6. Write ship report at `briefs/_reports/B3_pr<N>_cortex_3t_formalize_1c_20260428.md`
7. Notify A in chat — A dispatches B1 second-pair-review + runs `/security-review`

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
