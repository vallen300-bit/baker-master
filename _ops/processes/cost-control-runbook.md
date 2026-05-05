# Baker Cost-Control Runbook

Director-facing single source of truth for daily API spend discipline. Lives at
`_ops/processes/cost-control-runbook.md`. Authored 2026-05-05 under
`BRIEF_BAKER_COST_INSTRUMENTATION_1`.

> **Quick links**
> - **Slack channel:** `#cockpit` (all alarms + daily summary)
> - **Code:** `orchestrator/cost_monitor.py`
> - **Schema:** `api_cost_log` (per-call ledger), `cost_alert_state` (alarm idempotence)

---

## 1. Tiered Thresholds

Baker walks the spend tiers in ascending order each call. One Slack message per
(date, tier) per UTC day, persisted to PostgreSQL — a Render restart in the
middle of the day will not re-fire today's alarms.

| Tier | Default (EUR/day) | Slack emoji | Behavior |
|------|------------------:|:-----------:|----------|
| Info | 30.00 | ℹ️ | Visibility only — calls continue |
| Warn | 60.00 | ⚠️ | Visibility only — calls continue |
| Critical | 100.00 | 🚨 | Visibility only — calls continue |
| **Hard stop** | **100.00** (raised by Director when needed) | 🛑 | **All API calls blocked until tomorrow** |

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
| `BAKER_PROMPT_CACHE_ENABLED` | `true` post-merge | Anthropic prompt caching on agent loop. *Reserved for sibling brief BRIEF_BAKER_PROMPT_CACHING_1.* |
| `BAKER_PIPELINE_DEMOTION_ENABLED` | `true` post-merge | Gemini routing on pipeline. *Reserved for the pipeline-demotion brief.* |

### How env-var kill-switches work

1. Director flips the value on Render → Environment → Save.
2. Render auto-restarts the service (~30-60s).
3. On next request, the new process reads the env var at module load.
4. Behavior changes immediately for all callers.

**Forbidden:** per-call `os.getenv()` reads on `BAKER_*_ENABLED` flags. Caching
depends on stable values across requests; per-call reads create flapping
behavior and break cache hit rates. Module-load only.

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

## 4. Breaker Bypass Procedure (Director-only)

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

## 5. Alarm Investigation Checklist

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

## Changelog

| Date | Change | Ratified by |
|------|--------|-------------|
| 2026-05-05 | Initial runbook (BAKER-COST-INSTRUMENTATION-1 ship) | Director — chat ratification 2026-05-05 |
