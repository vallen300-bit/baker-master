# BRIEF: BAKER-PROMPT-CACHING-1 — Anthropic prompt caching on dashboard agent loop

## Context

Baker's dashboard chat (the conversational box at `baker-master.onrender.com`) sends ~16K input tokens per turn — system prompt + tool definitions + retrieved memory context — regardless of how trivial the user's prompt is. On 2026-05-05, 63 turns cost €14.64 at full Opus rate (€0.20-0.28/turn). The Anthropic SDK has supported prompt caching for over a year (90% discount on cached tokens); Baker never enabled it. This brief enables it.

**Estimated time:** ~3 days
**Complexity:** Low-Medium (SDK feature, not a redesign)
**Prerequisites:** None
**Tier:** A (no auth surface, no migration; mandatory `/security-review` not required, but `feature-dev:code-reviewer` 2nd-pass required because edits land in agent core)

**Director ratification:** 2026-05-05 chat ("go") — adopted app-side architect's split plan after compare-and-contrast against code-side architect verdict. Both architects converged on caching as the lowest-risk highest-leverage move.

---

## Design Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Cache `system_prompt` block** with `cache_control: {"type": "ephemeral"}` | Largest static block per turn (~5-8K tokens). Identical across turns within Director's session bursts. |
| 2 | **Cache `AGENT_TOOLS` block** | ~3-5K tokens of tool descriptions, identical across turns. Single hash key for the whole tool array per Anthropic spec. |
| 3 | **Do NOT cache `messages` (conversation history)** | Mutates every turn by definition. Caching it would invalidate on every call → zero hit rate + 25% cache-write penalty. |
| 4 | **Default TTL: 5 minutes** (standard ephemeral). NOT 1-hour beta. | App-side architect concern: realism. Director's chat patterns (clusters of 10-30 turns within 2-3 minutes) hit 5-min TTL fine. 1-hour beta adds API surface risk + Anthropic may price-change. Re-evaluate post-ship if hit rate <60%. |
| 5 | **Cache-key audit checklist mandatory before merge** | App-side + code-side architects both flagged: any f-string / `datetime.now()` / matter-slug interpolation in `system_prompt` or `AGENT_TOOLS` invalidates cache → 0% hit rate + 25% cache-write penalty = pure regression. |
| 6 | **Apply to BOTH agent.py call sites:** `agent_loop` (line 2250, `source="agent_loop"`) AND `run_agent_loop_streaming` (line 2499, `source="agent_loop_streaming"`). ALSO `_force_synthesis()` call sites (lines ~2223, 2358, 2438, 2478). | Both main paths use `config.claude.model` (Opus) + `system_prompt` + `AGENT_TOOLS`. Single-site fix leaves 50% of agent traffic uncached. `_force_synthesis` shares same `system_prompt` → already-warm cache, one-line addition. |
| 6.1 | **Gemini client guard:** wrap `cache_control` construction in `if not is_gemini_model(_effective_model)` | `claude` variable rebinds to `GeminiToolClient()` when `is_gemini_model()` is true (agent.py:~2412). Passing Anthropic-shaped `system` blocks to the Gemini adapter will 400 / silently drop. **Hard pre-merge requirement.** |
| 7 | **Telemetry: log `cache_creation_input_tokens` + `cache_read_input_tokens`** alongside existing `input_tokens` | Anthropic API returns both fields on every response. Without telemetry, "is caching working" is unanswerable. |
| 8 | **Kill-switch env var: `BAKER_PROMPT_CACHE_ENABLED`** (default `true` after merge) | Director can disable from Render UI without revert if a cache-invalidation bug ships. Standard Baker pattern (`BAKER_CLICKUP_READONLY` etc.). |
| 9 | **Acceptance gate: ACTUAL savings vs ACTUAL baseline, not modeled** | App-side architect concern. Brief verifies via `api_cost_log` queries 7 days pre/post merge. Modeled €10/day savings derated to €6-8/day per 5-min TTL realism. |
| 10 | **NOT in scope: pipeline.py caching, capability_runner.py caching, Cortex Phase 3 caching** | Pipeline = next brief (BRIEF_BAKER_PIPELINE_DEMOTION_1, deferred to Tuesday). Capability runner = different call shape (specialist invocations); separate evaluation. |

---

## Feature 1: Cache-control wiring on agent.py

### Problem
`agent.py:2250` and `agent.py:2499` both call `claude.messages.create()` with `system=system_prompt, tools=AGENT_TOOLS, messages=messages`. No `cache_control` anywhere. Every turn pays full input rate on the static blocks.

### Implementation

**File:** `orchestrator/agent.py`

**Change A — non-streaming path (line ~2250):**

```python
import os
from orchestrator.gemini_client import is_gemini_model  # already imported in file

PROMPT_CACHE_ENABLED = os.getenv("BAKER_PROMPT_CACHE_ENABLED", "true").lower() == "true"

# ... inside agent_loop() iteration ...

_use_cache = PROMPT_CACHE_ENABLED and not is_gemini_model(config.claude.model)

# Build system block(s) with optional cache_control
if _use_cache:
    system_blocks = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    # AGENT_TOOLS is a list of tool dicts; mark the LAST one with cache_control
    # to cache the entire tools array per Anthropic spec
    tools_with_cache = list(AGENT_TOOLS)
    if tools_with_cache:
        tools_with_cache[-1] = {
            **tools_with_cache[-1],
            "cache_control": {"type": "ephemeral"},
        }
else:
    system_blocks = system_prompt  # plain string fallback (Gemini or kill-switch off)
    tools_with_cache = AGENT_TOOLS

response = claude.messages.create(
    model=config.claude.model,
    max_tokens=2048,
    system=system_blocks,
    messages=messages,
    tools=tools_with_cache,
)
```

**Change B — streaming path (line ~2499):** identical pattern with `_model` and `_max_tok`. Use `is_gemini_model(_model)` for the gate.

**Change B.1 — `_force_synthesis()` call sites (lines ~2223, 2358, 2438, 2478):** synthesis path passes `system_prompt` + `messages` (no tools). Apply the same `system_blocks` construction (gated by `_use_cache`); this benefits from the already-warm cache entry written by the main path. One-line change per call site.

**Change C — telemetry extension:**

Update `log_api_cost()` signature in `orchestrator/cost_monitor.py` to accept optional `cache_creation_input_tokens` and `cache_read_input_tokens`. New `api_cost_log` columns:

```sql
ALTER TABLE api_cost_log ADD COLUMN IF NOT EXISTS cache_creation_input_tokens INTEGER DEFAULT 0;
ALTER TABLE api_cost_log ADD COLUMN IF NOT EXISTS cache_read_input_tokens INTEGER DEFAULT 0;
```

Migration file: `migrations/<UTC-timestamp>_api_cost_log_cache_columns.sql`. Idempotent `IF NOT EXISTS`. **Sibling brief `BRIEF_BAKER_COST_INSTRUMENTATION_1.md` adds `matter_slug` column to same table via its own migration file. Verify timestamps differ by ≥1s. After BOTH migrations apply (in whatever order), refresh `applied_migrations.lock` from prod ONCE in apply-order via `DATABASE_URL=$PROD_URL python3 scripts/refresh_applied_migrations_lock.py`.** Both columns are independent (`ADD COLUMN IF NOT EXISTS`) so merge order is safe.

Cost calculation update in `calculate_cost_eur()`:
- `cache_read_input_tokens` billed at 10% of standard input rate (90% discount)
- `cache_creation_input_tokens` billed at 125% of standard input rate (25% premium, one-time)
- Regular `input_tokens` billed at standard rate

### Key constraints
- **Cache-key audit:** before merge, B-code MUST grep `system_prompt` build path AND `AGENT_TOOLS` (`grep -n "system_prompt\s*=" orchestrator/`) AND `TOOL_DEFINITIONS` for f-strings, `datetime.now()`, `time.time()`, matter-slug interpolation, or any per-call dynamic value. **Findings list goes in ship report; if any found, brief's acceptance criteria are NOT met.**
- **NEVER cache `messages`** (conversation history mutates every turn by definition).
- **`cache_control` placement:** ONLY on the final block of each cacheable segment. System: one block. Tools: last entry of array. Anthropic API will 400 if placed elsewhere.

---

## Feature 2: Kill-switch env var

### Problem
If a cache-invalidation bug ships (e.g., dynamic value snuck into AGENT_TOOLS), Director needs disable path without git revert.

### Implementation
- Add `BAKER_PROMPT_CACHE_ENABLED` to Render env (default `true` post-merge).
- Code reads at module load: `PROMPT_CACHE_ENABLED = os.getenv("BAKER_PROMPT_CACHE_ENABLED", "true").lower() == "true"`.
- Document in `_ops/processes/cost-control-runbook.md` (NEW file in this brief): "If chat answers go stale or wrong, set `BAKER_PROMPT_CACHE_ENABLED=false` on baker-master in Render UI; service reload picks up; no code revert needed."

### Key constraints
- Default `true` AFTER merge (safe-after-validation pattern, not safe-by-default).
- Pre-merge: deploy with `BAKER_PROMPT_CACHE_ENABLED=false` for one deploy cycle, verify nothing broke, THEN flip to `true`.

---

## Acceptance Criteria

| AC | Description | Verification |
|---|---|---|
| **A1** | `cache_control` blocks present in both `agent_loop` and `agent_loop_streaming` call sites | grep `cache_control` in `orchestrator/agent.py` returns ≥4 matches |
| **A2** | Migration `<timestamp>_api_cost_log_cache_columns.sql` applies clean | `applied_migrations.lock` updated post-apply |
| **A3** | Cache-key audit checklist findings recorded in ship report | Ship report contains explicit "audited X locations, Y dynamic-value findings, Z resolutions" |
| **A4** | Kill-switch env var works | Manual test: set `BAKER_PROMPT_CACHE_ENABLED=false`, reload service, confirm `cache_creation_input_tokens=0` on next call |
| **A5** | Telemetry columns populate | `SELECT cache_read_input_tokens FROM api_cost_log WHERE source='agent_loop_streaming' AND logged_at > <ship_timestamp> LIMIT 5` returns non-zero values |
| **A6** | **ACTUAL savings ≥€4/day measured against ACTUAL baseline** (NOT modeled) | 7-day post-ship vs 7-day pre-ship query — sources `IN ('agent_loop','agent_loop_streaming','agent_loop_synthesis')`. Concrete: `SELECT AVG(daily) FROM (SELECT DATE(logged_at) d, SUM(cost_eur) daily FROM api_cost_log WHERE source IN ('agent_loop','agent_loop_streaming','agent_loop_synthesis') AND logged_at BETWEEN %s AND %s GROUP BY d) x`. Run twice (pre-ship window + post-ship window). Delta ≥€4/day. |
| **A7** | Cache savings ratio ≥60% on agent loop after 24h (renamed from "hit rate" — semantically: effective discount achieved) | `SELECT SUM(cache_read_input_tokens) / NULLIF(SUM(cache_read_input_tokens + cache_creation_input_tokens + input_tokens), 0) FROM api_cost_log WHERE source IN ('agent_loop','agent_loop_streaming','agent_loop_synthesis') AND logged_at > NOW() - INTERVAL '24 hours'` ≥ 0.60 |
| **A8** | No quality regression on chat responses | Manual: 10 test prompts pre-ship vs post-ship; Director eyeball-equivalent; ship report includes this confirmation |
| **A9** | Cost-control runbook landed at `_ops/processes/cost-control-runbook.md` | File exists with kill-switch instructions |
| **A10** | `feature-dev:code-reviewer` 2nd-pass clean | Per SKILL.md §Code-reviewer 2nd-pass Protocol — agent core touched, mandatory trigger |

**Ship gate:** literal pytest GREEN (no by-inspection) + A1-A10 all met. A6 + A7 verified at +24h post-ship; revert via env-var if either fails.

---

## Cache-Key Audit Checklist (B-code, run before merge)

Scope greps to the **system_prompt build path + TOOL_DEFINITIONS block only** (not file-wide — file-wide datetime greps return hundreds of false positives from timeout logic).

Locate the `system_prompt` build function(s) first (typically `_build_system_prompt`-style identifier near the top of `agent.py`); then run audits scoped to those functions + `TOOL_DEFINITIONS` block at agent.py:846.

```bash
# 1. Dynamic values in system_prompt construction path
grep -n "system_prompt\s*=" orchestrator/agent.py orchestrator/dashboard*.py
# Then for each construction site, read the function body and inspect for f-strings,
# .format(), datetime calls, or mutable-value concatenation.

# 2. Datetime / time interpolation INSIDE TOOL_DEFINITIONS (not file-wide)
sed -n '/^TOOL_DEFINITIONS\s*=/,/^]/p' orchestrator/agent.py | grep -n "datetime\|time\.time\|date\.today"
# Empty result = no dynamic values in tool defs.

# 3. Matter-slug interpolation in tools or system prompt
grep -n "matter_slug\|active_matter\|current_matter" orchestrator/agent.py

# 4. AGENT_TOOLS construction at module load (line 846) + later mutations
grep -n "AGENT_TOOLS\s*=\|AGENT_TOOLS\." orchestrator/
# Any AGENT_TOOLS.append / .extend / [i] = elsewhere shifts cache key on next call.

# 5. Anthropic spec reference (B-code self-verify)
# https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching#what-can-be-cached
# cache_control MUST be on the LAST block of each cacheable segment; misplacement = HTTP 400.
```

For each finding, ship report records: file:line, dynamic value, resolution (extracted to messages, made static, or accepted as cache-buster with justification).

---

## Open Questions for AH1 (none expected; brief is mature post-architect-double-review)

None. Both architects converged. Director ratified path 2026-05-05.

---

## Sequencing

1. B-code claims brief, runs cache-key audit FIRST (before any code edit) — record findings.
2. If audit finds blockers, escalate to AH1 before proceeding.
3. Implement Change A + B + C.
4. Run migration locally against TEST_DATABASE_URL, verify clean apply.
5. `feature-dev:code-reviewer` 2nd-pass.
6. Open PR against `main`.
7. AH1 reviews + merges; deploy with env-var `false` first.
8. **AH1 flips env-var to `true` after 1 deploy cycle clean** (no 5xx spike, no chat-quality complaint within 1h post-deploy). Flip timestamp recorded in ship report — defines start of A6/A7 baseline window.
9. A6 + A7 verification at +24h; ship report finalizes.

**Reviewer SLA:** AH1 dispatches `feature-dev:code-reviewer` 2nd-pass within 4h of B-code PR open; reviewer turns within 24h.
10. If ship clean: signal AH1 to proceed with `BRIEF_BAKER_COST_INSTRUMENTATION_1` (sibling brief).

---

## Reference

- Anthropic prompt caching docs: https://docs.anthropic.com/claude/docs/prompt-caching
- Existing cost telemetry: `orchestrator/cost_monitor.py` (`log_api_cost(source=...)`)
- Prior caching attempt: NONE — Baker has never enabled prompt caching; greenfield work
- Code-side architect review: agent ID `a249ec2b5a682662b` 2026-05-05
- App-side architect review: relayed by Director 2026-05-05 chat (six concerns folded above)
