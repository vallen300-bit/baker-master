# CODE_1_PENDING — BRIEF_BAKER_PROMPT_CACHING_1 — 2026-05-05

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
