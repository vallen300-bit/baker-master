"""
Sentinel Health Monitor — tracks poll success/failure for every sentinel trigger.

Status logic:
  healthy  — consecutive_failures = 0
  degraded — 1-2 failures
  down     — 3+ failures
  unknown  — never polled

Fires T1 alert when a sentinel transitions to 'down' (3 consecutive failures).
Fires T2 recovery alert when a previously-down sentinel succeeds.
Checks for all-sentinels-down scenario on every failure.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("sentinel.health")

# ─────────────────────────────────────────────
# Table DDL — called on first DB access
# ─────────────────────────────────────────────

_table_ensured = False


def _ensure_table(conn):
    """Create sentinel_health table if missing. Called once per process."""
    global _table_ensured
    if _table_ensured:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_health (
                source              TEXT PRIMARY KEY,
                last_success_at     TIMESTAMPTZ,
                last_error_at       TIMESTAMPTZ,
                last_error_msg      TEXT,
                consecutive_failures INT DEFAULT 0,
                status              TEXT DEFAULT 'unknown',
                last_alerted_at     TIMESTAMPTZ,
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        _table_ensured = True
        logger.info("sentinel_health table verified")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"sentinel_health table creation failed (non-fatal): {e}")


def _get_conn():
    """Get a DB connection from the global store pool."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    return store._get_conn(), store


def _put_conn(store, conn):
    """Return connection to pool."""
    store._put_conn(conn)


def _status_for_failures(n: int) -> str:
    if n == 0:
        return "healthy"
    elif n <= 2:
        return "degraded"
    else:
        return "down"


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def report_success(source: str):
    """Called after a successful poll. Resets failure count. Fires recovery alert if was down."""
    conn, store = _get_conn()
    if not conn:
        return
    try:
        _ensure_table(conn)
        cur = conn.cursor()

        # Read previous state
        cur.execute("SELECT status FROM sentinel_health WHERE source = %s", (source,))
        row = cur.fetchone()
        prev_status = row[0] if row else "unknown"

        # Upsert to healthy
        cur.execute("""
            INSERT INTO sentinel_health (source, last_success_at, consecutive_failures, status, updated_at)
            VALUES (%s, NOW(), 0, 'healthy', NOW())
            ON CONFLICT (source) DO UPDATE SET
                last_success_at = NOW(),
                consecutive_failures = 0,
                status = 'healthy',
                updated_at = NOW()
        """, (source,))
        conn.commit()
        cur.close()

        # Recovery alert if was down
        if prev_status == "down":
            _fire_recovery_alert(source)

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"report_success({source}) failed: {e}")
    finally:
        _put_conn(store, conn)


def report_failure(source: str, error: str):
    """Called after a failed poll. Increments failure count. Fires alert at 3."""
    conn, store = _get_conn()
    if not conn:
        return
    try:
        _ensure_table(conn)
        cur = conn.cursor()

        # Read previous state
        cur.execute(
            "SELECT status, consecutive_failures, last_alerted_at FROM sentinel_health WHERE source = %s",
            (source,),
        )
        row = cur.fetchone()
        prev_status = row[0] if row else "unknown"
        prev_failures = row[1] if row else 0
        last_alerted = row[2] if row else None

        new_failures = prev_failures + 1
        new_status = _status_for_failures(new_failures)

        # Truncate error message
        error_msg = (error or "")[:500]

        # Upsert
        cur.execute("""
            INSERT INTO sentinel_health (source, last_error_at, last_error_msg, consecutive_failures, status, updated_at)
            VALUES (%s, NOW(), %s, %s, %s, NOW())
            ON CONFLICT (source) DO UPDATE SET
                last_error_at = NOW(),
                last_error_msg = %s,
                consecutive_failures = %s,
                status = %s,
                updated_at = NOW()
        """, (source, error_msg, new_failures, new_status,
              error_msg, new_failures, new_status))
        conn.commit()
        cur.close()

        # Fire T1 alert on transition to down (3 failures)
        if new_status == "down" and prev_status != "down":
            _fire_down_alert(source, new_failures, error_msg)
        elif new_status == "down" and last_alerted:
            # Re-alert if still down after 24h
            hours_since = (datetime.now(timezone.utc) - last_alerted).total_seconds() / 3600
            if hours_since >= 24:
                _fire_down_alert(source, new_failures, error_msg)

        # H6: Check if ALL sentinels are down
        if new_status == "down":
            _check_all_down()

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"report_failure({source}) failed: {e}")
    finally:
        _put_conn(store, conn)


# ─────────────────────────────────────────────
# Alert helpers
# ─────────────────────────────────────────────

def _fire_down_alert(source: str, failures: int, error_msg: str):
    """Fire T1 alert when sentinel goes down."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        # Get last_success_at for the message
        conn = store._get_conn()
        last_success = "unknown"
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT last_success_at FROM sentinel_health WHERE source = %s", (source,))
                row = cur.fetchone()
                if row and row[0]:
                    last_success = row[0].isoformat()
                # Update last_alerted_at
                cur.execute(
                    "UPDATE sentinel_health SET last_alerted_at = NOW() WHERE source = %s",
                    (source,),
                )
                conn.commit()
                cur.close()
            finally:
                store._put_conn(conn)

        title = f"SENTINEL DOWN: {source}"
        body = (
            f"Failed {failures}x since {last_success}\n"
            f"Last error: {error_msg}"
        )
        # T2 not T1 — infrastructure alerts shouldn't consume T1 budget
        # or push to Director channels. Dashboard + Slack visibility is sufficient.
        store.create_alert(
            tier=2,
            title=title,
            body=body,
            source="sentinel_health",
            source_id=f"sentinel_down_{source}",
        )
        logger.warning(f"SENTINEL DOWN alert fired for {source}")
    except Exception as e:
        logger.error(f"Failed to fire down alert for {source}: {e}")


def _fire_recovery_alert(source: str):
    """Fire T2 recovery alert when sentinel comes back."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        store.create_alert(
            tier=2,
            title=f"SENTINEL RECOVERED: {source}",
            body=f"{source} — was down, now healthy.",
            source="sentinel_health",
            source_id=f"sentinel_recovered_{source}",
        )
        logger.info(f"SENTINEL RECOVERED alert fired for {source}")
    except Exception as e:
        logger.error(f"Failed to fire recovery alert for {source}: {e}")


def _check_all_down():
    """H6: If ALL tracked sentinels are down, fire critical alert."""
    conn, store = _get_conn()
    if not conn:
        return
    try:
        _ensure_table(conn)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sentinel_health WHERE status IN ('healthy', 'degraded')")
        healthy_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM sentinel_health")
        total = cur.fetchone()[0]
        cur.close()

        if total > 0 and healthy_count == 0:
            from memory.store_back import SentinelStoreBack
            s = SentinelStoreBack._get_global_instance()
            s.create_alert(
                tier=1,
                title="ALL SENTINELS DOWN",
                body="Baker may be disconnected from DB or missing env vars. All tracked sentinels report failures.",
                source="sentinel_health",
                source_id="all_sentinels_down",
            )
            logger.critical("ALL SENTINELS DOWN — alert fired")
    except Exception as e:
        logger.warning(f"_check_all_down failed: {e}")
    finally:
        _put_conn(store, conn)


# ─────────────────────────────────────────────
# Circuit Breaker (H2)
# ─────────────────────────────────────────────

_CIRCUIT_BREAKER_THRESHOLD = 20


def should_skip_poll(source: str) -> bool:
    """Check if a sentinel should skip its poll cycle.

    Returns True if:
    - status == 'disabled' (manually disabled by PM/Director)
    - consecutive_failures >= 20 (circuit breaker — prevents memory-leaking retry loops)

    Call this at the top of every trigger's run function.
    """
    conn, store = _get_conn()
    if not conn:
        return False  # fail open — allow poll if DB is unreachable
    try:
        _ensure_table(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT status, consecutive_failures FROM sentinel_health WHERE source = %s",
            (source,),
        )
        row = cur.fetchone()
        cur.close()

        if not row:
            return False  # no record yet — allow first poll

        status, failures = row[0], row[1] or 0

        if status == "disabled":
            logger.info(f"Sentinel {source}: DISABLED — skipping poll")
            return True

        if failures >= _CIRCUIT_BREAKER_THRESHOLD:
            # G5: Auto-recovery — if circuit breaker open >1 hour, reset and try once
            from datetime import datetime, timezone, timedelta
            cur2 = conn.cursor()
            cur2.execute(
                "SELECT last_error_at FROM sentinel_health WHERE source = %s",
                (source,),
            )
            err_row = cur2.fetchone()
            cur2.close()
            if err_row and err_row[0]:
                age = datetime.now(timezone.utc) - err_row[0].replace(tzinfo=timezone.utc) if err_row[0].tzinfo is None else datetime.now(timezone.utc) - err_row[0]
                if age > timedelta(hours=1):
                    # Auto-reset: the underlying issue likely resolved
                    logger.info(
                        f"Sentinel {source}: circuit breaker auto-recovery — "
                        f"open for {age.total_seconds()/3600:.1f}h, resetting to allow retry"
                    )
                    reset_sentinel(source)
                    return False  # allow this poll to proceed

            logger.warning(
                f"Sentinel {source}: circuit breaker OPEN ({failures} consecutive failures) — skipping poll"
            )
            return True

        return False
    except Exception as e:
        logger.warning(f"should_skip_poll({source}) check failed (allowing poll): {e}")
        return False
    finally:
        _put_conn(store, conn)


# ─────────────────────────────────────────────
# Stale Watermark Detector (SENTINEL-SAFETY-1)
# ─────────────────────────────────────────────

# Expected max age (hours) per trigger source before it's flagged stale
_WATERMARK_MAX_AGE = {
    "email_poll": 2,         # polls every 5 min
    "fireflies": 48,         # polls every 15 min, but may have no new data
    "todoist": 2,            # polls every 5 min
    "dropbox": 6,            # polls every 5 min
    "slack": 2,              # polls every 5 min
    "whatsapp_resync": 12,   # WAHA-HEALTH-FIXES-1: re-syncs every 6h, 12h max tolerable
    "exchange_poll": 2,      # EXCHANGE-IMAP-POLL-1: polls every 5 min, 2h max tolerable
}

# ClickUp workspaces — all should advance within 2 hours
_CLICKUP_WORKSPACE_IDS = ["2652545", "24368967", "24382372", "24382764", "24385290", "9004065517"]


def check_stale_watermarks():
    """SENTINEL-SAFETY-1: Check trigger_watermarks for sources that haven't
    advanced in longer than expected. Fires a T2 alert per stale source.
    Run every 6 hours."""
    conn, store = _get_conn()
    if not conn:
        return
    try:
        import psycopg2.extras
        _ensure_table(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        now = datetime.now(timezone.utc)
        stale_sources = []

        # Check named sources
        for source, max_hours in _WATERMARK_MAX_AGE.items():
            cur.execute(
                "SELECT last_seen, updated_at FROM trigger_watermarks WHERE source = %s",
                (source,),
            )
            row = cur.fetchone()
            if not row:
                continue  # source never ran — separate issue
            last_seen = row["last_seen"]
            if last_seen and last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if last_seen:
                hours_stale = (now - last_seen).total_seconds() / 3600
                if hours_stale > max_hours:
                    stale_sources.append({
                        "source": source,
                        "last_seen": last_seen.isoformat(),
                        "hours_stale": round(hours_stale, 1),
                        "max_hours": max_hours,
                    })

        # Check ClickUp workspaces
        for ws_id in _CLICKUP_WORKSPACE_IDS:
            source = f"clickup_{ws_id}"
            cur.execute(
                "SELECT last_seen FROM trigger_watermarks WHERE source = %s",
                (source,),
            )
            row = cur.fetchone()
            if not row or not row["last_seen"]:
                continue
            last_seen = row["last_seen"]
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            hours_stale = (now - last_seen).total_seconds() / 3600
            if hours_stale > 24:  # ClickUp should advance at least daily
                stale_sources.append({
                    "source": source,
                    "last_seen": last_seen.isoformat(),
                    "hours_stale": round(hours_stale, 1),
                    "max_hours": 24,
                })

        cur.close()

        if not stale_sources:
            logger.info("Stale watermark check: all sources fresh")
            return

        # Fire one alert per stale source (with dedup via source_id)
        for s in stale_sources:
            alert_id = f"stale_watermark_{s['source']}"
            title = f"STALE DATA: {s['source']} — no new data for {s['hours_stale']}h"
            body = (
                f"Source: {s['source']}\n"
                f"Last data: {s['last_seen']}\n"
                f"Expected max gap: {s['max_hours']}h\n"
                f"Actual gap: {s['hours_stale']}h\n\n"
                f"Likely cause: missing API key, expired credentials, or upstream API down.\n"
                f"Check Render env vars and sentinel_health table."
            )
            try:
                from memory.store_back import SentinelStoreBack
                st = SentinelStoreBack._get_global_instance()
                st.create_alert(
                    tier=2,
                    title=title,
                    body=body,
                    source="sentinel_health",
                    source_id=alert_id,
                )
                logger.warning(f"STALE WATERMARK alert: {s['source']} ({s['hours_stale']}h)")
            except Exception as e:
                logger.error(f"Failed to fire stale watermark alert for {s['source']}: {e}")

    except Exception as e:
        logger.warning(f"check_stale_watermarks failed: {e}")
    finally:
        _put_conn(store, conn)


# ─────────────────────────────────────────────
# Read API (for dashboard)
# ─────────────────────────────────────────────

def get_all_sentinel_health() -> list:
    """Return all sentinel health rows. Used by /api/sentinel-health endpoint."""
    conn, store = _get_conn()
    if not conn:
        return []
    try:
        import psycopg2.extras
        _ensure_table(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT source, status, last_success_at, last_error_at,
                   last_error_msg, consecutive_failures, updated_at
            FROM sentinel_health
            ORDER BY source
        """)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        logger.warning(f"get_all_sentinel_health failed: {e}")
        return []
    finally:
        _put_conn(store, conn)


def reset_sentinel(source: str) -> bool:
    """Reset a sentinel's circuit breaker — clear failures, set status to 'healthy'.
    Returns True on success."""
    conn, store = _get_conn()
    if not conn:
        return False
    try:
        _ensure_table(conn)
        cur = conn.cursor()
        cur.execute("""
            UPDATE sentinel_health
            SET consecutive_failures = 0, status = 'healthy', last_error_msg = NULL, updated_at = NOW()
            WHERE source = %s
        """, (source,))
        conn.commit()
        affected = cur.rowcount
        cur.close()
        if affected:
            logger.info(f"Sentinel {source}: circuit breaker RESET by operator")
        return affected > 0
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"reset_sentinel({source}) failed: {e}")
        return False
    finally:
        _put_conn(store, conn)


# ─────────────────────────────────────────────
# G5: WhatsApp Health Watchdog (Session 27)
# ─────────────────────────────────────────────

def run_health_watchdog():
    """G5: Check sentinel health and alert Director via WhatsApp if any source
    has been down for >2 hours. Runs every 2 hours via scheduler.

    This is the "Baker watching itself" safety net — if the circuit breaker
    auto-recovery doesn't fix things, the Director gets a WhatsApp message.
    """
    conn, store = _get_conn()
    if not conn:
        return

    try:
        import psycopg2.extras
        _ensure_table(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT source, status, consecutive_failures, last_error_at, last_error_msg
            FROM sentinel_health
            WHERE status = 'down'
              AND last_error_at < NOW() - INTERVAL '2 hours'
        """)
        stuck = [dict(r) for r in cur.fetchall()]
        cur.close()

        if not stuck:
            logger.info("Health watchdog: all sentinels healthy or recovering")
            return

        # Build WhatsApp alert message
        lines = [f"Baker Health Alert — {len(stuck)} sentinel(s) stuck down:\n"]
        for s in stuck:
            src = s["source"]
            failures = s.get("consecutive_failures", 0)
            err = (s.get("last_error_msg") or "")[:100]
            lines.append(f"- {src}: {failures} failures. {err}")
        lines.append(f"\nReset via: POST /api/sentinel-health/SOURCE/reset")
        message = "\n".join(lines)

        # Send via WAHA
        try:
            from outputs.whatsapp_sender import send_whatsapp
            send_whatsapp(message)
            logger.warning(f"Health watchdog: WhatsApp alert sent — {len(stuck)} stuck sentinels")
        except Exception as wa_err:
            logger.error(f"Health watchdog: WhatsApp send failed: {wa_err}")
            # Fallback: create a T1 alert in the dashboard
            try:
                from memory.store_back import SentinelStoreBack
                st = SentinelStoreBack._get_global_instance()
                st.create_alert(
                    tier=1,
                    title=f"SENTINEL WATCHDOG: {len(stuck)} source(s) stuck down >2h",
                    body=message,
                    source="sentinel_health",
                    source_id=f"watchdog-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H')}",
                )
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Health watchdog failed: {e}")
    finally:
        _put_conn(store, conn)


def check_waha_silence():
    """WAHA-SILENT-GUARD-1: Detect if no inbound WhatsApp messages in 4+ hours
    during business hours (06:00-22:00 UTC, roughly 08:00-00:00 CET).

    Fires T1 alert if silent. Skips overnight (low message volume is normal).
    """
    now = datetime.now(timezone.utc)
    hour_utc = now.hour

    # Only check during business hours (06:00-22:00 UTC = 08:00-00:00 CET)
    if hour_utc < 6 or hour_utc >= 22:
        logger.debug("WAHA silence check: outside business hours, skipping")
        return

    conn, store = _get_conn()
    if not conn:
        return

    try:
        _ensure_table(conn)
        cur = conn.cursor()

        # Check latest INBOUND message (not Baker's own outbound alerts)
        cur.execute("""
            SELECT MAX(timestamp) FROM whatsapp_messages
            WHERE is_director = false
            LIMIT 1
        """)
        row = cur.fetchone()
        latest_inbound = row[0] if row and row[0] else None
        cur.close()

        if latest_inbound is None:
            logger.warning("WAHA silence check: no inbound messages ever recorded")
            return

        # Calculate age
        if latest_inbound.tzinfo is None:
            latest_inbound = latest_inbound.replace(tzinfo=timezone.utc)

        age_hours = (now - latest_inbound).total_seconds() / 3600

        if age_hours > 4:
            alert_msg = (
                f"No inbound WhatsApp messages in {age_hours:.1f} hours. "
                f"Last inbound: {latest_inbound.strftime('%Y-%m-%d %H:%M UTC')}. "
                f"WAHA session may be dead. "
                f"Check: https://baker-waha.onrender.com/#/sessions/default"
            )
            logger.warning(f"WAHA silence detected: {alert_msg}")

            # Report failure to sentinel health
            report_failure("waha_silence", f"No inbound messages in {age_hours:.1f}h")

            # T1 alert
            try:
                from memory.store_back import SentinelStoreBack
                st = SentinelStoreBack._get_global_instance()
                st.create_alert(
                    tier=1,
                    title="WAHA SILENT — no inbound WhatsApp messages",
                    body=alert_msg,
                    source="waha_silence",
                    source_id=f"silence-{now.strftime('%Y%m%d-%H')}",
                )
            except Exception:
                pass

            # Try WhatsApp (may fail if session dead — falls through to dashboard alert)
            try:
                from outputs.whatsapp_sender import send_whatsapp
                send_whatsapp(f"*WAHA SILENT*\n\n{alert_msg}")
            except Exception:
                pass
        else:
            # Healthy — clear any previous silence failure
            report_success("waha_silence")
            logger.debug(f"WAHA silence check: last inbound {age_hours:.1f}h ago — OK")

    except Exception as e:
        logger.error(f"WAHA silence check failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(store, conn)


def poll_waha_session():
    """WAHA-SILENT-GUARD-1: Actively poll WAHA session status every 30 min.
    Catches session death even when no messages are flowing.
    """
    try:
        from triggers.waha_client import get_session_status
        result = get_session_status()
    except Exception as e:
        logger.error(f"WAHA session poll: import/call failed: {e}")
        report_failure("waha_session_poll", str(e))
        return

    if "error" in result:
        error_msg = result["error"]
        logger.warning(f"WAHA session poll: error — {error_msg}")
        report_failure("waha_session_poll", error_msg)

        # T1 alert if WAHA is completely unreachable
        try:
            from memory.store_back import SentinelStoreBack
            st = SentinelStoreBack._get_global_instance()
            st.create_alert(
                tier=1,
                title="WAHA UNREACHABLE",
                body=f"Cannot reach WAHA API: {error_msg}. Check https://baker-waha.onrender.com",
                source="waha_session_poll",
                source_id=f"unreachable-{datetime.now(timezone.utc).strftime('%Y%m%d-%H')}",
            )
        except Exception:
            pass
        return

    status = result.get("status", "UNKNOWN")
    logger.info(f"WAHA session poll: status={status}")

    _HEALTHY = {"WORKING"}
    _DEAD = {"SCAN_QR_CODE", "STOPPED", "FAILED"}

    if status in _HEALTHY:
        report_success("waha_session_poll")
    elif status in _DEAD:
        report_failure("waha_session_poll", f"Session status: {status}")

        alert_msg = (
            f"WAHA session is {status}. Inbound WhatsApp messages are NOT being received.\n"
            f"Re-scan QR: https://baker-waha.onrender.com/#/sessions/default"
        )

        # T1 alert
        try:
            from memory.store_back import SentinelStoreBack
            st = SentinelStoreBack._get_global_instance()
            st.create_alert(
                tier=1,
                title=f"WAHA SESSION: {status}",
                body=alert_msg,
                source="waha_session_poll",
                source_id=f"poll-{status}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H')}",
            )
        except Exception:
            pass

        # Try WhatsApp (best effort)
        try:
            from outputs.whatsapp_sender import send_whatsapp
            send_whatsapp(f"*WAHA SESSION DOWN*\n\nStatus: {status}\n\n{alert_msg}")
        except Exception:
            pass
    else:
        # Unknown status — log but don't alert
        logger.warning(f"WAHA session poll: unexpected status '{status}'")
