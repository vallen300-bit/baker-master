"""
Cost Monitor — Phase 4A + BAKER-COST-INSTRUMENTATION-1
Tracks API costs per call, aggregates daily, tiered alarms + hard-stop breaker.

Usage:
    from orchestrator.cost_monitor import log_api_cost, check_circuit_breaker

    # Before each API call:
    allowed, daily_cost = check_circuit_breaker()
    if not allowed:
        return  # hard-stopped

    # After each API call:
    log_api_cost(model, input_tokens, output_tokens, source="agent_loop",
                 matter_slug="oskolkov")  # matter_slug optional
"""
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional, Tuple

logger = logging.getLogger("baker.cost_monitor")

# Model costs (USD per million tokens) — GEMINI-MIGRATION-1
MODEL_COSTS = {
    # Anthropic
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    # Gemini
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    # xAI (GROK_API_CAPABILITY_1; pricing per xAI docs 2026-05-17)
    "grok-4.3": {"input": 1.25, "output": 2.50},
}
DEFAULT_COSTS = {"input": 15.00, "output": 75.00}

# EUR/USD conversion rate (approximate)
USD_TO_EUR = float(os.getenv("BAKER_USD_TO_EUR", "0.92"))

# BAKER-COST-INSTRUMENTATION-1: tiered alarm thresholds (EUR/day).
# Walked in ascending order; one alarm per (date, tier) per day, DB-persisted.
COST_TIERS = [
    (float(os.getenv("BAKER_COST_TIER_INFO_EUR", "30.0")), "info", "ℹ️"),
    (float(os.getenv("BAKER_COST_TIER_WARN_EUR", "60.0")), "warn", "⚠️"),
    (float(os.getenv("BAKER_COST_TIER_CRITICAL_EUR", "80.0")), "critical", "🚨"),
]

# Hard stop unchanged (existing behavior; absolute kill).
COST_HARD_STOP_EUR = float(os.getenv("BAKER_COST_HARD_STOP_EUR", "100.0"))

# Master kill-switch — disables all tier alarms AND daily summary.
# Hard stop is always on regardless.
COST_ALARMS_ENABLED = os.getenv("BAKER_COST_ALARMS_ENABLED", "true").lower() == "true"

# Backwards-compat alias — still referenced by get_daily_breakdown +
# get_cost_dashboard JSON payloads. Points at the lowest (info) tier so
# the dashboard's "alert_threshold_eur" remains a meaningful number.
COST_ALERT_EUR = COST_TIERS[0][0]

# In-process belt-and-suspenders cache for hard-stop alarm
# (one Slack message per process per day; DB-persisted in cost_alert_state for tier alarms).
_hard_stop_sent_date = None


# ─────────────────────────────────────────────
# Table DDL
# ─────────────────────────────────────────────

def ensure_api_cost_log_table(conn):
    """Create api_cost_log table. Called from store_back.__init__.

    Schema kept aligned with two migrations (Lesson #50 — migration-vs-bootstrap
    drift trap):
      - 20260505_api_cost_log_matter_slug.sql       (BAKER-COST-INSTRUMENTATION-1)
      - 20260505_140000_api_cost_log_cache_columns  (BAKER-PROMPT-CACHING-1)
    Fresh DBs (tests / new environments) match the migrated prod schema for
    both matter_slug attribution and cache-token accounting.
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_cost_log (
                id SERIAL PRIMARY KEY,
                logged_at TIMESTAMPTZ DEFAULT NOW(),
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_creation_input_tokens INTEGER DEFAULT 0,
                cache_read_input_tokens INTEGER DEFAULT 0,
                cost_eur NUMERIC(10,6) DEFAULT 0,
                source TEXT,
                capability_id TEXT,
                task_id TEXT,
                matter_slug TEXT DEFAULT NULL
            )
        """)
        # Idempotent column adds for existing DBs that pre-date this column set.
        cur.execute("""
            ALTER TABLE api_cost_log
            ADD COLUMN IF NOT EXISTS cache_creation_input_tokens INTEGER DEFAULT 0
        """)
        cur.execute("""
            ALTER TABLE api_cost_log
            ADD COLUMN IF NOT EXISTS cache_read_input_tokens INTEGER DEFAULT 0
        """)
        cur.execute("""
            ALTER TABLE api_cost_log
            ADD COLUMN IF NOT EXISTS matter_slug TEXT DEFAULT NULL
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_cost_log_logged_at
            ON api_cost_log (logged_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_cost_log_matter_slug
            ON api_cost_log (matter_slug) WHERE matter_slug IS NOT NULL
        """)
        conn.commit()
        cur.close()
        logger.info("api_cost_log table verified")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure api_cost_log table: {e}")


def ensure_cost_alert_state_table(conn):
    """Create cost_alert_state table for DB-persisted tier-alarm idempotence.
    Aligned with migration 20260505b_cost_alert_state.sql per Lesson #50."""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cost_alert_state (
                alert_date DATE NOT NULL,
                tier_label TEXT NOT NULL,
                fired_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (alert_date, tier_label)
            )
        """)
        conn.commit()
        cur.close()
        logger.info("cost_alert_state table verified")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure cost_alert_state table: {e}")


# ─────────────────────────────────────────────
# Cost Calculation
# ─────────────────────────────────────────────

def calculate_cost_eur(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """Calculate cost in EUR for a given API call.

    BAKER-PROMPT-CACHING-1: Anthropic prompt caching pricing per docs:
      - cache_read_input_tokens billed at 10% of standard input rate (90% discount)
      - cache_creation_input_tokens billed at 200% of standard input rate (1-hour TTL,
        per PR #176 2026-05-08; was 125% under default 5-min TTL)
      - regular input_tokens billed at standard rate

    For non-Anthropic models the cache args are zero (kwargs default), so this
    reduces to the original two-term formula. Safe for Gemini callers.
    """
    costs = MODEL_COSTS.get(model, DEFAULT_COSTS)
    cost_usd = (
        (input_tokens / 1_000_000) * costs["input"]
        + (cache_creation_input_tokens / 1_000_000) * costs["input"] * 2.00
        + (cache_read_input_tokens / 1_000_000) * costs["input"] * 0.10
        + (output_tokens / 1_000_000) * costs["output"]
    )
    return round(cost_usd * USD_TO_EUR, 6)


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

def log_api_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    source: str,
    capability_id: str = None,
    task_id: str = None,
    matter_slug: str = None,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> Optional[float]:
    """Log an API call cost. Returns cost in EUR or None on failure.

    Merged signature (BAKER-COST-INSTRUMENTATION-1 + BAKER-PROMPT-CACHING-1):
      - matter_slug: per-matter attribution (None = unattributed).
      - cache_creation_input_tokens / cache_read_input_tokens: Anthropic
        prompt-cache accounting; default 0 so non-caching callers
        (capability_runner, pipeline, Gemini paths) work unchanged.
    All trailing params are kwargs-defaulted — call sites should pass by name.
    """
    cost_eur = calculate_cost_eur(
        model, input_tokens, output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return cost_eur
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO api_cost_log
                   (model, input_tokens, output_tokens,
                    cache_creation_input_tokens, cache_read_input_tokens,
                    cost_eur, source, capability_id, task_id, matter_slug)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (model, input_tokens, output_tokens,
                 cache_creation_input_tokens, cache_read_input_tokens,
                 cost_eur, source, capability_id, task_id, matter_slug),
            )
            conn.commit()
            cur.close()
            logger.debug(
                f"Cost: {model} {input_tokens}in/{output_tokens}out "
                f"cache=({cache_creation_input_tokens}c/{cache_read_input_tokens}r) "
                f"= €{cost_eur:.4f} [{source}] matter={matter_slug or '-'}"
            )
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not log API cost: {e}")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Cost logging failed (non-fatal): {e}")
    return cost_eur


# ─────────────────────────────────────────────
# Daily Aggregation
# ─────────────────────────────────────────────

def get_daily_cost(day: date = None) -> float:
    """Get total API cost in EUR for a given day (default: today UTC)."""
    if day is None:
        day = datetime.now(timezone.utc).date()
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return 0.0
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COALESCE(SUM(cost_eur), 0) FROM api_cost_log WHERE DATE(logged_at) = %s",
                (day,),
            )
            total = float(cur.fetchone()[0])
            cur.close()
            return total
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not get daily cost: {e}")
            return 0.0
        finally:
            store._put_conn(conn)
    except Exception:
        return 0.0


def get_daily_breakdown(day: date = None) -> dict:
    """Get cost breakdown by model, source, and matter for a given day."""
    import psycopg2.extras

    if day is None:
        day = datetime.now(timezone.utc).date()
    result = {"date": str(day), "total_eur": 0.0, "total_input_tokens": 0,
              "total_output_tokens": 0, "call_count": 0,
              "by_model": {}, "by_source": {}, "by_matter": {},
              "alert_threshold_eur": COST_ALERT_EUR,
              "hard_stop_threshold_eur": COST_HARD_STOP_EUR}
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return result
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Total + count
            cur.execute(
                """SELECT COALESCE(SUM(cost_eur), 0) as total,
                          COALESCE(SUM(input_tokens), 0) as total_in,
                          COALESCE(SUM(output_tokens), 0) as total_out,
                          COUNT(*) as calls
                   FROM api_cost_log WHERE DATE(logged_at) = %s""",
                (day,),
            )
            row = cur.fetchone()
            result["total_eur"] = float(row["total"])
            result["total_input_tokens"] = int(row["total_in"])
            result["total_output_tokens"] = int(row["total_out"])
            result["call_count"] = int(row["calls"])
            # By model
            cur.execute(
                """SELECT model, COALESCE(SUM(cost_eur), 0) as cost,
                          COUNT(*) as calls,
                          COALESCE(SUM(input_tokens), 0) as tokens_in,
                          COALESCE(SUM(output_tokens), 0) as tokens_out
                   FROM api_cost_log WHERE DATE(logged_at) = %s
                   GROUP BY model ORDER BY cost DESC""",
                (day,),
            )
            result["by_model"] = {r["model"]: dict(r) for r in cur.fetchall()}
            # By source
            cur.execute(
                """SELECT source, COALESCE(SUM(cost_eur), 0) as cost,
                          COUNT(*) as calls
                   FROM api_cost_log WHERE DATE(logged_at) = %s
                   GROUP BY source ORDER BY cost DESC""",
                (day,),
            )
            result["by_source"] = {r["source"]: dict(r) for r in cur.fetchall()}
            # By matter (NULL bucketed as [unattributed], never silently filtered)
            cur.execute(
                """SELECT COALESCE(matter_slug, '[unattributed]') as matter,
                          COALESCE(SUM(cost_eur), 0) as cost,
                          COUNT(*) as calls
                   FROM api_cost_log WHERE DATE(logged_at) = %s
                   GROUP BY COALESCE(matter_slug, '[unattributed]')
                   ORDER BY cost DESC""",
                (day,),
            )
            result["by_matter"] = {r["matter"]: dict(r) for r in cur.fetchall()}
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not get daily breakdown: {e}")
        finally:
            store._put_conn(conn)
    except Exception:
        pass
    return result


def get_cost_history(days: int = 7) -> list:
    """Get daily cost totals for the last N days."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT DATE(logged_at) as day,
                          COALESCE(SUM(cost_eur), 0) as total_eur,
                          COUNT(*) as calls,
                          COALESCE(SUM(input_tokens), 0) as tokens_in,
                          COALESCE(SUM(output_tokens), 0) as tokens_out
                   FROM api_cost_log
                   WHERE logged_at > NOW() - (INTERVAL '1 day' * %s)
                   GROUP BY DATE(logged_at)
                   ORDER BY day DESC""",
                (days,),
            )
            rows = cur.fetchall()
            cur.close()
            return [
                {"date": str(r[0]), "total_eur": float(r[1]),
                 "calls": r[2], "tokens_in": r[3], "tokens_out": r[4]}
                for r in rows
            ]
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not get cost history: {e}")
            return []
        finally:
            store._put_conn(conn)
    except Exception:
        return []


# ─────────────────────────────────────────────
# G2: Per-Capability Cost Breakdown (Session 27)
# ─────────────────────────────────────────────

def get_capability_costs(days: int = 7) -> list:
    """G2: Cost breakdown per capability slug for the last N days."""
    try:
        import psycopg2.extras
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT capability_id as capability,
                       COUNT(*) as calls,
                       ROUND(SUM(cost_eur)::numeric, 4) as total_eur,
                       SUM(input_tokens) as tokens_in,
                       SUM(output_tokens) as tokens_out,
                       ROUND(AVG(cost_eur)::numeric, 4) as avg_cost_eur
                FROM api_cost_log
                WHERE logged_at > NOW() - (INTERVAL '1 day' * %s)
                  AND capability_id IS NOT NULL
                GROUP BY capability_id
                ORDER BY total_eur DESC
            """, (days,))
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            # Convert Decimal to float for JSON serialization
            for r in rows:
                for k in ("total_eur", "avg_cost_eur"):
                    if r.get(k) is not None:
                        r[k] = float(r[k])
                for k in ("tokens_in", "tokens_out", "calls"):
                    if r.get(k) is not None:
                        r[k] = int(r[k])
            return rows
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not get capability costs: {e}")
            return []
        finally:
            store._put_conn(conn)
    except Exception:
        return []


def get_cost_dashboard(days: int = 7) -> dict:
    """G2: Combined cost dashboard — daily history + source breakdown + capability breakdown."""
    history = get_cost_history(days)
    today = get_daily_breakdown()
    capabilities = get_capability_costs(days)

    # Compute week total
    week_total = sum(d.get("total_eur", 0) for d in history)
    avg_daily = week_total / max(len(history), 1)

    return {
        "today": today,
        "history": history,
        "capabilities": capabilities,
        "summary": {
            "week_total_eur": round(week_total, 2),
            "avg_daily_eur": round(avg_daily, 2),
            "days_tracked": len(history),
            "alert_threshold_eur": COST_ALERT_EUR,
            "hard_stop_eur": COST_HARD_STOP_EUR,
        },
    }


# ─────────────────────────────────────────────
# Tier-alarm idempotence (DB-persisted)
# ─────────────────────────────────────────────

def _claim_tier_alert(alert_date: date, tier_label: str) -> bool:
    """Atomically claim a (date, tier_label) slot in cost_alert_state.

    Returns True if we got the lock (caller should fire the Slack alert);
    False if the slot was already taken (someone else fired it today).

    Uses INSERT ... ON CONFLICT DO NOTHING — duplicate inserts are a no-op
    and report 0 rows affected. Safe across process restarts (Render bounces
    no longer re-fire today's alarms) and across concurrent workers.

    On DB failure returns True (degrade open — better to over-fire than
    under-fire on cost alarms).
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return True
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO cost_alert_state (alert_date, tier_label)
                   VALUES (%s, %s)
                   ON CONFLICT (alert_date, tier_label) DO NOTHING""",
                (alert_date, tier_label),
            )
            claimed = cur.rowcount == 1
            conn.commit()
            cur.close()
            return claimed
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not claim tier alert {tier_label}: {e}")
            return True
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Tier-alert claim degraded open: {e}")
        return True


# ─────────────────────────────────────────────
# Circuit Breaker
# ─────────────────────────────────────────────

def check_circuit_breaker() -> Tuple[bool, float]:
    """Check if API calls should be allowed.
    Returns (allowed: bool, daily_cost_eur: float).

    Walks COST_TIERS in ascending order; fires at most one Slack message per
    (date, tier_label) per day via DB-backed claim. Hard stop unchanged.
    """
    global _hard_stop_sent_date
    today = datetime.now(timezone.utc).date()
    daily_cost = get_daily_cost(today)

    # Tiered alarms (visibility only, do NOT block).
    if COST_ALARMS_ENABLED:
        for threshold, label, emoji in COST_TIERS:
            if daily_cost >= threshold:
                if _claim_tier_alert(today, label):
                    _send_tiered_alarm(daily_cost, threshold, label, emoji)
                    logger.warning(
                        f"Cost tier alarm [{label}]: €{daily_cost:.2f} >= €{threshold:.2f}"
                    )

    # Hard stop (kept bit-for-bit; always on regardless of COST_ALARMS_ENABLED).
    if daily_cost >= COST_HARD_STOP_EUR:
        if _hard_stop_sent_date != today:
            _hard_stop_sent_date = today
            _send_hard_stop_alert(daily_cost)
        logger.error(f"COST HARD STOP: €{daily_cost:.2f} >= €{COST_HARD_STOP_EUR:.2f}")
        return False, daily_cost

    return True, daily_cost


def _send_tiered_alarm(daily_cost: float, threshold: float,
                       tier_label: str, emoji: str):
    """Send a tiered cost alarm to #cockpit. Mirrors `_send_hard_stop_alert`."""
    try:
        import requests
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if not slack_token:
            logger.warning(f"No SLACK_BOT_TOKEN — cannot send {tier_label} alarm")
            return

        msg = (
            f"{emoji} *Baker Cost Alarm — {tier_label.upper()}*\n"
            f"Daily API spend: *€{daily_cost:.2f}* (tier: €{threshold:.2f})\n"
            f"Hard stop at: €{COST_HARD_STOP_EUR:.2f}\n"
            f"Disable tiers: `BAKER_COST_ALARMS_ENABLED=false` (hard stop stays on)"
        )

        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {slack_token}"},
            json={"channel": "#cockpit", "text": msg},
            timeout=5,
        )
        logger.info(f"Tier alarm sent to Slack: {tier_label} €{daily_cost:.2f}")
    except Exception as e:
        logger.warning(f"Could not send {tier_label} tier alarm: {e}")


def _send_hard_stop_alert(daily_cost: float):
    """Send hard-stop alert to #cockpit. Always-on; not gated by ALARMS_ENABLED."""
    try:
        import requests
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if not slack_token:
            logger.warning("No SLACK_BOT_TOKEN — cannot send hard stop alert")
            return

        msg = (
            f"🛑 *Baker HARD STOP*\n"
            f"Daily API spend: *€{daily_cost:.2f}* — ALL API CALLS BLOCKED\n"
            f"Threshold: €{COST_HARD_STOP_EUR:.2f}\n"
            f"Baker will resume tomorrow. Override: set BAKER_COST_HARD_STOP_EUR higher."
        )

        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {slack_token}"},
            json={"channel": "#cockpit", "text": msg},
            timeout=5,
        )
        logger.info(f"Hard stop alert sent to Slack: €{daily_cost:.2f}")
    except Exception as e:
        logger.warning(f"Could not send hard stop alert: {e}")


# Backwards-compat shim — older call sites may still import this symbol.
def _send_cost_alert(daily_cost: float, hard_stop: bool = False):
    """Deprecated; retained for any external import. Routes to new helpers."""
    if hard_stop:
        _send_hard_stop_alert(daily_cost)
    else:
        _send_tiered_alarm(daily_cost, COST_ALERT_EUR, "info", "ℹ️")


# ─────────────────────────────────────────────
# Daily summary post (BAKER-COST-INSTRUMENTATION-1 Feature 4)
# ─────────────────────────────────────────────

def post_daily_cost_summary(day: date = None) -> dict:
    """Post a daily cost summary to #cockpit. Idempotent per UTC day via the
    cost_alert_state table (tier_label='daily_summary'). Suppressed when
    BAKER_COST_ALARMS_ENABLED=false.

    Returns the rendered breakdown (whether or not the Slack post fired) so
    callers can log or test the structure.
    """
    if day is None:
        day = datetime.now(timezone.utc).date()
    breakdown = get_daily_breakdown(day)

    if not COST_ALARMS_ENABLED:
        logger.info("daily_cost_summary suppressed (BAKER_COST_ALARMS_ENABLED=false)")
        return breakdown

    # Idempotence — once-per-UTC-day Slack post even if scheduler retries.
    if not _claim_tier_alert(day, "daily_summary"):
        logger.info(f"daily_cost_summary already posted for {day}; skipping")
        return breakdown

    lines = [
        f"📊 *Baker daily cost — {breakdown['date']}*",
        f"Total: €{breakdown['total_eur']:.2f} (calls: {breakdown['call_count']})",
        "",
    ]

    by_source = breakdown.get("by_source") or {}
    if by_source:
        lines.append("*By source:*")
        for src, row in by_source.items():
            lines.append(f"  • {src}: €{float(row.get('cost', 0)):.2f}")
        lines.append("")

    by_matter = breakdown.get("by_matter") or {}
    if by_matter:
        lines.append("*By matter (where attributed):*")
        for matter, row in by_matter.items():
            lines.append(f"  • {matter}: €{float(row.get('cost', 0)):.2f}")
        lines.append("")

    by_model = breakdown.get("by_model") or {}
    if by_model:
        lines.append("*By model:*")
        for model, row in by_model.items():
            lines.append(f"  • {model}: €{float(row.get('cost', 0)):.2f}")

    msg = "\n".join(lines)

    try:
        import requests
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if not slack_token:
            logger.warning("No SLACK_BOT_TOKEN — daily summary not posted to Slack")
            return breakdown
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {slack_token}"},
            json={"channel": "#cockpit", "text": msg},
            timeout=5,
        )
        logger.info(f"daily_cost_summary posted to #cockpit for {day}")
    except Exception as e:
        logger.warning(f"Could not post daily_cost_summary: {e}")

    return breakdown
