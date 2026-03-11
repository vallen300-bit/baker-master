"""
Cost Monitor — Phase 4A
Tracks API costs per call, aggregates daily, circuit breaker at €15/€100.

Usage:
    from orchestrator.cost_monitor import log_api_cost, check_circuit_breaker

    # Before each API call:
    allowed, daily_cost = check_circuit_breaker()
    if not allowed:
        return  # hard-stopped

    # After each API call:
    log_api_cost(model, input_tokens, output_tokens, source="agent_loop")
"""
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional, Tuple

logger = logging.getLogger("baker.cost_monitor")

# Model costs (USD per million tokens) — Anthropic pricing 2025
MODEL_COSTS = {
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
}
DEFAULT_COSTS = {"input": 15.00, "output": 75.00}

# EUR/USD conversion rate (approximate)
USD_TO_EUR = float(os.getenv("BAKER_USD_TO_EUR", "0.92"))

# Thresholds (EUR/day) — raised Session 21 (€15 was too noisy)
COST_ALERT_EUR = float(os.getenv("BAKER_COST_ALERT_EUR", "50.0"))
COST_HARD_STOP_EUR = float(os.getenv("BAKER_COST_HARD_STOP_EUR", "100.0"))

# Track if alert was already sent today (avoid spamming)
_alert_sent_date = None
_hard_stop_sent_date = None


# ─────────────────────────────────────────────
# Table DDL
# ─────────────────────────────────────────────

def ensure_api_cost_log_table(conn):
    """Create api_cost_log table. Called from store_back.__init__."""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS api_cost_log (
                id SERIAL PRIMARY KEY,
                logged_at TIMESTAMPTZ DEFAULT NOW(),
                model TEXT NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_eur NUMERIC(10,6) DEFAULT 0,
                source TEXT,
                capability_id TEXT,
                task_id TEXT
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_cost_log_logged_at
            ON api_cost_log (logged_at)
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


# ─────────────────────────────────────────────
# Cost Calculation
# ─────────────────────────────────────────────

def calculate_cost_eur(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in EUR for a given API call."""
    costs = MODEL_COSTS.get(model, DEFAULT_COSTS)
    cost_usd = (
        (input_tokens / 1_000_000) * costs["input"]
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
) -> Optional[float]:
    """Log an API call cost. Returns cost in EUR or None on failure."""
    cost_eur = calculate_cost_eur(model, input_tokens, output_tokens)
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
                   (model, input_tokens, output_tokens, cost_eur, source, capability_id, task_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (model, input_tokens, output_tokens, cost_eur, source, capability_id, task_id),
            )
            conn.commit()
            cur.close()
            logger.debug(
                f"Cost: {model} {input_tokens}in/{output_tokens}out "
                f"= €{cost_eur:.4f} [{source}]"
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
    """Get cost breakdown by model and source for a given day."""
    import psycopg2.extras

    if day is None:
        day = datetime.now(timezone.utc).date()
    result = {"date": str(day), "total_eur": 0.0, "total_input_tokens": 0,
              "total_output_tokens": 0, "call_count": 0,
              "by_model": {}, "by_source": {},
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
                   WHERE logged_at > NOW() - INTERVAL '%s days'
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
# Circuit Breaker
# ─────────────────────────────────────────────

def check_circuit_breaker() -> Tuple[bool, float]:
    """Check if API calls should be allowed.
    Returns (allowed: bool, daily_cost_eur: float).
    Sends alert at €15/day, hard-stops at €100/day.
    """
    global _alert_sent_date, _hard_stop_sent_date
    today = datetime.now(timezone.utc).date()
    daily_cost = get_daily_cost(today)

    # Hard stop
    if daily_cost >= COST_HARD_STOP_EUR:
        if _hard_stop_sent_date != today:
            _hard_stop_sent_date = today
            _send_cost_alert(daily_cost, hard_stop=True)
        logger.error(f"COST HARD STOP: €{daily_cost:.2f} >= €{COST_HARD_STOP_EUR:.2f}")
        return False, daily_cost

    # Soft alert
    if daily_cost >= COST_ALERT_EUR:
        if _alert_sent_date != today:
            _alert_sent_date = today
            _send_cost_alert(daily_cost, hard_stop=False)
        logger.warning(f"Cost alert: €{daily_cost:.2f} >= €{COST_ALERT_EUR:.2f}")

    return True, daily_cost


def _send_cost_alert(daily_cost: float, hard_stop: bool = False):
    """Send cost alert via Slack (direct HTTP — no LLM call needed)."""
    try:
        import requests
        slack_token = os.getenv("SLACK_BOT_TOKEN")
        if not slack_token:
            logger.warning("No SLACK_BOT_TOKEN — cannot send cost alert")
            return

        if hard_stop:
            msg = (
                f":octagonal_sign: *Baker HARD STOP*\n"
                f"Daily API spend: *€{daily_cost:.2f}* — ALL API CALLS BLOCKED\n"
                f"Threshold: €{COST_HARD_STOP_EUR:.2f}\n"
                f"Baker will resume tomorrow. Override: set BAKER_COST_HARD_STOP_EUR higher."
            )
        else:
            msg = (
                f":warning: *Baker Cost Alert*\n"
                f"Daily API spend: *€{daily_cost:.2f}* (threshold: €{COST_ALERT_EUR:.2f})\n"
                f"Hard stop at: €{COST_HARD_STOP_EUR:.2f}"
            )

        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {slack_token}"},
            json={"channel": "#cockpit", "text": msg},
            timeout=5,
        )
        logger.info(f"Cost alert sent to Slack: €{daily_cost:.2f} (hard_stop={hard_stop})")
    except Exception as e:
        logger.warning(f"Could not send cost alert: {e}")

    # WhatsApp cost alerts REMOVED (Director decision, Session 21 — noisy, not helpful).
    # Slack alert above is sufficient. Hard stop still blocks API calls.
