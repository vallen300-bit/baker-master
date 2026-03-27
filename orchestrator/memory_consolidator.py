"""
THREE-TIER MEMORY — Consolidation Engine (v2, upgraded from B4)

Architecture v6: Baker's memory moves through 3 tiers:
  Tier 1: Active (0-90 days) — full detail, priority in retrieval
  Tier 2: Compressed (90 days - 1 year) — Opus summaries, reduced vectors
  Tier 3: Institutional (1 year+) — monthly digests, permanent knowledge

This module handles:
  1. Tier 1→2 transition: Weekly job compresses interactions >90 days old
     using Opus (not Haiku) for lossless compression of critical details.
  2. Tier 2→3 transition: Monthly job compresses >1 year summaries into
     institutional knowledge digests.
  3. Archive management: raw data moves to archive tables, not deleted.
  4. Vector lifecycle: compressed summaries get new embeddings, replacing
     individual interaction vectors in Qdrant.

Cost: ~$12/month for Opus (30 matters/week × $0.10 each).
      This is the step where Baker decides what to remember — worth it.

Runs weekly (Sundays 04:00 UTC) via embedded_scheduler.
Table: memory_summaries (Tier 2), memory_institutional (Tier 3).
"""
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import anthropic

from config.settings import config

logger = logging.getLogger("baker.memory_consolidator")

# ─────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────

# Tier 1 → Tier 2: Compress interactions older than this
TIER1_TO_TIER2_AGE_DAYS = 90
# Tier 2 → Tier 3: Compress summaries older than this
TIER2_TO_TIER3_AGE_DAYS = 365
# Max interactions per matter to feed into one summary
MAX_INTERACTIONS_PER_SUMMARY = 100
# Minimum interactions to bother summarizing
MIN_INTERACTIONS_FOR_SUMMARY = 3
# Model for Tier 2 compression (Opus — lossless critical details)
TIER2_MODEL = "claude-opus-4-20250514"
# Model for Tier 3 compression (Sonnet — strategic synthesis)
TIER3_MODEL = "claude-sonnet-4-20250514"

# ─────────────────────────────────────────────────
# Prompts — carefully designed for zero information loss
# ─────────────────────────────────────────────────

_TIER2_PROMPT = """You are Baker, an AI Chief of Staff for Dimitry Vallen (Chairman, Brisen Group).

Your task: compress {count} raw interactions about "{matter_name}" into a structured matter brief.
This brief REPLACES the raw data in Baker's working memory. Anything you omit is effectively forgotten.

CRITICAL REQUIREMENTS — preserve ALL of the following:

1. FINANCIAL FIGURES — Every EUR/CHF/USD amount, percentage, valuation, fee, cost mentioned. Include exact numbers.
2. DATES & DEADLINES — Every specific date, deadline, due date, expiry. Include the date AND what it's for.
3. COMMITMENTS — Who promised what to whom, and by when. Both Director's commitments AND counterparty commitments.
4. DECISIONS — What was decided, by whom, when. Include the reasoning if stated.
5. RELATIONSHIP DYNAMICS — Tone shifts, cooperation levels, tensions, trust signals. Note WHO said/did what.
6. NEGOTIATION POSITIONS — What each side wants, their leverage, red lines, concessions made.
7. LEGAL/CONTRACTUAL — Contract terms, warranty periods, dispute positions, legal opinions mentioned.
8. PEOPLE — Full names, roles, organizations, contact details if mentioned.
9. OPEN ITEMS — Anything unresolved, pending, or requiring follow-up. Include status.
10. STRATEGIC CONTEXT — Why this matter matters, how it connects to other matters/projects.

FORMAT your output as structured markdown:

## {matter_name} — Matter Brief
**Period:** {start_date} to {end_date} | **Interactions:** {count} | **Channels:** {channels}

### Key Facts & Figures
- [Every financial figure, date, and hard fact]

### Timeline of Events
- [Chronological: what happened, when, who was involved]

### Commitments & Open Items
- [Director's commitments: what, to whom, by when, status]
- [Counterparty commitments: what, from whom, by when, status]

### Relationship Map
- [Each person: name, role, stance, last interaction, trust level]

### Strategic Position
- [Current status, risks, opportunities, recommended next moves]

### Raw Quotes (preserve verbatim)
- [Any direct quotes that capture tone, intent, or legal significance]

Contact focus: {contact_name}
Period: {start_date} to {end_date}

Interactions (chronological):
{interactions}"""

_TIER3_PROMPT = """You are Baker, compressing a year of matter summaries into permanent institutional knowledge.

This is the final tier — what Baker remembers forever about "{matter_name}".

Distill the summaries below into a concise institutional brief (2-3 paragraphs):
- What is this matter about?
- What happened? (key milestones only)
- What was decided? (permanent decisions)
- Who are the key people? (roles and relationships)
- What is the current status?
- Any lessons learned?

Summaries to compress:
{summaries}"""

# ─────────────────────────────────────────────────
# Table setup
# ─────────────────────────────────────────────────

def _ensure_tables():
    """Create memory_summaries (Tier 2) + memory_institutional (Tier 3) + archive tables."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return False
        try:
            cur = conn.cursor()
            # Tier 2: Per-matter compressed summaries
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memory_summaries (
                    id SERIAL PRIMARY KEY,
                    matter_slug VARCHAR(100),
                    contact_name VARCHAR(200),
                    summary TEXT NOT NULL,
                    tier INTEGER DEFAULT 2,
                    interaction_count INTEGER DEFAULT 0,
                    period_start TIMESTAMPTZ,
                    period_end TIMESTAMPTZ,
                    source_channels TEXT[],
                    model_used VARCHAR(50),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(matter_slug, contact_name)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_summaries_matter ON memory_summaries(matter_slug)")
            # Add tier and model_used columns if missing (upgrade from v1)
            cur.execute("ALTER TABLE memory_summaries ADD COLUMN IF NOT EXISTS tier INTEGER DEFAULT 2")
            cur.execute("ALTER TABLE memory_summaries ADD COLUMN IF NOT EXISTS model_used VARCHAR(50)")

            # Tier 3: Institutional knowledge (permanent)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memory_institutional (
                    id SERIAL PRIMARY KEY,
                    matter_slug VARCHAR(100) UNIQUE,
                    brief TEXT NOT NULL,
                    summary_count INTEGER DEFAULT 0,
                    period_start TIMESTAMPTZ,
                    period_end TIMESTAMPTZ,
                    model_used VARCHAR(50),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_institutional_matter ON memory_institutional(matter_slug)")

            # Archive: tracks which interactions have been compressed (never delete raw data)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memory_archive_log (
                    id SERIAL PRIMARY KEY,
                    source_table VARCHAR(50),
                    source_id TEXT,
                    compressed_into INTEGER REFERENCES memory_summaries(id),
                    archived_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_archive_log_source ON memory_archive_log(source_table, source_id)")

            conn.commit()
            cur.close()
            return True
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Failed to create memory tier tables: {e}")
        return False


# ─────────────────────────────────────────────────
# Tier 1 → 2: Weekly Opus compression
# ─────────────────────────────────────────────────

def _get_matters_with_old_interactions() -> list:
    """Find matters that have enough old interactions (>90 days) to compress."""
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
            """ % (TIER1_TO_TIER2_AGE_DAYS, MIN_INTERACTIONS_FOR_SUMMARY))
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Failed to find consolidation candidates: {e}")
        return []


def _get_interactions_for_matter(matter_name: str) -> list:
    """Fetch old interactions for a matter."""
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
                       ci.subject, ci.sentiment, ci.source_ref
                FROM contact_interactions ci
                LEFT JOIN vip_contacts vc ON vc.id = ci.contact_id
                WHERE ci.subject ILIKE %s
                  AND ci.timestamp < NOW() - INTERVAL '%s days'
                ORDER BY ci.timestamp ASC
                LIMIT %s
            """ % ('%s', TIER1_TO_TIER2_AGE_DAYS, MAX_INTERACTIONS_PER_SUMMARY),
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
                        SELECT subject, LEFT(full_body, 800) as body
                        FROM email_messages WHERE id = %s
                    """, (source_ref.split(":")[-1] if ":" in source_ref else source_ref,))
                    row = cur.fetchone()
                    if row:
                        content = f"{row['subject']}: {row.get('body', '')}"
                elif channel == "whatsapp" and source_ref:
                    cur.execute("""
                        SELECT LEFT(full_text, 800) as body
                        FROM whatsapp_messages WHERE id = %s
                    """, (source_ref.split(":")[-1] if ":" in source_ref else source_ref,))
                    row = cur.fetchone()
                    if row and row.get("body"):
                        content = row["body"]
                elif channel == "meeting" and source_ref:
                    cur.execute("""
                        SELECT LEFT(full_transcript, 1000) as body, title
                        FROM meeting_transcripts WHERE source_id = %s
                    """, (source_ref,))
                    row = cur.fetchone()
                    if row:
                        content = f"Meeting: {row.get('title', '')}: {row.get('body', '')}"

                enriched.append({
                    **ix,
                    "content": content[:800],
                })
            cur.close()
            return enriched
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.debug(f"Enrichment failed (using raw): {e}")
        return interactions


def _generate_tier2_summary(
    matter_name: str,
    contact_name: str,
    interactions: list,
) -> Optional[str]:
    """Use OPUS to generate a comprehensive Tier 2 matter brief.
    Opus preserves financial figures, dates, relationship dynamics, and strategic context."""
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
        sentiment = ix.get("sentiment")
        sent_str = f" [tone:{sentiment}]" if sentiment else ""
        lines.append(f"[{ts}] {channel} ({direction}) {contact}{sent_str}: {content[:400]}")

    start_date = interactions[0].get("timestamp", "?")
    end_date = interactions[-1].get("timestamp", "?")
    if hasattr(start_date, "strftime"):
        start_date = start_date.strftime("%Y-%m-%d")
    if hasattr(end_date, "strftime"):
        end_date = end_date.strftime("%Y-%m-%d")

    channels = list(set(ix.get("channel", "?") for ix in interactions))

    prompt_text = _TIER2_PROMPT.format(
        matter_name=matter_name,
        contact_name=contact_name or "Multiple contacts",
        start_date=start_date,
        end_date=end_date,
        count=len(interactions),
        channels=", ".join(channels),
        interactions="\n".join(lines),
    )

    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model=TIER2_MODEL,
            max_tokens=4096,  # Opus needs room for detailed briefs
            messages=[{"role": "user", "content": prompt_text}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                TIER2_MODEL, resp.usage.input_tokens,
                resp.usage.output_tokens, source="tier2_consolidation",
            )
        except Exception:
            pass
        summary = resp.content[0].text.strip()
        logger.info(f"Tier 2 summary generated for {matter_name}: {len(summary)} chars, "
                     f"{resp.usage.input_tokens}+{resp.usage.output_tokens} tokens")
        return summary
    except Exception as e:
        logger.error(f"Tier 2 summary generation failed for {matter_name}: {e}")
        return None


def _store_summary(
    matter_slug: str,
    contact_name: str,
    summary: str,
    interaction_count: int,
    period_start,
    period_end,
    channels: list,
    model_used: str = None,
) -> Optional[int]:
    """Upsert summary into memory_summaries table. Returns summary ID."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO memory_summaries
                    (matter_slug, contact_name, summary, interaction_count,
                     period_start, period_end, source_channels, model_used, tier, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 2, NOW())
                ON CONFLICT (matter_slug, contact_name) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    interaction_count = EXCLUDED.interaction_count,
                    period_start = LEAST(memory_summaries.period_start, EXCLUDED.period_start),
                    period_end = GREATEST(memory_summaries.period_end, EXCLUDED.period_end),
                    source_channels = EXCLUDED.source_channels,
                    model_used = EXCLUDED.model_used,
                    updated_at = NOW()
                RETURNING id
            """, (matter_slug, contact_name or "general", summary,
                  interaction_count, period_start, period_end, channels, model_used or TIER2_MODEL))
            row = cur.fetchone()
            conn.commit()
            cur.close()
            summary_id = row[0] if row else None
            logger.info(f"Tier 2 summary stored for {matter_slug}/{contact_name or 'general'} (id={summary_id})")
            return summary_id
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Failed to store summary for {matter_slug}: {e}")
        return None


def _log_archived_interactions(interactions: list, summary_id: int):
    """Record which interactions were compressed into this summary (for audit trail)."""
    if not summary_id or not interactions:
        return
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            for ix in interactions:
                cur.execute("""
                    INSERT INTO memory_archive_log (source_table, source_id, compressed_into)
                    VALUES ('contact_interactions', %s, %s)
                    ON CONFLICT DO NOTHING
                """, (str(ix.get("id", "")), summary_id))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.debug(f"Archive log failed (non-fatal): {e}")


def _embed_summary_to_qdrant(matter_slug: str, summary: str, summary_id: int):
    """Create a Qdrant vector for the compressed summary (replaces individual interaction vectors)."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        # Embed the summary text
        embedding = store.voyage.embed(
            [summary[:8000]],  # Voyage has input limits
            model="voyage-3",
            input_type="document",
        ).embeddings[0]

        from qdrant_client.models import PointStruct
        import uuid
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "text": summary[:4000],
                "type": "tier2_summary",
                "matter_slug": matter_slug,
                "summary_id": summary_id,
                "collection": "sentinel-interactions",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        store.qdrant.upsert(
            collection_name="sentinel-interactions",
            points=[point],
        )
        logger.info(f"Tier 2 vector embedded for {matter_slug} (summary #{summary_id})")
    except Exception as e:
        logger.warning(f"Tier 2 Qdrant embedding failed for {matter_slug} (non-fatal): {e}")


# ─────────────────────────────────────────────────
# Tier 2 → 3: Monthly institutional compression
# ─────────────────────────────────────────────────

def _get_old_summaries_for_tier3() -> list:
    """Find Tier 2 summaries older than 1 year, grouped by matter."""
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
                SELECT matter_slug, COUNT(*) as summary_count,
                       STRING_AGG(summary, E'\n\n---\n\n' ORDER BY period_start) as combined_summaries,
                       MIN(period_start) as oldest, MAX(period_end) as newest
                FROM memory_summaries
                WHERE tier = 2
                  AND period_end < NOW() - INTERVAL '%s days'
                GROUP BY matter_slug
                HAVING COUNT(*) >= 1
                ORDER BY matter_slug
            """ % TIER2_TO_TIER3_AGE_DAYS)
            results = [dict(r) for r in cur.fetchall()]
            cur.close()
            return results
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Failed to find Tier 3 candidates: {e}")
        return []


def _generate_tier3_brief(matter_slug: str, summaries_text: str) -> Optional[str]:
    """Use Sonnet to distill Tier 2 summaries into institutional knowledge."""
    try:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = client.messages.create(
            model=TIER3_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": _TIER3_PROMPT.format(
                matter_name=matter_slug,
                summaries=summaries_text[:15000],
            )}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(TIER3_MODEL, resp.usage.input_tokens, resp.usage.output_tokens, source="tier3_consolidation")
        except Exception:
            pass
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"Tier 3 brief generation failed for {matter_slug}: {e}")
        return None


def _store_institutional(matter_slug: str, brief: str, summary_count: int,
                         period_start, period_end):
    """Upsert into memory_institutional table."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO memory_institutional
                    (matter_slug, brief, summary_count, period_start, period_end, model_used, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (matter_slug) DO UPDATE SET
                    brief = EXCLUDED.brief,
                    summary_count = EXCLUDED.summary_count,
                    period_start = LEAST(memory_institutional.period_start, EXCLUDED.period_start),
                    period_end = GREATEST(memory_institutional.period_end, EXCLUDED.period_end),
                    model_used = EXCLUDED.model_used,
                    updated_at = NOW()
            """, (matter_slug, brief, summary_count, period_start, period_end, TIER3_MODEL))
            conn.commit()
            cur.close()
            logger.info(f"Tier 3 institutional brief stored for {matter_slug}")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"Failed to store institutional brief for {matter_slug}: {e}")


# ─────────────────────────────────────────────────
# Main Entry Points — called by scheduler
# ─────────────────────────────────────────────────

def run_memory_consolidation():
    """Weekly job: Tier 1→2 compression using Opus. Runs Sundays 04:00 UTC."""
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

    logger.info("Memory consolidation (Tier 1→2): starting weekly run with Opus...")
    t0 = time.time()

    # Ensure tables exist
    if not _ensure_tables():
        logger.error("Memory consolidation: table creation failed, aborting")
        return

    # Find matters with enough old interactions
    candidates = _get_matters_with_old_interactions()
    if not candidates:
        logger.info("Memory consolidation: no matters need Tier 2 compression")
        return

    logger.info(f"Memory consolidation: {len(candidates)} matters to compress")

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
            summary = _generate_tier2_summary(matter_name, None, interactions)
            if summary:
                channels = list(set(ix.get("channel", "?") for ix in interactions))
                sid = _store_summary(
                    matter_name, "general", summary, len(interactions),
                    interactions[0].get("timestamp"),
                    interactions[-1].get("timestamp"),
                    channels,
                )
                if sid:
                    _log_archived_interactions(interactions, sid)
                    _embed_summary_to_qdrant(matter_name, summary, sid)
                summaries_created += 1
        else:
            for contact_name, contact_ixs in by_contact.items():
                if len(contact_ixs) < MIN_INTERACTIONS_FOR_SUMMARY:
                    continue
                summary = _generate_tier2_summary(matter_name, contact_name, contact_ixs)
                if summary:
                    channels = list(set(ix.get("channel", "?") for ix in contact_ixs))
                    sid = _store_summary(
                        matter_name, contact_name, summary, len(contact_ixs),
                        contact_ixs[0].get("timestamp"),
                        contact_ixs[-1].get("timestamp"),
                        channels,
                    )
                    if sid:
                        _log_archived_interactions(contact_ixs, sid)
                        _embed_summary_to_qdrant(matter_name, summary, sid)
                    summaries_created += 1

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        f"Memory consolidation (Tier 1→2) complete: {summaries_created} Opus summaries created "
        f"from {len(candidates)} matters ({elapsed_ms}ms)"
    )


def run_institutional_consolidation():
    """Monthly job: Tier 2→3 compression using Sonnet. Runs 1st of month 05:00 UTC."""
    logger.info("Institutional consolidation (Tier 2→3): starting monthly run...")
    t0 = time.time()

    if not _ensure_tables():
        return

    candidates = _get_old_summaries_for_tier3()
    if not candidates:
        logger.info("Institutional consolidation: no summaries old enough for Tier 3")
        return

    briefs_created = 0
    for matter in candidates:
        slug = matter["matter_slug"]
        brief = _generate_tier3_brief(slug, matter["combined_summaries"])
        if brief:
            _store_institutional(
                slug, brief, matter["summary_count"],
                matter["oldest"], matter["newest"],
            )
            briefs_created += 1

    elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        f"Institutional consolidation (Tier 2→3) complete: {briefs_created} briefs "
        f"from {len(candidates)} matters ({elapsed_ms}ms)"
    )
