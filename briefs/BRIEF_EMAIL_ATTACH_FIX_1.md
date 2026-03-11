# BRIEF: EMAIL-ATTACH-FIX-1 — Recursive Attachment Extraction for Forwarded Emails

**Author:** AI Head (Session 20)
**For:** Code 300
**Priority:** HIGH — Director reported missing attachment today
**Estimated scope:** 1 file (scripts/extract_gmail.py), ~30 lines changed
**Cost:** Zero — no LLM calls, just MIME traversal fix

---

## Problem

Baker misses attachments on forwarded emails. The Director forwarded the Hagenauer/LCG guarantee letter (Olga → Thomas → Edita → Director) on March 10. Baker found the email chain but the scanned PDF attachment is missing from the document store.

**Root cause:** `extract_attachments_text()` in `scripts/extract_gmail.py` (line 530) only iterates top-level MIME parts:

```python
parts = payload.get("parts", [])  # Only top-level!
for part in parts:
    filename = part.get("filename", "")
```

Gmail's MIME structure for forwarded emails is nested:

```
payload
  parts[0] → multipart/alternative (text body)
  parts[1] → multipart/mixed (forwarded message)
    parts[0] → text (forwarded body)
    parts[1] → application/pdf ← THE ATTACHMENT (never reached!)
```

## Solution

Replace flat iteration with recursive MIME traversal. Collect ALL parts with filenames from any depth.

## Implementation

### File: `scripts/extract_gmail.py`

#### Add recursive part collector (before `extract_attachments_text`, ~line 518):

```python
def _collect_attachment_parts(payload: dict) -> list:
    """
    Recursively collect all MIME parts that have filenames (attachments).
    Handles forwarded emails where attachments are nested in sub-parts.
    """
    results = []
    parts = payload.get("parts", [])
    for part in parts:
        filename = part.get("filename", "")
        if filename:
            results.append(part)
        # Recurse into nested multipart sections
        if part.get("parts"):
            results.extend(_collect_attachment_parts(part))
    return results
```

#### Modify `extract_attachments_text()` (line 530):

Replace:
```python
    parts = payload.get("parts", [])
    if not parts:
        return results

    for part in parts:
        filename = part.get("filename", "")
        if not filename:
            continue
```

With:
```python
    # Recursively collect attachment parts from all MIME levels
    # (handles forwarded emails with nested attachments)
    attachment_parts = _collect_attachment_parts(payload)
    if not attachment_parts:
        return results

    for part in attachment_parts:
        filename = part.get("filename", "")
        if not filename:
            continue
```

The rest of the function (extension check, size check, download, text extraction, document storage) stays exactly the same — it already works correctly once it has the right `part`.

### Also: Backfill script for missed attachments

Create `scripts/backfill_missed_attachments.py`:

```python
"""
Re-process emails that have attachments in Gmail but no documents in Baker.
Uses the fixed recursive MIME traversal to catch forwarded email attachments.

Run: python3 scripts/backfill_missed_attachments.py --days 30
"""
import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("backfill_attachments")


def run(days: int = 30, dry_run: bool = False):
    from scripts.extract_gmail import authenticate, extract_attachments_text
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
            from scripts.extract_gmail import _collect_attachment_parts
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

    print(f"Done. {found} emails had missing attachments, {stored} new docs stored.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(days=args.days, dry_run=args.dry_run)
```

## Testing

1. Syntax check `scripts/extract_gmail.py`
2. Verify the Hagenauer/LCG email gets its attachment:
   - Run: `python3 scripts/backfill_missed_attachments.py --days 5 --dry-run`
   - Should find the missing attachment on email `19cd7401b299946c`
3. Run without dry-run: `python3 scripts/backfill_missed_attachments.py --days 30`
4. Verify new document appears: `SELECT * FROM documents WHERE source_path LIKE 'email:19cd7401b299946c%'`

## Impact

- Fixes: forwarded email attachments (the most common forwarding pattern in business email)
- Backfill: recovers ~30 days of missed attachments
- Future: all new forwarded emails will have their attachments extracted automatically
