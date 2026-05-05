# Baker Cost-Control Runbook

Director-facing single source of truth for daily API spend discipline and the
Anthropic prompt-cache kill-switch on the dashboard agent loop. Lives at
`_ops/processes/cost-control-runbook.md`. Authored 2026-05-05 under
`BRIEF_BAKER_COST_INSTRUMENTATION_1`; cache subsections folded in same day
from `BRIEF_BAKER_PROMPT_CACHING_1`.

> **Quick links**
> - **Slack channel:** `#cockpit` (all alarms + daily summary)
> - **Code:** `orchestrator/cost_monitor.py`, `orchestrator/agent.py`
> - **Schema:** `api_cost_log` (per-call ledger with cache-token columns),
>   `cost_alert_state` (alarm idempotence)
> - **Dashboard:** `GET /api/cost-dashboard?days=7`

Audience: Director + AI Head A. Owner: AI Head A.

---

## 1. Tiered Thresholds

Baker walks the spend tiers in ascending order each call. One Slack message per
(date, tier) per UTC day, persisted to PostgreSQL — a Render restart in the
middle of the day will not re-fire today's alarms.

| Tier | Default (EUR/day) | Slack emoji | Behavior |
|------|------------------:|:-----------:|----------|
| Info | 30.00 | ℹ️ | Visibility only — calls continue |
| Warn | 60.00 | ⚠️ | Visibility only — calls continue |
| Critical | 80.00 | 🚨 | Visibility only — calls continue |
| **Hard stop** | **100.00** (raised by Director when needed) | 🛑 | **All API calls blocked until tomorrow** |

Critical tier is set ~20% below hard-stop by default (env-overridable) so the
critical alarm provides advance warning before the breaker trips.

### Changing thresholds

Set on Render → Environment → Service → Add/Edit env var → Save (service auto-restarts).

| To change … | Set env var … |
|---|---|
| Info tier | `BAKER_COST_TIER_INFO_EUR` |
| Warn tier | `BAKER_COST_TIER_WARN_EUR` |
| Critical tier | `BAKER_COST_TIER_CRITICAL_EUR` |
| Hard stop | `BAKER_COST_HARD_STOP_EUR` |

---

## 2. Kill-Switches (env-var pattern)

Each cost-saving feature ships behind an env var so Director can disable it
from the Render UI without a code revert. Naming pattern is strict:
`BAKER_<FEATURE>_ENABLED` — future briefs MUST use this pattern.

| Env var | Default | What it disables |
|---|---|---|
| `BAKER_COST_ALARMS_ENABLED` | `true` | All tier alarms (info / warn / critical) AND the 23:55 UTC daily summary post. **Hard stop is NEVER disabled by this flag.** |
| `BAKER_COST_DAILY_SUMMARY_ENABLED` | `true` | Just the 23:55 UTC daily summary scheduler job (registration-level kill). |
| `BAKER_PROMPT_CACHE_ENABLED` | `true` | Anthropic prompt caching on dashboard agent loop. See §2.1 below. |
| `BAKER_PIPELINE_DEMOTION_ENABLED` | `true` post-merge | Gemini routing on pipeline. *Reserved for the pipeline-demotion brief.* |

### How env-var kill-switches work

1. Director flips the value on Render → Environment → Save.
2. Render auto-restarts the service (~30-60s).
3. On next request, the new process reads the env var at module load.
4. Behavior changes immediately for all callers.

**Forbidden:** per-call `os.getenv()` reads on `BAKER_*_ENABLED` flags. Caching
depends on stable values across requests; per-call reads create flapping
behavior and break cache hit rates. Module-load only.

### 2.1 Prompt cache kill-switch — operational details

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
   WHERE source IN ('agent_loop', 'agent_loop_streaming', 'agent_loop_synthesis')
   ORDER BY logged_at DESC LIMIT 5;
   ```
5. No code revert needed. Reverse the flip when the underlying issue is
   resolved.

The Gemini adapter (`is_gemini_model()` true) is guarded inside the
helper — `cache_control` is never sent when Gemini is the active client,
so the kill switch is purely an Anthropic-path safety lever.

---

## 3. Per-Matter Attribution Queries

Every `log_api_cost()` row carries an optional `matter_slug`. Cortex specialist
calls (`source='capability_runner'` / `'capability_runner_streaming'` /
`'cortex_phase3a'` / `'cortex_phase3b'` / `'cortex_phase3c'` / `'auto_insight'`)
are tagged from ship date forward. Pipeline + agent_loop pass `NULL` until the
follow-up `BRIEF_PIPELINE_MATTER_RESOLUTION_1` lands — those rows show up as
`[unattributed]` in the daily summary.

### What did matter X cost in the last 7 days?

```sql
SELECT matter_slug,
       ROUND(SUM(cost_eur)::numeric, 4) AS total_eur,
       COUNT(*) AS calls
  FROM api_cost_log
 WHERE logged_at > NOW() - INTERVAL '7 days'
   AND matter_slug = 'oskolkov'
 GROUP BY matter_slug;
```

### Top matters by spend, last 7 days (Cortex sources only)

```sql
SELECT COALESCE(matter_slug, '[unattributed]') AS matter,
       ROUND(SUM(cost_eur)::numeric, 4) AS total_eur,
       COUNT(*) AS calls
  FROM api_cost_log
 WHERE logged_at > NOW() - INTERVAL '7 days'
   AND source IN (
     'capability_runner',
     'capability_runner_streaming',
     'cortex_phase3a',
     'cortex_phase3b',
     'cortex_phase3c',
     'auto_insight'
   )
 GROUP BY 1
 ORDER BY total_eur DESC;
```

### Today's per-matter spend

```sql
SELECT COALESCE(matter_slug, '[unattributed]') AS matter,
       ROUND(SUM(cost_eur)::numeric, 4) AS total_eur,
       COUNT(*) AS calls
  FROM api_cost_log
 WHERE DATE(logged_at) = CURRENT_DATE
 GROUP BY 1
 ORDER BY total_eur DESC;
```

---

## 4. Cache Effectiveness Queries

After 24 h of post-merge live traffic, A6 (savings) and A7 (cache hit
ratio) gates fire on `BAKER_PROMPT_CACHING_1`. Useful queries:

```sql
-- A6: actual savings, agent loop only.
SELECT DATE(logged_at) AS day, SUM(cost_eur) AS daily
FROM api_cost_log
WHERE source IN ('agent_loop', 'agent_loop_streaming', 'agent_loop_synthesis')
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
WHERE source IN ('agent_loop', 'agent_loop_streaming', 'agent_loop_synthesis')
  AND logged_at > NOW() - INTERVAL '24 hours';
```

If A7 < 0.60 sustained over 48 h, the cache key is being invalidated by
dynamic content in the system prompt. Re-run the cache-key audit
checklist in `briefs/BRIEF_BAKER_PROMPT_CACHING_1.md` and either extract
the offending dynamic block to messages or split the system into a
multi-block (cached prefix + uncached suffix).

---

## 5. Breaker Bypass Procedure (Director-only)

The hard stop blocks **all** Baker API calls when daily spend ≥
`BAKER_COST_HARD_STOP_EUR`. To raise the cap temporarily (e.g., on-day Cortex
re-fire after a productive incident):

1. Confirm necessity — what cycle / capability needs to fire today?
2. Render → Environment → set `BAKER_COST_HARD_STOP_EUR` to the new ceiling
   (e.g., `200.0`).
3. Save → service auto-restarts.
4. **Reset the new ceiling at the next session** so the breaker stays
   conservative. Permanent raises happen only on Director ratification with a
   logged decision in `_ops/decisions/`.
5. Tier alarms continue firing — they are independent of the hard stop and
   provide ongoing visibility while the cap is raised.

---

## 6. Alarm Investigation Checklist

When a tier alarm fires (`#cockpit` ping with ℹ️ / ⚠️ / 🚨), here is the order
of checks:

1. **Today's per-source breakdown** — which path is driving spend?
   ```sql
   SELECT source, ROUND(SUM(cost_eur)::numeric, 4) AS eur, COUNT(*) AS calls
     FROM api_cost_log WHERE DATE(logged_at) = CURRENT_DATE
    GROUP BY source ORDER BY eur DESC;
   ```
2. **Today's per-matter breakdown** (where attributed) — which matter is
   driving spend? See §3.
3. **Open Cortex cycles** — are we in a long-running cycle?
   ```sql
   SELECT cycle_id, matter_slug, status, started_at, cost_dollars
     FROM cortex_cycles
    WHERE status NOT IN ('archived', 'archive_failed', 'killed')
    ORDER BY started_at DESC LIMIT 20;
   ```
4. **Recent capability_id top spenders** —
   ```sql
   SELECT capability_id, ROUND(SUM(cost_eur)::numeric, 4) AS eur, COUNT(*) AS calls
     FROM api_cost_log WHERE DATE(logged_at) = CURRENT_DATE
      AND capability_id IS NOT NULL
    GROUP BY capability_id ORDER BY eur DESC LIMIT 10;
   ```
5. **If a runaway capability or cycle is identified** — surface to Director
   with a one-line recommendation (kill cycle / pause capability /
   raise cap / etc.). Do not act unilaterally.
6. **Daily summary** auto-posts at 23:55 UTC — captures the closing-day
   pattern even if no incident fired. Use it to spot drift over multiple days.

---

## 7. Daily / Weekly Spend Visibility

`GET /api/cost-dashboard?days=7` on the dashboard returns daily totals
plus per-source / per-capability / per-matter breakdown. The numbers come from
`orchestrator/cost_monitor.get_cost_dashboard()` (no separate ETL).

The circuit-breaker thresholds (`BAKER_COST_TIER_*_EUR`,
`BAKER_COST_HARD_STOP_EUR`) live in Render env. Hard stop blocks API
calls until UTC midnight or until thresholds are raised (see §5).

---

## Related

- `briefs/BRIEF_BAKER_COST_INSTRUMENTATION_1.md` — tiered alarms, daily
  summary, per-matter attribution, runbook authorship.
- `briefs/BRIEF_BAKER_PROMPT_CACHING_1.md` — Anthropic prompt-cache design + 10 ACs.
- `migrations/20260505_api_cost_log_matter_slug.sql` — `matter_slug` column.
- `migrations/20260505b_cost_alert_state.sql` — DB-persisted alarm idempotence.
- `migrations/20260505_140000_api_cost_log_cache_columns.sql` — cache token columns.
- `orchestrator/cost_monitor.py` — `log_api_cost`, `calculate_cost_eur`,
  `ensure_api_cost_log_table`, tier alarms, daily summary post.
- `orchestrator/agent.py` — `PROMPT_CACHE_ENABLED`,
  `_build_cached_system_and_tools`, `_force_synthesis`.

---

## Changelog

| Date | Change | Ratified by |
|------|--------|-------------|
| 2026-05-05 | Initial runbook (BAKER-COST-INSTRUMENTATION-1 ship) | Director — chat ratification 2026-05-05 |
| 2026-05-05 | Folded prompt-cache kill-switch + cache effectiveness queries (BAKER-PROMPT-CACHING-1 ship + B2/B1 cross-merge) | Director — chat ratification 2026-05-05 |
