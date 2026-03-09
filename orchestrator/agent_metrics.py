"""
Agent Metrics — Phase 4A
Logs every tool call with latency, tokens, success/fail for observability.

Usage:
    from orchestrator.agent_metrics import log_tool_call

    # After each tool execution:
    log_tool_call("search_memory", latency_ms=250, success=True, source="agent_loop")
"""
import logging
from datetime import datetime, timezone, date
from typing import Optional

logger = logging.getLogger("baker.agent_metrics")


# ─────────────────────────────────────────────
# Table DDL
# ─────────────────────────────────────────────

def ensure_agent_tool_calls_table(conn):
    """Create agent_tool_calls table. Called from store_back.__init__."""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_tool_calls (
                id SERIAL PRIMARY KEY,
                called_at TIMESTAMPTZ DEFAULT NOW(),
                tool_name TEXT NOT NULL,
                latency_ms INTEGER DEFAULT 0,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                success BOOLEAN DEFAULT TRUE,
                error_message TEXT,
                source TEXT,
                capability_id TEXT,
                task_id TEXT
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_called_at
            ON agent_tool_calls (called_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_tool
            ON agent_tool_calls (tool_name)
        """)
        conn.commit()
        cur.close()
        logger.info("agent_tool_calls table verified")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure agent_tool_calls table: {e}")


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

def log_tool_call(
    tool_name: str,
    latency_ms: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    success: bool = True,
    error_message: str = None,
    source: str = None,
    capability_id: str = None,
    task_id: str = None,
):
    """Log a single tool call to agent_tool_calls table."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO agent_tool_calls
                   (tool_name, latency_ms, input_tokens, output_tokens, success,
                    error_message, source, capability_id, task_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (tool_name, latency_ms, input_tokens, output_tokens, success,
                 error_message, source, capability_id, task_id),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not log tool call: {e}")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"Tool call logging failed (non-fatal): {e}")


# ─────────────────────────────────────────────
# Queries
# ─────────────────────────────────────────────

def get_tool_metrics(hours: int = 24) -> dict:
    """Get tool call metrics for the last N hours."""
    import psycopg2.extras

    result = {"hours": hours, "tools": [], "total_calls": 0, "avg_latency_ms": 0}
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return result
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT tool_name,
                          COUNT(*) as calls,
                          ROUND(AVG(latency_ms)) as avg_latency_ms,
                          MAX(latency_ms) as max_latency_ms,
                          SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                          SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failures
                   FROM agent_tool_calls
                   WHERE called_at > NOW() - make_interval(hours := %s)
                   GROUP BY tool_name
                   ORDER BY calls DESC""",
                (hours,),
            )
            tools = [dict(r) for r in cur.fetchall()]
            # Convert Decimal types
            for t in tools:
                t["avg_latency_ms"] = int(t["avg_latency_ms"] or 0)
                t["max_latency_ms"] = int(t["max_latency_ms"] or 0)
                t["successes"] = int(t["successes"] or 0)
                t["failures"] = int(t["failures"] or 0)
                t["calls"] = int(t["calls"])
            total_calls = sum(t["calls"] for t in tools)
            avg_lat = (
                sum(t["avg_latency_ms"] * t["calls"] for t in tools) / total_calls
                if total_calls else 0
            )
            result["tools"] = tools
            result["total_calls"] = total_calls
            result["avg_latency_ms"] = round(avg_lat)
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not get tool metrics: {e}")
        finally:
            store._put_conn(conn)
    except Exception:
        pass
    return result


def get_source_metrics(hours: int = 24) -> dict:
    """Get metrics grouped by source (agent_loop, capability_runner, pipeline)."""
    import psycopg2.extras

    result = {"hours": hours, "sources": []}
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return result
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT source,
                          COUNT(*) as calls,
                          ROUND(AVG(latency_ms)) as avg_latency_ms,
                          SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                          SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failures
                   FROM agent_tool_calls
                   WHERE called_at > NOW() - make_interval(hours := %s)
                   GROUP BY source
                   ORDER BY calls DESC""",
                (hours,),
            )
            sources = [dict(r) for r in cur.fetchall()]
            for s in sources:
                s["avg_latency_ms"] = int(s["avg_latency_ms"] or 0)
                s["successes"] = int(s["successes"] or 0)
                s["failures"] = int(s["failures"] or 0)
                s["calls"] = int(s["calls"])
            result["sources"] = sources
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not get source metrics: {e}")
        finally:
            store._put_conn(conn)
    except Exception:
        pass
    return result


def get_recent_errors(limit: int = 20) -> list:
    """Get recent tool call errors."""
    import psycopg2.extras

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT tool_name, called_at, latency_ms, error_message, source
                   FROM agent_tool_calls
                   WHERE NOT success
                   ORDER BY called_at DESC
                   LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
            cur.close()
            return [
                {**dict(r), "called_at": r["called_at"].isoformat() if r["called_at"] else None}
                for r in rows
            ]
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"Could not get recent errors: {e}")
            return []
        finally:
            store._put_conn(conn)
    except Exception:
        return []
