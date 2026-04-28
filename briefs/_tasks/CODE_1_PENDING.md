---
status: OPEN
brief: validation_sql_dryrun
trigger_class: LOW
dispatched_at: 2026-04-28T16:55:00Z
dispatched_by: ai-head-a
target_plan: briefs/_plans/CORTEX_V1_DRY_RUN_LAUNCH_PLAN_20260428.md
target_section: §3 (Validation SQL)
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
autopoll_eligible: false
---

# CODE_1_PENDING — B1: PLAN §3 VALIDATION SQL DRY-RUN — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b1`
**Trigger class:** LOW (read-only SQL execution against empty cortex state)

## §2 pre-dispatch busy-check

- **B1 prior state:** COMPLETE — PR #74 review APPROVE (`6eb9dc8`). IDLE.
- **Other B-codes:** B2 (App) IDLE; B3 in flight on rollback-script-op-path-fix-1.
- Read-only DB queries — zero conflict with B3's branch.

## What you're doing

Execute every validation query in plan §3 against current main DB state (no live cycle has run). Each query must:
- Parse cleanly (no syntax errors)
- Return the expected baseline (0 rows for cycle/phase/cost/terminal queries; baseline rows for A2 bridge + drift-audit queries)
- Have correct column names matching actual schema (catch any column-name typos before live cycle)

## Steps

```bash
cd ~/bm-b1
git checkout main
git pull -q
# Read §3 only:
sed -n '/^## 3\./,/^## 4\./p' briefs/_plans/CORTEX_V1_DRY_RUN_LAUNCH_PLAN_20260428.md > /tmp/section3.md
cat /tmp/section3.md
```

For each of the 6 §3 queries, run via Baker MCP `baker_raw_query` (read-only). Paste literal SQL + literal result for each.

Expected baselines:
1. cycle row check — 0 rows (no cycles yet)
2. per-phase artifacts (incl. `dry_run_marker` phase_order=8 canary) — 0 rows
3. cost ceiling — 0 rows or NULL aggregate
4. terminal status — 0 rows
5. A2 bridge sanity — query parses; row count depends on alerts_to_signal recent activity (any non-error result is PASS)
6. drift-audit verification — query parses; baseline depends on `_matter_config_drift_weekly_job` last fire (any non-error result is PASS)

## Pass criteria

- All 6 queries parse without error
- Queries 1-4 return empty/zero baseline as expected
- Queries 5-6 execute cleanly (any row count is PASS — these query existing data)
- Any query that errors, has a column-name typo, or returns unexpected non-zero on queries 1-4 → FAIL with reason

## Output

Ship report: `briefs/_reports/B1_validation_sql_dryrun_20260428.md`

Format:
```markdown
# B1 — Plan §3 Validation SQL dry-run — 2026-04-28

## Query 1 — cycle row check
SQL: <literal>
Result: <literal>
Status: PASS / FAIL <reason>

## Query 2 — per-phase artifacts
...

(repeat for all 6)

## Verdict
PASS / FAIL with per-query line. List any column-name typos / SQL bugs found.
```

Mailbox flip COMPLETE on ship; notify A in chat with verdict line.

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
