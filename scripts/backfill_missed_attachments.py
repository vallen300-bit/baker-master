"""
EMAIL-ATTACH-FIX-1: Re-process emails that have attachments in Gmail but
no documents in Baker. Uses the fixed recursive MIME traversal to catch
forwarded email attachments.

Run: python3 scripts/backfill_missed_attachments.py --days 30
"""
import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_attachments")


def run(days: int = 30, dry_run: bool = False):
    from scripts.extract_gmail import authenticate, extract_attachments_text, _collect_attachment_parts
    from googleapiclient.discovery import build
    import scripts.extract_gmail as eg

    service = build("gmail", "v1", credentials=authenticate())
    eg._gmail_service = service

    # Find emails that SHOULD have attachments but don't have docs
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        print("No DB connection")
        return

    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get emails from last N days
        cur.execute("""
            SELECT message_id, subject, received_date
            FROM email_messages
            WHERE received_date > NOW() - INTERVAL '%s days'
            ORDER BY received_date DESC
        """, (days,))
        emails = cur.fetchall()

        # Get existing email attachment docs
        cur.execute("SELECT source_path FROM documents WHERE source_path LIKE 'email:%%'")
        existing_paths = {r['source_path'] for r in cur.fetchall()}
        cur.close()
    finally:
        store._put_conn(conn)

    print(f"Checking {len(emails)} emails from last {days} days, {len(existing_paths)} existing attachment docs")

    found = 0
    stored = 0
    for i, email in enumerate(emails):
        mid = email['message_id']

        try:
            # Fetch full message from Gmail
            msg = service.users().messages().get(userId="me", id=mid, format="full").execute()

            # Check for attachment parts (using the fixed recursive collector)
            payload = msg.get("payload", {})
            att_parts = _collect_attachment_parts(payload)

            for part in att_parts:
                fname = part.get("filename", "")
                expected_path = f"email:{mid}/{fname}"

                if expected_path not in existing_paths:
                    found += 1
                    if not dry_run:
                        # Process this message's attachments
                        results = extract_attachments_text(service, msg)
                        stored += len(results)
                        print(f"  [{i+1}/{len(emails)}] {email['subject'][:60]} — found {len(results)} new attachments")
                    else:
                        print(f"  [DRY RUN] {email['subject'][:60]} — missing: {fname}")
                    break  # Already processed all attachments for this message

        except Exception as e:
            logger.debug(f"Failed to check {mid}: {e}")

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(emails)} checked, {found} missing found, {stored} stored")

    print(f"\nDone. {found} emails had missing attachments, {stored} new docs stored.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill missed email attachments (forwarded emails)")
    parser.add_argument("--days", type=int, default=30, help="Look back N days")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()
    run(days=args.days, dry_run=args.dry_run)
