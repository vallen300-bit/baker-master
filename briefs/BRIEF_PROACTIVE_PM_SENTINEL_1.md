# BRIEF: PROACTIVE_PM_SENTINEL_1 — Quiet-Thread Sentinel + Smart Triage

> **⚠️ B1 review required** (per `memory/feedback_ai_head_b1_review_triggers.md`):
> - **Trigger §2.1 Authentication** — introduces new `@app.post("/api/sentinel/feedback")` route (Feature 4) and new client-side auth-header handling (Feature 5).
> - **Trigger §2.2 Database migrations** — new `migrations/<YYYYMMDD>_sentinel_schema.sql` (Feature 1) adding `alerts.dismiss_reason` + `capability_threads.sla_hours` + one partial index.
>
> AI Head dispatch flow: B-code implements → AI Head `/security-review` → **B1 second-pair-of-eyes review** (per §2.1 + §2.2) → merge only on both green.

## Context

Phase 3 of the **AO PM Continuity Program** (ratified 2026-04-23; source artefact: `/Users/dimitry/baker-vault/_ops/ideas/2026-04-23-ao-pm-continuity-program.md` §7, §10 Q7). Adds the *proactive voice* layer — AO PM speaks up without being asked — plus a **smart triage surface** so Director's response to those alerts compounds into tuning signal.

**Scope history (three revisions):**
- Rev 1 (2026-04-24): three triggers from §7 — quiet-thread + draft-lint + relevance-on-ingest.
- Rev 2 (2026-04-24): Trigger 2 (Gmail draft-lint) stripped per Director directive — Director doesn't use Gmail drafts; Gmail deprecates post-M365. Deferred to Monday audit scratch §D1 with M365-usage decision gate. Trigger 3 already shipped Phase 1 (PR #50).
- **Rev 3 (2026-04-24, this revision):** Director-ratified **Upgrade 1 (Snooze)** + **Upgrade 2 (Dismiss-with-reason + 14-day pattern surface)**. Both expand the triage surface so every Director click produces learning signal. Part H §H2 unchanged — no new PM-state-write surfaces.

**Program sequencing:**
- Phase 0 Amendment H — canonical 2026-04-23.
- Phase 1 — shipped PR #50/#54/#56 (2026-04-24).
- Phase 2 — BRIEF_CAPABILITY_THREADS_1 drafted + dispatched to B2 (2026-04-24, held for merge).
- **Phase 3 (this brief)** — drafting during Phase 2 build per Q7 sequencing. **Dispatch gated on Phase 2 merge** (quiet-thread detection reads `capability_threads.last_turn_at` — hard dep; wrong-thread dismiss calls Phase 2's `/api/pm/threads/re-thread` — hard dep).
- Trigger 2 (Gmail draft-lint) tracked on Monday 2026-04-27 audit scratch §D1.

## Estimated time: ~11–17h Code Brisen
## Complexity: Medium–High
## Prerequisites
- ⏳ **BLOCKING:** BRIEF_CAPABILITY_THREADS_1 (Phase 2) merged + deployed. `capability_threads` + `capability_turns` tables live; `POST /api/pm/threads/re-thread` endpoint live (Upgrade 2 reason "wrong_thread" integrates with it).
- ✅ BRIEF_AI_HEAD_WEEKLY_AUDIT_1 merged — APScheduler + `scheduler_executions` + `baker_actions` audit patterns live.
- ✅ Slack substrate live (`outputs/slack_notifier.py::post_to_channel`, Director DM `D0AFY28N030`).
- ✅ `baker_corrections` table live (`memory/store_back.py:626`, write API `store_correction()` at :664).
- ✅ `alerts` table live — `snoozed_until TIMESTAMPTZ NULL` column **already present** (verified 2026-04-24 via `information_schema`). `dismiss_reason` added by this brief.

## API/dependency versions (deprecation check 2026-04-24)

| Dependency | Version/endpoint | Deprecation | Fallback |
|---|---|---|---|
| APScheduler | existing, `triggers/embedded_scheduler.py` | current | n/a |
| Slack Web API | `chat.postMessage` via `outputs/slack_notifier.py::post_to_channel` | current | n/a |
| PostgreSQL (Neon) | 16+ | ongoing | migrations via `config/migration_runner.py` |
| Phase 2 re-thread endpoint | `POST /api/pm/threads/re-thread` (BRIEF_CAPABILITY_THREADS_1 Feature 5.1) | ships with Phase 2 | if Phase 2 endpoint name changes at review, update Upgrade 2 `wrong_thread` client call |

No LLM calls. No external-API net-new dependencies beyond Slack (already live).

## Corrections to the ratified program

Source artefact §7.2 says "feedback loop into `capability_corrections`" — **actual table is `baker_corrections`** (`memory/store_back.py:626`). Verified via BRIEF_AO_PM_EXTENSION_1 line 585. **This brief uses `baker_corrections` throughout.**

Trigger 2 (Gmail draft-lint) from program §7 is **out of scope** — stripped 2026-04-24 per Director directive. Deferred on Monday 2026-04-27 audit scratch §D1.

---

## Design summary

Five additions, two schema touch-ups, zero LLM calls:

1. **Schema** — `capability_threads.sla_hours INTEGER DEFAULT NULL` (unchanged from Rev 2) + `alerts.dismiss_reason TEXT NULL` (new for Upgrade 2). `alerts.snoozed_until` already exists on the table; no DDL needed for Upgrade 1.
2. **Sentinel module** `orchestrator/proactive_pm_sentinel.py` — two entry points: `detect_quiet_threads()` (respects `alerts.snoozed_until` per Upgrade 1) + `detect_dismiss_patterns()` (14-day rolling-window aggregation per Upgrade 2 pattern-surface).
3. **Two APScheduler jobs** — `sentinel_quiet_thread` (every 30 min) + `sentinel_dismiss_patterns` (every 6 h). Both gated by `PROACTIVE_SENTINEL_ENABLED` env kill-switch.
4. **Enhanced feedback endpoint** — `/api/sentinel/feedback` handles four verdicts: `accept` / `snooze` (hours param) / `dismiss` (preset reason enum) / `reject` (learned_rule). Reason `wrong_thread` chains into Phase 2's `/api/pm/threads/re-thread` endpoint for stitcher-miscategorization fix.
5. **Triage UI** — 4-button desktop row (Accept / Snooze / Dismiss / Reject) with dropdown on Dismiss (4 preset reasons) + numeric input on Snooze (default 24h). Mobile: kebab-menu overflow per lesson #18. All pure DOM (lesson #17 + security hook).

**Reuses existing infrastructure:**
- `alerts` table — `source='proactive_pm_sentinel'` + `source_id=<thread_id>`; snoozed_until already exists.
- `outputs/slack_notifier.py::post_to_channel` — existing Director DM path.
- `store_correction()` — existing 5-per-capability cap + 90-day expiry; new `correction_type` values added.
- Phase 2 `/api/pm/threads/re-thread` — reused for Upgrade 2 reason `wrong_thread`.
- APScheduler `scheduler_executions` + job listener (BRIEF_AUDIT_SENTINEL_1).

**What this brief does NOT do:**
- No Trigger 2 (Gmail draft-lint) — stripped.
- No Trigger 3 (relevance-on-ingest) — shipped Phase 1.
- **No LLM calls.** Zero Opus / Haiku / Voyage cost.
- No auto-apply of pattern-surface suggestions — Director always has the click. Pattern surface *proposes* an SLA tweak; applying it uses existing `sla_hours` per-thread override or manual default change.
- No thread resolution automation — sentinel flags; Director decides.

---

## Feature 1: Schema — `capability_threads.sla_hours` + `alerts.dismiss_reason`

### Problem
(a) Per-thread SLA override needed for critical red-flag threads (Rev 2 scope). (b) Dismiss-with-reason (Upgrade 2) needs a column to store the reason enum. (c) Snooze (Upgrade 1) uses pre-existing `alerts.snoozed_until` — no DDL.

### Current state
- `capability_threads` (shipped by Phase 2): no SLA column.
- `alerts` columns verified 2026-04-24: includes `id, tier, title, body, action_required, status, acknowledged_at, resolved_at, trigger_id, contact_id, deal_id, created_at, structured_actions, matter_slug, exit_reason, tags, board_status, travel_date, source, source_id, snoozed_until`. **`snoozed_until` already exists. No `dismiss_reason` — needs ADD COLUMN.**

Note on `exit_reason`: pre-existing column with travel-dismissal semantics (per schema hints). Adding a dedicated `dismiss_reason` avoids overloading; lesson #43 dormant-reference-sweep applies — `exit_reason` stays for its pre-existing callers.

### Implementation

**NEW file** `migrations/<YYYYMMDD>_sentinel_schema.sql` (Code Brisen picks date = Phase 2 merge date + 1 or day-of; must sort-after Phase 2's `20260424_capability_threads.sql`):

```sql
-- == migrate:up ==
-- BRIEF_PROACTIVE_PM_SENTINEL_1 (Rev 3, 2026-04-24):
--   (a) per-thread SLA override for quiet-thread sentinel (Feature 1a)
--   (b) dismiss reason for Upgrade 2 triage surface (Feature 1b)
-- Both additive + nullable. Zero impact on existing rows.
-- alerts.snoozed_until pre-exists and is reused by Upgrade 1 — no DDL here.

ALTER TABLE capability_threads
    ADD COLUMN IF NOT EXISTS sla_hours INTEGER DEFAULT NULL;

COMMENT ON COLUMN capability_threads.sla_hours IS
  'BRIEF_PROACTIVE_PM_SENTINEL_1: override per-thread quiet-period alert threshold. NULL = use pm-level default. Typical values 6/12/24/48/72.';

ALTER TABLE alerts
    ADD COLUMN IF NOT EXISTS dismiss_reason TEXT DEFAULT NULL;

COMMENT ON COLUMN alerts.dismiss_reason IS
  'BRIEF_PROACTIVE_PM_SENTINEL_1: enum-style reason for alert dismissal. Accepted values: waiting_for_counterparty, already_handled_offline, low_priority, wrong_thread. NULL for non-dismissed or pre-this-brief rows.';

-- Index for pattern surface (14-day rolling aggregation)
CREATE INDEX IF NOT EXISTS idx_alerts_sentinel_dismiss_pattern
    ON alerts (source, status, dismiss_reason, resolved_at DESC)
    WHERE source = 'proactive_pm_sentinel' AND dismiss_reason IS NOT NULL;

-- == migrate:down ==
-- BEGIN;
-- ALTER TABLE capability_threads DROP COLUMN IF EXISTS sla_hours;
-- DROP INDEX IF EXISTS idx_alerts_sentinel_dismiss_pattern;
-- ALTER TABLE alerts DROP COLUMN IF EXISTS dismiss_reason;
-- COMMIT;
```

### Key constraints
- **Depends on Phase 2 migration** (`20260424_capability_threads.sql`) applied first. Migration-runner processes filename sort order — date-prefix this migration after Phase 2's.
- **No DDL in Python** (lesson #37) — file-only.
- **Partial index** uses `IMMUTABLE` operators only (`=`, `IS NOT NULL`) per lesson #38 — safe on Neon 16+.
- **Dismiss reason is unconstrained TEXT** (not a CHECK constraint) to allow reason-taxonomy evolution without migration churn. Endpoint validates against the canonical enum; unknown values rejected with HTTP 400.

### Verification SQL (post-deploy)
```sql
SELECT column_name, data_type, is_nullable FROM information_schema.columns
WHERE (table_name = 'capability_threads' AND column_name = 'sla_hours')
   OR (table_name = 'alerts' AND column_name = 'dismiss_reason')
ORDER BY table_name, column_name;
-- expect: 2 rows, both data_type varies (integer | text), is_nullable = YES.

SELECT indexname FROM pg_indexes
WHERE indexname = 'idx_alerts_sentinel_dismiss_pattern';
-- expect: 1 row.
```

---

## Feature 2: Sentinel module — `orchestrator/proactive_pm_sentinel.py`

### Problem
Quiet-thread detection (snooze-aware) + dismiss-pattern aggregation need a shared home. Keep it one module for single blast radius and centralised retry/dedup.

### Implementation — NEW `orchestrator/proactive_pm_sentinel.py`

```python
"""BRIEF_PROACTIVE_PM_SENTINEL_1: proactive quiet-thread sentinel + dismiss-pattern surface.

Two public entry points invoked by APScheduler:
  - detect_quiet_threads()     — every 30 min (respects alerts.snoozed_until)
  - detect_dismiss_patterns()  — every 6 h  (14-day rolling aggregation)

Non-fatal. Writes to scheduler_executions via the existing listener + to
alerts + baker_actions via _get_store().log_action(...).

Trigger 2 (Gmail draft-lint) stripped 2026-04-24 per Director directive.
Trigger 3 (relevance-on-ingest) shipped Phase 1 (PR #50).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg2.extras

logger = logging.getLogger("baker.proactive_pm_sentinel")

# PM-level SLA defaults (hours). Per-thread override via capability_threads.sla_hours.
# Director-ratified defaults 2026-04-24; tune after 2 weeks of real data OR when
# dismiss-pattern surface (Upgrade 2) fires a suggestion.
PM_SLA_DEFAULT_HOURS = {
    "ao_pm": 48,
    "movie_am": 24,
}
PM_SLA_FALLBACK_HOURS = 48

# Alert dedup window — don't re-fire on the same thread within this many hours.
QUIET_ALERT_COOLDOWN_HOURS = 24

# Dismiss-pattern surface (Upgrade 2)
DISMISS_PATTERN_WINDOW_DAYS = 14
DISMISS_PATTERN_THRESHOLD = 10
DISMISS_PATTERN_COOLDOWN_DAYS = 14

# Canonical dismiss reasons (validated at endpoint; stored as text for evolvability)
DISMISS_REASONS = {
    "waiting_for_counterparty",
    "already_handled_offline",
    "low_priority",
    "wrong_thread",
}

# Director DM Slack channel (canonical).
DIRECTOR_DM_CHANNEL = "D0AFY28N030"


# ─── Upgrade 1 + core: quiet-thread detection with snooze awareness ───

def detect_quiet_threads() -> dict:
    """Scan active capability_threads; Slack-push any that exceed their SLA.
    
    Upgrade 1: threads with an active-snooze alert (alerts.snoozed_until > NOW())
    are skipped. Snoozes auto-expire — no manual unsnooze needed.
    
    Returns {"checked": N, "alerted": M, "snoozed_skipped": S, "errors": K}.
    Non-fatal — one failing thread must not block the rest.
    """
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    
    result = {"checked": 0, "alerted": 0, "snoozed_skipped": 0, "errors": 0}
    conn = store._get_conn()
    if not conn:
        return result
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # LEFT JOIN to alerts filters out threads with an active snooze window.
        # Using text-cast on thread_id to match alerts.source_id (TEXT in alerts).
        cur.execute(
            """
            SELECT t.thread_id, t.pm_slug, t.topic_summary, t.last_turn_at, t.sla_hours
            FROM capability_threads t
            WHERE t.status = 'active'
              AND t.last_turn_at < NOW() - INTERVAL '6 hours'
              AND NOT EXISTS (
                SELECT 1 FROM alerts a
                WHERE a.source = 'proactive_pm_sentinel'
                  AND a.source_id = t.thread_id::text
                  AND a.snoozed_until IS NOT NULL
                  AND a.snoozed_until > NOW()
              )
            ORDER BY t.last_turn_at ASC
            LIMIT 200
            """
        )
        threads = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"detect_quiet_threads query failed: {e}")
        return result
    finally:
        store._put_conn(conn)
    
    # Telemetry: count snooze-skipped threads. Second query scoped tight to avoid
    # bloating the main query above; it's cheap (indexed source + snoozed_until).
    result["snoozed_skipped"] = _count_active_snoozes(store)
    
    for t in threads:
        result["checked"] += 1
        try:
            sla = t["sla_hours"] or PM_SLA_DEFAULT_HOURS.get(t["pm_slug"], PM_SLA_FALLBACK_HOURS)
            last = t["last_turn_at"]
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            hours_silent = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
            if hours_silent < sla:
                continue
            
            if _already_alerted_recently(store, "quiet_thread", str(t["thread_id"]),
                                         QUIET_ALERT_COOLDOWN_HOURS):
                continue
            
            text = _format_quiet_thread_alert(t, hours_silent, sla)
            pushed = _slack_push(DIRECTOR_DM_CHANNEL, text)
            _record_alert(store,
                          source="proactive_pm_sentinel",
                          source_id=str(t["thread_id"]),
                          tier=2,
                          title=f"Quiet thread [{t['pm_slug']}]: {(t['topic_summary'] or '')[:80]}",
                          body=text,
                          matter_slug=t["pm_slug"],
                          structured={"trigger": "quiet_thread",
                                      "hours_silent": round(hours_silent, 1),
                                      "sla_hours": sla,
                                      "slack_push_ok": bool(pushed)})
            if pushed:
                result["alerted"] += 1
        except Exception as e:
            logger.warning(f"detect_quiet_threads thread={t.get('thread_id')}: {e}")
            result["errors"] += 1
    
    logger.info(f"detect_quiet_threads done: {result}")
    return result


def _count_active_snoozes(store) -> int:
    conn = store._get_conn()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM alerts
            WHERE source = 'proactive_pm_sentinel'
              AND snoozed_until IS NOT NULL
              AND snoozed_until > NOW()
            """
        )
        row = cur.fetchone()
        cur.close()
        return int(row[0]) if row else 0
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"_count_active_snoozes failed: {e}")
        return 0
    finally:
        store._put_conn(conn)


def _format_quiet_thread_alert(thread: dict, hours_silent: float, sla: int) -> str:
    topic = (thread.get("topic_summary") or "(no summary)")[:200]
    pm_label = thread["pm_slug"].upper().replace("_", " ")
    return (
        f"*{pm_label} quiet-thread alert*\n"
        f"Thread: {topic}\n"
        f"Silent for {hours_silent:.1f}h (SLA {sla}h).\n"
        f"_Accept / Snooze / Dismiss / Reject via dashboard sentinel feedback._"
    )


# ─── Upgrade 2: dismiss-pattern surface ───

def detect_dismiss_patterns() -> dict:
    """Aggregate dismissed alerts by (pm_slug, dismiss_reason) over a 14-day rolling
    window. When a combo exceeds DISMISS_PATTERN_THRESHOLD and wasn't already
    surfaced in the last DISMISS_PATTERN_COOLDOWN_DAYS, Slack-push a suggestion.
    
    Returns {"patterns_checked": N, "surfaced": M, "errors": K}.
    """
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    
    result = {"patterns_checked": 0, "surfaced": 0, "errors": 0}
    conn = store._get_conn()
    if not conn:
        return result
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            """
            SELECT matter_slug AS pm_slug, dismiss_reason, COUNT(*) AS n
            FROM alerts
            WHERE source = 'proactive_pm_sentinel'
              AND status = 'dismissed'
              AND dismiss_reason IS NOT NULL
              AND resolved_at > NOW() - (%s || ' days')::interval
            GROUP BY matter_slug, dismiss_reason
            HAVING COUNT(*) >= %s
            ORDER BY n DESC
            LIMIT 20
            """,
            (str(DISMISS_PATTERN_WINDOW_DAYS), DISMISS_PATTERN_THRESHOLD),
        )
        patterns = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"detect_dismiss_patterns query failed: {e}")
        return result
    finally:
        store._put_conn(conn)
    
    for p in patterns:
        result["patterns_checked"] += 1
        try:
            pattern_key = f"{p['pm_slug']}::{p['dismiss_reason']}"
            # Dedup: don't re-surface the same pattern within cooldown window
            if _pattern_already_surfaced(store, pattern_key, DISMISS_PATTERN_COOLDOWN_DAYS):
                continue
            text = _format_dismiss_pattern_surface(p)
            pushed = _slack_push(DIRECTOR_DM_CHANNEL, text)
            _record_alert(store,
                          source="proactive_pm_sentinel",
                          source_id=f"pattern::{pattern_key}",
                          tier=3,
                          title=f"Dismiss pattern [{p['pm_slug']}]: {p['dismiss_reason']} ×{p['n']}",
                          body=text,
                          matter_slug=p["pm_slug"],
                          structured={"trigger": "dismiss_pattern",
                                      "pm_slug": p["pm_slug"],
                                      "dismiss_reason": p["dismiss_reason"],
                                      "count": int(p["n"]),
                                      "window_days": DISMISS_PATTERN_WINDOW_DAYS,
                                      "slack_push_ok": bool(pushed)})
            if pushed:
                result["surfaced"] += 1
        except Exception as e:
            logger.warning(f"detect_dismiss_patterns pattern={p}: {e}")
            result["errors"] += 1
    
    logger.info(f"detect_dismiss_patterns done: {result}")
    return result


def _pattern_already_surfaced(store, pattern_key: str, cooldown_days: int) -> bool:
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM alerts
            WHERE source = 'proactive_pm_sentinel'
              AND source_id = %s
              AND structured_actions->>'trigger' = 'dismiss_pattern'
              AND created_at >= NOW() - (%s || ' days')::interval
            LIMIT 1
            """,
            (f"pattern::{pattern_key}", str(cooldown_days)),
        )
        hit = cur.fetchone()
        cur.close()
        return bool(hit)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"_pattern_already_surfaced: {e}")
        return False
    finally:
        store._put_conn(conn)


def _format_dismiss_pattern_surface(pattern: dict) -> str:
    pm_label = pattern["pm_slug"].upper().replace("_", " ")
    reason = pattern["dismiss_reason"].replace("_", " ")
    n = int(pattern["n"])
    suggestion = _suggestion_for_pattern(pattern["pm_slug"], pattern["dismiss_reason"], n)
    return (
        f"*{pm_label} triage pattern surfaced*\n"
        f"Dismiss reason: _{reason}_\n"
        f"{n}× in the last {DISMISS_PATTERN_WINDOW_DAYS} days.\n\n"
        f"Suggestion:\n{suggestion}\n\n"
        f"_Acknowledge / apply / dismiss pattern via dashboard._"
    )


def _suggestion_for_pattern(pm_slug: str, reason: str, n: int) -> str:
    """Derive a human-readable suggestion from (pm_slug, reason, count).
    
    Pure rule-based — no LLM. Kept lightweight + extensible.
    """
    cur = PM_SLA_DEFAULT_HOURS.get(pm_slug, PM_SLA_FALLBACK_HOURS)
    if reason == "waiting_for_counterparty":
        proposed = max(cur * 3 // 2, cur + 24)  # e.g., 48 → 72
        return (f"Extend `{pm_slug}` default SLA from {cur}h → {proposed}h, "
                f"OR add per-thread `sla_hours={proposed}` for the dominant waiting threads.")
    if reason == "already_handled_offline":
        return (f"Consider adding an ingest-signal for the offline channel you're "
                f"using (WhatsApp? phone?) so threads auto-receive a turn when you "
                f"handle them offline. Else raise `{pm_slug}` SLA.")
    if reason == "low_priority":
        return (f"Raise `{pm_slug}` default SLA (currently {cur}h) OR raise the "
                f"`last_turn_at < NOW() - INTERVAL '6 hours'` floor in the sentinel — "
                f"consider {cur * 2}h floor before flagging.")
    if reason == "wrong_thread":
        return ("Stitcher miscategorized ≥10 turns. Review `capability_turns.stitch_decision` "
                "for the affected rows (high `alternatives` confidence gaps) and consider "
                "lowering `STITCH_MIN_COSINE` threshold in `orchestrator/capability_threads.py`.")
    return "No automated suggestion; investigate pattern manually."


# ─── Shared helpers ───

def _slack_push(channel_id: str, text: str) -> bool:
    try:
        from outputs.slack_notifier import post_to_channel
        return bool(post_to_channel(channel_id=channel_id, text=text))
    except Exception as e:
        logger.warning(f"_slack_push failed: {e}")
        return False


def _already_alerted_recently(store, trigger: str, source_id: str, cooldown_hours: int) -> bool:
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM alerts
            WHERE source = 'proactive_pm_sentinel'
              AND source_id = %s
              AND structured_actions->>'trigger' = %s
              AND created_at >= NOW() - (%s || ' hours')::interval
            LIMIT 1
            """,
            (source_id, trigger, str(cooldown_hours)),
        )
        hit = cur.fetchone()
        cur.close()
        return bool(hit)
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"_already_alerted_recently: {e}")
        return False
    finally:
        store._put_conn(conn)


def _record_alert(store, source: str, source_id: str, tier: int, title: str,
                  body: str, matter_slug: Optional[str], structured: dict) -> None:
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alerts (source, source_id, tier, title, body,
                                matter_slug, status, structured_actions, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s::jsonb, NOW())
            """,
            (source, source_id, tier, title[:500], body[:4000], matter_slug,
             json.dumps(structured, default=str)),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"_record_alert failed: {e}")
    finally:
        store._put_conn(conn)
```

### Key constraints
- **Singleton access (SKILL.md Rule 8):** every `SentinelStoreBack` access via `_get_global_instance()`. Pre-commit check: `grep -n 'SentinelStoreBack()' orchestrator/proactive_pm_sentinel.py` → 0 hits.
- **Non-fatal throughout:** every Slack push / PG write wraps in `try/except → logger.warning → return`.
- **No LLM calls. No external API net-new.** Zero Opus / Voyage / Haiku cost.
- **PostgreSQL:** every `except` → `conn.rollback()` before `_put_conn` per `.claude/rules/python-backend.md`.
- **All queries `LIMIT`:** threads scan at 200; patterns scan at 20.
- **Cast discipline:** `t.thread_id::text = a.source_id` works because `alerts.source_id` is TEXT and `capability_threads.thread_id` is UUID; cast-once on the thread side avoids per-row casting cost on a joined 200-row scan.
- **No `((col::date))`** per lesson #38; interval math uses `date_trunc` / `NOW() - INTERVAL`.
- **Extensible suggestion function:** rule-based, pure Python — no LLM. Add branches when new dismiss reasons surface.

---

## Feature 3: APScheduler wiring — `triggers/embedded_scheduler.py`

### Problem
Two cron jobs register alongside existing ~20 jobs. Both gated by single env kill-switch.

### Current state
`triggers/embedded_scheduler.py` uses `scheduler.add_job(...)` with standard kwargs. Job listener writes to `scheduler_executions`.

### Implementation
Add to `_register_jobs` (Code Brisen locates via `grep -n "scheduler.add_job" triggers/embedded_scheduler.py`):

```python
# BRIEF_PROACTIVE_PM_SENTINEL_1: proactive sentinels
if os.environ.get("PROACTIVE_SENTINEL_ENABLED", "true").lower() not in ("0", "false", "off"):
    # Upgrade 1 + core: quiet-thread detection (respects alerts.snoozed_until)
    from orchestrator.proactive_pm_sentinel import detect_quiet_threads as _sentinel_quiet
    scheduler.add_job(
        func=_sentinel_quiet,
        trigger="interval", minutes=30,
        id="sentinel_quiet_thread",
        replace_existing=True, max_instances=1,
        name="Proactive sentinel — quiet-thread detection",
    )
    # Upgrade 2: dismiss-pattern surface (14-day rolling aggregation)
    from orchestrator.proactive_pm_sentinel import detect_dismiss_patterns as _sentinel_dismiss_patterns
    scheduler.add_job(
        func=_sentinel_dismiss_patterns,
        trigger="interval", hours=6,
        id="sentinel_dismiss_patterns",
        replace_existing=True, max_instances=1,
        name="Proactive sentinel — dismiss pattern surface",
    )
```

**Env kill-switch:** `PROACTIVE_SENTINEL_ENABLED=false` disables both jobs without code deploy. Default true.

### Verification SQL (post-deploy)

```sql
-- First fire within 30 min / 6 h of deploy
SELECT job_id, fired_at, status, outputs_summary FROM scheduler_executions
WHERE job_id IN ('sentinel_quiet_thread', 'sentinel_dismiss_patterns')
  AND fired_at > NOW() - INTERVAL '12 hours'
ORDER BY fired_at DESC LIMIT 10;

-- Error rate check (24h)
SELECT job_id, status, COUNT(*) FROM scheduler_executions
WHERE job_id IN ('sentinel_quiet_thread', 'sentinel_dismiss_patterns')
  AND fired_at > NOW() - INTERVAL '24 hours'
GROUP BY job_id, status ORDER BY job_id;
```

---

## Feature 4: Feedback endpoint — `/api/sentinel/feedback`

### Problem
Director needs four verdicts: **accept** (resolve), **snooze** (defer N hours, reuses `alerts.snoozed_until`), **dismiss** (with preset reason enum), **reject** (store learned rule into `baker_corrections`). The `wrong_thread` dismiss reason chains into Phase 2's re-thread endpoint.

### Current state
`baker_corrections` table with `store_correction()` signature verified `memory/store_back.py:664`. Phase 2 introduces `POST /api/pm/threads/re-thread` (BRIEF_CAPABILITY_THREADS_1 Feature 5.1).

### Implementation

**New endpoint in `outputs/dashboard.py`** (grep-verify `/api/sentinel/feedback` has no pre-existing route; lesson #11 — confirmed free of conflict, existing `/api/sentinel-health*` routes at lines 1345/1462 are a different namespace).

**Auth required** per B1 trigger §2.1 + PR #57 anchor incident (Apr 2026). Sibling convention in `outputs/dashboard.py` has ≥60 `/api/*` routes all carrying `dependencies=[Depends(verify_api_key)]`.

```python
@app.post("/api/sentinel/feedback", dependencies=[Depends(verify_api_key)])
async def sentinel_feedback(req: Request):
    """BRIEF_PROACTIVE_PM_SENTINEL_1: Director triage surface.
    
    Body: {"alert_id": int, "verdict": "accept"|"snooze"|"dismiss"|"reject",
           "snooze_hours": int?,        # when verdict=snooze (default 24)
           "dismiss_reason": str?,       # when verdict=dismiss (must be in DISMISS_REASONS)
           "director_comment": str?,
           "learned_rule": str?,         # required when verdict=reject
           "auto_apply_suggestion": bool?}  # when verdict=reject on pattern-surface alert
    
    Returns:
      - standard feedback response dict
      - for dismiss_reason='wrong_thread': additional `rethread_hint` field with
        thread_id so the client can POST /api/pm/threads/re-thread (Phase 2).
    """
    body = await req.json()
    alert_id = body.get("alert_id")
    verdict = (body.get("verdict") or "").lower()
    if not alert_id or verdict not in ("accept", "snooze", "dismiss", "reject"):
        return JSONResponse(
            {"error": "alert_id and verdict in {accept,snooze,dismiss,reject} required"},
            status_code=400,
        )
    
    # Validate verdict-specific fields
    from orchestrator.proactive_pm_sentinel import DISMISS_REASONS
    if verdict == "snooze":
        try:
            snooze_hours = int(body.get("snooze_hours") or 24)
        except (TypeError, ValueError):
            return JSONResponse({"error": "snooze_hours must be integer"}, status_code=400)
        if snooze_hours < 1 or snooze_hours > 720:  # 30-day max
            return JSONResponse({"error": "snooze_hours out of range [1, 720]"}, status_code=400)
    elif verdict == "dismiss":
        dismiss_reason = (body.get("dismiss_reason") or "").strip().lower()
        if dismiss_reason not in DISMISS_REASONS:
            return JSONResponse(
                {"error": f"dismiss_reason must be one of {sorted(DISMISS_REASONS)}"},
                status_code=400,
            )
    
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return JSONResponse({"error": "db unavailable"}, status_code=503)
    
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT id, source, source_id, matter_slug, structured_actions
            FROM alerts WHERE id = %s AND source = 'proactive_pm_sentinel' LIMIT 1
        """, (alert_id,))
        row = cur.fetchone()
        if not row:
            return JSONResponse({"error": "alert not found"}, status_code=404)
        
        verdict_meta = {
            "director_verdict": verdict,
            "director_comment": (body.get("director_comment") or "")[:2000],
            "verdict_at": datetime.now(timezone.utc).isoformat(),
        }
        
        if verdict == "snooze":
            snoozed_until_sql = f"NOW() + INTERVAL '{int(body.get('snooze_hours') or 24)} hours'"
            cur.execute(f"""
                UPDATE alerts
                SET status = 'pending',
                    snoozed_until = {snoozed_until_sql},
                    structured_actions = structured_actions || %s::jsonb
                WHERE id = %s
            """, (json.dumps({**verdict_meta, "snooze_hours": int(body.get('snooze_hours') or 24)}),
                  alert_id))
            new_status = "snoozed"
        elif verdict == "dismiss":
            cur.execute("""
                UPDATE alerts
                SET status = 'dismissed',
                    dismiss_reason = %s,
                    resolved_at = NOW(),
                    structured_actions = structured_actions || %s::jsonb
                WHERE id = %s
            """, (body.get("dismiss_reason").strip().lower(),
                  json.dumps(verdict_meta), alert_id))
            new_status = "dismissed"
        else:  # accept or reject — both resolve
            cur.execute("""
                UPDATE alerts
                SET status = 'resolved', resolved_at = NOW(),
                    structured_actions = structured_actions || %s::jsonb
                WHERE id = %s
            """, (json.dumps(verdict_meta), alert_id))
            new_status = "resolved"
        
        conn.commit()
        cur.close()
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"/api/sentinel/feedback update failed: {e}")
        return JSONResponse({"error": "feedback_failed"}, status_code=500)
    finally:
        store._put_conn(conn)
    
    response = {"alert_id": alert_id, "status": new_status, "verdict": verdict}
    
    # Verdict-specific post-processing
    if verdict == "reject":
        learned_rule = (body.get("learned_rule") or "").strip()
        director_comment = (body.get("director_comment") or "").strip()
        if not learned_rule:
            response["warning"] = "reject without learned_rule — no correction stored"
        else:
            try:
                store.store_correction(
                    baker_task_id=int(alert_id),
                    capability_slug=row["matter_slug"] or "ao_pm",
                    correction_type="sentinel_false_positive",
                    director_comment=director_comment,
                    learned_rule=learned_rule,
                    matter_slug=row["matter_slug"],
                    applies_to="capability",
                )
            except Exception as e:
                logger.warning(f"store_correction failed: {e}")
                response["warning"] = f"correction_store_failed: {type(e).__name__}"
    
    # Upgrade 2: wrong_thread dismiss → hint to client to call re-thread UI
    if verdict == "dismiss" and body.get("dismiss_reason", "").strip().lower() == "wrong_thread":
        # The alerts.source_id for a quiet-thread alert is the thread_id (UUID str);
        # client uses this to call Phase 2's /api/pm/threads/re-thread.
        response["rethread_hint"] = {
            "turn_id_hint": None,  # client knows which turn; may not apply at thread-level
            "thread_id": row["source_id"],
            "pm_slug": row["matter_slug"],
            "rethread_endpoint": "/api/pm/threads/re-thread",
        }
    
    return JSONResponse(response)
```

### Key constraints
- **Enum validation** in endpoint (not DB CHECK) — allows evolving the reason taxonomy without migration churn.
- **Snooze cap** 720 hours / 30 days — prevents runaway defer.
- **Safe SQL composition** for `snoozed_until`: the interval value is built from a cast `int()` — no string injection possible. Literal SQL fragment with integer-coerced value.
- **`store_correction` anti-bloat** already enforces 5-per-capability cap.
- **`baker_task_id` is INTEGER NOT NULL** per schema — reuse `alert_id` (matches `alerts.id` SERIAL).

---

## Feature 5: Triage UI — 4-button row + Dismiss dropdown + Snooze input

### Problem
Director needs a fast triage surface on the dashboard. 4 buttons on desktop; overflow to kebab menu on mobile per lesson #18.

### Current state
`outputs/static/app.js` + `index.html` + `style.css`. No existing sentinel-alert UI. All DOM must be pure (no `innerHTML` with user-derived content per lesson #17 + security hook).

### Implementation

**`outputs/static/app.js`** — 4-button panel with dropdown and input:

```javascript
// BRIEF_PROACTIVE_PM_SENTINEL_1: sentinel alert triage surface
const DISMISS_REASONS = [
    { key: 'waiting_for_counterparty', label: 'Waiting for counterparty' },
    { key: 'already_handled_offline', label: 'Already handled offline' },
    { key: 'low_priority',             label: 'Low priority' },
    { key: 'wrong_thread',             label: 'Wrong thread (re-thread)' },
];

function renderSentinelAlert(alertRow) {
    const wrap = document.createElement('div');
    wrap.className = 'sentinel-alert';
    wrap.dataset.alertId = alertRow.id;
    wrap.dataset.matterSlug = alertRow.matter_slug || '';

    const title = document.createElement('div');
    title.className = 'sentinel-alert-title';
    title.textContent = alertRow.title || '(no title)';
    wrap.appendChild(title);

    const body = document.createElement('div');
    body.className = 'sentinel-alert-body';
    body.textContent = (alertRow.body || '').slice(0, 800);
    wrap.appendChild(body);

    const btnRow = document.createElement('div');
    btnRow.className = 'sentinel-alert-buttons';
    btnRow.appendChild(makeButton('Accept', 'accept', () => sendFeedback(alertRow, 'accept')));
    btnRow.appendChild(makeSnoozeButton(alertRow));
    btnRow.appendChild(makeDismissButton(alertRow));
    btnRow.appendChild(makeButton('Reject + teach', 'reject', () => handleReject(alertRow)));
    wrap.appendChild(btnRow);

    // Mobile overflow (lesson #18): CSS + kebab container
    const kebab = document.createElement('div');
    kebab.className = 'sentinel-alert-kebab';
    kebab.dataset.forAlertId = alertRow.id;
    kebab.setAttribute('aria-label', 'More triage options');
    kebab.textContent = '⋯';  // plain ellipsis, not an image — fits pure-DOM rule
    kebab.addEventListener('click', () => toggleKebabMenu(alertRow.id));
    wrap.appendChild(kebab);

    return wrap;
}

function makeButton(label, verdictClass, onClick) {
    const b = document.createElement('button');
    b.className = 'sentinel-btn sentinel-btn-' + verdictClass;
    b.textContent = label;
    b.addEventListener('click', onClick);
    return b;
}

function makeSnoozeButton(alertRow) {
    const wrap = document.createElement('div');
    wrap.className = 'sentinel-snooze-wrap';
    const b = document.createElement('button');
    b.className = 'sentinel-btn sentinel-btn-snooze';
    b.textContent = 'Snooze…';
    b.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const open = wrap.querySelector('.sentinel-snooze-input');
        if (open) { open.remove(); return; }
        const input = document.createElement('input');
        input.className = 'sentinel-snooze-input';
        input.type = 'number';
        input.min = '1';
        input.max = '720';
        input.value = '24';
        input.setAttribute('aria-label', 'Snooze hours');
        const go = document.createElement('button');
        go.className = 'sentinel-btn sentinel-btn-snooze-confirm';
        go.textContent = 'OK';
        go.addEventListener('click', () => {
            const hours = Math.max(1, Math.min(720, parseInt(input.value || '24', 10)));
            sendFeedback(alertRow, 'snooze', { snooze_hours: hours });
            input.remove(); go.remove();
        });
        wrap.appendChild(input);
        wrap.appendChild(go);
        input.focus();
    });
    wrap.appendChild(b);
    return wrap;
}

function makeDismissButton(alertRow) {
    const wrap = document.createElement('div');
    wrap.className = 'sentinel-dismiss-wrap';
    const b = document.createElement('button');
    b.className = 'sentinel-btn sentinel-btn-dismiss';
    b.textContent = 'Dismiss because…';
    b.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const existing = wrap.querySelector('.sentinel-dismiss-menu');
        if (existing) { existing.remove(); return; }
        const menu = document.createElement('div');
        menu.className = 'sentinel-dismiss-menu';
        DISMISS_REASONS.forEach(r => {
            const item = document.createElement('div');
            item.className = 'sentinel-dismiss-item';
            item.textContent = r.label;
            item.dataset.reason = r.key;
            item.addEventListener('click', () => {
                sendFeedback(alertRow, 'dismiss', { dismiss_reason: r.key });
                menu.remove();
            });
            menu.appendChild(item);
        });
        wrap.appendChild(menu);
    });
    wrap.appendChild(b);
    return wrap;
}

function handleReject(alertRow) {
    const comment = window.prompt('Why was this a false positive?');
    if (!comment) return;
    const rule = window.prompt('One-line rule to avoid this in future:');
    if (!rule) return;
    sendFeedback(alertRow, 'reject', { director_comment: comment, learned_rule: rule });
}

async function sendFeedback(alertRow, verdict, extra) {
    const body = Object.assign({ alert_id: alertRow.id, verdict }, extra || {});
    try {
        // Use existing bakerFetch wrapper (outputs/static/app.js:25) — auto-adds X-Baker-Key.
        // Raw fetch() would 401 against the auth-gated endpoint.
        const res = await bakerFetch('/api/sentinel/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) { console.warn('sentinel feedback failed', res.status); return; }
        const data = await res.json();

        // Upgrade 2 chain: wrong_thread → open Phase 2 re-thread UI
        if (verdict === 'dismiss' && extra && extra.dismiss_reason === 'wrong_thread' && data.rethread_hint) {
            openRethreadFor(data.rethread_hint);
        }
        // Remove rendered row on terminal verdicts; snooze stays visible with indicator
        if (verdict !== 'snooze') {
            const el = document.querySelector('.sentinel-alert[data-alert-id="' + alertRow.id + '"]');
            if (el && el.parentNode) el.parentNode.removeChild(el);
        } else {
            const el = document.querySelector('.sentinel-alert[data-alert-id="' + alertRow.id + '"]');
            if (el) el.classList.add('sentinel-alert-snoozed');
        }
    } catch (e) {
        console.warn('sentinel feedback network error', e);
    }
}

function openRethreadFor(hint) {
    // Phase 2 already exposes a re-thread UI / endpoint; call into it.
    // Code Brisen: if Phase 2 ships a function/UI, wire it here. Otherwise,
    // direct POST to /api/pm/threads/re-thread with a prompt for the new thread target.
    if (typeof window.openThreadReThread === 'function') {
        window.openThreadReThread(hint);
        return;
    }
    const newThreadId = window.prompt(
        'Re-thread: enter new thread_id (leave blank to create a fresh thread):',
        ''
    );
    // Phase 2 endpoint is auth-gated (PR #57 fix-back) — must use bakerFetch wrapper.
    bakerFetch('/api/pm/threads/re-thread', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            turn_id: hint.turn_id_hint,  // may be null at alert-level; Phase 2 tolerates
            new_thread_id: newThreadId || null,
        }),
    }).catch(e => console.warn('rethread network error', e));
}

function toggleKebabMenu(alertId) {
    // Mobile kebab: reveals the same action set as desktop (Accept / Snooze / Dismiss / Reject)
    // in a dropdown. Implementation mirrors makeDismissButton menu shape.
    const wrap = document.querySelector('.sentinel-alert[data-alert-id="' + alertId + '"]');
    if (!wrap) return;
    const existing = wrap.querySelector('.sentinel-alert-kebab-menu');
    if (existing) { existing.remove(); return; }
    const menu = document.createElement('div');
    menu.className = 'sentinel-alert-kebab-menu';
    ['Accept', 'Snooze 24h', 'Dismiss: waiting', 'Dismiss: offline', 'Dismiss: low prio',
     'Dismiss: wrong thread', 'Reject + teach'].forEach(label => {
        const item = document.createElement('div');
        item.className = 'sentinel-alert-kebab-item';
        item.textContent = label;
        item.addEventListener('click', () => dispatchKebabLabel(alertId, label));
        menu.appendChild(item);
    });
    wrap.appendChild(menu);
}

function dispatchKebabLabel(alertId, label) {
    // Map kebab label → existing feedback call.
    const alertRow = { id: alertId };  // minimal; server fills in matter_slug etc.
    if (label === 'Accept') return sendFeedback(alertRow, 'accept');
    if (label === 'Snooze 24h') return sendFeedback(alertRow, 'snooze', { snooze_hours: 24 });
    if (label === 'Reject + teach') return handleReject(alertRow);
    const reasonMap = {
        'Dismiss: waiting': 'waiting_for_counterparty',
        'Dismiss: offline': 'already_handled_offline',
        'Dismiss: low prio': 'low_priority',
        'Dismiss: wrong thread': 'wrong_thread',
    };
    if (reasonMap[label]) return sendFeedback(alertRow, 'dismiss', { dismiss_reason: reasonMap[label] });
}
```

**`outputs/static/style.css`** — minimal responsive styles:

```css
/* BRIEF_PROACTIVE_PM_SENTINEL_1: sentinel triage */
.sentinel-alert { padding: 12px; margin: 8px 0; border-left: 4px solid #d97706; position: relative; }
.sentinel-alert.sentinel-alert-snoozed { opacity: 0.55; }
.sentinel-alert-buttons { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.sentinel-btn { padding: 6px 12px; border: 1px solid #444; background: #fafafa; cursor: pointer; }
.sentinel-btn:hover { background: #f0f0f0; }
.sentinel-dismiss-menu, .sentinel-alert-kebab-menu {
    position: absolute; background: #fff; border: 1px solid #888;
    box-shadow: 0 4px 12px rgba(0,0,0,.15); min-width: 200px; z-index: 100;
}
.sentinel-dismiss-item, .sentinel-alert-kebab-item { padding: 8px 12px; cursor: pointer; }
.sentinel-dismiss-item:hover, .sentinel-alert-kebab-item:hover { background: #f0f0f0; }
.sentinel-snooze-input { width: 60px; margin-left: 4px; }
.sentinel-alert-kebab { display: none; position: absolute; top: 8px; right: 8px;
    font-size: 20px; cursor: pointer; padding: 4px 8px; }

/* Mobile: hide button row, show kebab (lesson #18) */
@media (max-width: 640px) {
    .sentinel-alert-buttons { display: none; }
    .sentinel-alert-kebab { display: inline-block; }
}
```

**`outputs/static/index.html`** — add a container (if the dashboard doesn't already render alerts) + bump `?v=N` cache-bust on JS/CSS refs per lesson #4:

```html
<!-- Bump ?v=N on these three when this brief ships -->
<link rel="stylesheet" href="/static/style.css?v=<N>" />
<script defer src="/static/app.js?v=<N>"></script>
```

### Key UI constraints
- **Pure DOM throughout.** No `innerHTML` with user-derived content (lesson #17, security hook).
- **`window.prompt`** is a minimal MVP for reject-rule capture; acceptable because Director himself is the sole user and it avoids modal-framework churn. Can be upgraded to a modal later.
- **Cache bust** (lesson #4): bump `?v=N` on all three static refs.
- **No HTML5 Drag API** (lesson #1) — all actions click-based.
- **Mobile kebab** per lesson #18 — desktop button row hidden at `max-width: 640px`.
- **Accessible:** buttons are `<button>` elements; inputs have `aria-label`; kebab has `aria-label`.

---

## Feature 6: Tests — ship-gate discipline (literal `pytest` green)

**NEW `tests/test_proactive_pm_sentinel.py`:**

```python
"""BRIEF_PROACTIVE_PM_SENTINEL_1 tests."""
from datetime import datetime, timezone
import pytest


# ─── Unit: SLA defaults ───

def test_sla_defaults():
    from orchestrator.proactive_pm_sentinel import PM_SLA_DEFAULT_HOURS, PM_SLA_FALLBACK_HOURS
    assert PM_SLA_DEFAULT_HOURS["ao_pm"] == 48
    assert PM_SLA_DEFAULT_HOURS["movie_am"] == 24
    assert PM_SLA_DEFAULT_HOURS.get("unknown_pm", PM_SLA_FALLBACK_HOURS) == PM_SLA_FALLBACK_HOURS


def test_dismiss_reasons_canonical():
    from orchestrator.proactive_pm_sentinel import DISMISS_REASONS
    assert DISMISS_REASONS == {
        "waiting_for_counterparty",
        "already_handled_offline",
        "low_priority",
        "wrong_thread",
    }


# ─── Unit: alert formatters ───

def test_format_quiet_thread_alert():
    from orchestrator.proactive_pm_sentinel import _format_quiet_thread_alert
    thread = {"thread_id": "t", "pm_slug": "ao_pm", "topic_summary": "Aukera release"}
    text = _format_quiet_thread_alert(thread, hours_silent=50.5, sla=48)
    assert "AO PM" in text and "Aukera" in text and "50.5" in text and "48" in text


def test_format_dismiss_pattern_surface_waiting():
    from orchestrator.proactive_pm_sentinel import _format_dismiss_pattern_surface, DISMISS_PATTERN_WINDOW_DAYS
    pattern = {"pm_slug": "ao_pm", "dismiss_reason": "waiting_for_counterparty", "n": 12}
    text = _format_dismiss_pattern_surface(pattern)
    assert "AO PM" in text
    assert "waiting for counterparty" in text
    assert "12×" in text
    assert f"{DISMISS_PATTERN_WINDOW_DAYS} days" in text


def test_suggestion_for_waiting_proposes_higher_sla():
    from orchestrator.proactive_pm_sentinel import _suggestion_for_pattern
    s = _suggestion_for_pattern("ao_pm", "waiting_for_counterparty", 15)
    # Current 48 → proposed at least 72 (max(48*3//2, 48+24) = 72)
    assert "72" in s


def test_suggestion_for_wrong_thread_mentions_stitcher():
    from orchestrator.proactive_pm_sentinel import _suggestion_for_pattern
    s = _suggestion_for_pattern("ao_pm", "wrong_thread", 10)
    assert "Stitcher" in s or "STITCH" in s or "stitch_decision" in s


# ─── Unit: snooze + cooldown helpers (SQL-assertion style) ───

class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or [None]
        self.queries = []
        self.rowcount = 1
    def execute(self, q, params=None):
        self.queries.append((q, params))
    def fetchone(self):
        return self._rows[0] if self._rows else None
    def close(self): pass


def test_count_active_snoozes_no_rows():
    from orchestrator.proactive_pm_sentinel import _count_active_snoozes
    class _FakeStore:
        def _get_conn(self):
            class _C:
                def cursor(self): return _FakeCursor(rows=[(0,)])
                def commit(self): pass
                def rollback(self): pass
            return _C()
        def _put_conn(self, c): pass
    assert _count_active_snoozes(_FakeStore()) == 0


def test_already_alerted_recently_dedup_query_uses_correct_source():
    """Regression direction: ensure we filter by source='proactive_pm_sentinel' not generic."""
    from orchestrator.proactive_pm_sentinel import _already_alerted_recently
    captured = _FakeCursor(rows=[None])
    class _FakeStore:
        def _get_conn(self):
            class _C:
                def cursor(self): return captured
                def commit(self): pass
                def rollback(self): pass
            return _C()
        def _put_conn(self, c): pass
    _already_alerted_recently(_FakeStore(), "quiet_thread", "tid", 24)
    q, _params = captured.queries[0]
    assert "'proactive_pm_sentinel'" in q
    assert "structured_actions->>'trigger'" in q


def test_pattern_already_surfaced_uses_pattern_prefix():
    """Regression direction: dedup uses source_id='pattern::<key>'."""
    from orchestrator.proactive_pm_sentinel import _pattern_already_surfaced
    captured = _FakeCursor(rows=[None])
    class _FakeStore:
        def _get_conn(self):
            class _C:
                def cursor(self): return captured
                def commit(self): pass
                def rollback(self): pass
            return _C()
        def _put_conn(self, c): pass
    _pattern_already_surfaced(_FakeStore(), "ao_pm::waiting_for_counterparty", 14)
    q, params = captured.queries[0]
    assert "source_id = %s" in q
    assert params[0] == "pattern::ao_pm::waiting_for_counterparty"


# ─── Integration: DDL smoke ───

@pytest.mark.skipif("not config.getoption('--run-integration')", reason="integration only")
def test_sentinel_schema_applied():
    import psycopg2
    from config.settings import config as cfg
    conn = psycopg2.connect(**cfg.postgres.dsn_params)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE (table_name='capability_threads' AND column_name='sla_hours')
               OR (table_name='alerts' AND column_name='dismiss_reason')
        """)
        cols = sorted(r[0] for r in cur.fetchall())
        assert cols == ["dismiss_reason", "sla_hours"]
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE indexname = 'idx_alerts_sentinel_dismiss_pattern'
        """)
        assert cur.fetchone() is not None
    finally:
        conn.close()
```

**NEW `tests/test_proactive_pm_sentinel_h5.py`** — §H5 roundtrip test (snooze + dismiss-with-reason + reject learning loop):

```python
"""BRIEF_PROACTIVE_PM_SENTINEL_1 §Part H §H5 — triage roundtrip."""
import pytest
import psycopg2
import psycopg2.extras
from config.settings import config as cfg


@pytest.mark.skipif("not config.getoption('--run-integration')", reason="integration only")
def test_h5_triage_roundtrip_snooze_dismiss_reject():
    """Three alert rows → Director verdicts → correct DB state."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    
    # Seed three sentinel alerts (simulating detect_quiet_threads output)
    seeded_ids = []
    conn = psycopg2.connect(**cfg.postgres.dsn_params)
    try:
        cur = conn.cursor()
        for i in range(3):
            cur.execute("""
                INSERT INTO alerts (source, source_id, tier, title, body, matter_slug,
                                    status, structured_actions, created_at)
                VALUES ('proactive_pm_sentinel', %s, 2, %s, 'H5 body', 'ao_pm',
                        'pending', %s::jsonb, NOW())
                RETURNING id
            """, (f"h5-thread-{i}", f"H5 alert {i}",
                  '{"trigger": "quiet_thread"}'))
            seeded_ids.append(cur.fetchone()[0])
        conn.commit()
        cur.close()
    finally:
        conn.close()
    
    # (1) Snooze the first
    _apply_verdict(seeded_ids[0], verdict="snooze", snooze_hours=12)
    # (2) Dismiss the second with 'waiting_for_counterparty'
    _apply_verdict(seeded_ids[1], verdict="dismiss", dismiss_reason="waiting_for_counterparty")
    # (3) Reject the third with a learned rule
    store.store_correction(
        baker_task_id=int(seeded_ids[2]),
        capability_slug="ao_pm",
        correction_type="sentinel_false_positive",
        director_comment="This thread was parked by Director directly.",
        learned_rule="Do not alert on threads with status='dormant'.",
        matter_slug="ao_pm",
        applies_to="capability",
    )
    
    # Verify
    conn = psycopg2.connect(**cfg.postgres.dsn_params)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT id, status, snoozed_until, dismiss_reason FROM alerts WHERE id = ANY(%s)", (seeded_ids,))
        rows = {r["id"]: dict(r) for r in cur.fetchall()}
        
        # Snoozed row: snoozed_until > NOW(); status still 'pending'
        snoozed_row = rows[seeded_ids[0]]
        assert snoozed_row["snoozed_until"] is not None
        assert snoozed_row["status"] == "pending"
        
        # Dismissed row: status = dismissed, dismiss_reason set
        dismissed_row = rows[seeded_ids[1]]
        assert dismissed_row["status"] == "dismissed"
        assert dismissed_row["dismiss_reason"] == "waiting_for_counterparty"
        
        # Rejected row has entry in baker_corrections
        cur.execute("""
            SELECT COUNT(*) FROM baker_corrections
            WHERE baker_task_id = %s AND correction_type = 'sentinel_false_positive' AND active = TRUE
        """, (seeded_ids[2],))
        assert cur.fetchone()[0] >= 1
    finally:
        conn.close()


def _apply_verdict(alert_id, **kwargs):
    """Directly exercise the update path (bypasses HTTP; fine for integration test)."""
    import psycopg2
    import json
    from config.settings import config as cfg
    conn = psycopg2.connect(**cfg.postgres.dsn_params)
    try:
        cur = conn.cursor()
        if kwargs["verdict"] == "snooze":
            cur.execute(f"""
                UPDATE alerts
                SET snoozed_until = NOW() + INTERVAL '{int(kwargs['snooze_hours'])} hours',
                    structured_actions = structured_actions || %s::jsonb
                WHERE id = %s
            """, (json.dumps({"verdict": "snooze", "snooze_hours": int(kwargs["snooze_hours"])}), alert_id))
        elif kwargs["verdict"] == "dismiss":
            cur.execute("""
                UPDATE alerts
                SET status = 'dismissed', dismiss_reason = %s, resolved_at = NOW(),
                    structured_actions = structured_actions || %s::jsonb
                WHERE id = %s
            """, (kwargs["dismiss_reason"],
                  json.dumps({"verdict": "dismiss", "dismiss_reason": kwargs["dismiss_reason"]}),
                  alert_id))
        conn.commit()
        cur.close()
    finally:
        conn.close()
```

### Ship gate

```bash
$ python3 -m pytest tests/test_proactive_pm_sentinel.py tests/test_proactive_pm_sentinel_h5.py -v --run-integration 2>&1 | tail -40
```

Expected: `X passed, 0 failed` (literal output pasted into PR; no "pass by inspection" per SKILL.md).

---

## §Part H — Invocation-Path Audit (Amendment H — BLOCKER)

### H1. Enumerate invocation paths

| # | file:line | Entry function | Surface | Reads state | Writes state |
|---|---|---|---|---|---|
| 1 | `triggers/embedded_scheduler.py` → `orchestrator/proactive_pm_sentinel.py::detect_quiet_threads` | `detect_quiet_threads` | **sentinel_cron** | Layer 1 (`capability_threads`) + `alerts.snoozed_until` (for Upgrade 1 skip-filter) | writes `alerts` + `baker_actions`; does NOT write `pm_project_state` |
| 2 | `triggers/embedded_scheduler.py` → `orchestrator/proactive_pm_sentinel.py::detect_dismiss_patterns` | `detect_dismiss_patterns` | sentinel_cron | `alerts` (aggregation over 14-day window) | writes `alerts` (pattern-surface rows) + `baker_actions`; does NOT write `pm_project_state` |
| 3 | `outputs/dashboard.py::sentinel_feedback` | `sentinel_feedback` (endpoint) | dashboard_api (Director explicit) | `alerts` lookup | writes `alerts.{status,snoozed_until,dismiss_reason,resolved_at,structured_actions}` + optionally `baker_corrections` via `store_correction` |
| 4 | (Upgrade 2 chain only) `outputs/static/app.js::openRethreadFor` → POST `/api/pm/threads/re-thread` | Phase 2 endpoint | dashboard_api (Director explicit) | Phase 2 surface — see BRIEF_CAPABILITY_THREADS_1 §Part H | writes `capability_turns.thread_id` per Phase 2 |

### H2. Write-path closure

**Sentinels do NOT write to `pm_project_state`.** They observe + alert + learn + (via Upgrade 2 chain) request re-threading. Pattern-2 state mutation remains the domain of `extract_and_update_pm_state` (Phase 1/2). Amendment H's original concern (4-door write-loop divergence) is **orthogonal** to this brief.

`mutation_source` taxonomy (H4) is **not extended** — no new PM-state writes.

Side-effect tables touched (with reason):
- `alerts` — core sentinel surface (writes for alerts; writes for triage verdict; writes for pattern-surface rows).
- `baker_corrections` via `store_correction(correction_type='sentinel_false_positive')` — learning loop (reject verdict only).
- `capability_turns.thread_id` via Phase 2 re-thread endpoint — Upgrade 2 chain only; Phase 2 owns that write-path audit.

### H3. Read-path completeness

| Caller | Reads | Notes |
|---|---|---|
| detect_quiet_threads | Layer 1 (`capability_threads`) + `alerts.snoozed_until` subquery | Partial-read of Layer 1 only — INTENTIONAL. Full Layer 2/3 load would add latency to a 30-min cron iterating ≤200 threads. Justified. |
| detect_dismiss_patterns | `alerts` aggregation (14-day rolling window) | Pure aggregation; no Layer 1/2/3 read needed. |
| sentinel_feedback | `alerts` row lookup | Endpoint-scoped; Director has full context before clicking. |

All partial loads explicitly justified.

### H4. `mutation_source` tag allocation

Not extended. Sentinels don't write `pm_state_history`.

New `baker_corrections.correction_type` values introduced by this brief:
- `sentinel_false_positive` — reject verdict on any sentinel alert.

(Future: if pattern-surface acceptance ever auto-applies an SLA tweak, a new `correction_type='sla_tune_from_pattern'` will be added then — not in this brief.)

### H5. Cross-surface continuity test

Test: `tests/test_proactive_pm_sentinel_h5.py::test_h5_triage_roundtrip_snooze_dismiss_reject`.

Shape: *Three alerts seeded → snooze sets `snoozed_until`, status='pending' → dismiss sets `dismiss_reason='waiting_for_counterparty'`, status='dismissed' → reject leaves alert resolved AND creates `baker_corrections` row with `correction_type='sentinel_false_positive'` retrievable for future use.*

Integration-gated. Buildable against Phase 2 + existing infrastructure.

---

## Files Modified (complete list)

- **NEW** `migrations/<YYYYMMDD>_sentinel_schema.sql` — Feature 1 DDL (`capability_threads.sla_hours` + `alerts.dismiss_reason` + partial index)
- **NEW** `orchestrator/proactive_pm_sentinel.py` — Feature 2 (~450 lines)
- **MODIFY** `triggers/embedded_scheduler.py` — Feature 3 (2 new `scheduler.add_job` calls under `PROACTIVE_SENTINEL_ENABLED`)
- **MODIFY** `outputs/dashboard.py` — Feature 4 (new endpoint `/api/sentinel/feedback` with 4-verdict dispatch). Grep-verify no duplicate route (lesson #11).
- **MODIFY** `outputs/static/app.js` — Feature 5 (4-button row, dismiss dropdown, snooze input, kebab overflow, rethread chain). Pure DOM.
- **MODIFY** `outputs/static/index.html` + `style.css` — Feature 5 styles + bumped `?v=N` cache bust (lesson #4).
- **NEW** `tests/test_proactive_pm_sentinel.py` — unit + SQL-assertion (Feature 6)
- **NEW** `tests/test_proactive_pm_sentinel_h5.py` — integration H5 roundtrip

## Files NOT to Touch

- `orchestrator/capability_runner.py` — sentinels don't touch the runner or its system prompt.
- `orchestrator/capability_threads.py` (Phase 2 new file) — reads only; no schema or logic changes; wrong-thread chain calls the Phase 2 endpoint, not the module directly.
- `memory/store_back.py` — reuse `_get_global_instance`, `store_correction`, `_get_conn`/`_put_conn`. No new methods.
- `memory/retriever.py` — not involved.
- `orchestrator/pm_signal_detector.py` — not coupled.
- `config/migration_runner.py` — reuse unchanged.
- `alerts.exit_reason` — pre-existing column with travel-dismissal semantics; untouched (dedicated `dismiss_reason` added to avoid overload per lesson #43).
- **No Gmail-related code** (Trigger 2 stripped).

## Quality Checkpoints (post-deploy)

1. **Migration applied:** `SELECT * FROM schema_migrations WHERE filename LIKE '%sentinel_schema%'` = 1 row.
2. **Columns present:** `SELECT column_name FROM information_schema.columns WHERE (table_name='capability_threads' AND column_name='sla_hours') OR (table_name='alerts' AND column_name='dismiss_reason')` = 2 rows.
3. **Partial index present:** `SELECT indexname FROM pg_indexes WHERE indexname='idx_alerts_sentinel_dismiss_pattern'` = 1 row.
4. **Scheduler jobs registered:** `SELECT DISTINCT job_id FROM scheduler_executions WHERE fired_at > NOW() - INTERVAL '12 hours'` includes `sentinel_quiet_thread` + `sentinel_dismiss_patterns`.
5. **Error rate:** `SELECT status, COUNT(*) FROM scheduler_executions WHERE job_id IN ('sentinel_quiet_thread','sentinel_dismiss_patterns') AND fired_at > NOW() - INTERVAL '24 hours' GROUP BY job_id, status` — error count <5% of executed.
6. **First alert fires within 4h of deploy** (if qualifying threads exist): `SELECT COUNT(*) FROM alerts WHERE source='proactive_pm_sentinel' AND created_at > NOW() - INTERVAL '4 hours'` ≥ 0.
7. **Snooze round-trips:** Director exercises one snooze → `alerts.snoozed_until > NOW()` set; next cron tick does NOT re-fire on that thread. Confirmed via `SELECT thread_id FROM capability_threads WHERE thread_id::text IN (SELECT source_id FROM alerts WHERE snoozed_until > NOW())` present.
8. **Dismiss-with-reason round-trips:** Director exercises one dismiss → `alerts.dismiss_reason` populated; status='dismissed'.
9. **Reject + learning loop:** Director exercises one reject with learned_rule → `baker_corrections` row present, active=TRUE.
10. **Pattern surface** (needs 10+ dismiss rows same pm_slug/reason in 14 days — may take weeks to naturally trigger; can be seeded for QA): first pattern-surface row present after threshold hit; Slack push visible in Director DM.
11. **Kill-switch works:** `PROACTIVE_SENTINEL_ENABLED=false` → next deploy, neither job registers.
12. **Mobile kebab:** iPhone PWA — at `width <= 640px`, button row hidden, kebab visible; menu items wired correctly.

## Cost impact

- **detect_quiet_threads:** zero LLM. ~200 rows/run × 48 runs/day × 7 days ≈ 67K PG reads/week. Neon trivial.
- **detect_dismiss_patterns:** zero LLM. Aggregation query × 4 runs/day × 7 days = 28 aggregations/week. Indexed via `idx_alerts_sentinel_dismiss_pattern` — microseconds each.
- **Slack pushes:** ~0–5/week quiet-thread + ~0–2/week pattern-surface.
- **`alerts` rows:** ~5–20/week total.
- **`baker_corrections`:** ~0–2/week new rows (reject path). 5-cap + 90-day expiry.

**Total net-new cost: €0.** No LLM, no paid APIs.

## Safety rules compliance

- **PostgreSQL:** every `except` → `conn.rollback()` before `_put_conn`. Verified.
- **LIMIT on unbounded queries:** threads 200, patterns 20.
- **No secrets in code:** only new env var is `PROACTIVE_SENTINEL_ENABLED` (boolean).
- **Fault-tolerant writes:** every sentinel + endpoint path non-fatal on PG/Slack errors.
- **Render restart survival:** state in PG + env. APScheduler re-registers jobs at startup.
- **SQL injection:** snooze interval built from `int(value)`-coerced literal — no string-path user input reaches the SQL.
- **No `innerHTML` with user-derived content.** Feature 5 JS is pure DOM (lesson #17, security hook).
- **Cache bust** on all three static refs (lesson #4).

## Pre-merge verification (per lesson #40)

```bash
# 1. Phase 2 merged + live (hard dep)
# Via Baker HTTP API — MCP may be unavailable; curl fallback per CLAUDE.md:
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT table_name FROM information_schema.tables WHERE table_name IN ('\''capability_threads'\'', '\''capability_turns'\'')"}}}'
# Expected: 2 rows. If fewer → STOP, Phase 2 not merged.

# 2. Phase 2 /api/pm/threads/re-thread endpoint live (Upgrade 2 wrong_thread chain)
grep -n '/api/pm/threads/re-thread' outputs/dashboard.py
# Expected: exactly 1 route definition (from Phase 2).

# 3. alerts.snoozed_until pre-exists (Upgrade 1 consumes, not creates)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT column_name FROM information_schema.columns WHERE table_name='\''alerts'\'' AND column_name IN ('\''snoozed_until'\'', '\''structured_actions'\'', '\''source'\'', '\''source_id'\'') ORDER BY column_name"}}}'
# Expected: 4 rows.

# 4. baker_corrections present
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT column_name FROM information_schema.columns WHERE table_name='\''baker_corrections'\'' AND column_name IN ('\''capability_slug'\'', '\''active'\'', '\''learned_rule'\'') ORDER BY column_name"}}}'
# Expected: 3 rows.

# 5. No duplicate /api/sentinel route (lesson #11)
grep -n '/api/sentinel' outputs/dashboard.py
# Expected: 0 pre-existing.

# 6. Singleton hook pre-push
bash scripts/check_singletons.sh
# Expected: pass.

# 7. JSONResponse imported (lesson #18 spot-check)
sed -n '23p' outputs/dashboard.py
# Expected: line contains 'JSONResponse'.
```

## Dispatch checklist (AI Head → B-code, GATED ON PHASE 2 MERGE)

**Do NOT dispatch until:**
- BRIEF_CAPABILITY_THREADS_1 PR merged + Render deploy green
- Phase 2 Quality Checkpoints 1–8 verified by AI Head (including H5 cross-surface test passing)
- Phase 2 `/api/pm/threads/re-thread` confirmed live (needed for Upgrade 2 wrong_thread chain)

**When ready:**
- Working dir: `~/bm-bN` (AI Head selects by then-idle status)
- Working branch: `proactive-pm-sentinel-1`
- Pre-reqs: §Pre-merge verification pasted in PR body
- Acceptance: Quality Checkpoints 1–12 verifiably pass (QC 10 may require manual seeding for faster QA)
- Ship gate: `pytest tests/test_proactive_pm_sentinel.py tests/test_proactive_pm_sentinel_h5.py -v --run-integration` — **no "pass by inspection"**
- Security review gate: `/security-review` mandatory
- Deploy gate: post-merge verify QC 1–6; 48h soak for QC 7–12.

---

## Lessons pre-applied

- #1 / no HTML5 Drag — UI uses click only.
- #2 / #3 column names verified (alerts snoozed_until pre-existing; baker_corrections + capability_threads via `information_schema` 2026-04-24).
- #4 cache-bust on UI JS/CSS.
- #8 verify before done — Director-driven triage roundtrip is the proof.
- #11 duplicate endpoint check included in pre-merge verification.
- #17 grep-verified signatures: `post_to_channel(channel_id, text)` at `outputs/slack_notifier.py:111`, `store_correction(...)` at `memory/store_back.py:664`.
- #18 `JSONResponse` import at `outputs/dashboard.py:23` + **mobile kebab overflow** applied at 640px breakpoint per UI constraint.
- #34 integration test (H5 triage-roundtrip) included.
- #35 / #37 migrations in `migrations/*.sql`, zero DDL in Python.
- #38 no `((col::date))` — partial index uses `WHERE source='...'` + `IS NOT NULL` only (IMMUTABLE operators).
- #40 pre-merge verification includes Phase 2 dependency check + re-thread endpoint check.
- #42 fixture + real-DB + SQL-assertion tests all present.
- #43 legacy-reference sweep: `alerts.exit_reason` identified as pre-existing travel-dismissal column; dedicated `dismiss_reason` added to avoid overload.
- #44 `/write-brief` REVIEW step ran.
- **Security:** no `innerHTML` with user-derived content anywhere in Feature 5 JS (pure DOM throughout).
- **Corrections:** v3 continuity program §7.2 `capability_corrections` → actual table is `baker_corrections` (cited + corrected at top of brief). Trigger 2 stripped pre-draft per Director directive; deferred to Monday audit scratch §D1.

---

**Brief ends.**

_Revision 3 of 2026-04-24 — Upgrade 1 (Snooze) + Upgrade 2 (Dismiss-with-reason + 14-day pattern surface) added per Director ratification. Dispatch gated on Phase 2 merge._

_Revision 3 polish pass (2026-04-24 post-PR-#57-merge, AI Head #2) — three fixes applied ahead of Director read-first:_
1. _Feature 4 `/api/sentinel/feedback` decorator now carries `dependencies=[Depends(verify_api_key)]` (matches sibling convention in `outputs/dashboard.py`; closes the exact gap PR #57 tripped on)._
2. _Feature 5 JS `sendFeedback()` + `openRethreadFor()` now use the existing `bakerFetch()` wrapper (auto-adds `X-Baker-Key`) instead of raw `fetch()` — required because Phase 2's `/api/pm/threads/re-thread` is now auth-gated per the PR #57 fix-back._
3. _Brief header flags the two B1-review triggers (§2.1 Authentication + §2.2 Database migrations) per `memory/feedback_ai_head_b1_review_triggers.md`._

_Phase 2 deploy verified green on Render 2026-04-24 09:05 UTC (CP1-4 + CP13). Drafting gate released by Director post-merge; dispatch still waits on Director ratify + CP5-8 organic observation (per brief §Dispatch checklist)._
