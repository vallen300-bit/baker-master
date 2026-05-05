# BRIEF: BAKER-COST-INSTRUMENTATION-1 — Tiered alarms + per-matter attribution + per-track kill-switches

## Context

Baker has a cost-circuit-breaker (€100 hard-stop, raised to €150 today) but no graduated alarms before it trips. On 2026-05-05 daily spend climbed to €59.30 invisibly until Director surfaced the Slack soft-alert at €50. There is no per-matter spend attribution (we cannot today say "AO matter cost €X, MOVIE cost €Y, Hagenauer cost €Z"); there are no per-track kill-switches (Director cannot disable a single LLM-routing decision via Render UI without a code revert). Architect-side critique: **this is the cultural fix.** Without it, Baker re-drifts to opaque-spend in 6 months, regardless of which routing changes ship.

This brief is intentionally split from `BRIEF_BAKER_PROMPT_CACHING_1.md` — different commit boundary, different acceptance gate. A frustrated revert on caching must NOT take alarms with it.

**Estimated time:** ~2 days
**Complexity:** Low (pure instrumentation, no API surface change, no model swap)
**Prerequisites:** None (independent of caching brief; can ship in parallel or after)
**Tier:** A (no auth surface, no migration risk; `feature-dev:code-reviewer` standard pass)

**Director ratification:** 2026-05-05 chat ("go") — adopted app-side architect's split plan after compare-and-contrast with code-side architect.

---

## Design Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Tiered alarm thresholds: €30 (info) / €60 (warn) / €100 (critical) / €150 (hard-kill, existing)** | Director called out: Today's €59 surprise had no alarm before the breaker. Tiered visibility = cultural fix, not just a number bump. |
| 2 | **Slack channel `#cockpit` for alarms** (existing) — distinct emoji per tier | Reuse existing `_send_cost_alert` infra in `cost_monitor.py:397`. No new integration. Emoji: ℹ️ €30, ⚠️ €60, 🚨 €100, 🛑 €150. |
| 3 | **Add `matter_slug` column to `api_cost_log`** (nullable, default NULL) | Per-matter attribution requires this column. Backfill not in scope; new rows tagged from ship date forward. |
| 4 | **Tagging strategy: ALL paths that already have a matter slug** (`capability_runner` Cortex cycles, `pipeline` triggers when matter resolved upstream, `agent_loop_streaming` when active matter detectable) | App-side architect concern #6: "per-matter attribution next-step instrument." This brief lands the instrument. |
| 5 | **Kill-switches as ENV vars, not DB flags** | Director can flip from Render UI without service restart-loop. DB flag would need polling logic + cache invalidation. Env var: process-load read on each fork. |
| 6 | **Three named env vars defined in this brief: `BAKER_PROMPT_CACHE_ENABLED`, `BAKER_PIPELINE_DEMOTION_ENABLED`, `BAKER_COST_ALARMS_ENABLED`** | Future briefs add their own (`BAKER_CHAT_ROUTER_ENABLED` if Track 3 ever revives, etc.). One naming pattern, one runbook entry per. |
| 7 | **Alarms idempotent per day per tier** | Existing pattern at `cost_monitor.py:44-45` (`_alert_sent_date`) extends to per-tier. No spam. |
| 8 | **Daily summary post to `#cockpit` at 23:55 UTC** | Closure + per-matter breakdown table. Surfaces matters that drove spend. Cultural visibility, not just incident reaction. |
| 9 | **Cost-control runbook at `_ops/processes/cost-control-runbook.md`** (NEW) | Single source of truth for: alarm thresholds, env-var kill-switches, per-matter query patterns, breaker bypass procedure. Director-facing language. |
| 10 | **NOT in scope: Voyage embedding cost tracking, OpenAI/Gemini provider-side cost tracking beyond what `cost_monitor.MODEL_COSTS` already does** | Out of scope for this brief — covered well enough today. Flag as next-step if Voyage cost ever crosses €5/day threshold. |

---

## Feature 1: Tiered alarm thresholds

### Problem
`cost_monitor.py:39-41` defines two thresholds (`COST_ALERT_EUR=50`, `COST_HARD_STOP_EUR=100`). One soft alert + one hard kill = blunt instrument. Director's €59 surprise today had no graduated visibility.

### Implementation

**File:** `orchestrator/cost_monitor.py`

Replace single-threshold logic with tiered list:

```python
# Tiered alarm thresholds (EUR/day) — replaces single COST_ALERT_EUR
COST_TIERS = [
    (float(os.getenv("BAKER_COST_TIER_INFO_EUR", "30.0")), "info", "ℹ️"),
    (float(os.getenv("BAKER_COST_TIER_WARN_EUR", "60.0")), "warn", "⚠️"),
    (float(os.getenv("BAKER_COST_TIER_CRITICAL_EUR", "100.0")), "critical", "🚨"),
]
COST_HARD_STOP_EUR = float(os.getenv("BAKER_COST_HARD_STOP_EUR", "100.0"))  # kept; existing breaker
COST_ALARMS_ENABLED = os.getenv("BAKER_COST_ALARMS_ENABLED", "true").lower() == "true"

# Track per-tier alarm state per day (avoid duplicate Slack pings)
_tier_alert_sent = {}  # {(date, tier_label): True}
```

Update `check_circuit_breaker()` to walk tiers in ascending order:

```python
def check_circuit_breaker() -> Tuple[bool, float]:
    today = datetime.now(timezone.utc).date()
    daily_cost = get_daily_cost(today)

    if COST_ALARMS_ENABLED:
        for threshold, label, emoji in COST_TIERS:
            if daily_cost >= threshold:
                key = (today, label)
                if not _tier_alert_sent.get(key):
                    _tier_alert_sent[key] = True
                    _send_tiered_alarm(daily_cost, threshold, label, emoji)

    # Hard stop unchanged
    if daily_cost >= COST_HARD_STOP_EUR:
        # ... existing hard-stop logic, with 🛑 prefix on Slack ...
        return False, daily_cost

    return True, daily_cost
```

New helper `_send_tiered_alarm()` mirrors `_send_cost_alert()` shape but uses per-tier emoji + label.

### Key constraints
- **Idempotent per day per tier — within a single process lifetime:** `_tier_alert_sent` is module-level dict; **process restart loses state** (Render restart at 14:00 with €70 already spent re-fires the €30 + €60 pings). With four tiers this is 4× noisier than the existing single-alarm bug. **Decision (locked):** persist tier-alert state in PostgreSQL via new `cost_alert_state` table keyed on `(alert_date, tier_label)`. Insert-on-fire, SELECT-before-fire. Failure mode of the existing single-alarm pattern is fixed in passing.
- **Hard stop unchanged:** existing €100/€150 breaker logic preserved bit-for-bit; tiered alarms ADD visibility, do NOT change blocking behavior.
- **`BAKER_COST_ALARMS_ENABLED=false` disables ALL tier alarms** (info/warn/critical) but does NOT disable hard stop. Hard stop is always on.

**Migration addendum (this brief, second migration):** `migrations/<UTC-timestamp>_cost_alert_state.sql`:

```sql
CREATE TABLE IF NOT EXISTS cost_alert_state (
    alert_date DATE NOT NULL,
    tier_label TEXT NOT NULL,
    fired_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (alert_date, tier_label)
);
```

---

## Feature 2: Per-matter spend attribution

### Problem
`api_cost_log` has no `matter_slug` column. We can today say "Cortex specialists cost €23" but cannot say "AO matter cost €23 / MOVIE cost €0 / Hagenauer cost €0." Cross-matter attribution = next-step instrument per app-side architect.

### Implementation

**Migration:** `migrations/<timestamp>_api_cost_log_matter_slug.sql`

```sql
-- Per-matter cost attribution (BAKER-COST-INSTRUMENTATION-1)
ALTER TABLE api_cost_log ADD COLUMN IF NOT EXISTS matter_slug TEXT DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_api_cost_log_matter_slug
  ON api_cost_log (matter_slug) WHERE matter_slug IS NOT NULL;
```

Idempotent. Refresh `applied_migrations.lock` post-apply per migration-immutability rule.

**File:** `orchestrator/cost_monitor.py`

Extend `log_api_cost()` signature — **only the `matter_slug` parameter belongs to this brief.** Cache-token parameters (`cache_creation_input_tokens`, `cache_read_input_tokens`) are owned by the sibling caching brief — do NOT add them here. If the sibling brief lands first, this brief's signature edit is additive (just `matter_slug`); if this brief lands first, sibling adds the cache params later. Decoupled signatures.

```python
def log_api_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    source: str,
    capability_id: str = None,
    task_id: str = None,
    matter_slug: str = None,  # NEW (this brief)
) -> Optional[float]:
    # ... existing INSERT ... extended with matter_slug column ...
```

**Call sites to update (matter_slug pass-through):**

1. **`orchestrator/capability_runner.py`** — Cortex cycles run with known `matter_slug` (loaded from `cortex_cycles.matter_slug`). Pass through every `log_api_cost()` invocation in this file.
2. **`orchestrator/pipeline.py:531,633`** — pipeline-level matter resolution may not exist yet; pass `matter_slug=None` for now (allow nullable). Flagged as next-step.
3. **`orchestrator/agent.py:2262,2511`** — dashboard chat: matter_slug detectable IF question references a matter (via `kbl/slug_registry.py`). Best-effort; pass `None` if undetected. Do NOT introduce new resolution logic in this brief — out of scope.

### Key constraints
- **All new column writes nullable.** Old writes pre-ship stay NULL. Backfill NOT in scope.
- **Reading: ALWAYS treat NULL matter_slug as "unattributed" in queries** — never filter it out silently.
- **Slug values match canonical `baker-vault/slugs.yml`** (loaded via `kbl/slug_registry.py`). Free-text slugs not allowed.

---

## Feature 3: Per-track kill-switches (env-var pattern)

### Problem
Each cost-saving change ships with the risk it regresses quality or behavior. Director needs disable-without-revert for each.

### Implementation

This brief defines THREE env vars (others added by future briefs):

| Env var | Default | Disables |
|---|---|---|
| `BAKER_PROMPT_CACHE_ENABLED` | `true` post-merge | Anthropic prompt caching on agent loop (sibling brief) |
| `BAKER_PIPELINE_DEMOTION_ENABLED` | `true` post-merge of pipeline-demotion brief | Gemini routing on pipeline (Tuesday brief) |
| `BAKER_COST_ALARMS_ENABLED` | `true` always (defined IN this brief) | Tiered alarm Slack pings (this brief) |

For THIS brief, `BAKER_COST_ALARMS_ENABLED` is the only one that activates immediately. The other two are documented in the runbook as **reserved for sibling briefs** so they have a single naming home.

### Key constraints
- **Naming pattern: `BAKER_<FEATURE>_ENABLED`** — strict. Future feature briefs MUST use this pattern.
- **Reading at module load** (NOT per call) — env-var change requires service reload. Render auto-restarts on env-var change so prod-safe; local-dev gotcha (must restart Python process). **Runbook §2 makes this binding: per-call `os.getenv()` reads on `BAKER_*_ENABLED` flags are forbidden — caching depends on stable values across requests.**
- **Default `true` for shipped features.** Bug-shipped features may stage with default `false` per their own brief — caller's choice.

---

## Feature 4: Daily summary post to `#cockpit`

### Problem
Tiered alarms surface incidents. Daily summary surfaces patterns — which matters drove spend, which sources, which models.

### Implementation

**File:** `orchestrator/cost_monitor.py` — new function `post_daily_cost_summary()`.

**Scheduler registration:** No 23:55 UTC tick exists in `triggers/embedded_scheduler.py` today. Register a new APScheduler `CronTrigger(hour=23, minute=55, timezone='UTC')` job, id=`daily_cost_summary`, mirroring the `gold_audit_sentinel` registration pattern at `triggers/embedded_scheduler.py:746`. Keep registration idempotent (`replace_existing=True`).

Output structure:

```
📊 Baker daily cost — 2026-05-06
Total: €X.XX (calls: NNN)

By source:
  • capability_runner: €Y.YY
  • pipeline: €Y.YY
  • agent_loop_streaming: €Y.YY

By matter (where attributed):
  • oskolkov: €Z.ZZ
  • movie: €Z.ZZ
  • [unattributed]: €Z.ZZ

By model:
  • claude-opus-4-6: €Z.ZZ
  • gemini-2.5-pro: €Z.ZZ
  • gemini-2.5-flash: €Z.ZZ

Cache hit rate (chat): NN%
```

### Key constraints
- **Idempotent per day** — once-per-UTC-day post; do not re-post on scheduler retry.
- **Suppressed if `BAKER_COST_ALARMS_ENABLED=false`** — same kill-switch as alarms.
- **No PII** — matter slugs only, never sender names / email subjects.

---

## Feature 5: Cost-control runbook

### Problem
Director-facing single-source-of-truth for cost discipline. Without it, the cultural fix dies in code comments.

### Implementation

**NEW file:** `_ops/processes/cost-control-runbook.md`

Sections:
1. **Tiered thresholds** — current values + how to change
2. **Kill-switches** — full env var table + Render UI procedure ("flip on Render → service auto-reloads → next request reads new value")
3. **Per-matter attribution queries** — copy-paste SQL for "what did matter X cost last 7 days"
4. **Breaker bypass** — Director-only procedure for raising €150 hard stop temporarily
5. **Alarm investigation** — when €60 warn fires, what to check first

Director-facing language; no engineering jargon.

### Key constraints
- **Append-only changelog at file end** — date + change, who ratified.
- **Promoted from this brief, not from ideas/.** Direct land in `_ops/processes/`.

---

## Acceptance Criteria

| AC | Description | Verification |
|---|---|---|
| **A1** | Migration `<timestamp>_api_cost_log_matter_slug.sql` applies clean | `applied_migrations.lock` updated post-apply |
| **A2** | `cost_monitor.COST_TIERS` list defined; **old `COST_ALERT_EUR` constant kept as alias** (referenced by `get_daily_breakdown:190` + `get_cost_dashboard:360`) — point it to `COST_TIERS[0][0]` (info threshold) so existing dashboard JSON still serializes a meaningful number | grep `COST_ALERT_EUR` returns module-level alias only; existing readers compile-clean |
| **A3** | All `log_api_cost()` call sites in `capability_runner.py` pass `matter_slug` | grep `log_api_cost` in capability_runner.py shows matter_slug arg on every call |
| **A4** | Tiered alarms fire idempotently | Manual: trigger spend at €30, €60, €100 thresholds in shadow env; confirm exactly one Slack message per tier per day |
| **A5** | `BAKER_COST_ALARMS_ENABLED=false` suppresses tier alarms but NOT hard stop | Manual: set false, push spend past €30, confirm zero Slack messages; push past €150, confirm hard stop still blocks |
| **A6** | Daily summary posts to `#cockpit` at 23:55 UTC | Verified next-day after ship; matches schema in Feature 4 |
| **A7** | Per-matter attribution query works **for capability_runner sources only** | `SELECT matter_slug, SUM(cost_eur) FROM api_cost_log WHERE logged_at > NOW() - INTERVAL '7 days' AND source='capability_runner' GROUP BY matter_slug ORDER BY 2 DESC` returns non-NULL rows. **Honest scope:** `pipeline` + `agent_loop` matter resolution is OUT OF SCOPE this brief — pass-through `None` is acceptable. ~95% `[unattributed]` on day-one daily summary is expected. Follow-up brief stub `BRIEF_PIPELINE_MATTER_RESOLUTION_1.md` opens the gap visibly. |
| **A8** | Cost-control runbook landed | `_ops/processes/cost-control-runbook.md` exists; Director-readable |
| **A9** | Existing hard-stop behavior unchanged | Existing test `tests/test_cost_gate.py` (or equivalent) GREEN; new test added: `test_tiered_alarms_idempotent` GREEN |
| **A10** | `feature-dev:code-reviewer` standard pass clean | Per SKILL.md — agent core not touched, standard pass; auth-touching trigger NOT applicable |

**Ship gate:** literal pytest GREEN + A1-A10 all met. A4 + A5 require manual shadow-env test (call out in ship report).

---

## Open Questions for AH1 (none expected)

None. App-side architect's six items all folded as design decisions or features. Code-side architect's missing-from-design item #1 (kill-switches) lands here. Item #3 (tiered alarms) lands here.

---

## Sequencing

1. B-code claims brief.
2. Implement migration FIRST (smallest, sets up nullable column for downstream code).
3. Apply migration locally + refresh `applied_migrations.lock`.
4. Extend `log_api_cost()` signature + update capability_runner call sites.
5. Implement tiered alarms in `cost_monitor.py`.
6. Implement daily summary function.
7. Add tests for tier-alarm idempotence + hard-stop preservation.
8. `feature-dev:code-reviewer` standard pass.
9. Open PR against `main`.
10. AH1 reviews + merges.
11. Verify A4 + A5 + A6 in production within 24h via shadow tests + next-day summary.
12. Sibling brief `BRIEF_BAKER_PROMPT_CACHING_1.md` ships in parallel or before; both lean on `_send_tiered_alarm` infrastructure if interleaved.

---

## Reference

- Existing cost-monitor: `orchestrator/cost_monitor.py` (single-threshold logic at lines 39-41; alarm dispatch at 397-431)
- Existing cost gate test: `tests/test_cost_gate.py` — B-code verified absent at brief author time (2026-05-05); brief authorizes new test file `tests/test_cost_alarms.py` covering tier idempotence + hard-stop preservation + DB-backed alert state
- Existing api_cost_log schema: `orchestrator/cost_monitor.py:53-67` (`ensure_api_cost_log_table`)
- Sibling brief: `briefs/BRIEF_BAKER_PROMPT_CACHING_1.md`
- Code-side architect review: agent ID `a249ec2b5a682662b` 2026-05-05 (6 missing-from-design items, #1 + #3 land here)
- App-side architect review: relayed by Director 2026-05-05 chat (cultural-fix split rationale)
- Migration immutability: `migrations/applied_migrations.lock` refresh procedure per `tasks/lessons.md` Lesson #50
