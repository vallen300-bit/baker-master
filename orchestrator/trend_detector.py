"""
F6: Trend Detection — Monthly Pattern Analysis

Runs monthly (1st of each month, 05:00 UTC). Analyzes the previous month's data
and produces a trend report covering:
- Alert volume and tier distribution vs previous month
- Contact activity (who's gone quiet, who's heating up)
- Cost trends (API spend by source)
- Matter activity (which matters are most active)
- Deadline compliance (met vs missed)

Report stored as deep_analysis + injected into next morning brief.
"""
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from config.settings import config

logger = logging.getLogger("baker.trend_detector")


def _query(sql: str, params: tuple = ()) -> list:
    """Execute a read query and return list of dicts."""
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql, params)
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Trend query failed: {e}")
        return []


def _get_alert_trends() -> dict:
    """Compare this month vs last month alert volumes."""
    rows = _query("""
        SELECT
            CASE WHEN created_at >= date_trunc('month', NOW()) THEN 'current'
                 ELSE 'previous' END as period,
            tier,
            COUNT(*) as cnt
        FROM alerts
        WHERE created_at >= date_trunc('month', NOW()) - INTERVAL '1 month'
        GROUP BY period, tier
        ORDER BY period, tier
    """)
    current = {r["tier"]: int(r["cnt"]) for r in rows if r["period"] == "current"}
    previous = {r["tier"]: int(r["cnt"]) for r in rows if r["period"] == "previous"}
    current_total = sum(current.values())
    previous_total = sum(previous.values())
    pct_change = ((current_total - previous_total) / previous_total * 100) if previous_total else 0
    return {
        "current_month": current,
        "previous_month": previous,
        "current_total": current_total,
        "previous_total": previous_total,
        "pct_change": round(pct_change, 1),
    }


def _get_contact_trends() -> dict:
    """Find contacts with significant activity changes."""
    # Contacts who were active last month but silent this month
    gone_quiet = _query("""
        SELECT vc.name, COUNT(ci.id) as last_month_count
        FROM vip_contacts vc
        JOIN contact_interactions ci ON ci.contact_id = vc.id
        WHERE ci.timestamp >= date_trunc('month', NOW()) - INTERVAL '1 month'
          AND ci.timestamp < date_trunc('month', NOW())
        GROUP BY vc.id, vc.name
        HAVING COUNT(ci.id) >= 3
           AND vc.id NOT IN (
               SELECT DISTINCT contact_id FROM contact_interactions
               WHERE timestamp >= date_trunc('month', NOW())
                 AND contact_id IS NOT NULL
           )
        ORDER BY last_month_count DESC
        LIMIT 5
    """)

    # Contacts with increased activity this month
    heating_up = _query("""
        WITH current AS (
            SELECT contact_id, COUNT(*) as cnt
            FROM contact_interactions
            WHERE timestamp >= date_trunc('month', NOW())
              AND contact_id IS NOT NULL
            GROUP BY contact_id
        ),
        previous AS (
            SELECT contact_id, COUNT(*) as cnt
            FROM contact_interactions
            WHERE timestamp >= date_trunc('month', NOW()) - INTERVAL '1 month'
              AND timestamp < date_trunc('month', NOW())
              AND contact_id IS NOT NULL
            GROUP BY contact_id
        )
        SELECT vc.name,
               COALESCE(c.cnt, 0) as current_count,
               COALESCE(p.cnt, 0) as previous_count
        FROM current c
        JOIN vip_contacts vc ON vc.id = c.contact_id
        LEFT JOIN previous p ON p.contact_id = c.contact_id
        WHERE COALESCE(c.cnt, 0) > COALESCE(p.cnt, 0) * 1.5
          AND COALESCE(c.cnt, 0) >= 3
        ORDER BY c.cnt DESC
        LIMIT 5
    """)

    return {
        "gone_quiet": [{"name": r["name"], "last_month": int(r["last_month_count"])} for r in gone_quiet],
        "heating_up": [{"name": r["name"], "current": int(r["current_count"]),
                        "previous": int(r["previous_count"])} for r in heating_up],
    }


def _get_cost_trends() -> dict:
    """Compare API costs this month vs last month."""
    rows = _query("""
        SELECT
            CASE WHEN logged_at >= date_trunc('month', NOW()) THEN 'current'
                 ELSE 'previous' END as period,
            model,
            COUNT(*) as calls,
            ROUND(SUM(cost_eur)::numeric, 2) as total_cost
        FROM api_cost_log
        WHERE logged_at >= date_trunc('month', NOW()) - INTERVAL '1 month'
        GROUP BY period, model
        ORDER BY period, total_cost DESC
    """)
    current = {r["model"]: {"calls": int(r["calls"]), "cost": float(r["total_cost"])}
               for r in rows if r["period"] == "current"}
    previous = {r["model"]: {"calls": int(r["calls"]), "cost": float(r["total_cost"])}
                for r in rows if r["period"] == "previous"}
    current_total = sum(v["cost"] for v in current.values())
    previous_total = sum(v["cost"] for v in previous.values())
    pct_change = ((current_total - previous_total) / previous_total * 100) if previous_total else 0
    return {
        "current_month": current,
        "previous_month": previous,
        "current_total_eur": round(current_total, 2),
        "previous_total_eur": round(previous_total, 2),
        "pct_change": round(pct_change, 1),
    }


def _get_matter_activity() -> list:
    """Most active matters this month by alert + interaction count."""
    return _query("""
        SELECT matter_slug,
               COUNT(DISTINCT id) as alert_count,
               MAX(created_at) as last_activity
        FROM alerts
        WHERE created_at >= date_trunc('month', NOW())
          AND matter_slug IS NOT NULL
        GROUP BY matter_slug
        ORDER BY alert_count DESC
        LIMIT 10
    """)


def _get_deadline_compliance() -> dict:
    """How many deadlines were met vs missed this month."""
    rows = _query("""
        SELECT
            CASE
                WHEN status = 'completed' THEN 'met'
                WHEN status = 'active' AND due_date < NOW() THEN 'overdue'
                WHEN status = 'active' THEN 'upcoming'
                WHEN status = 'dismissed' THEN 'dismissed'
                ELSE status
            END as outcome,
            COUNT(*) as cnt
        FROM deadlines
        WHERE due_date >= date_trunc('month', NOW())
          AND due_date < date_trunc('month', NOW()) + INTERVAL '1 month'
        GROUP BY outcome
    """)
    return {r["outcome"]: int(r["cnt"]) for r in rows}


def _format_trend_report(
    alerts: dict,
    contacts: dict,
    costs: dict,
    matters: list,
    deadlines: dict,
) -> str:
    """Format the trend data into a readable report."""
    now = datetime.now(timezone.utc)
    month_name = now.strftime("%B %Y")

    parts = [f"# Baker Monthly Trend Report — {month_name}\n"]

    # Alerts
    direction = "up" if alerts["pct_change"] > 0 else "down"
    parts.append(f"## Alerts")
    parts.append(
        f"**{alerts['current_total']}** alerts this month "
        f"({direction} {abs(alerts['pct_change'])}% from {alerts['previous_total']} last month)"
    )
    if alerts["current_month"]:
        tier_parts = []
        for tier in sorted(alerts["current_month"].keys()):
            tier_parts.append(f"T{tier}: {alerts['current_month'][tier]}")
        parts.append(f"Breakdown: {', '.join(tier_parts)}")

    # Contacts
    parts.append(f"\n## Contact Activity")
    if contacts["gone_quiet"]:
        parts.append("**Gone quiet** (active last month, silent this month):")
        for c in contacts["gone_quiet"]:
            parts.append(f"- {c['name']} ({c['last_month']} interactions last month → 0)")
    if contacts["heating_up"]:
        parts.append("**Heating up** (50%+ more activity):")
        for c in contacts["heating_up"]:
            parts.append(f"- {c['name']} ({c['previous']} → {c['current']} interactions)")
    if not contacts["gone_quiet"] and not contacts["heating_up"]:
        parts.append("No significant contact activity changes.")

    # Costs
    cost_dir = "up" if costs["pct_change"] > 0 else "down"
    parts.append(f"\n## API Costs")
    parts.append(
        f"**EUR {costs['current_total_eur']}** this month "
        f"({cost_dir} {abs(costs['pct_change'])}% from EUR {costs['previous_total_eur']})"
    )
    for model, data in costs.get("current_month", {}).items():
        parts.append(f"- {model}: {data['calls']} calls, EUR {data['cost']}")

    # Matters
    parts.append(f"\n## Matter Activity (Top 5)")
    for m in matters[:5]:
        parts.append(f"- **{m.get('matter_slug', '?')}**: {int(m.get('alert_count', 0))} alerts")

    # Deadlines
    parts.append(f"\n## Deadline Compliance")
    met = deadlines.get("met", 0)
    overdue = deadlines.get("overdue", 0)
    upcoming = deadlines.get("upcoming", 0)
    total = met + overdue + upcoming
    if total > 0:
        compliance_rate = round(met / total * 100) if total else 0
        parts.append(f"Met: {met} | Overdue: {overdue} | Upcoming: {upcoming} | Rate: {compliance_rate}%")
    else:
        parts.append("No deadlines due this month.")

    return "\n".join(parts)


# ─────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────

def run_trend_detection():
    """Monthly job: analyze trends and store report."""
    # Advisory lock
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT pg_try_advisory_xact_lock(8005)")
                got_lock = cur.fetchone()[0]
                cur.close()
                if not got_lock:
                    logger.info("Trend detection: another instance running, skipping")
                    return
            finally:
                store._put_conn(conn)
    except Exception:
        pass

    logger.info("Trend detection: starting monthly analysis...")
    t0 = time.time()

    # Gather data
    alerts = _get_alert_trends()
    contacts = _get_contact_trends()
    costs = _get_cost_trends()
    matters = _get_matter_activity()
    deadlines = _get_deadline_compliance()

    # Format report
    report = _format_trend_report(alerts, contacts, costs, matters, deadlines)

    # Store as deep analysis
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        now = datetime.now(timezone.utc)
        month_name = now.strftime("%B %Y")
        store.store_deep_analysis(
            topic=f"Monthly Trend Report — {month_name}",
            analysis_text=report,
            prompt="Automated monthly trend detection (F6)",
            source_documents="alerts, contact_interactions, api_cost_log, deadlines",
        )
        logger.info("Trend report stored as deep analysis")
    except Exception as e:
        logger.warning(f"Failed to store trend report: {e}")

    # Also create an alert so it shows in the Cockpit
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        now = datetime.now(timezone.utc)

        # Build summary for alert
        summary_parts = []
        if alerts["pct_change"] != 0:
            direction = "up" if alerts["pct_change"] > 0 else "down"
            summary_parts.append(f"Alerts {direction} {abs(alerts['pct_change'])}%")
        if costs["pct_change"] != 0:
            direction = "up" if costs["pct_change"] > 0 else "down"
            summary_parts.append(f"Costs {direction} {abs(costs['pct_change'])}%")
        if contacts["gone_quiet"]:
            names = ", ".join(c["name"] for c in contacts["gone_quiet"][:3])
            summary_parts.append(f"Gone quiet: {names}")

        title = f"Monthly Trends — {now.strftime('%B %Y')}: {'; '.join(summary_parts[:3])}"

        store.create_alert(
            tier=3,
            title=title[:120],
            body=report[:3000],
            action_required=False,
            tags=["trends", "monthly"],
            source="trend_detector",
            source_id=f"trend-{now.strftime('%Y-%m')}",
        )
    except Exception as e:
        logger.warning(f"Failed to create trend alert: {e}")

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(f"Trend detection complete ({elapsed_ms}ms)")
