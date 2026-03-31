"""
SENTIMENT-TRAJECTORY-1 — Relationship Sentiment Scoring (Session 29)

Haiku scores the tone of inbound messages on a 1-5 scale:
  1 = hostile/angry
  2 = cold/terse/formal-negative
  3 = neutral/professional
  4 = warm/friendly
  5 = very positive/enthusiastic

Two modes:
  - Inline: score_message_sentiment() called from email_trigger/waha_webhook at ingestion
  - Batch: run_sentiment_backfill() called by scheduler to score unscored interactions

Scores stored on contact_interactions.sentiment (VARCHAR) as "N" (1-5 string).
Cadence tracker extended to compute sentiment_trend per contact.

Cost: ~EUR 0.50/day (Haiku batch scoring, ~100 messages/day × ~100 tokens each).
"""
import json
import logging
from datetime import datetime, timezone

from config.settings import config

logger = logging.getLogger("baker.sentiment_scorer")


# ─────────────────────────────────────────────────
# Inline scoring (single message)
# ─────────────────────────────────────────────────

_SENTIMENT_PROMPT = """Score the TONE of this message on a 1-5 scale.
1 = hostile/angry/threatening
2 = cold/terse/dissatisfied
3 = neutral/professional/factual
4 = warm/friendly/positive
5 = very positive/enthusiastic/grateful

Consider: word choice, formality level, punctuation, emoticons, overall warmth.
Short factual messages (e.g., "OK", "Noted", scheduling confirmations) are 3 (neutral).
Auto-generated notifications are 3 (neutral).

Return ONLY the number (1-5). Nothing else."""


def score_message_sentiment(text: str) -> int:
    """Score a single message's sentiment. Returns 1-5 (3 = neutral on failure).

    Lightweight — uses Haiku with minimal tokens. ~EUR 0.0002 per call.
    """
    if not text or len(text.strip()) < 5:
        return 3  # Too short to score

    try:
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"{_SENTIMENT_PROMPT}\n\nMessage:\n{text[:500]}",
            }],
            max_tokens=5,
        )

        # Log cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "gemini-2.5-flash", resp.usage.input_tokens,
                resp.usage.output_tokens, source="sentiment_scorer",
            )
        except Exception:
            pass

        raw = resp.text.strip()
        # Extract first digit
        for char in raw:
            if char.isdigit() and char in "12345":
                return int(char)
        return 3  # Default neutral

    except Exception as e:
        logger.debug(f"Sentiment scoring failed (defaulting to 3): {e}")
        return 3


# ─────────────────────────────────────────────────
# Batch scoring (efficient — scores multiple messages in one call)
# ─────────────────────────────────────────────────

_BATCH_PROMPT = """Score the TONE of each message on a 1-5 scale.
1 = hostile/angry  2 = cold/terse  3 = neutral  4 = warm/friendly  5 = very positive

Return ONLY a JSON array of numbers, one per message, in the same order.
Example: [3, 4, 2, 5, 3]"""


def _score_batch(messages: list) -> list:
    """Score a batch of messages (max 20) in a single Haiku call.
    Returns list of scores (1-5).
    """
    if not messages:
        return []

    msg_parts = []
    for i, msg in enumerate(messages[:20], 1):
        text = (msg.get("text") or "")[:200]
        msg_parts.append(f"{i}. {text}")

    try:
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"{_BATCH_PROMPT}\n\nMessages:\n" + "\n".join(msg_parts),
            }],
            max_tokens=100,
        )

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "gemini-2.5-flash", resp.usage.input_tokens,
                resp.usage.output_tokens, source="sentiment_batch",
            )
        except Exception:
            pass

        raw = resp.text.strip()
        # Parse JSON array
        if raw.startswith("["):
            scores = json.loads(raw)
            # Validate each score
            return [max(1, min(5, int(s))) for s in scores[:len(messages)]]

        # Fallback: extract individual digits
        scores = []
        for char in raw:
            if char.isdigit() and char in "12345":
                scores.append(int(char))
        return scores[:len(messages)]

    except Exception as e:
        logger.warning(f"Batch sentiment scoring failed: {e}")
        return [3] * len(messages)  # Default all neutral


# ─────────────────────────────────────────────────
# Backfill job — score unscored interactions
# ─────────────────────────────────────────────────

def run_sentiment_backfill():
    """
    Scheduled job: score unscored contact_interactions.
    Processes up to 100 interactions per run in batches of 20.
    """
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Advisory lock
        cur.execute("SELECT pg_try_advisory_xact_lock(900400)")
        if not cur.fetchone()["pg_try_advisory_xact_lock"]:
            logger.info("Sentiment backfill: another instance running — skipping")
            return

        # Get unscored inbound interactions with text
        cur.execute("""
            SELECT ci.id, ci.subject, ci.channel
            FROM contact_interactions ci
            WHERE ci.direction = 'inbound'
              AND (ci.sentiment IS NULL OR ci.sentiment = '')
              AND ci.subject IS NOT NULL
              AND ci.subject != ''
            ORDER BY ci.timestamp DESC
            LIMIT 100
        """)
        rows = cur.fetchall()

        if not rows:
            logger.info("Sentiment backfill: no unscored interactions")
            return

        logger.info(f"Sentiment backfill: scoring {len(rows)} interactions")

        # Process in batches of 20
        scored = 0
        for i in range(0, len(rows), 20):
            batch = rows[i:i + 20]
            messages = [{"text": r["subject"]} for r in batch]
            scores = _score_batch(messages)

            # Update each interaction
            for j, row in enumerate(batch):
                score = scores[j] if j < len(scores) else 3
                cur.execute(
                    "UPDATE contact_interactions SET sentiment = %s WHERE id = %s",
                    (str(score), row["id"]),
                )
                scored += 1

            conn.commit()

        logger.info(f"Sentiment backfill complete: {scored} interactions scored")

        # After scoring, update sentiment trends on vip_contacts
        _update_vip_sentiment_trends(cur, conn)

    except Exception as e:
        logger.error(f"Sentiment backfill failed: {e}")
    finally:
        store._put_conn(conn)


# ─────────────────────────────────────────────────
# Update vip_contacts.sentiment_trend
# ─────────────────────────────────────────────────

def _update_vip_sentiment_trends(cur, conn):
    """Update sentiment_trend on vip_contacts for all contacts with 5+ scored interactions."""
    try:
        cur.execute("""
            WITH scored AS (
                SELECT
                    ci.contact_id,
                    CAST(ci.sentiment AS INTEGER) as score,
                    CASE WHEN ci.timestamp > NOW() - INTERVAL '30 days' THEN TRUE ELSE FALSE END as is_recent
                FROM contact_interactions ci
                WHERE ci.direction = 'inbound'
                  AND ci.sentiment IS NOT NULL
                  AND ci.sentiment ~ '^[1-5]$'
            ),
            trends AS (
                SELECT
                    contact_id,
                    AVG(score) as avg_all,
                    AVG(CASE WHEN is_recent THEN score END) as avg_recent,
                    COUNT(*) as total
                FROM scored
                GROUP BY contact_id
                HAVING COUNT(*) >= 5
            )
            UPDATE vip_contacts vc
            SET sentiment_trend = CASE
                WHEN t.avg_recent IS NULL THEN 'insufficient_data'
                WHEN t.avg_recent - t.avg_all >= 0.5 THEN 'warming'
                WHEN t.avg_all - t.avg_recent >= 0.5 THEN 'cooling'
                ELSE 'stable'
            END
            FROM trends t
            WHERE vc.id = t.contact_id
        """)
        updated = cur.rowcount
        conn.commit()
        logger.info(f"Updated sentiment_trend for {updated} contacts")
    except Exception as e:
        logger.warning(f"VIP sentiment trend update failed (non-fatal): {e}")


# ─────────────────────────────────────────────────
# Sentiment trend computation (API)
# ─────────────────────────────────────────────────

def compute_sentiment_trends() -> list:
    """
    Compute sentiment trends for contacts with 5+ scored interactions.
    Returns list of dicts with name, avg_sentiment, recent_sentiment, trend.
    """
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return []

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Overall average vs last-30-day average per contact
        cur.execute("""
            WITH scored AS (
                SELECT
                    ci.contact_id,
                    vc.name,
                    vc.tier,
                    CAST(ci.sentiment AS INTEGER) as score,
                    ci.timestamp,
                    CASE WHEN ci.timestamp > NOW() - INTERVAL '30 days' THEN TRUE ELSE FALSE END as is_recent
                FROM contact_interactions ci
                JOIN vip_contacts vc ON vc.id = ci.contact_id
                WHERE ci.direction = 'inbound'
                  AND ci.sentiment IS NOT NULL
                  AND ci.sentiment ~ '^[1-5]$'
            ),
            trends AS (
                SELECT
                    contact_id,
                    name,
                    tier,
                    COUNT(*) as total_scored,
                    AVG(score) as avg_all,
                    AVG(CASE WHEN is_recent THEN score END) as avg_recent,
                    COUNT(CASE WHEN is_recent THEN 1 END) as recent_count
                FROM scored
                GROUP BY contact_id, name, tier
                HAVING COUNT(*) >= 5
            )
            SELECT
                name,
                tier,
                total_scored,
                ROUND(avg_all::numeric, 2) as avg_sentiment,
                ROUND(COALESCE(avg_recent, avg_all)::numeric, 2) as recent_sentiment,
                recent_count,
                CASE
                    WHEN avg_recent IS NULL THEN 'insufficient_data'
                    WHEN avg_recent - avg_all >= 0.5 THEN 'warming'
                    WHEN avg_all - avg_recent >= 0.5 THEN 'cooling'
                    ELSE 'stable'
                END as trend
            FROM trends
            ORDER BY
                CASE
                    WHEN COALESCE(avg_recent, avg_all) - avg_all <= -0.5 THEN 0
                    WHEN COALESCE(avg_recent, avg_all) - avg_all >= 0.5 THEN 1
                    ELSE 2
                END,
                total_scored DESC
        """)
        results = [dict(r) for r in cur.fetchall()]
        cur.close()

        # Convert Decimal to float
        for r in results:
            for key in ("avg_sentiment", "recent_sentiment"):
                if r.get(key) is not None:
                    r[key] = float(r[key])

        return results

    except Exception as e:
        logger.error(f"Sentiment trend computation failed: {e}")
        return []
    finally:
        store._put_conn(conn)


def get_contact_sentiment(contact_name: str) -> dict:
    """Get sentiment profile for a specific contact. For use by profiling specialist."""
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return {}

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT
                CAST(ci.sentiment AS INTEGER) as score,
                ci.timestamp,
                ci.subject,
                ci.channel
            FROM contact_interactions ci
            JOIN vip_contacts vc ON vc.id = ci.contact_id
            WHERE vc.name ILIKE %s
              AND ci.direction = 'inbound'
              AND ci.sentiment IS NOT NULL
              AND ci.sentiment ~ '^[1-5]$'
            ORDER BY ci.timestamp DESC
            LIMIT 20
        """, (f"%{contact_name}%",))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()

        if not rows:
            return {"contact": contact_name, "data": "no_sentiment_data"}

        scores = [r["score"] for r in rows]
        recent_5 = scores[:5]
        older = scores[5:]

        return {
            "contact": contact_name,
            "total_scored": len(rows),
            "avg_sentiment": round(sum(scores) / len(scores), 2),
            "recent_avg": round(sum(recent_5) / len(recent_5), 2) if recent_5 else None,
            "trend": (
                "warming" if recent_5 and older and (sum(recent_5) / len(recent_5)) - (sum(older) / len(older)) >= 0.5
                else "cooling" if recent_5 and older and (sum(older) / len(older)) - (sum(recent_5) / len(recent_5)) >= 0.5
                else "stable"
            ),
            "recent_messages": [
                {
                    "score": r["score"],
                    "date": r["timestamp"].isoformat() if r.get("timestamp") else None,
                    "channel": r.get("channel"),
                    "subject": (r.get("subject") or "")[:60],
                }
                for r in rows[:5]
            ],
        }

    except Exception as e:
        logger.error(f"get_contact_sentiment failed: {e}")
        return {}
    finally:
        store._put_conn(conn)
