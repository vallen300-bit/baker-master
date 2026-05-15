---
status: PENDING
brief: briefs/BRIEF_CORTEX_TIER_B_RUNTIME_V1.md
brief_id: CORTEX_TIER_B_RUNTIME_V1
trigger_class: TIER_B_DB_MIGRATION_+_BUDGET_RUNTIME_+_CRON_+_ENDPOINT
dispatched_at: 2026-05-15
dispatched_by: ai-head-1 (AH1)
target: b3
mandatory_2nd_pass: true
security_review_required: true
effort_estimate: ~6-8h
ratified_spec: ~/baker-vault/_ops/briefs/CORTEX_B3_TIER_B_RUNTIME_V1.md (AID design)
director_ratification: D8 via D3+D8 Triaga 2026-05-10 + re-dispatch ratify 2026-05-15
predecessor:
  brief: briefs/BRIEF_DEADLINE_FEEDBACK_LOOP_1.md
  pr: 203
  merge_commit: 0e770ee
  status: COMPLETE 2026-05-13
---

# CODE_3_PENDING — CORTEX_TIER_B_RUNTIME_V1 — 2026-05-15

**Brief:** `briefs/BRIEF_CORTEX_TIER_B_RUNTIME_V1.md` (already in repo — read in full before starting)
**Working branch:** `b3/cortex-tier-b-runtime-v1`
**Pre-requisites:**
- `baker_actions` table exists (bootstrap at `memory/store_back.py:1036`)
- GOLD ratify workflow exists (PR #66 — visual template reused, separate domain)
- D8 caps locked 2026-05-10: per-action €100 / daily €500 / monthly €2,500 / 1st of month UTC reset

**Re-dispatch context (read this before brief body):**
This brief was first dispatched 2026-05-10 (per `_ops/agents/ai-head/CYCLE_REGISTER.md` In-flight B-code dispatches). B3 went on to do `DEADLINE_SIGNAL_HYGIENE_1` (PR #202) + `DEADLINE_FEEDBACK_LOOP_1` (PR #203) instead — never picked up this brief. Now re-dispatched fresh on 2026-05-15.

**Why now:** today's oskolkov Cortex cycle (`f2954da4`, ratified 2026-05-15) surfaced russo_fr's process-anomaly finding: the nudge sentinel for stale `tier_b_pending` cycles is itself gated on this brief (B3 Tier-B budget + S5 runtime STATUS NOT-STARTED). Real cost just landed: cycle `c4242a20` sat unratified for 10 days before the resurface-via-fresh-cycle happened today. Director ratified re-dispatch 2026-05-15 ("a" on AH1 strategic recommendation).

**Acceptance criteria (literal — see brief §Quality Checkpoints for full list):**
1. Migration `20260510_baker_actions_tier_b_runtime.sql` applies clean (idempotent — `ON CONFLICT DO NOTHING` + `IF NOT EXISTS`)
2. `enforce_tier_b(committer, action_class, est_cost_eur)` service function: returns either `{"allowed": True, "action_id": <id>}` OR `{"allowed": False, "reason": "<cap-name>", "current": <€>, "cap": <€>}` — never raises on cap-hit, always returns
3. Counter aggregation queries verified against seeded test fixtures (per-action / daily / monthly all correctly aggregate `cost_eur` over `committed_at` window with calendar-month UTC reset)
4. `POST /api/tier_b/preflight` endpoint returns same shape as `enforce_tier_b` (used by future call-sites for dry-run) — `verify_api_key` dependency
5. `GET /api/tier_b/budget` endpoint returns current spend / cap / pct-used per cap (UI-consumable JSON) — `verify_api_key` dependency
6. Cron job `tier_b_monthly_reset` registered in APScheduler — fires 1st of calendar month 00:00 UTC; logs reset to `baker_actions` with `action_class='tier_b.monthly_reset'`; idempotent if double-fired
7. **Ship gate:** literal `pytest tests/test_tier_b_runtime.py -v` GREEN — no "pass by inspection"
8. Forward-looking only: zero call-sites touched in existing flows (Cortex Phase 5 / B4 / B5 will adopt as they ship)

**Mandatory 4-gate review chain pre-merge** per SKILL.md §Code-reviewer 2nd-pass triggers #2 (DB schema/migrations/atomicity) + #3 (concurrency: `committed_at` window aggregation) + #4 (external-surface endpoints):
1. B3 pytest GREEN (literal)
2. AH2 static review
3. AH2 `/security-review`
4. picker-architect + `feature-dev:code-reviewer` 2nd-pass (parallel, AH1-spawned)

**Unblocks on merge:**
- I5 first Cortex auto-trigger cycle (STUCK since 2026-05-03, ~12 days)
- B4 6-phase loop runtime
- B5 substrate push runtime
- russo_fr stale-cycle nudge sentinel (separate downstream work, references this runtime)

**Heartbeat cadence:** ≥ every 12h while in_progress per SKILL.md §B-code stall chase. Use mailbox UPDATE entry pattern OR commit-msg `mailbox(b3): heartbeat <ISO> — <where>` pattern.

**Brief-vs-codebase surface conflicts to verify before silently amending:**
- `baker_actions` table column names + types (brief quoted bootstrap from `memory/store_back.py:1036` — re-grep, schema may have evolved since 2026-05-10)
- Auth dependency pattern: brief may show inline `verify_api_key`; repo convention is `dependencies=[Depends(verify_api_key)]` (matches `/api/cortex/*` + `/api/worker/*`)
- Singleton pattern: any `SentinelStoreBack` / `SentinelRetriever` use must call `._get_global_instance()` per `scripts/check_singletons.sh`
- APScheduler registration site: grep existing cron patterns (e.g. `ai_head_weekly_audit` registration)
- Migration filename collision: brief proposes `20260510_baker_actions_tier_b_runtime.sql`. Verify `migrations/20260510_baker_actions_tier_b_runtime.sql` doesn't already exist (it didn't on 2026-05-10; verify today before writing)
- Surface conflicts in ship report — DO NOT silently amend brief; flag in PR body

**Bus topic on ship:** `ship/CORTEX_TIER_B_RUNTIME_V1` to lead.
