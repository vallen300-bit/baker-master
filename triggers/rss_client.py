"""
Sentinel AI — RSS/Atom Feed Client
Parses OPML exports, fetches RSS/Atom feeds via httpx + feedparser.
Singleton pattern matching todoist_client.py / dropbox_client.py.

No external API keys required. Zero cost.
"""
import logging
import time
import xml.etree.ElementTree as ET
from calendar import timegm
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx

from config.settings import config

logger = logging.getLogger("sentinel.rss_client")

_USER_AGENT = "Baker-AI/1.0 (RSS Sentinel)"


class RssClient:
    """RSS/Atom feed client — OPML parsing + feed fetching."""

    _instance = None

    @classmethod
    def _get_global_instance(cls):
        """Return the module-level singleton. Lazy-init if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._client = httpx.Client(
            timeout=config.rss.request_timeout,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        self._request_count = 0
        self._last_request_time = 0.0

    # -------------------------------------------------------
    # OPML Parsing
    # -------------------------------------------------------

    def parse_opml(self, opml_content: str) -> list[dict]:
        """Parse OPML XML string into a list of feed dicts.

        Returns list of {url, title, category, html_url}.
        Handles nested <outline> elements (Feedly exports nest feeds under categories).
        """
        feeds = []
        try:
            root = ET.fromstring(opml_content)
        except ET.ParseError as e:
            logger.error(f"OPML parse error: {e}")
            return feeds

        body = root.find("body")
        if body is None:
            logger.warning("OPML has no <body> element")
            return feeds

        self._parse_outlines(body, feeds, category=None)
        logger.info(f"Parsed {len(feeds)} feeds from OPML")
        return feeds

    def _parse_outlines(self, parent, feeds: list, category: Optional[str]):
        """Recursively parse <outline> elements."""
        for outline in parent.findall("outline"):
            xml_url = outline.get("xmlUrl")
            if xml_url:
                # This is a feed entry
                feeds.append({
                    "url": xml_url.strip(),
                    "title": outline.get("title") or outline.get("text") or "",
                    "category": category,
                    "html_url": outline.get("htmlUrl") or "",
                })
            else:
                # This is a category folder — recurse
                folder_name = outline.get("title") or outline.get("text") or category
                self._parse_outlines(outline, feeds, category=folder_name)

    # -------------------------------------------------------
    # Feed Fetching
    # -------------------------------------------------------

    def fetch_feed(self, url: str) -> list[dict]:
        """Fetch and parse an RSS/Atom feed URL.

        Returns list of {title, link, published, author, summary, content}.
        On error: logs warning, returns empty list.
        """
        self._rate_limit()

        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching feed: {url}")
            return []
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP {e.response.status_code} fetching feed: {url}")
            return []
        except Exception as e:
            logger.warning(f"Error fetching feed {url}: {e}")
            return []

        self._request_count += 1

        try:
            feed = feedparser.parse(resp.text)
        except Exception as e:
            logger.warning(f"feedparser error for {url}: {e}")
            return []

        articles = []
        for entry in feed.entries:
            published = self._parse_published(entry)
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            if not content:
                content = getattr(entry, "summary", "")

            articles.append({
                "title": getattr(entry, "title", ""),
                "link": getattr(entry, "link", ""),
                "published": published,
                "author": getattr(entry, "author", ""),
                "summary": getattr(entry, "summary", ""),
                "content": content,
            })

        return articles

    # -------------------------------------------------------
    # Helpers
    # -------------------------------------------------------

    def _parse_published(self, entry) -> Optional[datetime]:
        """Convert feedparser's struct_time to datetime. Returns None if unparseable."""
        for attr in ("published_parsed", "updated_parsed"):
            st = getattr(entry, attr, None)
            if st:
                try:
                    return datetime.fromtimestamp(timegm(st), tz=timezone.utc)
                except Exception:
                    continue
        return None

    def _rate_limit(self):
        """Enforce max 1 request per second to be polite to feed hosts."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self._last_request_time = time.time()
