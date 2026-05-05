---
status: COMPLETE
brief: briefs/BRIEF_BAKER_PROMPT_CACHING_1.md
trigger_class: TIER_A_AGENT_CORE_PLUS_DB_SCHEMA
dispatched_at: 2026-05-05
dispatched_by: ai-head-a-pl
claimed_by: b1
ship_report: briefs/_reports/B1_baker_prompt_caching_20260505.md
gate_chain: pytest GREEN 35/35 + AH2 /security-review PASS + Architect PASS-WITH-NITS (comment 4382710967, 5 NITs non-blocking) + feature-dev:code-reviewer PASS-WITH-NITS-FOLD-NEEDED → fold H1+M1+M2 → re-fired gates 1+2+3 PASS on fold diff
fold_commit: 57b3043
merged_at: 2026-05-05T20:5XZ
merge_commit: a8dea7ccb9c03bcd2636747e9485cba8b5338c57
pr: 159
verdict: PASS
follow_ups: N1+N5 → cost-control-runbook rollout note (pending); N2/N3/N4 → scaling-followups stub (pending)
autopoll_eligible: false
---

# CODE_1_PENDING — BRIEF_BAKER_PROMPT_CACHING_1 — 2026-05-05 (COMPLETE)

**Brief:** baker-master `briefs/BRIEF_BAKER_PROMPT_CACHING_1.md` (Tier A, ~3 days, 10 ACs)
**Working branch:** `b1/baker-prompt-caching-1`
**Pre-requisites:** baker-master main HEAD (commit `d086c8d` introducing this brief). No env state, no other briefs blocking.
**Acceptance criteria:** per brief §ACs (10 testable items)
**Ship gate:** literal `pytest` GREEN — no by-inspection (Lesson #52)
**Heartbeat:** 12h cadence binding (per SKILL.md `59f23c4` §B-code stall chase)

**Read first (MANDATORY):**
1. `briefs/BRIEF_BAKER_PROMPT_CACHING_1.md` — full spec + design decisions + 10 ACs + cache-key audit checklist
2. `~/baker-vault/_ops/agents/b1/orientation.md` — your role
3. `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` — canonical Baker memory

**First-message confirmation phrase (evidence-bound, exact):**
`"B1 oriented. Read: CODE_1_PENDING.md, MEMORY.md."`

**Path forward:**
1. Read brief BRIEF_BAKER_PROMPT_CACHING_1.md cover-to-cover
2. Run cache-key audit checklist FIRST (before any code edit) — record findings in ship report
3. Implement 10 ACs on `b1/baker-prompt-caching-1` branch (Changes A + B + B.1 + C per brief)
4. Apply migration `<UTC-timestamp>_api_cost_log_cache_columns.sql`; refresh `applied_migrations.lock` from prod
5. Live pytest GREEN
6. Open PR
7. Ship via PL paste-block per SKILL.md §"PL ship-report contract"
8. 4-gate review chain: live pytest + AH2 /security-review + architect spot-check + feature-dev:code-reviewer 2nd-pass (per SKILL.md `59f23c4` Trigger §1+§2 — agent core touched + DB schema change)

**Critical pre-merge gates (from architect post-WRITE review):**
- Gemini-client guard: `if not is_gemini_model(_model)` MUST wrap `cache_control` construction
- Both call sites: `agent_loop` (source=`agent_loop`) AND `run_agent_loop_streaming` (source=`agent_loop_streaming`) AND `_force_synthesis()` call sites (~lines 2223/2358/2438/2478)
- Migration sibling-coupling: filename timestamp differs from `BRIEF_BAKER_COST_INSTRUMENTATION_1` migration by ≥1s; refresh lock once after BOTH apply
- A6/A7 SQL queries both `agent_loop` AND `agent_loop_streaming` sources

**Anchor:** Director ratification 2026-05-05 ("go" after compare-and-contrast of code-side vs app-side architect verdicts); brief commit `d086c8d`; AH2 busy-check confirmed B1 idle 2026-05-05.

---

## Prior CODE_1 task (archive reference)
BRIEF_CORTEX_SCAN_FLASH_ROUTE_KILL_1 — COMPLETE 2026-05-04, PR #156 (verdict PASS, /security-review NO FINDINGS, AH2 review pending). Ship report: `briefs/_reports/B1_cortex_scan_flash_route_kill_20260504.md`. Mailbox hygiene rule applied — overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.

---

## GATE-4 2nd-pass UPDATE — 2026-05-05 (fold before merge)

**Source:** feature-dev:code-reviewer 2nd-pass on PR #159 — verdict PASS-WITH-NITS-FOLD-NEEDED. 1 HIGH + 2 MED substantive (no current breakage on H1; M2 is measurement-accuracy gap on A6/A7). 2 LOW non-blocking (not appended). Same fold-pre-merge pattern as B4 cycle.

**H1** `orchestrator/agent.py:2291,2293,2308` — `run_agent_loop` passes
`config.claude.model` raw to `_build_cached_system_and_tools` instead of
the already-resolved `_effective_model`. Streaming path uses `_model`
consistently. Fix: replace all three `config.claude.model` references
inside the `run_agent_loop` iteration body with `_effective_model`. No
current breakage (both resolve identically today) but creates a
maintenance trap if a `model_override` param is ever added to
`run_agent_loop` mirroring the streaming path.
Regression test: unit test asserting `_build_cached_system_and_tools` is
called with `_effective_model`, not a fresh config read.

**M1** `orchestrator/agent.py:59-62` — `list(tools)` is a shallow copy;
`{**tools_value[-1]}` creates a new top-level dict for the last entry but
nested dicts (`input_schema`, etc.) are shared with the module-level
`AGENT_TOOLS` constant. SDK doesn't mutate today, but wrong defensive
posture for a loop-invariant constant. Fix: replace `{**tools_value[-1],
"cache_control": ...}` with `{**copy.deepcopy(tools_value[-1]),
"cache_control": ...}` (add `import copy` at module level).
Regression test: after calling the helper, mutate a nested key on
`tools_v[-1]["input_schema"]` and assert `AGENT_TOOLS[-1]["input_schema"]`
is unchanged.

**M2** `orchestrator/agent.py:2192-2211` — `_force_synthesis` emits
`cache_control` (via the helper) but never calls `log_api_cost` for the
synthesis turn. Cache tokens on synthesis responses are lost — A6/A7 SQL
undercounts cache activity on timeout/max_iter/tool_limit paths. Fix:
add `log_api_cost(..., source="agent_loop_synthesis", cache_creation_input_tokens=...,
cache_read_input_tokens=...)` inside `_force_synthesis` after the API call,
and extend A6/A7 SQL IN clause to include `'agent_loop_synthesis'`.
Regression test: mock claude_client in a `_force_synthesis` unit test;
assert `log_api_cost` is called with source `"agent_loop_synthesis"` and
non-zero cache token values.

**Path forward:**
1. Apply H1+M1+M2 on `b1/baker-prompt-caching-1` branch
2. Add 3 regression tests (one per finding)
3. Live pytest GREEN both sides
4. Re-fire focused gate chain on diff only
5. Report new HEAD SHA + gate verdicts back to PL
