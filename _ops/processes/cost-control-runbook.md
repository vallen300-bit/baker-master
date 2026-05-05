# Cost Control Runbook — Baker Dashboard Agent Loop

Operating handbook for the kill switches and observability around Baker's
LLM spend on the dashboard agent loop (Ask Baker / Scan SSE) and the
prompt-cache mechanism shipped in BAKER-PROMPT-CACHING-1.

Audience: Director + AI Head A. Owner: AI Head A.

## Prompt cache kill switch

The dashboard agent loop wraps the static system prompt + `AGENT_TOOLS`
array with Anthropic `cache_control: {"type": "ephemeral"}` blocks. This
gives a 90% discount on cached input tokens (5-minute TTL) at a one-time
25% premium on the cache-write turn. Default state on `baker-master` is
**enabled**.

If chat answers go stale, return wrong content, or the agent loop starts
returning 4xx from Anthropic, disable caching without a code revert:

1. Render dashboard → `baker-master` service → Environment.
2. Set `BAKER_PROMPT_CACHE_ENABLED=false`.
3. Save → service auto-redeploys (~30 s).
4. Confirm the next agent call logs `cache_creation_input_tokens=0` AND
   `cache_read_input_tokens=0` in `api_cost_log`:
   ```sql
   SELECT logged_at, cache_creation_input_tokens, cache_read_input_tokens
   FROM api_cost_log
   WHERE source IN ('agent_loop', 'agent_loop_streaming')
   ORDER BY logged_at DESC LIMIT 5;
   ```
5. No code revert needed. Reverse the flip when the underlying issue is
   resolved.

The Gemini adapter (`is_gemini_model()` true) is guarded inside the
helper — `cache_control` is never sent when Gemini is the active client,
so the kill switch is purely an Anthropic-path safety lever.

## Reading cache effectiveness

After 24 h of post-merge live traffic, A6 (savings) and A7 (cache hit
ratio) gates fire. Useful queries:

```sql
-- A6: actual savings, agent loop only.
SELECT DATE(logged_at) AS day, SUM(cost_eur) AS daily
FROM api_cost_log
WHERE source IN ('agent_loop', 'agent_loop_streaming')
  AND logged_at > NOW() - INTERVAL '7 days'
GROUP BY day ORDER BY day;

-- A7: effective cache discount achieved.
SELECT
    SUM(cache_read_input_tokens)::numeric
    / NULLIF(
        SUM(cache_read_input_tokens
            + cache_creation_input_tokens
            + input_tokens), 0)
    AS savings_ratio
FROM api_cost_log
WHERE source IN ('agent_loop', 'agent_loop_streaming')
  AND logged_at > NOW() - INTERVAL '24 hours';
```

If A7 < 0.60 sustained over 48 h, the cache key is being invalidated by
dynamic content in the system prompt. Re-run the cache-key audit
checklist in `briefs/BRIEF_BAKER_PROMPT_CACHING_1.md` and either extract
the offending dynamic block to messages or split the system into a
multi-block (cached prefix + uncached suffix).

## Daily / weekly spend visibility

`GET /api/cost-dashboard?days=7` on the dashboard returns daily totals
plus per-source / per-capability breakdown. The numbers come from
`orchestrator/cost_monitor.get_cost_dashboard()` (no separate ETL).

The circuit breaker thresholds (`BAKER_COST_ALERT_EUR`,
`BAKER_COST_HARD_STOP_EUR`) live in Render env. Hard stop blocks API
calls until UTC midnight or until thresholds are raised.

## Related

- `briefs/BRIEF_BAKER_PROMPT_CACHING_1.md` — design + 10 ACs.
- `migrations/20260505_140000_api_cost_log_cache_columns.sql` — schema
  for the cache token columns.
- `orchestrator/cost_monitor.py` — `log_api_cost`, `calculate_cost_eur`,
  `ensure_api_cost_log_table`.
- `orchestrator/agent.py` — `PROMPT_CACHE_ENABLED`,
  `_build_cached_system_and_tools`, `_force_synthesis`.
