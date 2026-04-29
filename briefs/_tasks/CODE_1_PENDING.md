# CODE_1 — DISPATCH (SCHEDULER_DUPLICATE_INSTANCE_RCA_1)

**Status:** PENDING — assigned 2026-04-29T~12:25Z
**Brief:** `briefs/BRIEF_SCHEDULER_DUPLICATE_INSTANCE_RCA_1.md` (commit `e4c5ba1`)
**Builder:** B1
**Trigger class:** LOW (read-only RCA; surgical fix only if ≤20 LOC and not lifecycle-touching — per brief STOP criteria)
**Dispatched by:** AI Head A (sole orchestrator)
**Director authorization:** "Park for tomorrow brief" (2026-04-29 ~11:30Z) — picked up same session

## Scope reminder (read brief for full detail)

- RCA-only deliverable: identify second-source of `kbl_bridge_tick` 2× firing.
- Stable 1.34s offset every minute → two scheduler INSTANCES, not one with `max_instances=2`.
- Bridge-specific (other jobs fire 1×) → disproves "two complete schedulers" hypothesis.
- Investigation goals: §"Investigation goals" in brief (find 2nd source / confirm topology / trace second instance).

## Hard rails

- NO touching: Cortex code (`orchestrator/cortex_*`, `triggers/slack_interactivity.py`, `triggers/cortex_stuck_cycle_sentinel.py`), KBL pipeline, migrations.
- ALLOWED edits ONLY if RCA finds a one-liner: `triggers/embedded_scheduler.py` (≤5 LOC) or `outputs/dashboard.py` (≤5 LOC, scheduler-setup only).
- STOP and surface RCA-alone if fix touches scheduler lifecycle / watchdog / FastAPI lifespan, OR exceeds 20 LOC, OR touches Cortex / Slack interactivity / Phase 5.

## Output

`briefs/_reports/B1_scheduler_duplicate_instance_rca_20260429.md` with §0–§5 shape per brief.

## Test plan (Lesson #48 literal stdout)

- IF code fix shipped: literal `pytest tests/test_embedded_scheduler*.py -v` stdout in report §0.
- IF config-only fix: smoke via `scheduler_executions` table query showing 1× firing across 5-min window post-deploy.
- IF RCA-only: no test required; §3 must include LOC-estimate of proposed fix.

## Pass criteria

- §2 names second source with file:line evidence
- §2 explains why ONLY `kbl_bridge_tick` is 2× (other jobs fire 1×)
- §3 proposed fix with LOC count + scope
- IF fix shipped: 5 consecutive minutes of 1× firing in `scheduler_executions` post-deploy

## Mailbox hygiene (RATIFIED 2026-04-24 §3)

- On report-only completion: overwrite this file with `COMPLETE` + report path
- On PR merge (if fix lands): same — overwrite with `COMPLETE` + PR URL + post-deploy verification

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
