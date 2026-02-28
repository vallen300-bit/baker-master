"""
Sentinel Trigger State Management
Manages watermarks, briefing queues, and dedup tracking.
All state stored in PostgreSQL (Neon) — no filesystem state.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("sentinel.trigger_state")


class TriggerState:
    """Manages watermarks and state via PostgreSQL.
    Uses SentinelStoreBack's connection pool (established by C3 fix).
    """

    def __init__(self):
        self._ensure_tables()

    def _get_store(self):
        """Get the global SentinelStoreBack instance for DB access."""
        from memory.store_back import SentinelStoreBack
        return SentinelStoreBack._get_global_instance()

    def _ensure_tables(self):
        """Create watermark and briefing_queue tables if they don't exist."""
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                logger.warning("No DB connection — cannot ensure trigger tables")
                return
            try:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS trigger_watermarks (
                        source      TEXT PRIMARY KEY,
                        last_seen   TIMESTAMPTZ NOT NULL,
                        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS briefing_queue (
                        id          SERIAL PRIMARY KEY,
                        item        JSONB NOT NULL,
                        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                # Add cursor_data column for opaque cursor storage (Dropbox, etc.)
                cur.execute("""
                    ALTER TABLE trigger_watermarks
                    ADD COLUMN IF NOT EXISTS cursor_data TEXT
                """)
                # RSS Sentinel tables (RSS-1)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS rss_feeds (
                        id                    SERIAL PRIMARY KEY,
                        feed_url              TEXT UNIQUE NOT NULL,
                        title                 TEXT,
                        category              TEXT,
                        html_url              TEXT,
                        is_active             BOOLEAN DEFAULT TRUE,
                        consecutive_failures  INTEGER DEFAULT 0,
                        last_polled           TIMESTAMPTZ,
                        created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS rss_articles (
                        id           SERIAL PRIMARY KEY,
                        feed_id      INTEGER REFERENCES rss_feeds(id),
                        url_hash     TEXT UNIQUE NOT NULL,
                        title        TEXT,
                        url          TEXT,
                        author       TEXT,
                        published_at TIMESTAMPTZ,
                        ingested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                conn.commit()
                cur.close()
                logger.info("Trigger state tables verified")
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.warning(f"Could not ensure trigger tables: {e}")

    # -------------------------------------------------------
    # Watermarks
    # -------------------------------------------------------

    def get_watermark(self, source: str) -> datetime:
        """
        Get last-processed timestamp for a source from PostgreSQL.
        Returns a timezone-aware UTC datetime.
        Falls back to 24 hours ago if no record exists.
        """
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                return datetime.now(timezone.utc) - timedelta(hours=24)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT last_seen FROM trigger_watermarks WHERE source = %s",
                    (source,),
                )
                row = cur.fetchone()
                cur.close()
                if row and row[0]:
                    return row[0] if row[0].tzinfo else row[0].replace(tzinfo=timezone.utc)
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.warning(f"Could not read {source} watermark from DB: {e}")

        return datetime.now(timezone.utc) - timedelta(hours=24)

    def watermark_exists(self, source: str) -> bool:
        """Return True if a watermark row exists in DB for this source."""
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                return False
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT 1 FROM trigger_watermarks WHERE source = %s",
                    (source,),
                )
                exists = cur.fetchone() is not None
                cur.close()
                return exists
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.warning(f"Could not check watermark existence for {source}: {e}")
            return False

    def set_watermark(self, source: str, timestamp: datetime = None):
        """Update watermark after successful processing (PostgreSQL upsert)."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                logger.warning(f"No DB connection — could not update {source} watermark")
                return
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO trigger_watermarks (source, last_seen, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (source) DO UPDATE
                        SET last_seen = EXCLUDED.last_seen, updated_at = NOW()
                    """,
                    (source, timestamp),
                )
                conn.commit()
                cur.close()
                logger.info(f"Watermark updated for {source}: {timestamp.isoformat()}")
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.error(f"Failed to set watermark for {source}: {e}")

    # -------------------------------------------------------
    # Cursor Storage (opaque strings — Dropbox, etc.)
    # -------------------------------------------------------

    def get_cursor(self, source: str) -> Optional[str]:
        """Get stored cursor string for a trigger source. Returns None if not set."""
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                return None
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT cursor_data FROM trigger_watermarks WHERE source = %s",
                    (source,),
                )
                row = cur.fetchone()
                cur.close()
                return row[0] if row and row[0] else None
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.warning(f"Could not read {source} cursor from DB: {e}")
            return None

    def set_cursor(self, source: str, cursor: str):
        """Store an opaque cursor string for a trigger source."""
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                logger.warning(f"No DB connection — could not update {source} cursor")
                return
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO trigger_watermarks (source, cursor_data, last_seen)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (source) DO UPDATE
                        SET cursor_data = EXCLUDED.cursor_data, last_seen = NOW(), updated_at = NOW()
                    """,
                    (source, cursor),
                )
                conn.commit()
                cur.close()
                logger.info(f"Cursor updated for {source} ({len(cursor)} chars)")
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.error(f"Failed to set cursor for {source}: {e}")

    # -------------------------------------------------------
    # Briefing Queue
    # -------------------------------------------------------

    def get_briefing_queue(self) -> list:
        """Get queued low-priority items for daily briefing from PostgreSQL."""
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                return []
            try:
                cur = conn.cursor()
                cur.execute("SELECT item FROM briefing_queue ORDER BY created_at")
                rows = cur.fetchall()
                cur.close()
                return [row[0] for row in rows]
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.warning(f"Could not read briefing queue: {e}")
            return []

    def add_to_briefing_queue(self, items: list):
        """Add low-priority items to briefing queue in PostgreSQL."""
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                logger.warning("No DB connection — skipping briefing queue add")
                return
            try:
                cur = conn.cursor()
                for item in items:
                    cur.execute(
                        "INSERT INTO briefing_queue (item) VALUES (%s::jsonb)",
                        (json.dumps(item, default=str),),
                    )
                conn.commit()
                cur.close()
                logger.info(f"Added {len(items)} items to briefing queue")
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.error(f"Failed to add to briefing queue: {e}")

    def clear_briefing_queue(self):
        """Clear after morning briefing generated."""
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                return
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM briefing_queue")
                conn.commit()
                cur.close()
                logger.info("Briefing queue cleared")
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.error(f"Failed to clear briefing queue: {e}")

    # -------------------------------------------------------
    # Processed ID tracking (for dedup)
    # -------------------------------------------------------

    def is_processed(self, source: str, source_id: str) -> bool:
        """Check if a source_id has already been processed (via trigger_log).
        Uses SentinelStoreBack's connection pool to avoid connection leaks.
        """
        try:
            store = self._get_store()
            conn = store._get_conn()
            if not conn:
                logger.warning("No pooled DB connection — assuming not processed")
                return False
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT 1 FROM trigger_log WHERE source_id = %s LIMIT 1",
                    (source_id,),
                )
                exists = cur.fetchone() is not None
                cur.close()
                return exists
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.warning(f"Could not check processed status: {e}")
            return False


# Global instance
trigger_state = TriggerState()
