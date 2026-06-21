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

# Alert dedup window — kept for Slack-push throttle semantics only. Card creation
# is now governed by upsert (one live card per thread), not this window.
QUIET_ALERT_COOLDOWN_HOURS = 24

# DASHBOARD_ALERT_NOISE_FIX_1 (Fix 1 + Fix 2).
# Quiet-thread families that the upsert / auto-resolve / sweep treat as one card
# per thread. 'quiet_thread' = counterparty spoke last (Director to-do, tier 2);
# 'awaiting_counterparty' = Director spoke last, demoted to tier 3 "Waiting on them".
QUIET_TRIGGERS = ("quiet_thread", "awaiting_counterparty")

# Canonical direction marker. capability_threads.topic_summary carries a structured
# prefix: outbound threads read "<channel>_outbound: Director outbound — ...",
# inbound threads read "<channel>: <Counterparty> — ...". This substring is the
# single reliable direction signal (the thread-builder has no direction column and
# no independent inbound/outbound input — verified 2026-06-20). 122/122 of the live
# Director-outbound cards match it.
OUTBOUND_MARKER = "director outbound"

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

    result = {
        "checked": 0, "alerted": 0, "snoozed_skipped": 0,
        "resolved_active": 0, "demoted_awaiting": 0, "refreshed": 0, "errors": 0,
    }

    # DASHBOARD_ALERT_NOISE_FIX_1 Fix 1: before scanning, auto-resolve quiet-thread
    # cards whose thread has since received a new turn (no longer quiet). This is
    # what stops the board from only ever growing. Non-fatal; never touches
    # acknowledged/snoozed cards.
    try:
        result["resolved_active"] = _auto_resolve_active_quiet_alerts(store)
    except Exception as e:
        logger.warning(f"detect_quiet_threads auto-resolve pass failed: {e}")

    conn = store._get_conn()
    if not conn:
        return result
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # LEFT-anti-join to alerts filters out threads with an active snooze window.
        # Cast t.thread_id (UUID) to text to match alerts.source_id (TEXT).
        cur.execute(
            """
            SELECT t.thread_id, t.pm_slug, t.topic_summary, t.last_turn_at,
                   t.sla_hours, t.last_turn_direction
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

            # Fix 2: if the Director sent the last turn, this is "waiting on the
            # counterparty", not a Director to-do. Demote to tier 3 (off the action
            # feed) — the card still exists, per Director ruling "demote, don't hide".
            topic = t.get("topic_summary") or ""
            # Fix 3 (ALERT_NOISE_FASTFOLLOW_1): prefer the durable
            # capability_threads.last_turn_direction column (fed at write-time from
            # the same @brisengroup.com direction signal that drives
            # contact_interactions.direction). Fall back to the OUTBOUND_MARKER
            # substring in topic_summary for old/un-rebuilt threads where the column
            # is still NULL — so the demote never regresses for un-migrated rows.
            _dir = (t.get("last_turn_direction") or "").lower()
            if _dir == "outbound":
                is_outbound = True
            elif _dir == "inbound":
                is_outbound = False
            else:
                is_outbound = OUTBOUND_MARKER in topic.lower()
            tier = 3 if is_outbound else 2
            trigger = "awaiting_counterparty" if is_outbound else "quiet_thread"

            text = _format_quiet_thread_alert(t, hours_silent, sla, awaiting=is_outbound)
            label = "Waiting on counterparty" if is_outbound else "Quiet thread"
            structured = {
                "trigger": trigger,
                "hours_silent": round(hours_silent, 1),
                "sla_hours": sla,
                "last_turn_direction": "outbound" if is_outbound else "inbound",
            }

            # Fix 1: upsert — one live card per thread. Refresh the existing pending
            # card instead of inserting a duplicate; never re-noise an acknowledged
            # thread (snoozed threads never reach here — anti-joined in the scan).
            op, _existing_sa = _upsert_quiet_alert(
                store,
                source_id=str(t["thread_id"]),
                tier=tier,
                title=f"{label} [{t['pm_slug']}]: {topic[:80]}",
                body=text,
                matter_slug=t["pm_slug"],
                structured=structured,
            )
            if op == "skipped_acknowledged":
                continue
            if op == "updated":
                result["refreshed"] += 1
            if is_outbound:
                # Demoted "waiting on them" cards are passive — no Director DM push.
                result["demoted_awaiting"] += 1
                continue

            # Slack-push throttle: push the Director DM only when a quiet episode is
            # first surfaced (a fresh card). Refreshes don't re-ping; auto-resolve
            # closes the card when the thread revives, so the next quiet episode is a
            # new INSERT that re-pushes. Tighter than the old 24h window, no spam.
            if op == "inserted":
                pushed = _slack_push(DIRECTOR_DM_CHANNEL, text)
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


def _format_quiet_thread_alert(
    thread: dict, hours_silent: float, sla: int, awaiting: bool = False
) -> str:
    topic = (thread.get("topic_summary") or "(no summary)")[:200]
    pm_label = thread["pm_slug"].upper().replace("_", " ")
    if awaiting:
        # Director spoke last — passive "waiting on the counterparty" card.
        return (
            f"*{pm_label} — waiting on counterparty*\n"
            f"Thread: {topic}\n"
            f"Director sent the last turn {hours_silent:.1f}h ago (SLA {sla}h); "
            f"awaiting their reply.\n"
            f"_Low priority — surfaced in 'Waiting on them', not the action feed._"
        )
    return (
        f"*{pm_label} quiet-thread alert*\n"
        f"Thread: {topic}\n"
        f"Silent for {hours_silent:.1f}h (SLA {sla}h).\n"
        f"_Accept / Snooze / Dismiss / Reject via dashboard sentinel feedback._"
    )


def _auto_resolve_active_quiet_alerts(store) -> int:
    """Fix 1: resolve pending quiet-thread cards whose thread has since received a
    new turn (no longer quiet).

    NEVER touches acknowledged or actively-snoozed cards. Bounded by the indexed
    `source` filter. Returns the count resolved; non-fatal.
    """
    conn = store._get_conn()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE alerts a
            SET status = 'resolved', exit_reason = 'thread_active_again', resolved_at = NOW()
            FROM capability_threads t
            WHERE a.source = 'proactive_pm_sentinel'
              AND a.structured_actions->>'trigger' IN ('quiet_thread', 'awaiting_counterparty')
              AND a.status = 'pending'
              AND a.acknowledged_at IS NULL
              AND (a.snoozed_until IS NULL OR a.snoozed_until <= NOW())
              AND t.thread_id::text = a.source_id
              AND t.last_turn_at > a.created_at
            """
        )
        n = cur.rowcount
        conn.commit()
        cur.close()
        return n if n and n > 0 else 0
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_auto_resolve_active_quiet_alerts failed: {e}")
        return 0
    finally:
        store._put_conn(conn)


def _upsert_quiet_alert(
    store,
    source_id: str,
    tier: int,
    title: str,
    body: str,
    matter_slug: Optional[str],
    structured: dict,
) -> tuple[str, Optional[dict]]:
    """Fix 1: one live quiet-thread card per thread.

    If a pending (un-acknowledged) quiet-family card already exists for this
    thread, UPDATE it in place (refresh body/tier/title/structured, bump
    created_at). Otherwise INSERT a fresh pending card — UNLESS the thread already
    has an acknowledged quiet card (the Director saw this episode; don't re-noise).

    Snoozed threads never reach here (the scan anti-joins active snoozes). Returns
    (op, existing_structured) where op ∈ {'inserted','updated','skipped_acknowledged','noop'}.
    """
    conn = store._get_conn()
    if not conn:
        return ("noop", None)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, structured_actions FROM alerts
            WHERE source = 'proactive_pm_sentinel'
              AND source_id = %s
              AND status = 'pending'
              AND acknowledged_at IS NULL
              AND (snoozed_until IS NULL OR snoozed_until <= NOW())
              AND structured_actions->>'trigger' IN ('quiet_thread', 'awaiting_counterparty')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (source_id,),
        )
        row = cur.fetchone()
        if row:
            existing_id = row[0]
            existing_sa = row[1] if isinstance(row[1], dict) else None
            # Fix 1 (ALERT_NOISE_FASTFOLLOW_1): TOCTOU guard. The SELECT above
            # filtered acknowledged/snoozed, but the Director could ack/snooze this
            # exact row in the window between SELECT and UPDATE. Re-assert the guard
            # in the UPDATE WHERE so we never refresh tier/title/body or bump
            # created_at on a row that became curated mid-call (which would
            # re-surface an acknowledged card). rowcount=0 → the row was curated in
            # the window: skip, do NOT fall through to INSERT (that would create the
            # duplicate this upsert exists to prevent).
            cur.execute(
                """
                UPDATE alerts
                SET tier = %s, title = %s, body = %s,
                    matter_slug = COALESCE(matter_slug, %s),
                    structured_actions = %s::jsonb,
                    created_at = NOW(), updated_at = NOW()
                WHERE id = %s
                  AND acknowledged_at IS NULL
                  AND (snoozed_until IS NULL OR snoozed_until <= NOW())
                """,
                (
                    tier, title[:500], body[:4000], matter_slug,
                    json.dumps(structured, default=str), existing_id,
                ),
            )
            updated = cur.rowcount
            conn.commit()
            cur.close()
            if updated == 0:
                return ("skipped_acknowledged", None)
            return ("updated", existing_sa)

        # No pending card. Respect a Director-curated card for the same thread —
        # never re-noise something acknowledged OR actively snoozed. Key on
        # acknowledged_at (not status), so a still-'pending' row that carries an
        # acknowledged_at timestamp is also honored (codex gate note, PR #398).
        cur.execute(
            """
            SELECT 1 FROM alerts
            WHERE source = 'proactive_pm_sentinel'
              AND source_id = %s
              AND structured_actions->>'trigger' IN ('quiet_thread', 'awaiting_counterparty')
              AND (acknowledged_at IS NOT NULL
                   OR (snoozed_until IS NOT NULL AND snoozed_until > NOW()))
            LIMIT 1
            """,
            (source_id,),
        )
        if cur.fetchone():
            cur.close()
            return ("skipped_acknowledged", None)

        # Fix 2 (ALERT_NOISE_FASTFOLLOW_1): race-proof dedup at the DB. The partial
        # unique index uq_alerts_pending_quiet (migration 20260621_alerts_uq_pending_quiet)
        # guarantees ≤1 pending quiet/awaiting card per (source, source_id, trigger).
        # If a concurrent sweep / second worker / restart-overlap inserts first, this
        # INSERT no-ops (rowcount=0) instead of raising — no duplicate, no Slack re-push.
        #
        # Arbiter is PINNED via index inference — the index column list + the exact
        # partial WHERE predicate — NOT a bare targetless `ON CONFLICT DO NOTHING`
        # (codex gate #3612): a targetless clause would swallow ANY future unique
        # violation on alerts, masking unrelated bugs. Inference instead fails loud
        # ("no unique constraint matching the ON CONFLICT specification") if this
        # index is ever dropped, and lets unrelated unique violations propagate.
        # NOTE: `ON CONFLICT ON CONSTRAINT uq_alerts_pending_quiet` (codex's literal
        # wording) is NOT usable here — uq_alerts_pending_quiet is a partial UNIQUE
        # INDEX, not a table CONSTRAINT; the ON CONSTRAINT form raises "constraint ...
        # does not exist" at runtime (verified empirically). A partial index can only
        # be inferred by (columns) + WHERE predicate. Same arbiter, same fail-loud
        # guarantee, correct syntax.
        cur.execute(
            """
            INSERT INTO alerts (source, source_id, tier, title, body,
                                matter_slug, status, structured_actions, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s::jsonb, NOW())
            ON CONFLICT (source, source_id, (structured_actions->>'trigger'))
            WHERE status = 'pending'
              AND source = 'proactive_pm_sentinel'
              AND structured_actions->>'trigger' IN ('quiet_thread', 'awaiting_counterparty')
            DO NOTHING
            """,
            (
                "proactive_pm_sentinel", source_id, tier, title[:500], body[:4000],
                matter_slug, json.dumps(structured, default=str),
            ),
        )
        inserted = cur.rowcount
        conn.commit()
        cur.close()
        if inserted == 0:
            # Lost an insert race against a concurrent process — the card exists.
            return ("noop", None)
        return ("inserted", None)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"_upsert_quiet_alert({source_id}) failed: {e}")
        return ("noop", None)
    finally:
        store._put_conn(conn)


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
