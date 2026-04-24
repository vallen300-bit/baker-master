"""BRIEF_PROACTIVE_PM_SENTINEL_1: proactive quiet-thread sentinel + dismiss-pattern surface.

Two public entry points invoked by APScheduler:
  - detect_quiet_threads()     — every 30 min (respects alerts.snoozed_until)
  - detect_dismiss_patterns()  — every 6 h  (14-day rolling aggregation)

Non-fatal. Writes to scheduler_executions via the existing listener + to
alerts via _record_alert(). No LLM calls. Singleton access only.

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
        # LEFT-anti-join to alerts filters out threads with an active snooze window.
        # Cast t.thread_id (UUID) to text to match alerts.source_id (TEXT).
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
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"detect_quiet_threads query failed: {e}")
        return result
    finally:
        store._put_conn(conn)

    # Telemetry: count snooze-skipped threads. Second query scoped tight —
    # cheap (indexed source + snoozed_until filter).
    result["snoozed_skipped"] = _count_active_snoozes(store)

    for t in threads:
        result["checked"] += 1
        try:
            sla = t["sla_hours"] or PM_SLA_DEFAULT_HOURS.get(
                t["pm_slug"], PM_SLA_FALLBACK_HOURS
            )
            last = t["last_turn_at"]
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            hours_silent = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
            if hours_silent < sla:
                continue

            if _already_alerted_recently(
                store, "quiet_thread", str(t["thread_id"]),
                QUIET_ALERT_COOLDOWN_HOURS,
            ):
                continue

            text = _format_quiet_thread_alert(t, hours_silent, sla)
            pushed = _slack_push(DIRECTOR_DM_CHANNEL, text)
            _record_alert(
                store,
                source="proactive_pm_sentinel",
                source_id=str(t["thread_id"]),
                tier=2,
                title=f"Quiet thread [{t['pm_slug']}]: {(t['topic_summary'] or '')[:80]}",
                body=text,
                matter_slug=t["pm_slug"],
                structured={
                    "trigger": "quiet_thread",
                    "hours_silent": round(hours_silent, 1),
                    "sla_hours": sla,
                    "slack_push_ok": bool(pushed),
                },
            )
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
        try:
            conn.rollback()
        except Exception:
            pass
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
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"detect_dismiss_patterns query failed: {e}")
        return result
    finally:
        store._put_conn(conn)

    for p in patterns:
        result["patterns_checked"] += 1
        try:
            pattern_key = f"{p['pm_slug']}::{p['dismiss_reason']}"
            if _pattern_already_surfaced(
                store, pattern_key, DISMISS_PATTERN_COOLDOWN_DAYS
            ):
                continue
            text = _format_dismiss_pattern_surface(p)
            pushed = _slack_push(DIRECTOR_DM_CHANNEL, text)
            _record_alert(
                store,
                source="proactive_pm_sentinel",
                source_id=f"pattern::{pattern_key}",
                tier=3,
                title=f"Dismiss pattern [{p['pm_slug']}]: {p['dismiss_reason']} ×{p['n']}",
                body=text,
                matter_slug=p["pm_slug"],
                structured={
                    "trigger": "dismiss_pattern",
                    "pm_slug": p["pm_slug"],
                    "dismiss_reason": p["dismiss_reason"],
                    "count": int(p["n"]),
                    "window_days": DISMISS_PATTERN_WINDOW_DAYS,
                    "slack_push_ok": bool(pushed),
                },
            )
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
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_pattern_already_surfaced: {e}")
        return False
    finally:
        store._put_conn(conn)


def _format_dismiss_pattern_surface(pattern: dict) -> str:
    pm_label = pattern["pm_slug"].upper().replace("_", " ")
    reason = pattern["dismiss_reason"].replace("_", " ")
    n = int(pattern["n"])
    suggestion = _suggestion_for_pattern(
        pattern["pm_slug"], pattern["dismiss_reason"], n
    )
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
        proposed = max(cur * 3 // 2, cur + 24)
        return (
            f"Extend `{pm_slug}` default SLA from {cur}h → {proposed}h, "
            f"OR add per-thread `sla_hours={proposed}` for the dominant waiting threads."
        )
    if reason == "already_handled_offline":
        return (
            f"Consider adding an ingest-signal for the offline channel you're "
            f"using (WhatsApp? phone?) so threads auto-receive a turn when you "
            f"handle them offline. Else raise `{pm_slug}` SLA."
        )
    if reason == "low_priority":
        return (
            f"Raise `{pm_slug}` default SLA (currently {cur}h) OR raise the "
            f"`last_turn_at < NOW() - INTERVAL '6 hours'` floor in the sentinel — "
            f"consider {cur * 2}h floor before flagging."
        )
    if reason == "wrong_thread":
        return (
            "Stitcher miscategorized ≥10 turns. Review `capability_turns.stitch_decision` "
            "for the affected rows (high `alternatives` confidence gaps) and consider "
            "lowering `STITCH_MIN_COSINE` threshold in `orchestrator/capability_threads.py`."
        )
    return "No automated suggestion; investigate pattern manually."


# ─── Shared helpers ───

def _slack_push(channel_id: str, text: str) -> bool:
    try:
        from outputs.slack_notifier import post_to_channel
        return bool(post_to_channel(channel_id=channel_id, text=text))
    except Exception as e:
        logger.warning(f"_slack_push failed: {e}")
        return False


def _already_alerted_recently(
    store, trigger: str, source_id: str, cooldown_hours: int
) -> bool:
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
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_already_alerted_recently: {e}")
        return False
    finally:
        store._put_conn(conn)


def _record_alert(
    store,
    source: str,
    source_id: str,
    tier: int,
    title: str,
    body: str,
    matter_slug: Optional[str],
    structured: dict,
) -> None:
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
            (
                source, source_id, tier, title[:500], body[:4000], matter_slug,
                json.dumps(structured, default=str),
            ),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_record_alert failed: {e}")
    finally:
        store._put_conn(conn)
