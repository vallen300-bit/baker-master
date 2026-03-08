"""
Proactive Signal Scanner + AO Mood Classification + Communication Gap Tracker
Phase 4 — PROACTIVE-FLAG-AO

Two scheduled jobs:
  - run_proactive_scan() every 30 min: scans recent content against proactive_flag
    capability trigger patterns, creates T2/T1 alerts
  - run_communication_gap_check() every 6h: alerts if no Director→VIP message in N days
"""
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger("baker.proactive_scanner")


# -------------------------------------------------------
# AO Mood Detection Keywords (Russian + English)
# -------------------------------------------------------

_AO_POSITIVE = re.compile(
    r"\b(appreciate|grateful|thank.you|good.news|progress|agreed|"
    r"looking.forward|pleased|excellent|partnership|together|"
    r"constructive|opportunity|optimistic|"
    r"спасибо|отлично|хорошо|договорились|рад|благодарю|"
    r"прогресс|партнёрство|вместе|конструктивно)\b", re.IGNORECASE
)

_AO_NEGATIVE = re.compile(
    r"\b(disappointed|unacceptable|demand|legal.action|breach|"
    r"concerned|overdue|default|penalty|lawyer|litigation|"
    r"frustrat|delay|unresponsive|broken.promise|"
    r"неприемлемо|разочарован|требую|юрист|нарушение|штраф|"
    r"задержка|обещание|претензия|ответственность)\b", re.IGNORECASE
)

_AO_IDENTIFIERS = re.compile(
    r"\b(oskolkov|andrey|aelio|andrej)\b", re.IGNORECASE
)


def classify_ao_mood(content: str) -> str:
    """Classify AO message mood: positive, neutral, or negative."""
    pos = len(_AO_POSITIVE.findall(content))
    neg = len(_AO_NEGATIVE.findall(content))
    if neg >= 2 or (neg > 0 and neg > pos):
        return "negative"
    elif pos >= 2 or (pos > 0 and pos > neg):
        return "positive"
    return "neutral"


# -------------------------------------------------------
# Part 1 + 2: Proactive Signal Scanner
# -------------------------------------------------------

def run_proactive_scan():
    """Scheduled job (every 30 min): scan recent content for proactive signals."""
    from memory.store_back import SentinelStoreBack
    from orchestrator.capability_registry import CapabilityRegistry

    store = SentinelStoreBack._get_global_instance()
    registry = CapabilityRegistry.get_instance()

    # 1. Load proactive capabilities
    proactive_caps = [
        c for c in registry.get_all_active()
        if c.autonomy_level == "proactive_flag" and c.trigger_patterns
    ]
    if not proactive_caps:
        logger.info("Proactive scan: no proactive_flag capabilities found")
        return

    # 2. Compile trigger patterns per capability
    cap_patterns = []
    for cap in proactive_caps:
        patterns = []
        for p in cap.trigger_patterns:
            try:
                patterns.append(re.compile(p, re.IGNORECASE))
            except re.error:
                logger.warning(f"Bad regex in {cap.slug}: {p}")
        if patterns:
            cap_patterns.append((cap, patterns))

    # 3. Fetch recent content (last 35 min to overlap with poll interval)
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        items = []

        # Recent emails
        cur.execute("""
            SELECT 'email' as source_type, message_id as source_id,
                   COALESCE(subject, '') || ' ' || COALESCE(full_body, '') as content,
                   sender_name
            FROM email_messages
            WHERE received_date > NOW() - INTERVAL '35 minutes'
            LIMIT 50
        """)
        items.extend([dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()])

        # Recent WhatsApp messages (non-Director)
        cur.execute("""
            SELECT 'whatsapp' as source_type, message_id as source_id,
                   COALESCE(full_text, '') as content,
                   sender_name
            FROM whatsapp_messages
            WHERE timestamp > NOW() - INTERVAL '35 minutes'
              AND is_director = FALSE
            LIMIT 50
        """)
        items.extend([dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()])

        # Recent alerts (avoid re-flagging proactive alerts)
        cur.execute("""
            SELECT 'alert' as source_type, id::text as source_id,
                   COALESCE(title, '') || ' ' || COALESCE(body, '') as content,
                   NULL as sender_name
            FROM alerts
            WHERE created_at > NOW() - INTERVAL '35 minutes'
              AND COALESCE(source, '') != 'proactive_scan'
            LIMIT 50
        """)
        items.extend([dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()])

        cur.close()
    except Exception as e:
        logger.warning(f"Proactive scan query failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return
    finally:
        store._put_conn(conn)

    if not items:
        logger.info("Proactive scan: no recent content to scan")
        return

    # 4. Match content against capability patterns
    flagged = 0
    for item in items:
        content = item.get("content", "")
        if not content or len(content) < 10:
            continue

        for cap, patterns in cap_patterns:
            if not any(p.search(content) for p in patterns):
                continue

            # Dedup key
            dedup_key = f"proactive:{cap.slug}:{item['source_type']}:{item['source_id']}"

            # Check if already flagged
            if store.alert_source_id_exists("proactive_scan", dedup_key):
                continue

            # AO-specific mood detection (Part 2)
            if cap.slug == "profiling" and _AO_IDENTIFIERS.search(content):
                mood = classify_ao_mood(content)
                sender = item.get("sender_name") or item["source_type"]
                if mood == "negative":
                    store.create_alert(
                        tier=1,
                        title=f"[Profiling] AO mood shift: NEGATIVE signal from {sender}",
                        body=content[:500],
                        source="proactive_scan",
                        source_id=dedup_key,
                        matter_slug="oskolkov-rg7",
                    )
                    flagged += 1
                    break
                elif mood == "positive":
                    store.create_alert(
                        tier=2,
                        title=f"[Profiling] AO mood: positive signal from {sender}",
                        body=content[:500],
                        source="proactive_scan",
                        source_id=dedup_key,
                        matter_slug="oskolkov-rg7",
                    )
                    flagged += 1
                    break

            # Generic proactive flag alert (T2)
            sender = item.get("sender_name") or item["source_type"]
            snippet = content[:120].replace("\n", " ")
            store.create_alert(
                tier=2,
                title=f"[{cap.name}] Signal from {sender}: {snippet}"[:300],
                body=content[:500],
                source="proactive_scan",
                source_id=dedup_key,
            )
            flagged += 1
            break  # One alert per content item

    logger.info(f"Proactive scan complete: {len(items)} items scanned, {flagged} signals flagged")


# -------------------------------------------------------
# Part 3: Communication Gap Tracker
# -------------------------------------------------------

# Configurable gap thresholds per VIP (days)
_COMMUNICATION_GAP_DAYS = {
    "oskolkov": 3,   # AO: 3 days
}


def run_communication_gap_check():
    """Check for communication gaps with profiled VIPs."""
    from memory.store_back import SentinelStoreBack

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return

    try:
        cur = conn.cursor()
        for vip_keyword, max_gap_days in _COMMUNICATION_GAP_DAYS.items():
            # Find last Director message to this VIP
            cur.execute("""
                SELECT MAX(timestamp) as last_contact
                FROM whatsapp_messages
                WHERE is_director = TRUE
                  AND (
                    sender_name ILIKE %s
                    OR chat_id ILIKE %s
                  )
            """, (f"%{vip_keyword}%", f"%{vip_keyword}%"))
            row = cur.fetchone()
            last_contact = row[0] if row and row[0] else None

            if last_contact is None:
                gap_days = 999
            else:
                if last_contact.tzinfo is None:
                    last_contact = last_contact.replace(tzinfo=timezone.utc)
                gap_days = (datetime.now(timezone.utc) - last_contact).days

            if gap_days >= max_gap_days:
                # Dedup: check if gap alert exists in last 24h
                cur.execute("""
                    SELECT 1 FROM alerts
                    WHERE source = 'communication_gap'
                      AND title ILIKE %s
                      AND created_at > NOW() - INTERVAL '24 hours'
                    LIMIT 1
                """, (f"%{vip_keyword}%",))
                if cur.fetchone():
                    continue

                title = f"Communication gap: {gap_days} days since last contact with {vip_keyword.title()}"
                body = (
                    f"No Director message to {vip_keyword.title()} detected in the last {gap_days} days.\n"
                    f"Threshold: {max_gap_days} days.\n\n"
                    f"Suggested: Send a brief update or check-in to maintain relationship cadence."
                )
                store.create_alert(
                    tier=2,
                    title=title,
                    body=body,
                    source="communication_gap",
                    matter_slug="oskolkov-rg7",
                )
                logger.info(f"Communication gap alert: {vip_keyword} ({gap_days} days)")

        cur.close()
    except Exception as e:
        logger.warning(f"Communication gap check failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        store._put_conn(conn)

    logger.info("Communication gap check complete")
