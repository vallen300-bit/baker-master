# BRIEF: BAKER-PROMPT-CACHING-1 — scaling follow-ups (N2 + N3 + N4)

**Author:** AH1-App PL
**Source:** Architect Gate-3 verdict on PR #159 (comment [4382710967](https://github.com/vallen300-bit/baker-master/pull/159#issuecomment-4382710967))
**Status:** stub — open for next ops cycle, not blocking ship
**Filed:** 2026-05-05 (post B1 PR #159 merge `a8dea7c`)
**Priority:** P3 — quality / cost-optimisation, not correctness

---

## N2 — 5-min ephemeral TTL only (Anthropic 1-hour extended-TTL beta unused)

**Architect note:** No use of Anthropic's 1-hour extended-TTL cache (beta). 5-min TTL means cache reuse only within the same conversation burst. If post-deploy `cache_read_input_tokens / (cache_read + input)` < 30% over a 7-day window, revisit with extended TTL.

**Trigger condition:** A7 7-day cache hit rate (per cost-control-runbook §8.2) lands < 30% AND root cause is "TTL expired between adjacent conversation bursts" (i.e., cache-creation tokens dominate cache-read tokens).

**Scope of follow-up brief:**
- Evaluate Anthropic's 1-hour extended-TTL beta availability (check API docs for prod-readiness gate).
- Cost model delta: extended TTL is billed differently — verify `calculate_cost_eur` math still holds (likely 2× creation premium for 1-hour vs 1.25× for 5-min).
- Rollout: behind a `PROMPT_CACHE_TTL_EXTENDED` kill-switch parallel to existing `PROMPT_CACHE_ENABLED`.
- Decision tree: which conversation classes warrant extended TTL (Cortex multi-turn? cross-session memory replay? agent_loop_streaming with long pauses?).

**Out of scope:** retrofit if A7 hit rate is already ≥30% over 7 days — the savings vs added complexity don't justify the change.

---

## N3 — Migration filename naming convention drift

**Architect note:** B1 uses `YYYYMMDD_HHMMSS_<topic>.sql`; existing migrations on `b2/baker-cost-instrumentation-1` use `YYYYMMDD_<topic>.sql` and `YYYYMMDD<letter>_<topic>.sql`. Lex sort works for current files but the team should settle the convention in `_ops/processes/cost-control-runbook.md` (or sibling) before more same-day migrations stack up.

**Trigger condition:** any same-day migration collision OR convention-question raised by a future B-code dispatch.

**Scope of follow-up brief:**
- Audit existing baker-master `migrations/` filenames; classify into the three observed patterns.
- Decide canonical pattern. Recommend: `YYYYMMDD_HHMMSS_<topic>.sql` (always 14 chars before topic). Rationale: explicit ordering across sibling-coupled briefs; trivially extends to multiple per minute; lex sort = chronological sort.
- Author short ops-runbook section (`_ops/processes/migration-naming.md` OR fold into existing cost-control-runbook).
- Optional: rename existing non-conforming files (low-risk; migrations have `IF NOT EXISTS` idempotence so no DB impact, but `applied_migrations.lock` would need refresh).

**Out of scope (per architect):** retrofitting B1's filename. B1 is already on canonical pattern.

---

## N4 — `_force_synthesis` cache key diverges from main loop

**Architect note:** `agent.py:2192` calls `_build_cached_system_and_tools(system_prompt, None, model)` — caches system alone (no tools). Main agent loop caches system+tools. Different cache keys → synthesis writes its own cache entry, doesn't share with the warm main-loop entry. Minor cost-optimization gap; synthesis path is rare (token-budget-exceeded fallback) so impact is small. Acceptable.

**Trigger condition:** A7 7-day data shows `agent_loop_synthesis` source contributing >5% of total spend AND cache hit rate on that source <40% (signals the divergence is materially costing).

**Scope of follow-up brief:**
- Decide: pass `tools` through `_build_cached_system_and_tools` from `_force_synthesis` even though synthesis doesn't use tools, to share the cache key with the main loop. Trade-off: cache key alignment vs sending unused tool definitions to the model (small cache-creation token tax on first synthesis).
- Alternative: split synthesis into its own cache namespace explicitly (current behaviour formalised) and accept the duplicate cache entry as the design.
- Quantify break-even from A6/A7 data before deciding.

**Out of scope:** changing `_force_synthesis` to actually use tools — it's an emergency fallback path; complicating the synthesis logic to chase cache savings is the wrong trade.

---

## Related

- `briefs/BRIEF_BAKER_PROMPT_CACHING_1.md` — V0.1 brief (10 ACs, shipped PR #159 merged at `a8dea7c`).
- `_ops/processes/cost-control-runbook.md` §8 — N1 + N5 rollout follow-ups (operational).
- PR #159 merge cascade: B1 + B2 + B4 V0.3.7 all shipped 2026-05-05.

---

**End scaling-followups stub.** Next ops cycle picks up if/when trigger conditions fire.
