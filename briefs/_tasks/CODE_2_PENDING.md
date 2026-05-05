---
status: COMPLETE
brief: briefs/BRIEF_CORTEX_PHASE3B_PARALLEL_AND_INCREMENTAL_COST_1.md
trigger_class: CORE_ORCHESTRATION_FIX
dispatched_at: 2026-05-03T~earlier
dispatched_by: ai-head-a
claimed_at: 2026-05-03T12:53:06Z
claimed_by: b2
completed_at: 2026-05-03T12:53:06Z
ah2_review: GREEN (2 non-blocking nits — env-verify of CORTEX_CYCLE_TIMEOUT_SECONDS=900 [empirically confirmed via cycle 70c5e634 wall-clock=900s] + pre-existing docstring drift on _invoke_one)
merged_at: 2026-05-03T19:48:26Z
merge_commit: 7fa48cb4f4647c4f74546abadbe52ca845e23577
verdict: PASS
ship_report: briefs/_reports/B2_phase3b_parallel_cost_20260503.md
pr: 155
autopoll_eligible: false
---

B2: Phase 3b parallel + per-completion cost bump (the Step 30 wall-clock blocker).

**Verdict:** SHIP — AH2 review GREEN, AH1 autonomous-merge per charter §3 + Director "Go" 2026-05-03.

Files (in merge):
- `orchestrator/cortex_phase3_invoker.py` (+49/-10) — `asyncio.gather` + `_invoke_one_with_persist_and_bump` helper + `Semaphore(3)` DB gate
- `tests/test_cortex_phase3_invoker.py` (+47/-7) — concurrent-ordering test + per-completion bump test + zero-cost-failure skip
- Tests: 13/13 invoker + 16/16 runner_phase126 + 62/62 caller regressions + singleton CI clean

**Next gates (AH1):**
1. Render auto-deploy from main (typically 3-5 min for baker-master).
2. Smoke-test cycle on AO with benign question (or Director-announced topic) — verify SSE phase_output events cluster within ~30-60s, cost roll-up grows incrementally.
3. Verification SQL post-deploy: `gap_seconds` between `specialist_invocation` rows in `cortex_phase_outputs` is sub-second to few-second (not the 100-300s gaps observed in cycle 70c5e634).
4. After smoke clean → surface to Director for §4 Step 30 LIVE re-fire authorization.

**B2 mailbox-hygiene flip 2026-05-05:** prior brief CORTEX_PHASE3B_PARALLEL_AND_INCREMENTAL_COST_1 confirmed COMPLETE — shipped 2026-05-04 as PR #155, merge commit `7fa48cb` on baker-master main. New dispatch appended below.

---

---
status: COMPLETE
brief: briefs/BRIEF_BAKER_COST_INSTRUMENTATION_1.md
trigger_class: TIER_A_DB_SCHEMA_PLUS_COST_TRACKING
dispatched_at: 2026-05-05
dispatched_by: ai-head-a-pl
claimed_by: b2
ship_report: briefs/_reports/B2_cost_instrumentation_20260505.md
gate_chain_initial: pytest GREEN 67/67 + AH2 /security-review PASS-WITH-NITS (5 NITs non-blocking) + Architect PASS + feature-dev:code-reviewer PASS-WITH-NITS-FOLD-NEEDED → fold H1+M1 → re-fired gates 1+3+4 PASS on fold diff (parallel Terminal architect + code-reviewer agents) + AH2 gate-2 re-fire PASS on fold diff (comment 4383029994)
fold_commit: 55d2ad19
mergeconflict_resolution_spec_commit: eb3d6293
merge_commit_b2_branch: 6e3bb51c (true merge against origin/main 46c5b1a)
merged_at: 2026-05-05T~21:XXZ
merge_commit: 4b457b2ec32b24249f10ed02a934910217b599ae
pr: 158
verdict: PASS
follow_ups: B1 NITs (N1+N5 → cost-control-runbook rollout note; N2/N3/N4 → scaling-followups stub) pending; sweep brief 1553b6e dispatch to next idle B-code pending
autopoll_eligible: false
---

# CODE_2_PENDING — BRIEF_BAKER_COST_INSTRUMENTATION_1 — 2026-05-05 (COMPLETE)

**Brief:** baker-master `briefs/BRIEF_BAKER_COST_INSTRUMENTATION_1.md` (Tier A, ~2 days, 10 ACs)
**Working branch:** `b2/baker-cost-instrumentation-1`
**Pre-requisites:** baker-master main HEAD (commit `d086c8d` introducing this brief). Decoupled from caching brief per architect review (signature ownership decoupled).
**Acceptance criteria:** per brief §ACs (10 testable items)
**Ship gate:** literal `pytest` GREEN — no by-inspection (Lesson #52)
**Heartbeat:** 12h cadence binding (per SKILL.md `59f23c4` §B-code stall chase)

**Read first (MANDATORY):**
1. `briefs/BRIEF_BAKER_COST_INSTRUMENTATION_1.md` — full spec + design decisions + 10 ACs
2. `~/baker-vault/_ops/agents/b2/orientation.md` — your role
3. `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` — canonical Baker memory

**First-message confirmation phrase (evidence-bound, exact):**
`"B2 oriented. Read: CODE_2_PENDING.md, MEMORY.md."`

**Path forward:**
1. Read brief BRIEF_BAKER_COST_INSTRUMENTATION_1.md cover-to-cover
2. Implement 10 ACs on `b2/baker-cost-instrumentation-1` branch
3. Apply two migrations: `<UTC-timestamp>_api_cost_log_matter_slug.sql` + `<UTC-timestamp>_cost_alert_state.sql`. Refresh `applied_migrations.lock` from prod after BOTH apply
4. Note new `cost_alert_state` table for DB-persisted tier idempotence (per architect post-WRITE fix — fixes the existing `_alert_sent_date` restart-bug in passing)
5. 23:55 UTC scheduler registration named explicitly: APScheduler `CronTrigger(hour=23, minute=55, timezone='UTC')` job id=`daily_cost_summary` in `triggers/embedded_scheduler.py` (mirror `gold_audit_sentinel` pattern at line 746)
6. Live pytest GREEN
7. Open PR
8. Ship via PL paste-block per SKILL.md §"PL ship-report contract"
9. 4-gate review chain: live pytest + AH2 /security-review + architect spot-check + feature-dev:code-reviewer 2nd-pass (per SKILL.md `59f23c4` Trigger §2 — DB schema change)

**Critical pre-merge gates (from architect post-WRITE review):**
- `log_api_cost()` signature: only `matter_slug` param belongs to this brief. Cache-token params owned by sibling caching brief — do NOT add them here
- Migration sibling-coupling: filenames timestamps differ from `BRIEF_BAKER_PROMPT_CACHING_1` migration by ≥1s; refresh lock once after BOTH apply (independent ADD COLUMN IF NOT EXISTS, safe regardless of merge order)
- `COST_ALERT_EUR` constant kept as alias (referenced by `get_daily_breakdown:190` + `get_cost_dashboard:360`); point alias to `COST_TIERS[0][0]`
- A7 honest scope: matter_slug attribution for `capability_runner` only; pipeline + agent_loop pass-through `None` is acceptable (~95% `[unattributed]` day-one expected); follow-up brief stub `BRIEF_PIPELINE_MATTER_RESOLUTION_1.md` opens the gap visibly

**Anchor:** Director ratification 2026-05-05 ("go" after compare-and-contrast of code-side vs app-side architect verdicts); brief commit `d086c8d`; AH2 busy-check confirmed B2 effectively idle 2026-05-05.

---

## GATE-4 2nd-pass UPDATE — 2026-05-05 (fold before merge)

**Source:** feature-dev:code-reviewer 2nd-pass on PR #158 — verdict PASS-WITH-NITS-FOLD-NEEDED. 1 HIGH (real runtime crash on cost dashboard endpoint) + 1 MED (zero-warning-window on critical tier). Same fold-pre-merge pattern as B1/B4.

### H1 — FOLD REQUIRED — SQL INTERVAL parameterization crash in get_cost_history / get_capability_costs

File: `orchestrator/cost_monitor.py`
Lines: 334 (get_cost_history) + 386 (get_capability_costs)

Issue: Both queries use `INTERVAL '%s days'` with `(days,)` as a bound
parameter. psycopg2 does NOT interpolate %s inside a SQL string literal — the
interval string is sent verbatim as `'%s days'` to PostgreSQL, which is not a
valid interval syntax and raises a runtime error. The cost dashboard endpoint
and `get_cost_dashboard()` will 500 on every call.

Fix (both sites):
    Change: WHERE logged_at > NOW() - INTERVAL '%s days'
    To:     WHERE logged_at > NOW() - (INTERVAL '1 day' * %s)

Regression test: add `test_get_cost_history_interval_parameterization` to
`tests/test_cost_alarms.py` using the existing `_Cursor` harness — assert
cursor.queries[-1][0] contains `INTERVAL '1 day' * %s` and does NOT contain
`INTERVAL '%s'`.

### M1 — FOLD RECOMMENDED — critical tier threshold equals hard-stop (zero warning window)

File: `orchestrator/cost_monitor.py`
Lines: 45, 49

Issue: Default `BAKER_COST_TIER_CRITICAL_EUR=100.0` == `BAKER_COST_HARD_STOP_EUR=100.0`.
Critical alarm and hard-stop fire atomically on the same call; critical tier
provides no advance warning.

Fix: Change `BAKER_COST_TIER_CRITICAL_EUR` default from `"100.0"` to `"80.0"`.

Regression test: add `test_critical_tier_below_hard_stop_by_default` asserting
`cost_monitor.COST_TIERS[2][0] < cost_monitor.COST_HARD_STOP_EUR` when env
vars are unset. Also update any test that hardcodes critical=100.

**Path forward:**
1. Apply H1+M1 on `b2/baker-cost-instrumentation-1` branch
2. Add 2 regression tests (one per finding)
3. Live pytest GREEN both sides (literal output — Lesson #52)
4. Re-fire focused gate chain on diff only
5. Report new HEAD SHA + gate verdicts back to PL

---

## MERGE-CONFLICT RESOLUTION UPDATE — 2026-05-05 (post B1 PR #159 merge)

**Source:** PR #158 mergeStateStatus=DIRTY against `origin/main` after B1 PR #159 (BAKER_PROMPT_CACHING_1) merged at `a8dea7c`. AH1 PL skip+merge authorization withheld pending conflict resolution by you (B2 has full test coverage).

**Conflicts surfaced (5 total):**

1. `orchestrator/cost_monitor.py` lines ~72-80 — docstring of `ensure_api_cost_log_table`. Both branches updated for Lesson #50 alignment. Merge: combine both docstring intents (matter_slug parity + cache token parity).

2. `orchestrator/cost_monitor.py` lines ~194-219 — `log_api_cost` signature + docstring + `calculate_cost_eur` call.
   **Architect-mandated decoupling:** matter_slug param OWNED by you (B2); cache_creation_input_tokens / cache_read_input_tokens params OWNED by B1. Merged signature MUST include all three, kwargs-defaulted.
   ```
   def log_api_cost(
       model: str,
       input_tokens: int,
       output_tokens: int,
       source: str,
       capability_id: str = None,
       task_id: str = None,
       matter_slug: str = None,
       cache_creation_input_tokens: int = 0,
       cache_read_input_tokens: int = 0,
   ) -> Optional[float]:
   ```
   Update `calculate_cost_eur` call to pass cache token kwargs (B1's enhanced signature on main accepts them).

3. `orchestrator/cost_monitor.py` lines ~230-244 — INSERT statement. 10 columns required: model, input, output, cache_creation, cache_read, cost_eur, source, capability_id, task_id, matter_slug. Update VALUES bind list to match (10 placeholders).

4. `orchestrator/cost_monitor.py` lines ~250-255 — log message. Combine matter + cache info, e.g.:
   ```
   f"Cost: {model} {input_tokens}in/{output_tokens}out cache=({cache_creation_input_tokens}c/{cache_read_input_tokens}r) = €{cost_eur:.4f} [{source}] matter={matter_slug or '-'}"
   ```

5. `_ops/processes/cost-control-runbook.md` add/add conflict — both B1 and B2 authored this file fresh. Merge: combine sections (B1 added §"Cache hit rate" + §"Caching kill-switch" subsections; B2 authored core tier-thresholds + alert dispatch sections). Preserve both Director-facing sections.

**Critical post-merge verification:**
- All log_api_cost call sites in main use kwargs for trailing params — verify no positional clashes (capability_runner, agent_loop, _force_synthesis x5).
- B1's A6/A7 SQL extension (`IN ('agent_loop','agent_loop_streaming','agent_loop_synthesis')`) is on main — your A6/A7 SQL queries elsewhere should not regress this.
- ensure_api_cost_log_table bootstrap DDL must include matter_slug + cache_creation + cache_read columns + indexes.

**Action:**
1. `git fetch origin && git checkout b2/baker-cost-instrumentation-1`
2. `git merge origin/main` → resolve 5 conflicts per spec above
3. Run full pytest GREEN (literal output, Lesson #52)
4. Push merge commit to `b2/baker-cost-instrumentation-1`
5. Confirm PR #158 mergeable=MERGEABLE
6. Report new HEAD SHA back to PL → I autonomous-merge per AH1 charter §3.

No autonomous polling. Stop after step 6 report.
