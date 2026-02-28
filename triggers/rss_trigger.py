"""
Sentinel Trigger — RSS/Atom Feeds
Polls active feeds from PostgreSQL every 60 minutes.
Downloads articles, deduplicates by URL hash, ingests into
Qdrant baker-documents + PostgreSQL rss_articles, and feeds
new articles into the Sentinel pipeline.

Called by scheduler every 60 minutes.

Pattern: follows dropbox_trigger.py structure (lazy imports, module-level entry point).

No external API keys required. Zero cost.
Deprecation check date: N/A — RSS is an open standard.
"""
import hashlib
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from triggers.state import trigger_state

logger = logging.getLogger("sentinel.rss_trigger")


def _get_client():
    """Get the global RssClient singleton."""
    from triggers.rss_client import RssClient
    return RssClient._get_global_instance()


def _get_store():
    """Get the global SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _url_hash(url: str) -> str:
    """SHA-256 hash of a URL string."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


# -------------------------------------------------------
# Main poll entry point
# -------------------------------------------------------

def run_rss_poll():
    """Main entry point — called by scheduler every 60 minutes."""
    logger.info("RSS trigger: starting poll...")

    from config.settings import config

    client = _get_client()
    store = _get_store()
    rss_config = config.rss

    # 1. Load active feeds from PostgreSQL
    feeds = _get_active_feeds(store)
    if not feeds:
        logger.warning(
            "No RSS feeds configured. Upload OPML via POST /api/rss/import-opml"
        )
        return

    feeds_polled = 0
    articles_ingested = 0
    articles_skipped = 0
    feeds_errored = 0

    # 2. Poll each feed
    for feed in feeds:
        feed_id = feed["id"]
        feed_url = feed["feed_url"]
        feed_title = feed.get("title") or feed_url
        url_h = _url_hash(feed_url)
        watermark_key = f"rss:{url_h}"

        # 2a. Get watermark
        watermark = trigger_state.get_watermark(watermark_key)

        # 2b. Fetch feed
        try:
            articles = client.fetch_feed(feed_url)
        except Exception as e:
            logger.warning(f"Error fetching feed {feed_title}: {e}")
            _increment_failures(store, feed_id)
            feeds_errored += 1
            continue

        if articles is None:
            articles = []

        feeds_polled += 1

        # If fetch returned empty (client logs its own warnings)
        if not articles:
            _update_last_polled(store, feed_id)
            continue

        # 2c. Filter by watermark + age
        cutoff = datetime.now(timezone.utc) - timedelta(days=rss_config.max_article_age_days)
        new_articles = []
        for article in articles:
            pub = article.get("published")
            if pub is None:
                # No publish date — include it but it won't advance watermark
                new_articles.append(article)
                continue
            if pub <= watermark:
                articles_skipped += 1
                continue
            if pub < cutoff:
                articles_skipped += 1
                continue
            new_articles.append(article)

        # Safety cap
        new_articles = new_articles[:rss_config.max_articles_per_feed]

        if new_articles:
            _reset_failures(store, feed_id)
        else:
            _increment_failures(store, feed_id)
            logger.warning(f"RSS feed {feed_title}: no new articles after filtering, incrementing failures")

        # 2d. Process each new article
        latest_pub = watermark
        for article in new_articles:
            link = article.get("link", "")
            if not link:
                articles_skipped += 1
                continue

            article_hash = _url_hash(link)

            # Dedup check
            if _article_exists(store, article_hash):
                articles_skipped += 1
                continue

            # Store metadata in PostgreSQL
            _store_article(store, feed_id, article, article_hash)

            # Embed to Qdrant
            _embed_article(store, article, feed_title, rss_config.collection)

            # Feed to pipeline
            _feed_to_pipeline(article, feed_title, url_h)

            articles_ingested += 1

            # Track latest published date
            pub = article.get("published")
            if pub and pub > latest_pub:
                latest_pub = pub

        # 2e. Update watermark
        if latest_pub > watermark:
            trigger_state.set_watermark(watermark_key, latest_pub)

        _update_last_polled(store, feed_id)

    # 3. Summary
    logger.info(
        f"RSS poll complete: {feeds_polled} feeds polled, "
        f"{articles_ingested} articles ingested, {articles_skipped} skipped, "
        f"{feeds_errored} errors"
    )


# -------------------------------------------------------
# OPML Import
# -------------------------------------------------------

def import_opml(opml_content: str) -> dict:
    """Parse OPML XML string and populate rss_feeds table.

    Returns {"imported": N, "skipped_duplicates": M, "total_active": T}.
    """
    client = _get_client()
    store = _get_store()

    feeds = client.parse_opml(opml_content)
    if not feeds:
        return {"imported": 0, "skipped_duplicates": 0, "total_active": 0}

    imported = 0
    skipped = 0

    conn = store._get_conn()
    if not conn:
        logger.error("No DB connection — cannot import OPML")
        return {"imported": 0, "skipped_duplicates": 0, "total_active": 0}

    try:
        cur = conn.cursor()
        for feed in feeds:
            try:
                cur.execute(
                    """
                    INSERT INTO rss_feeds (feed_url, title, category, html_url)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (feed_url) DO NOTHING
                    """,
                    (feed["url"], feed["title"], feed.get("category"), feed.get("html_url")),
                )
                if cur.rowcount > 0:
                    imported += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning(f"Failed to insert feed {feed.get('url')}: {e}")
                conn.rollback()
                skipped += 1
                continue

        conn.commit()

        # Get total active count
        cur.execute("SELECT COUNT(*) FROM rss_feeds WHERE is_active = TRUE")
        total_active = cur.fetchone()[0]
        cur.close()
    finally:
        store._put_conn(conn)

    logger.info(f"OPML import: {imported} imported, {skipped} duplicates, {total_active} total active")
    return {"imported": imported, "skipped_duplicates": skipped, "total_active": total_active}


# -------------------------------------------------------
# Database helpers
# -------------------------------------------------------

def _get_active_feeds(store) -> list[dict]:
    """Load active feeds from rss_feeds table."""
    conn = store._get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, feed_url, title, category FROM rss_feeds WHERE is_active = TRUE ORDER BY id"
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        logger.error(f"Failed to load RSS feeds: {e}")
        return []
    finally:
        store._put_conn(conn)


def _article_exists(store, url_hash: str) -> bool:
    """Check if article URL hash already exists in rss_articles."""
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM rss_articles WHERE url_hash = %s LIMIT 1", (url_hash,))
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception as e:
        logger.warning(f"Dedup check failed: {e}")
        return False
    finally:
        store._put_conn(conn)


def _store_article(store, feed_id: int, article: dict, url_hash: str):
    """Insert article metadata into rss_articles table."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO rss_articles (feed_id, url_hash, title, url, author, published_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (url_hash) DO NOTHING
            """,
            (
                feed_id,
                url_hash,
                (article.get("title") or "")[:500],
                (article.get("link") or "")[:2000],
                (article.get("author") or "")[:200],
                article.get("published"),
            ),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"Failed to store article: {e}")
    finally:
        store._put_conn(conn)


def _increment_failures(store, feed_id: int):
    """Increment consecutive_failures. Disable feed at 5."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE rss_feeds
            SET consecutive_failures = consecutive_failures + 1,
                last_polled = NOW()
            WHERE id = %s
            RETURNING consecutive_failures
            """,
            (feed_id,),
        )
        row = cur.fetchone()
        if row and row[0] >= 5:
            cur.execute(
                "UPDATE rss_feeds SET is_active = FALSE WHERE id = %s", (feed_id,)
            )
            logger.warning(f"RSS feed {feed_id} disabled after 5 consecutive failures")
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"Failed to update failure count for feed {feed_id}: {e}")
    finally:
        store._put_conn(conn)


def _reset_failures(store, feed_id: int):
    """Reset consecutive_failures to 0 on successful fetch."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE rss_feeds SET consecutive_failures = 0 WHERE id = %s", (feed_id,)
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"Failed to reset failures for feed {feed_id}: {e}")
    finally:
        store._put_conn(conn)


def _update_last_polled(store, feed_id: int):
    """Set last_polled timestamp."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("UPDATE rss_feeds SET last_polled = NOW() WHERE id = %s", (feed_id,))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"Failed to update last_polled for feed {feed_id}: {e}")
    finally:
        store._put_conn(conn)


# -------------------------------------------------------
# Qdrant embedding
# -------------------------------------------------------

def _embed_article(store, article: dict, feed_title: str, collection: str):
    """Embed article text into Qdrant baker-documents collection."""
    title = article.get("title") or ""
    content = article.get("content") or article.get("summary") or ""
    link = article.get("link") or ""

    if not title and not content:
        return

    embed_text = f"[RSS] {feed_title} — {title}\n{content[:3000]}".strip()

    metadata = {
        "source": "rss",
        "feed_title": feed_title,
        "article_title": title[:200],
        "url": link[:2000],
        "author": (article.get("author") or "")[:200],
        "published": article["published"].isoformat() if article.get("published") else "",
        "content_type": "article",
        "label": f"rss:{title[:80]}",
        "date": (
            article["published"].strftime("%Y-%m-%d")
            if article.get("published")
            else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ),
    }

    try:
        store.store_document(embed_text, metadata, collection=collection)
    except Exception as e:
        logger.warning(f"Failed to embed article '{title[:60]}' to Qdrant: {e}")


# -------------------------------------------------------
# Pipeline feed
# -------------------------------------------------------

def _feed_to_pipeline(article: dict, feed_title: str, url_hash: str):
    """Feed article into Sentinel pipeline."""
    try:
        from orchestrator.pipeline import SentinelPipeline, TriggerEvent

        content_text = article.get("content") or article.get("summary") or ""

        trigger = TriggerEvent(
            type="rss_article_new",
            content=(
                f"Source: {feed_title}\n"
                f"Title: {article.get('title', '')}\n"
                f"URL: {article.get('link', '')}\n"
                f"Published: {article.get('published', '')}\n\n"
                f"{content_text[:2000]}"
            ),
            source_id=f"rss:{url_hash}",
            contact_name=None,
        )

        pipeline = SentinelPipeline()
        pipeline.run(trigger)
    except Exception as e:
        logger.warning(f"Pipeline feed failed for '{article.get('title', '?')[:60]}': {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    run_rss_poll()
