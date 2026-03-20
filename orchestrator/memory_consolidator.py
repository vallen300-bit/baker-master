"""
B4: Memory Consolidation — Weekly Compression Job

Compresses old interactions (>30 days) into per-matter summaries.
Reduces retrieval noise: instead of 50 old interactions for "Cupial",
the agent gets 1 consolidated summary paragraph.

Runs weekly (Sundays 04:00 UTC) via embedded_scheduler.
Uses Haiku for summarization (~EUR 0.01 per matter summary).

Table: memory_summaries (created on first run).
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import anthropic

from config.settings import config

logger = logging.getLogger("baker.memory_consolidator")

# Only consolidate interactions older than this
CONSOLIDATION_AGE_DAYS = 30
# Max interactions per matter to feed into one summary
MAX_INTERACTIONS_PER_SUMMARY = 100
# Minimum interactions to bother summarizing
MIN_INTERACTIONS_FOR_SUMMARY = 3


_SUMMARY_PROMPT = """You are Baker, an AI Chief of Staff. Summarize these historical interactions
into a concise matter brief (3-5 paragraphs). Focus on:

1. Key events and decisions (what happened, when, who was involved)
2. Current status and open items
3. Relationship dynamics (who is cooperative, who is difficult, any tensions)
4. Financial figures mentioned (amounts, deadlines, obligations)
5. Next steps or pending actions

Be factual and specific. Include names, dates, and amounts. This summary replaces
the raw interactions in Baker's memory — nothing important should be lost.

Matter: {matter_name}
Contact: {contact_name}
Period: {start_date} to {end_date}
Interaction count: {count}

Interactions (chronological):
{interactions}"""


def _ensure_table():
    """Create memory_summaries table if not exists."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memory_summaries (
                    id SERIAL PRIMARY KEY,
                    matter_slug VARCHAR(100),
                    contact_name VARCHAR(200),
                    summary TEXT NOT NULL,
                    interaction_count INTEGER DEFAULT 0,
                    period_start TIMESTAMPTZ,
                    period_end TIMESTAMPTZ,
                    source_channels TEXT[],
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(matter_slug, contact_name)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_summaries_matter ON memory_summaries(matter_slug)")
            conn.commit()
            cur.close()
            return True
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Failed to create memory_summaries table: {e}")
        return False


def _get_matters_with_old_interactions() -> list:
    """Find matters that have enough old interactions to summarize."""
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT m.matter_name,
                       COUNT(ci.id) as interaction_count,
                       MIN(ci.timestamp) as oldest,
                       MAX(ci.timestamp) as newest
                FROM matter_registry m
                JOIN contact_interactions ci
                    ON ci.subject ILIKE '%%' || m.matter_name || '%%'
                WHERE m.status = 'active'
                  AND ci.timestamp < NOW() - INTERVAL '%s days'
                GROUP BY m.matter_name
                HAVING COUNT(ci.id) >= %s
                ORDER BY COUNT(ci.id) DESC
            """ % (CONSOLIDATION_AGE_DAYS, MIN_INTERACTIONS_FOR_SUMMARY))
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Failed to find consolidation candidates: {e}")
        return []


def _get_interactions_for_matter(matter_name: str) -> list:
    """Fetch old interactions for a matter, grouped by contact."""
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT ci.id, ci.contact_id, vc.name as contact_name,
                       ci.channel, ci.direction, ci.timestamp,
                       ci.subject, ci.sentiment
                FROM contact_interactions ci
                LEFT JOIN vip_contacts vc ON vc.id = ci.contact_id
                WHERE ci.subject ILIKE %s
                  AND ci.timestamp < NOW() - INTERVAL '%s days'
                ORDER BY ci.timestamp ASC
                LIMIT %s
            """ % ('%s', CONSOLIDATION_AGE_DAYS, MAX_INTERACTIONS_PER_SUMMARY),
            (f"%{matter_name}%",))
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Failed to fetch interactions for {matter_name}: {e}")
        return []


def _enrich_interactions(interactions: list, matter_name: str) -> list:
    """Add full content from email/WA/meeting tables for richer summaries."""
    enriched = []
    try:
        from memory.store_back import SentinelStoreBack
        import psycopg2.extras
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return interactions
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            for ix in interactions:
                source_ref = ix.get("source_ref", "")
                channel = ix.get("channel", "")
                content = ix.get("subject", "")

                # Try to get full content from source table
                if channel == "email" and source_ref:
                    cur.execute("""
                        SELECT subject, LEFT(full_body, 500) as body
                        FROM email_messages WHERE id = %s
                    """, (source_ref.split(":")[-1] if ":" in source_ref else source_ref,))
                    row = cur.fetchone()
                    if row:
                        content = f"{row['subject']}: {row.get('body', '')}"
                elif channel == "whatsapp" and source_ref:
                    cur.execute("""
                        SELECT LEFT(full_text, 500) as body
                        FROM whatsapp_messages WHERE id = %s
                    """, (source_ref.split(":")[-1] if ":" in source_ref else source_ref,))
                    row = cur.fetchone()
                    if row and row.get("body"):
                        content = row["body"]

                enriched.append({
                    **ix,
                    "content": content[:500],
                })
            cur.close()
            return enriched
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.debug(f"Enrichment failed (using raw): {e}")
        return interactions


def _generate_summary(
    matter_name: str,
    contact_name: str,
    interactions: list,
) -> Optional[str]:
    """Use Haiku to generate a consolidated summary."""
    if not interactions:
        return None

    # Format interactions for the prompt
    lines = []
    for ix in interactions:
        ts = ix.get("timestamp", "")
        if hasattr(ts, "strftime"):
            ts = ts.strftime("%Y-%m-%d")
        channel = ix.get("channel", "?")
        direction = ix.get("direction", "?")
        content = ix.get("content", ix.get("subject", ""))
        contact = ix.get("contact_name", "?")
        lines.append(f"[{ts}] {channel} ({direction}) {contact}: {content[:200]}")

    start_date = interactions[0].get("timestamp", "?")
    end_date = interactions[-1].get("timestamp", "?")
    if hasattr(start_date, "strftime"):
        start_date = start_date.strftime("%Y-%m-%d")
    if hasattr(end_date, "strftime"):
        end_date = end_date.strftime("%Y-%m-%d")

    prompt_text = _SUMMARY_PROMPT.format(
        matter_name=matter_name,
        contact_name=contact_name or "Multiple contacts",
        start_date=start_date,
        end_date=end_date,
        count=len(interactions),
        interactions="\n".join(lines),
    )

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt_text}],
        )
        # Log cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "claude-haiku-4-5-20251001", resp.usage.input_tokens,
                resp.usage.output_tokens, source="memory_consolidation",
            )
        except Exception:
            pass
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"Summary generation failed for {matter_name}: {e}")
        return None


def _store_summary(
    matter_slug: str,
    contact_name: str,
    summary: str,
    interaction_count: int,
    period_start,
    period_end,
    channels: list,
):
    """Upsert summary into memory_summaries table."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO memory_summaries
                    (matter_slug, contact_name, summary, interaction_count,
                     period_start, period_end, source_channels, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (matter_slug, contact_name) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    interaction_count = EXCLUDED.interaction_count,
                    period_start = LEAST(memory_summaries.period_start, EXCLUDED.period_start),
                    period_end = GREATEST(memory_summaries.period_end, EXCLUDED.period_end),
                    source_channels = EXCLUDED.source_channels,
                    updated_at = NOW()
            """, (matter_slug, contact_name or "general", summary,
                  interaction_count, period_start, period_end, channels))
            conn.commit()
            cur.close()
            logger.info(f"Summary stored for {matter_slug}/{contact_name or 'general'}")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Failed to store summary for {matter_slug}: {e}")


# ─────────────────────────────────────────────────
# Main Entry Point — called by scheduler
# ─────────────────────────────────────────────────

def run_memory_consolidation():
    """Weekly job: compress old interactions into per-matter summaries."""
    # Advisory lock to prevent concurrent runs
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            logger.warning("Memory consolidation: no DB connection")
            return
        try:
            cur = conn.cursor()
            cur.execute("SELECT pg_try_advisory_xact_lock(8004)")
            got_lock = cur.fetchone()[0]
            cur.close()
            if not got_lock:
                logger.info("Memory consolidation: another instance running, skipping")
                return
        finally:
            store._put_conn(conn)
    except Exception:
        pass

    logger.info("Memory consolidation: starting weekly run...")
    t0 = time.time()

    # Ensure table exists
    if not _ensure_table():
        logger.error("Memory consolidation: table creation failed, aborting")
        return

    # Find matters with enough old interactions
    candidates = _get_matters_with_old_interactions()
    if not candidates:
        logger.info("Memory consolidation: no matters need consolidation")
        return

    logger.info(f"Memory consolidation: {len(candidates)} matters to process")

    summaries_created = 0
    for matter in candidates:
        matter_name = matter["matter_name"]
        count = matter["interaction_count"]

        # Get interactions
        interactions = _get_interactions_for_matter(matter_name)
        if len(interactions) < MIN_INTERACTIONS_FOR_SUMMARY:
            continue

        # Enrich with full content where available
        interactions = _enrich_interactions(interactions, matter_name)

        # Group by contact for per-contact summaries
        by_contact = {}
        for ix in interactions:
            cname = ix.get("contact_name") or "general"
            by_contact.setdefault(cname, []).append(ix)

        # Generate summary per contact group (or one for all if <10 interactions)
        if len(interactions) < 10:
            # Small enough to summarize all at once
            summary = _generate_summary(matter_name, None, interactions)
            if summary:
                channels = list(set(ix.get("channel", "?") for ix in interactions))
                _store_summary(
                    matter_name, "general", summary, len(interactions),
                    interactions[0].get("timestamp"),
                    interactions[-1].get("timestamp"),
                    channels,
                )
                summaries_created += 1
        else:
            # Summarize per contact
            for contact_name, contact_ixs in by_contact.items():
                if len(contact_ixs) < MIN_INTERACTIONS_FOR_SUMMARY:
                    continue
                summary = _generate_summary(matter_name, contact_name, contact_ixs)
                if summary:
                    channels = list(set(ix.get("channel", "?") for ix in contact_ixs))
                    _store_summary(
                        matter_name, contact_name, summary, len(contact_ixs),
                        contact_ixs[0].get("timestamp"),
                        contact_ixs[-1].get("timestamp"),
                        channels,
                    )
                    summaries_created += 1

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        f"Memory consolidation complete: {summaries_created} summaries created "
        f"from {len(candidates)} matters ({elapsed_ms}ms)"
    )
