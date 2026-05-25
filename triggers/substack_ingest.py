"""Substack ingest — Nate's Newsletter v1 (SUBSTACK_NATE_INGEST_1).

Detects Substack emails via List-Id header, extracts (title, post URL, publish
date, body HTML→markdown, paid-tier flag), writes one markdown file per post
to ~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/YYYY-MM-DD-<slug>.md.

Called from triggers/email_trigger.py BEFORE _should_skip_pipeline(). Failures
are caught + logged + reported to sentinel_health — never propagated up.

Implementation note (pre-verify finding 2026-05-23): `format_thread()` in
scripts/extract_gmail.py strips raw headers + HTML payload before exposing the
thread dict to email_trigger.py. The caller therefore uses sender-email
substring as cheap pre-filter, then `fetch_full_message()` to round-trip back
to Gmail for headers + HTML body before calling `is_substack_nate` + `ingest`.

API: Gmail v1 (googleapiclient). Last verified 2026-05-23. Substack adds
List-Id headers to every newsletter email; format stable since 2020.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import html2text

from triggers.sentinel_health import report_failure, report_success

logger = logging.getLogger("sentinel.trigger.substack_ingest")


def _safe_report_success(source: str) -> None:
    """Swallow health-reporter exceptions — must not break ingest path."""
    try:
        report_success(source)
    except Exception as e:
        logger.debug("substack_ingest: report_success(%s) failed (non-fatal): %s", source, e)


def _safe_report_failure(source: str, error: str) -> None:
    try:
        report_failure(source, error)
    except Exception as e:
        logger.debug("substack_ingest: report_failure(%s) failed (non-fatal): %s", source, e)

_DEFAULT_VAULT = Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))
_NATE_DIR = _DEFAULT_VAULT / "wiki" / "_ai-it" / "aid-t" / "external-substack" / "nate"

NATE_SENDER_SUBSTRING = "natesnewsletter.substack.com"

# Canonical Nate List-Id format: "post.natesnewsletter.substack.com <id.list-id.substack.com>"
# Word boundaries prevent substring spoofing from third-party Substack publishers.
_LIST_ID_RE = re.compile(r"\bpost\.natesnewsletter\.substack\.com\b", re.IGNORECASE)
_SENDER_FALLBACK_RE = re.compile(r"@.*natesnewsletter\.substack\.com", re.IGNORECASE)

_PAID_TIER_MARKERS = (
    "this post is for paying subscribers",
    "this post is for paid subscribers",
    "subscribe to read",
    "upgrade to paid",
)


def is_substack_nate_sender(sender_email: str | None) -> bool:
    """Cheap pre-filter — substring match on sender domain.

    Used by email_trigger.py before paying the cost of a Gmail round-trip
    to fetch raw headers + HTML body.
    """
    if not sender_email:
        return False
    return NATE_SENDER_SUBSTRING in sender_email.lower()


def is_substack_nate(headers: list[dict] | None, sender_email: str | None) -> bool:
    """Return True if message looks like a Nate Substack post.

    Args:
        headers: list of {name, value} dicts from Gmail API payload.
        sender_email: From: address (may be None).
    """
    for h in headers or []:
        if h.get("name", "").lower() == "list-id" and _LIST_ID_RE.search(h.get("value", "")):
            return True
    if sender_email and _SENDER_FALLBACK_RE.search(sender_email):
        return True
    return False


def fetch_full_message(gmail_message_id: str) -> dict | None:
    """Re-fetch raw Gmail message in 'full' format to get headers + HTML body.

    format_thread() in scripts/extract_gmail.py strips the raw payload before
    exposing the thread to email_trigger.py, so the caller must round-trip
    back to Gmail when it needs headers or the HTML body. Uses the existing
    module-level `_gmail_service` handle set by email_trigger.py at startup
    (extract_gmail.py:441 ARCH-6).

    Returns the raw API dict or None on failure (logged, never raised).
    """
    try:
        from scripts import extract_gmail
        svc = getattr(extract_gmail, "_gmail_service", None)
        if svc is None:
            logger.warning(
                "substack_ingest.fetch_full_message: _gmail_service not set; "
                "cannot fetch msg %s", gmail_message_id,
            )
            return None
        request = svc.users().messages().get(
            userId="me", id=gmail_message_id, format="full",
        )
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(request.execute)
            try:
                return future.result(timeout=10)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "substack_ingest.fetch_full_message: 10s timeout for msg %s "
                    "(Gmail API hung); abandoning ingest for this message",
                    gmail_message_id,
                )
                _safe_report_failure("substack_ingest", "fetch_full_message timeout 10s")
                return None
    except Exception as e:
        logger.warning(
            "substack_ingest.fetch_full_message failed for %s: %s",
            gmail_message_id, e,
        )
        return None


def _slugify(title: str) -> str:
    """Conservative ASCII slug: lowercase, dashes, max 60 chars."""
    s = re.sub(r"[^a-z0-9]+", "-", (title or "untitled").lower()).strip("-")
    return s[:60] or "untitled"


def _extract_html_body(message_payload: dict | None) -> str | None:
    """Walk Gmail payload parts to find the text/html part. Returns decoded HTML or None."""
    if not message_payload:
        return None

    def walk(part):
        mime = part.get("mimeType", "")
        if mime == "text/html":
            data = part.get("body", {}).get("data")
            if data:
                padded = data.replace("-", "+").replace("_", "/")
                padded += "=" * (-len(padded) % 4)
                try:
                    return base64.b64decode(padded).decode("utf-8", errors="replace")
                except Exception:
                    return None
        for sub in part.get("parts", []) or []:
            result = walk(sub)
            if result:
                return result
        return None

    return walk(message_payload)


def _extract_post_url(html: str | None) -> str | None:
    """First href pointing at natesnewsletter.substack.com/p/ — that's the canonical post URL."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "natesnewsletter.substack.com/p/" in href:
            return href.split("?")[0]
    return None


def _detect_paid_tier(html: str | None) -> bool:
    """Returns True if any paid-tier marker phrase appears in plain text of the HTML."""
    if not html:
        return False
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
    return any(marker in text for marker in _PAID_TIER_MARKERS)


def _html_to_markdown(html: str) -> str:
    """Convert email HTML body to markdown. html2text config tuned for Substack."""
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_images = False
    h.protect_links = True
    h.unicode_snob = True
    return h.handle(html).strip()


def _publication_from_url(post_url: str | None) -> str:
    """Extract publication subdomain from a Substack canonical URL.

    `https://natesnewsletter.substack.com/p/foo` → `natesnewsletter`.
    Falls back to `natesnewsletter` since current trigger is Nate-scoped.
    """
    if not post_url:
        return "natesnewsletter"
    host = (urlparse(post_url).hostname or "").lower()
    if host.endswith(".substack.com"):
        return host.split(".", 1)[0]
    return "natesnewsletter"


def _point_id_for_url(canonical_url: str) -> str:
    """Deterministic UUID-string ID — must match scripts/backfill_substack_archive.py.

    Backfill + forward-flow share the same Qdrant collection; identical IDs are
    the dedupe contract between the two paths.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, canonical_url))


def _index_to_qdrant(
    *,
    canonical_url: str,
    publication: str,
    title: str,
    post_date: str,
    paid_tier: bool,
    body_text: str,
) -> None:
    """Non-blocking embed + Qdrant upsert. Catches all exceptions.

    Markdown on disk is the ground truth; Qdrant is a derived queryable index.
    Any Qdrant or Voyage failure here MUST NOT propagate — re-backfill via
    `scripts/backfill_substack_archive.py` can recover gaps.
    """
    try:
        if not os.environ.get("VOYAGE_API_KEY") or not os.environ.get("QDRANT_URL"):
            logger.info(
                "substack_ingest: Qdrant index skipped (Voyage/Qdrant env not configured)"
            )
            return
        if not canonical_url:
            logger.info("substack_ingest: Qdrant index skipped (no canonical_url)")
            return
        if len(body_text) < 200:
            logger.info(
                "substack_ingest: Qdrant index skipped — body too short (%d chars)",
                len(body_text),
            )
            return

        from kbl.voyage_client import embed as voyage_embed
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        collection_name = f"baker-substack-{publication}"
        qdrant = QdrantClient(
            url=os.environ["QDRANT_URL"],
            api_key=os.environ.get("QDRANT_API_KEY") or os.environ.get("QDRANT_KEY"),
        )

        # Idempotent collection create (cheap if exists)
        try:
            qdrant.get_collection(collection_name)
        except Exception:
            try:
                qdrant.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
                )
            except Exception as e:
                # Race-condition tolerable: another caller may have created it
                logger.info("substack_ingest: create_collection raced/failed: %s", e)

        point_id = _point_id_for_url(canonical_url)
        payload = {
            "point_id": point_id,
            "slug": canonical_url.rstrip("/").rsplit("/", 1)[-1] if canonical_url else "",
            "publication": publication,
            "title": title,
            "post_date": post_date,
            "canonical_url": canonical_url,
            "audience": "only_paid" if paid_tier else "public",
            "source": "forward_flow_gmail",
            "body_text": body_text[:8000],
            "char_count": len(body_text),
        }

        vector = voyage_embed(body_text)
        qdrant.upsert(
            collection_name=collection_name,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )
        _safe_report_success("substack_qdrant_index")
        logger.info(
            "substack_ingest: indexed %s into %s", canonical_url, collection_name
        )
    except Exception as e:
        logger.warning("substack_ingest: Qdrant index failed (non-fatal): %s", e)
        _safe_report_failure("substack_qdrant_index", f"{type(e).__name__}:{e}")


def ingest(
    *,
    gmail_message_id: str,
    headers: list[dict],
    sender_email: str | None,
    subject: str,
    received_date: datetime,
    raw_payload: dict,
    nate_dir: Path | None = None,
) -> Path | None:
    """Idempotent ingest. Returns path to written file, or None on no-op/fail.

    Idempotency: filename is derived from received_date + slug(subject).
    If file already exists at that path, treat as already-ingested and return None.
    """
    target_dir = nate_dir or _NATE_DIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        html = _extract_html_body(raw_payload)
        if not html:
            logger.warning("substack_ingest: no HTML part in msg %s", gmail_message_id)
            _safe_report_failure("substack_ingest", f"no_html_body:{gmail_message_id}")
            return None

        post_url = _extract_post_url(html)
        paid_tier = _detect_paid_tier(html)
        body_md = _html_to_markdown(html)

        date_str = received_date.astimezone(timezone.utc).strftime("%Y-%m-%d")
        slug = _slugify(subject)
        out_path = target_dir / f"{date_str}-{slug}.md"

        if out_path.exists():
            logger.info("substack_ingest: already ingested %s", out_path.name)
            return None

        frontmatter = (
            "---\n"
            "source: nate_substack\n"
            f"url: {post_url or 'unknown'}\n"
            f"publish_date: {date_str}\n"
            f"paid_tier: {str(paid_tier).lower()}\n"
            f"ingested_at: {datetime.now(timezone.utc).isoformat()}\n"
            f"gmail_message_id: {gmail_message_id}\n"
            f"sender_email: {sender_email or ''}\n"
            f"subject: {json.dumps(subject)}\n"
            "---\n\n"
            f"# {subject}\n\n"
        )
        out_path.write_text(frontmatter + body_md, encoding="utf-8")
        _safe_report_success("substack_ingest")
        logger.info("substack_ingest: wrote %s (paid_tier=%s)", out_path.name, paid_tier)

        # Non-blocking Qdrant index for agent-queryable retrieval. Any failure
        # is logged + reported but does NOT roll back the markdown write.
        _index_to_qdrant(
            canonical_url=post_url or "",
            publication=_publication_from_url(post_url),
            title=subject,
            post_date=date_str,
            paid_tier=paid_tier,
            body_text=body_md,
        )

        return out_path
    except Exception as e:
        logger.exception("substack_ingest: failed for msg %s: %s", gmail_message_id, e)
        _safe_report_failure("substack_ingest", f"{type(e).__name__}:{e}")
        return None
