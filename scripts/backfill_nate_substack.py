"""SUBSTACK_NATE_INGEST_1 30-day backfill.

Run once: pulls last 30 days of Nate Substack posts from Gmail, runs them
through the same ingest module the live trigger uses. Idempotent — if a target
file already exists, skip.

Pre-verify finding (2026-05-23): scripts/extract_gmail.py has no
`_build_gmail_service` helper; the existing pattern is `authenticate()` +
`build("gmail", "v1", credentials=creds)` inline (extract_gmail.py:1095-1097).
This script replicates that pattern locally rather than inventing a helper.

Usage:
    python3 scripts/backfill_nate_substack.py [--days 30] [--dry-run]

Post-merge handoff: AI Head runs this once after the PR merges. NOT a B-code task.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from googleapiclient.discovery import build  # noqa: E402

from scripts.extract_gmail import authenticate  # noqa: E402
from triggers.substack_ingest import (  # noqa: E402
    ingest as substack_ingest_run,
    is_substack_nate,
)

logger = logging.getLogger("substack_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _header(headers: list[dict], name: str) -> str:
    """Case-insensitive header lookup. Returns '' if not found."""
    target = name.lower()
    for h in headers:
        if h.get("name", "").lower() == target:
            return h.get("value", "")
    return ""


def run(days: int = 30, dry_run: bool = False) -> int:
    """Returns count of files written (0 if dry_run)."""
    creds = authenticate()
    svc = build("gmail", "v1", credentials=creds)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    query = f"list:natesnewsletter.substack.com after:{cutoff.strftime('%Y/%m/%d')}"
    logger.info("backfill query: %s", query)

    page_token = None
    written = 0
    seen = 0
    while True:
        resp = svc.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token,
        ).execute()
        for m in resp.get("messages", []) or []:
            seen += 1
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="full",
            ).execute()
            payload = full.get("payload", {}) or {}
            headers = payload.get("headers", []) or []

            sender = _header(headers, "From")
            subject = _header(headers, "Subject")
            received = full.get("internalDate")
            if received:
                received_dt = datetime.fromtimestamp(int(received) / 1000, tz=timezone.utc)
            else:
                received_dt = datetime.now(timezone.utc)

            if not is_substack_nate(headers, sender):
                continue
            if dry_run:
                logger.info("DRY %s | %s | %s", received_dt.date(), subject[:60], m["id"])
                continue

            out = substack_ingest_run(
                gmail_message_id=m["id"],
                headers=headers,
                sender_email=sender,
                subject=subject,
                received_date=received_dt,
                raw_payload=payload,
            )
            if out:
                written += 1
                logger.info("WROTE %s", out.name)
            else:
                logger.info("SKIP %s (already-ingested or no-html)", subject[:60])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    logger.info("backfill complete: seen=%d written=%d dry_run=%s", seen, written, dry_run)
    return written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
