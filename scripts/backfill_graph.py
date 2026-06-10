#!/usr/bin/env python3
"""BACKFILL_GRAPH_1: historical M365 Graph backfill of dvallen@brisengroup.com.

Standalone, env-driven, resumable. Pulls Inbox + SentItems history (messages +
attachments) into email_messages + email_attachments via direct INSERT — NO LLM
classification on historical rows (priority stays NULL). Watermark-independent:
never touches trigger_state / the live graph_mail_poll cursor.

Auth reuses the existing working Graph token path (kbl.graph_client.GraphClient
+ config.settings.GraphConfig — same cert/app-token helper the live poller
uses). HTTP is done locally (NOT via GraphClient.get) because GraphClient
swallows status codes and returns None on 429 — this backfill must see
Retry-After to throttle correctly.

Resumability: cursor = @odata.nextLink persisted per page in
email_backfill_progress (source='graph:<Folder>', b3 EMAIL_ATTACHMENT_STORE_1
locked schema). Kill at any point; re-run continues from the last committed
page. A completed folder stores cursor='DONE' and is skipped on re-run
(message-level dedup via ON CONFLICT (message_id) DO NOTHING makes overlap
harmless either way).

Usage:
    python3 scripts/backfill_graph.py                 # full run, both folders
    python3 scripts/backfill_graph.py --limit 50      # dry-run cap per folder
    python3 scripts/backfill_graph.py --folders Inbox # subset

Env: DATABASE_URL (required), BAKER_USE_GRAPH=true + M365_* Graph creds
(required — GraphClient.is_ready() is the gate, same as the live poller).
"""
from __future__ import annotations

import argparse
import base64
import logging
import os
import re
import sys
import time
from urllib.parse import urlparse

import psycopg2
import requests

# Repo root on sys.path so kbl/config import when run as scripts/backfill_graph.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import GraphConfig                  # noqa: E402
from kbl.graph_client import GraphClient                 # noqa: E402
from kbl.attachment_store import (                       # noqa: E402
    insert_attachment,
    insert_attachment_meta,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("backfill_graph")

GRAPH_HOST = "graph.microsoft.com"
PAGE_SIZE = 100
PAGE_SLEEP = 0.3            # seconds between pages (brief-locked throttle)
MAX_RETRIES = 6
STORE_RETRIES = 3           # bounded retry on store-layer failure (bus #2775)
BODY_CAP = 10000            # mirror triggers/graph_mail_trigger._html_to_text cap
SELECT_FIELDS = (
    "id,conversationId,subject,from,receivedDateTime,body,isDraft,hasAttachments"
)
DONE_SENTINEL = "DONE"


# ---------------------------------------------------------------- HTTP layer

def _graph_get(client: GraphClient, url: str, *, timeout: int = 60) -> dict:
    """GET an absolute Graph URL with 429/5xx awareness. Raises on exhaustion.

    Token comes from the existing working helper (GraphClient._acquire_token —
    MSAL-cached, auto-renewing cert/secret path). Host-pinned: never attaches
    the bearer to a non-Graph URL (mirrors GraphClient._request).
    """
    p = urlparse(url)
    if p.scheme != "https" or p.hostname != GRAPH_HOST:
        raise RuntimeError("graph backfill: refusing non-Graph URL")
    for attempt in range(MAX_RETRIES):
        token = client._acquire_token()
        if not token:
            raise RuntimeError("graph backfill: token acquisition failed")
        try:
            resp = requests.get(
                url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout
            )
        except requests.RequestException as e:
            logger.warning("transient request error (%s), attempt %d/%d",
                           type(e).__name__, attempt + 1, MAX_RETRIES)
            time.sleep(2 ** attempt)
            continue
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5") or "5")
            logger.warning("429 throttled — honoring Retry-After=%ds", wait)
            time.sleep(wait)
            continue
        if resp.status_code in (500, 502, 503, 504):
            logger.warning("HTTP %d, attempt %d/%d", resp.status_code,
                           attempt + 1, MAX_RETRIES)
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"graph backfill: gave up after {MAX_RETRIES} attempts")


# ------------------------------------------------------------------ DB layer

def _connect():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(dsn)


def _ensure_progress_table(conn) -> None:
    """Defensive ensure of b3's locked email_backfill_progress DDL (IF NOT EXISTS)."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_backfill_progress (
                  source TEXT PRIMARY KEY, cursor TEXT,
                  done_count BIGINT DEFAULT 0, total_estimate BIGINT,
                  updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _get_progress(conn, source: str) -> tuple[str | None, int]:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cursor, done_count FROM email_backfill_progress WHERE source = %s",
                (source,),
            )
            row = cur.fetchone()
        return (row[0], int(row[1] or 0)) if row else (None, 0)
    except Exception:
        conn.rollback()
        raise


def _set_progress(conn, source: str, cursor: str | None, done_count: int,
                  total_estimate: int | None = None) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO email_backfill_progress (source, cursor, done_count, total_estimate, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (source) DO UPDATE SET
                    cursor = EXCLUDED.cursor,
                    done_count = EXCLUDED.done_count,
                    total_estimate = COALESCE(EXCLUDED.total_estimate,
                                              email_backfill_progress.total_estimate),
                    updated_at = now()
            """, (source, cursor, done_count, total_estimate))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _clean(s: str | None) -> str:
    """Strip NUL bytes — psycopg2 raises ValueError on 0x00 in string literals
    (hit live on historical Outlook HTML bodies, dry-run 2026-06-10)."""
    return (s or "").replace("\x00", "")


def _html_to_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", _clean(html))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:BODY_CAP]


def _insert_message(conn, m: dict) -> bool:
    """Direct INSERT, dedup ON CONFLICT (message_id) DO NOTHING.

    priority=NULL (no LLM on historical rows), source='graph'. DO NOTHING (not
    upsert) so rows already ingested by the live poller are never clobbered.
    Returns True when a NEW row was inserted, False on conflict (dup).

    A DB ERROR is NOT a dup (bus #2775 class): bounded retry, then RAISE so the
    page cursor is never advanced past a message that was silently dropped —
    counting a transient failure as "skipped" would lose the row permanently.
    """
    sender = (m.get("from") or {}).get("emailAddress") or {}
    body = (m.get("body") or {})
    last_err: Exception | None = None
    for attempt in range(STORE_RETRIES):
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO email_messages
                        (message_id, thread_id, sender_name, sender_email,
                         subject, full_body, received_date, priority, source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, 'graph')
                    ON CONFLICT (message_id) DO NOTHING
                """, (
                    m.get("id"),
                    m.get("conversationId") or m.get("id"),
                    _clean(sender.get("name", "")),
                    _clean(sender.get("address", "")),
                    _clean(m.get("subject", "")),
                    _html_to_text(body.get("content", "")),
                    m.get("receivedDateTime") or None,
                ))
                inserted = cur.rowcount == 1
            conn.commit()
            return inserted
        except Exception as e:
            conn.rollback()
            last_err = e
            logger.warning("insert_message attempt %d/%d failed for %s: %s",
                           attempt + 1, STORE_RETRIES, m.get("id"),
                           type(e).__name__)
            time.sleep(1 + attempt)
    raise RuntimeError(
        f"message store failure after {STORE_RETRIES} attempts: "
        f"message_id={m.get('id')} ({type(last_err).__name__})"
    )


def _store_with_retry(fn, *args, desc: str, **kwargs) -> int:
    """Call a b3 attachment-store function with bounded retry (bus #2775).

    The locked store API never raises and returns None on failure — a None must
    NOT count as stored. Retry STORE_RETRIES times, then raise loudly with the
    message id so backfill_folder aborts BEFORE advancing the page cursor
    (message dedup blocks re-walk, so a skipped attachment is otherwise lost
    permanently).
    """
    for attempt in range(STORE_RETRIES):
        try:
            result = fn(*args, **kwargs)
        except Exception as e:                  # defensive — API contract is no-raise
            result = None
            logger.warning("%s raised %s (attempt %d/%d)", desc,
                           type(e).__name__, attempt + 1, STORE_RETRIES)
        if result is not None:
            return result
        logger.warning("%s returned None (attempt %d/%d)", desc,
                       attempt + 1, STORE_RETRIES)
        time.sleep(1 + attempt)
    raise RuntimeError(f"attachment store failure after {STORE_RETRIES} attempts: {desc}")


# ------------------------------------------------------------- backfill core

def _process_attachments(client: GraphClient, mail_user: str,
                         message_id: str) -> int:
    """Fetch + persist all attachments for one message. Returns count stored."""
    url = (f"{client.cfg.base_url}/users/{mail_user}/messages/{message_id}"
           f"/attachments?$top=20")
    stored = 0
    while url:
        page = _graph_get(client, url)
        for att in page.get("value", []):
            otype = att.get("@odata.type", "")
            if otype == "#microsoft.graph.fileAttachment":
                raw = att.get("contentBytes")
                if raw is None:
                    # contentBytes omitted in list response (rare, very large
                    # files) — fetch the single attachment directly.
                    single = _graph_get(
                        client,
                        f"{client.cfg.base_url}/users/{mail_user}/messages/"
                        f"{message_id}/attachments/{att.get('id')}",
                    )
                    raw = single.get("contentBytes")
                if raw is None:
                    logger.warning("fileAttachment without contentBytes on %s — skipped",
                                   message_id)
                    continue
                try:
                    payload = base64.b64decode(raw)
                except Exception:
                    logger.error("base64 decode failed on %s — skipped", message_id)
                    continue
                _store_with_retry(
                    insert_attachment,
                    message_id, "graph", att.get("name"),
                    att.get("contentType"), payload,
                    desc=f"insert_attachment {message_id}/{att.get('name')}",
                )
                stored += 1
            else:
                # itemAttachment / referenceAttachment → metadata_only row via
                # b3's API (lead-ratified bus #2765; meta_key = Graph att id).
                _store_with_retry(
                    insert_attachment_meta,
                    message_id, "graph", att.get("name"),
                    att.get("contentType"), att.get("size"),
                    meta_key=att.get("id"),
                    desc=f"insert_attachment_meta {message_id}/{att.get('id')}",
                )
                stored += 1
        url = page.get("@odata.nextLink")
    return stored


def _folder_total(client: GraphClient, mail_user: str, folder: str) -> int | None:
    try:
        info = _graph_get(
            client, f"{client.cfg.base_url}/users/{mail_user}/mailFolders/{folder}"
        )
        return info.get("totalItemCount")
    except Exception as e:
        logger.warning("could not read totalItemCount for %s: %s", folder,
                       type(e).__name__)
        return None


def backfill_folder(conn, client: GraphClient, folder: str,
                    limit: int | None = None) -> dict:
    """Backfill one folder. Returns {'inserted': n, 'skipped': n, 'attachments': n}."""
    mail_user = client.cfg.mail_user
    source = f"graph:{folder}"
    cursor, done = _get_progress(conn, source)

    if cursor == DONE_SENTINEL:
        logger.info("[%s] already complete (%d done) — skipping", folder, done)
        return {"inserted": 0, "skipped": 0, "attachments": 0}

    if cursor:
        url = cursor
        logger.info("[%s] resuming from saved cursor (%d done so far)", folder, done)
    else:
        total = _folder_total(client, mail_user, folder)
        _set_progress(conn, source, None, 0, total)
        url = (f"{client.cfg.base_url}/users/{mail_user}/mailFolders/{folder}"
               f"/messages?$top={PAGE_SIZE}&$orderby=receivedDateTime asc"
               f"&$select={SELECT_FIELDS}")
        logger.info("[%s] fresh start, total_estimate=%s", folder, total)

    stats = {"inserted": 0, "skipped": 0, "attachments": 0}
    page_no = 0
    while url:
        page = _graph_get(client, url)
        page_no += 1
        batch = page.get("value", [])
        for m in batch:
            if m.get("isDraft"):
                continue
            if _insert_message(conn, m):
                stats["inserted"] += 1
            else:
                stats["skipped"] += 1
            if m.get("hasAttachments"):
                stats["attachments"] += _process_attachments(
                    client, mail_user, m.get("id")
                )
        done += len(batch)
        next_link = page.get("@odata.nextLink")
        # Persist cursor ONLY after the page's rows are committed — kill-safe.
        _set_progress(conn, source, next_link or DONE_SENTINEL, done)
        logger.info("[%s] page %d: %d msgs (+%d new, %d dup, %d att) done=%d",
                    folder, page_no, len(batch), stats["inserted"],
                    stats["skipped"], stats["attachments"], done)
        if limit is not None and done >= limit:
            logger.info("[%s] --limit %d reached, stopping (cursor saved)",
                        folder, limit)
            break
        url = next_link
        if url:
            time.sleep(PAGE_SLEEP)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M365 Graph historical mail backfill")
    ap.add_argument("--limit", type=int, default=None,
                    help="max messages per folder (dry-run cap)")
    ap.add_argument("--folders", default="Inbox,SentItems",
                    help="comma-separated Graph folder names")
    args = ap.parse_args(argv)

    client = GraphClient(GraphConfig())
    if not client.is_ready():
        logger.error("GraphClient not ready (BAKER_USE_GRAPH off or creds missing) — aborting")
        return 1

    conn = _connect()
    try:
        _ensure_progress_table(conn)
        grand = {"inserted": 0, "skipped": 0, "attachments": 0}
        for folder in [f.strip() for f in args.folders.split(",") if f.strip()]:
            try:
                stats = backfill_folder(conn, client, folder, limit=args.limit)
            except Exception as e:
                # Loud abort (bus #2775): cursor for the failed page was NOT
                # advanced — re-run resumes exactly there. Message id is in
                # the exception text.
                logger.error("ABORT in folder %s: %s — cursor NOT advanced, "
                             "re-run to resume", folder, e)
                return 2
            for k in grand:
                grand[k] += stats[k]
        logger.info("BACKFILL COMPLETE: %d inserted, %d dup-skipped, %d attachments",
                    grand["inserted"], grand["skipped"], grand["attachments"])
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
