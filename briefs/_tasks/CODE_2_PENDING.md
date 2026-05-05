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

# CODE_2_PENDING — BRIEF_BAKER_COST_INSTRUMENTATION_1 — 2026-05-05

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
