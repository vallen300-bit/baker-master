#!/usr/bin/env python3
"""BAKER_SUBSTACK_SEARCH_1 — Substack archive backfill into Qdrant.

Generic, publication-scoped: walks `<publication>.substack.com/api/v1/archive`,
fetches each post with Director's session cookie, embeds via Voyage (1024d),
upserts into Qdrant collection `baker-substack-<publication>`.

Usage:
    python3 scripts/backfill_substack_archive.py --publication natesnewsletter --dry-run
    python3 scripts/backfill_substack_archive.py --publication natesnewsletter --apply

Env required (sourced from 1Password before invocation):
    VOYAGE_API_KEY                  — Voyage AI key
    QDRANT_URL + QDRANT_API_KEY     — Qdrant Cloud
    SUBSTACK_COOKIE_<publication>   — substack.sid session cookie (one per paid sub)

Companion to triggers/substack_ingest.py (PR #248 forward-flow). This script
covers pre-subscription archive; the trigger covers new posts as they arrive.
Both write into the same Qdrant collection — idempotent point IDs (Substack
post_id) make re-runs cheap.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbl.voyage_client import embed as voyage_embed  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_substack_archive")

_REQUIRED_ENV_BASE = ("VOYAGE_API_KEY", "QDRANT_URL", "QDRANT_API_KEY")
_ARCHIVE_PAGE_SIZE = 50
_ARCHIVE_PAGE_DELAY_SEC = 0.3
_POST_FETCH_DELAY_SEC = 0.5
_HTTP_TIMEOUT_SEC = 30.0
_BODY_TEXT_CAP_BYTES = 8000
_BODY_MIN_CHARS = 200
_USER_AGENT = "BakerSubstackBackfill/1.0 (+brisengroup.com)"


class CookieExpiredError(RuntimeError):
    """Raised when Substack returns auth-required for a post that should be accessible.

    Surfaced + halt rather than silently inserting zero-body entries (brief §Quality
    Checkpoint #9).
    """


def _check_required_env(publication: str) -> None:
    """Fail fast if env vars are missing. Lists all missing in one error."""
    cookie_var = f"SUBSTACK_COOKIE_{publication}"
    required = [v for v in _REQUIRED_ENV_BASE if not os.environ.get(v)]
    if not os.environ.get(cookie_var):
        required.append(cookie_var)
    if required:
        msg = (
            "ERROR: missing required environment variables:\n"
            + "\n".join(f"  - {v}" for v in required)
            + "\nSource from 1Password before running. Examples:\n"
            + "  export VOYAGE_API_KEY=\"$(op read 'op://Baker API Keys/VOYAGE_API_KEY/credential')\"\n"
            + f"  export {cookie_var}=\""
              "$(op read 'op://Baker API Keys/SUBSTACK_COOKIE_"
              f"{publication}/credential')\"\n"
            + "Exiting (no init was performed)."
        )
        print(msg, file=sys.stderr)
        sys.exit(2)


def _fetch_archive(publication: str, cookie: str) -> list[dict]:
    """Paginate archive endpoint until empty page. Returns list of post metadata."""
    posts: list[dict] = []
    offset = 0
    headers = {
        "Cookie": f"substack.sid={cookie}",
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    with httpx.Client(timeout=_HTTP_TIMEOUT_SEC) as client:
        while True:
            url = (
                f"https://{publication}.substack.com/api/v1/archive"
                f"?sort=new&limit={_ARCHIVE_PAGE_SIZE}&offset={offset}"
            )
            try:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                batch = resp.json()
            except httpx.HTTPError as e:
                logger.error("archive fetch failed at offset=%d: %s", offset, e)
                raise
            if not batch:
                break
            posts.extend(batch)
            logger.info("archive page offset=%d size=%d (running total: %d)", offset, len(batch), len(posts))
            if len(batch) < _ARCHIVE_PAGE_SIZE:
                break
            offset += _ARCHIVE_PAGE_SIZE
            time.sleep(_ARCHIVE_PAGE_DELAY_SEC)
    return posts


def _fetch_post_body(publication: str, slug: str, cookie: str) -> Optional[dict]:
    """Fetch single post with full body. Returns None on HTTP error.

    Raises CookieExpiredError if response indicates auth required.
    """
    url = f"https://{publication}.substack.com/api/v1/posts/{slug}"
    headers = {
        "Cookie": f"substack.sid={cookie}",
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
    }
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT_SEC) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code == 401 or resp.status_code == 403:
            raise CookieExpiredError(
                f"Substack returned {resp.status_code} for {slug} — "
                "session cookie likely expired; re-extract from logged-in Chrome."
            )
        if resp.status_code != 200:
            logger.warning("post fetch %s returned HTTP %d", slug, resp.status_code)
            return None
        return resp.json()
    except httpx.HTTPError as e:
        logger.warning("post fetch %s failed: %s", slug, e)
        return None


def _html_to_text(body_html: str) -> str:
    """Strip HTML tags; preserve paragraph breaks."""
    return BeautifulSoup(body_html, "html.parser").get_text(separator="\n\n", strip=True)


def _ensure_collection(qdrant, collection_name: str) -> None:
    """Idempotent create-if-missing."""
    from qdrant_client.models import Distance, VectorParams

    try:
        qdrant.get_collection(collection_name)
        logger.info("collection exists: %s", collection_name)
    except Exception:
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )
        logger.info("collection created: %s (1024d cosine)", collection_name)


def _already_indexed(qdrant, collection_name: str, point_id: str) -> bool:
    try:
        existing = qdrant.retrieve(collection_name=collection_name, ids=[point_id])
        return bool(existing)
    except Exception:
        return False


def _point_id_for_url(canonical_url: str) -> str:
    """Deterministic UUID-string ID from canonical URL.

    Same canonical URL must hash to the same ID whether ingested via this
    backfill script or via the forward-flow `triggers/substack_ingest.py` —
    that's the dedupe contract between the two paths.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, canonical_url))


def _build_payload(post: dict, body_text: str, publication: str) -> dict:
    canonical_url = post.get("canonical_url", "")
    return {
        "point_id": _point_id_for_url(canonical_url),
        "substack_post_id": post.get("id"),
        "slug": post.get("slug", ""),
        "publication": publication,
        "title": post.get("title", ""),
        "post_date": post.get("post_date", ""),
        "canonical_url": canonical_url,
        "audience": post.get("audience", ""),
        "type": post.get("type", ""),
        "preview": (post.get("search_engine_description") or "")[:300],
        "body_text": body_text[:_BODY_TEXT_CAP_BYTES],
        "char_count": len(body_text),
    }


def _upsert(qdrant, collection_name: str, payload: dict, vector: list[float]) -> None:
    from qdrant_client.models import PointStruct

    qdrant.upsert(
        collection_name=collection_name,
        points=[PointStruct(id=payload["point_id"], vector=vector, payload=payload)],
    )


def run(publication: str, apply: bool) -> int:
    _check_required_env(publication)
    cookie = os.environ[f"SUBSTACK_COOKIE_{publication}"]

    from qdrant_client import QdrantClient

    qdrant = QdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ["QDRANT_API_KEY"],
    )
    collection_name = f"baker-substack-{publication}"

    if apply:
        _ensure_collection(qdrant, collection_name)

    posts = _fetch_archive(publication, cookie)
    logger.info("archive walk complete: %d posts total in %s", len(posts), publication)

    inserted = 0
    skipped = 0
    failed: list[tuple[str, str]] = []
    est_chars = 0

    for post in posts:
        slug = post.get("slug")
        canonical_url = post.get("canonical_url", "")
        if not slug or not canonical_url:
            failed.append((slug or "?", "missing slug or canonical_url"))
            continue
        point_id = _point_id_for_url(canonical_url)

        # Idempotency: skip if Qdrant already has this point (apply mode only)
        if apply and _already_indexed(qdrant, collection_name, point_id):
            skipped += 1
            continue

        # Cookie-expiry path raises CookieExpiredError + halts (brief Q9)
        full = _fetch_post_body(publication, slug, cookie)
        if not full or not full.get("body_html"):
            audience = post.get("audience", "")
            logger.warning("no body for %s (audience=%s) — skipping", slug, audience)
            failed.append((slug, f"no body_html (audience={audience})"))
            continue

        body_text = _html_to_text(full["body_html"])
        if len(body_text) < _BODY_MIN_CHARS:
            logger.warning("body too short for %s (%d chars) — possible paywall", slug, len(body_text))
            failed.append((slug, f"body too short ({len(body_text)} chars)"))
            continue

        est_chars += len(body_text)
        payload = _build_payload(post, body_text, publication)

        if apply:
            try:
                vector = voyage_embed(body_text)
                _upsert(qdrant, collection_name, payload, vector)
                inserted += 1
                logger.info("OK %s (%d chars)", slug, len(body_text))
            except Exception as e:
                logger.warning("upsert failed for %s: %s", slug, e)
                failed.append((slug, str(e)))
        else:
            logger.info("DRY would index %s (%d chars)", slug, len(body_text))

        time.sleep(_POST_FETCH_DELAY_SEC)

    est_tokens = est_chars // 4  # rough chars→tokens
    est_cost = (est_tokens / 1_000_000) * 0.06  # voyage-3 = $0.06/M tokens

    logger.info(
        "DONE — inserted=%d skipped=%d failed=%d (est_tokens=%d est_voyage_cost=$%.4f)",
        inserted, skipped, len(failed), est_tokens, est_cost,
    )
    if failed:
        for slug, reason in failed[:10]:
            logger.info("  FAIL %s: %s", slug, reason)
        if len(failed) > 10:
            logger.info("  ... and %d more", len(failed) - 10)

    return 0 if not failed or apply else 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument("--publication", required=True,
                   help="Substack publication subdomain (e.g. natesnewsletter)")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="Walk archive + count posts; no Qdrant writes.")
    mode.add_argument("--apply", action="store_true",
                      help="Embed + upsert into Qdrant.")
    args = p.parse_args(argv)
    return run(publication=args.publication, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
