"""
Baker AI — Gmail Thread Extractor
Pulls email threads from Gmail API and saves them as JSON files ready
for bulk_ingest.py.

Prerequisites:
    1. Enable Gmail API at console.cloud.google.com
    2. Create OAuth 2.0 Client ID (Desktop app)
    3. Download credentials → save as config/gmail_credentials.json
    4. First run will open browser for OAuth consent

Usage:
    # Historical backfill (one-time)
    python scripts/extract_gmail.py --mode historical --since 2025-08-19
    python scripts/extract_gmail.py --mode historical --since 2025-08-19 --dry-run
    python scripts/extract_gmail.py --mode historical --limit 100 --dry-run

    # Live polling (called by trigger system every ~5 min)
    python scripts/extract_gmail.py --mode poll

Output:
    Historical: 03_data/gmail/gmail_threads.json
    Poll:       03_data/gmail/gmail_incremental.json
    State:      config/gmail_poll_state.json
"""
import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config

# Google API imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Output directory: 15_Baker_Master/03_data/gmail/
_BAKER_MASTER_ROOT = _PROJECT_ROOT.parent
_OUTPUT_DIR = _BAKER_MASTER_ROOT / "03_data" / "gmail"

# Writable state dir: /tmp on Render (read-only /etc/secrets), config/ locally
_WRITABLE_DIR = Path(config.gmail.writable_state_dir)

# Poll state file: tracks last-seen timestamp for incremental polling
_POLL_STATE_PATH = _WRITABLE_DIR / "gmail_poll_state.json"

# Writable token path — where refreshed tokens are saved
_WRITABLE_TOKEN_PATH = _WRITABLE_DIR / "gmail_token.json"

# Are we on a headless server (Render, Docker, etc.)?
_HEADLESS = os.path.exists("/etc/secrets") or os.environ.get("RENDER")


# ---------------------------------------------------------------------------
# OAuth2 Authentication
# ---------------------------------------------------------------------------

def authenticate() -> Credentials:
    """
    Authenticate with Gmail API using OAuth2.
    - If token exists and is valid, use it.
    - If token is expired, refresh it.
    - On headless servers (Render): never attempt browser flow; fail loudly.
    - Refreshed tokens are saved to writable dir (/tmp on Render).
    """
    creds_path = Path(config.gmail.credentials_path)
    token_path = Path(config.gmail.token_path)
    scopes = config.gmail.scopes

    if not creds_path.exists():
        print(f"ERROR: Gmail credentials file not found: {creds_path}")
        print()
        print("  To set up Gmail API access:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. Create project 'Baker-Gmail' (or select existing)")
        print("  3. Enable the Gmail API")
        print("  4. Credentials → Create OAuth 2.0 Client ID (Desktop app)")
        print("  5. Download JSON → save as config/gmail_credentials.json")
        if _HEADLESS:
            print("  6. On Render: upload as Secret File at /etc/secrets/gmail_credentials.json")
        sys.exit(1)

    creds = None

    # Try writable copy first (refreshed token), then original (from secrets)
    for tp in [_WRITABLE_TOKEN_PATH, token_path]:
        if tp.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(tp), scopes)
                print(f"Gmail: Loaded token from {tp}")
                break
            except Exception as e:
                print(f"  Warning: Could not load token from {tp} ({e})")

    # Refresh or run new flow
    if creds and creds.valid:
        print("Gmail: Using cached OAuth token.")
    elif creds and creds.expired and creds.refresh_token:
        print("Gmail: Refreshing expired OAuth token...")
        try:
            creds.refresh(Request())
            # Save refreshed token to writable dir
            _WRITABLE_DIR.mkdir(parents=True, exist_ok=True)
            with open(_WRITABLE_TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
            print(f"Gmail: Token refreshed → saved to {_WRITABLE_TOKEN_PATH}")
        except Exception as e:
            print(f"  Token refresh failed: {e}")
            creds = None

    if not creds or not creds.valid:
        if _HEADLESS:
            # On Render / headless: cannot open browser — fail with instructions
            print("ERROR: Gmail token invalid and cannot run OAuth browser flow on headless server.")
            print()
            print("  To fix:")
            print("  1. Run locally: python scripts/extract_gmail.py --mode poll")
            print("  2. This generates config/gmail_token.json")
            print("  3. Upload it to Render as Secret File: /etc/secrets/gmail_token.json")
            sys.exit(1)
        else:
            # Local dev: open browser for consent
            print("Gmail: Starting OAuth2 consent flow (will open browser)...")
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), scopes)
            creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            print(f"Gmail: Token saved to {token_path}")

    return creds


# ---------------------------------------------------------------------------
# Newsletter / noise detection
# ---------------------------------------------------------------------------

# Compiled regex patterns for noise senders
_NOISE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in config.gmail.noise_senders]


def is_noise_sender(from_header: str) -> bool:
    """Check if the sender matches known newsletter/noise patterns."""
    _, email_addr = parseaddr(from_header)
    email_lower = email_addr.lower()
    for pattern in _NOISE_PATTERNS:
        if pattern.search(email_lower):
            return True
    return False


def has_unsubscribe_signals(headers: List[Dict]) -> bool:
    """Check if the message has List-Unsubscribe or mailing list headers."""
    noise_headers = {"list-unsubscribe", "list-id", "list-post", "list-help",
                     "x-mailer", "x-campaign", "x-mailgun-tag",
                     "x-sg-eid", "x-sendgrid-eid"}
    for h in headers:
        name = h.get("name", "").lower()
        if name in noise_headers:
            return True
        # Check for Precedence: bulk/list
        if name == "precedence":
            val = h.get("value", "").lower()
            if val in ("bulk", "list", "junk"):
                return True
    return False


def is_noise_thread(messages: List[Dict]) -> Tuple[bool, str]:
    """
    Determine if a thread is noise (newsletter, marketing, automated).
    Returns (is_noise, reason).
    """
    if not messages:
        return True, "empty thread"

    # Check first message (thread starter)
    first_msg = messages[0]
    headers = first_msg.get("payload", {}).get("headers", [])
    header_map = {h["name"].lower(): h["value"] for h in headers}

    from_header = header_map.get("from", "")

    # Check sender patterns
    if is_noise_sender(from_header):
        return True, f"noise sender: {from_header}"

    # Check unsubscribe/mailing list headers
    if has_unsubscribe_signals(headers):
        return True, "has unsubscribe/mailing-list headers"

    return False, ""


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------

def get_header(headers: List[Dict], name: str) -> str:
    """Extract a specific header value (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def extract_body_text(payload: Dict) -> str:
    """
    Recursively extract plain text body from a Gmail message payload.
    Prefers text/plain, falls back to text/html (stripped of tags).
    """
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})

    # Direct text/plain part
    if mime_type == "text/plain" and body.get("data"):
        return base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="replace")

    # Multipart: recurse into parts
    parts = payload.get("parts", [])
    if parts:
        # First pass: look for text/plain
        for part in parts:
            if part.get("mimeType") == "text/plain":
                part_body = part.get("body", {})
                if part_body.get("data"):
                    return base64.urlsafe_b64decode(part_body["data"]).decode(
                        "utf-8", errors="replace"
                    )

        # Second pass: recurse into multipart/* parts
        for part in parts:
            if part.get("mimeType", "").startswith("multipart/"):
                text = extract_body_text(part)
                if text:
                    return text

        # Third pass: fallback to text/html (strip tags)
        for part in parts:
            if part.get("mimeType") == "text/html":
                part_body = part.get("body", {})
                if part_body.get("data"):
                    html = base64.urlsafe_b64decode(part_body["data"]).decode(
                        "utf-8", errors="replace"
                    )
                    return strip_html(html)

    # Direct text/html fallback
    if mime_type == "text/html" and body.get("data"):
        html = base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="replace")
        return strip_html(html)

    return ""


def strip_html(html: str) -> str:
    """Simple HTML tag stripper for fallback body extraction."""
    # Remove style and script blocks
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def parse_message_date(headers: List[Dict]) -> Optional[datetime]:
    """Parse the Date header from a message."""
    date_str = get_header(headers, "Date")
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Thread formatting
# ---------------------------------------------------------------------------

def format_thread(thread_data: Dict, messages: List[Dict]) -> Optional[Dict]:
    """
    Convert a Gmail thread into a {text, metadata} object ready for bulk_ingest.py.
    Returns None if thread has no substantive content.
    """
    if not messages:
        return None

    # Extract info from all messages
    msg_blocks = []
    all_participants = set()
    dates = []
    subject = ""

    for msg in messages:
        headers = msg.get("payload", {}).get("headers", [])
        header_map = {h["name"].lower(): h["value"] for h in headers}

        from_addr = header_map.get("from", "")
        to_addr = header_map.get("to", "")
        cc_addr = header_map.get("cc", "")
        msg_subject = header_map.get("subject", "")
        if msg_subject and not subject:
            subject = msg_subject

        # Parse date
        msg_date = parse_message_date(headers)
        if msg_date:
            dates.append(msg_date)
        date_str = msg_date.strftime("%Y-%m-%d %H:%M") if msg_date else "unknown"

        # Collect participants
        for addr_field in [from_addr, to_addr, cc_addr]:
            for part in addr_field.split(","):
                _, email = parseaddr(part.strip())
                if email:
                    all_participants.add(email.lower())

        # Extract body
        body = extract_body_text(msg.get("payload", {}))
        body = body.strip()

        # Skip empty messages
        if not body:
            continue

        # Truncate very long bodies (e.g. forwarded chains)
        if len(body) > 8000:
            body = body[:8000] + "\n[...truncated]"

        # Build message block
        sender_name, sender_email = parseaddr(from_addr)
        sender_display = sender_name if sender_name else sender_email
        msg_blocks.append(
            f"--- {sender_display} ({date_str}) ---\n{body}"
        )

    # Skip threads with no content
    if not msg_blocks:
        return None

    # Skip very short threads (likely auto-replies, OOO, etc.)
    total_body_chars = sum(len(b) for b in msg_blocks)
    if total_body_chars < 100:
        return None

    # Date range
    if dates:
        dates.sort()
        date_range = (
            f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}"
            if len(dates) > 1
            else dates[0].strftime("%Y-%m-%d")
        )
        first_date = dates[0].strftime("%Y-%m-%d")
    else:
        date_range = "unknown"
        first_date = "unknown"

    # Assemble text block
    participants_str = ", ".join(sorted(all_participants))
    parts = [
        f"Email Thread: {subject}",
        f"Date: {date_range}",
        f"Participants: {participants_str}",
        f"Messages: {len(msg_blocks)}",
        "",
    ]
    parts.extend(msg_blocks)

    text_block = "\n".join(parts)

    thread_id = thread_data.get("id", "")
    # Use the latest message ID for dedup (thread_id is reused across replies)
    all_messages = thread_data.get("messages", [])
    latest_message_id = all_messages[-1].get("id", thread_id) if all_messages else thread_id
    metadata = {
        "subject": subject,
        "date": first_date,
        "date_range": date_range,
        "participants": participants_str,
        "message_count": len(msg_blocks),
        "thread_id": thread_id,
        "message_id": latest_message_id,
        "source": "gmail",
    }

    return {"text": text_block, "metadata": metadata}


# ---------------------------------------------------------------------------
# Gmail API fetching
# ---------------------------------------------------------------------------

def fetch_thread_ids(service, query: str, limit: Optional[int] = None) -> List[str]:
    """Fetch all thread IDs matching the query, handling pagination."""
    thread_ids = []
    page_token = None
    page_num = 0

    while True:
        page_num += 1
        kwargs = {
            "userId": "me",
            "q": query,
            "maxResults": min(100, limit - len(thread_ids)) if limit else 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token

        result = service.users().threads().list(**kwargs).execute()
        threads = result.get("threads", [])

        if not threads:
            break

        for t in threads:
            thread_ids.append(t["id"])

        print(f"  Page {page_num}: found {len(threads)} threads "
              f"(total so far: {len(thread_ids)})")

        # Check limit
        if limit and len(thread_ids) >= limit:
            thread_ids = thread_ids[:limit]
            break

        page_token = result.get("nextPageToken")
        if not page_token:
            break

        # Small delay to be nice to the API
        time.sleep(0.2)

    return thread_ids


def fetch_thread_detail(service, thread_id: str) -> Optional[Dict]:
    """Fetch full thread detail including all messages."""
    try:
        thread = service.users().threads().get(
            userId="me",
            id=thread_id,
            format="full",
        ).execute()
        return thread
    except Exception as e:
        print(f"  Warning: Failed to fetch thread {thread_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Historical extraction
# ---------------------------------------------------------------------------

def extract_historical(
    service,
    since: str,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> List[Dict]:
    """
    Extract historical email threads from Gmail.
    Returns list of {text, metadata} dicts ready for bulk_ingest.py.
    """
    # Build query
    query_parts = [f"after:{since}"]
    query_parts.append(config.gmail.default_query)
    query = " ".join(query_parts)

    print(f"\nGmail query: {query}")
    if limit:
        print(f"Limit: {limit} threads")

    # --- Fetch thread IDs ---
    print(f"\nFetching thread list...")
    thread_ids = fetch_thread_ids(service, query, limit=limit)

    if not thread_ids:
        print("No threads found matching the query.")
        return []

    print(f"\nFound {len(thread_ids)} threads matching query.")

    if dry_run:
        # In dry-run, fetch a small sample for preview
        print(f"\n[DRY RUN] Fetching 3 sample threads for preview...")
        sample_ids = thread_ids[:3]
        sample_texts = []

        for tid in sample_ids:
            thread = fetch_thread_detail(service, tid)
            if not thread:
                continue
            messages = thread.get("messages", [])

            # Check noise
            is_noise, reason = is_noise_thread(messages)
            if is_noise:
                print(f"  Thread {tid}: NOISE ({reason})")
                continue

            # Limit messages
            if len(messages) > config.gmail.max_messages_per_thread:
                messages = messages[:config.gmail.max_messages_per_thread]

            formatted = format_thread(thread, messages)
            if formatted:
                sample_texts.append(formatted)

            time.sleep(0.1)

        print(f"\n[DRY RUN] Would process:")
        print(f"  - {len(thread_ids)} threads to fetch")
        print(f"  - Noise filtering applied (newsletters, noreply, mailing lists)")
        print(f"  - Output → 03_data/gmail/gmail_threads.json")

        if sample_texts:
            for i, item in enumerate(sample_texts):
                chars = len(item["text"])
                tokens_est = chars // 4
                print(f"\n  Sample thread {i+1} (~{tokens_est} tokens):")
                print(f"    Subject: {item['metadata']['subject']}")
                print(f"    Date: {item['metadata']['date_range']}")
                print(f"    Participants: {item['metadata']['participants'][:100]}")
                print(f"    Messages: {item['metadata']['message_count']}")
                # Show first 200 chars of text
                preview = item["text"][:200].replace("\n", " | ")
                print(f"    Preview: {preview}...")
        return []

    # --- Full extraction ---
    print(f"\nFetching full thread details ({len(thread_ids)} threads)...")
    texts = []
    noise_count = 0
    empty_count = 0
    error_count = 0

    for i, tid in enumerate(thread_ids):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"  Processing thread {i+1}/{len(thread_ids)}...")

        thread = fetch_thread_detail(service, tid)
        if not thread:
            error_count += 1
            continue

        messages = thread.get("messages", [])

        # Noise filter
        is_noise, reason = is_noise_thread(messages)
        if is_noise:
            noise_count += 1
            continue

        # Limit messages per thread
        if len(messages) > config.gmail.max_messages_per_thread:
            messages = messages[:config.gmail.max_messages_per_thread]

        # Format
        formatted = format_thread(thread, messages)
        if formatted:
            texts.append(formatted)
        else:
            empty_count += 1

        # Rate limit: Gmail API allows ~250 quota units/sec
        # threads.get = 10 units, so ~25 threads/sec max
        # We'll be conservative with a small sleep
        if (i + 1) % 10 == 0:
            time.sleep(0.5)

    print(f"\nExtraction complete:")
    print(f"  Total threads fetched: {len(thread_ids)}")
    print(f"  Noise filtered: {noise_count}")
    print(f"  Empty/too-short: {empty_count}")
    print(f"  Fetch errors: {error_count}")
    print(f"  Substantive threads kept: {len(texts)}")

    return texts


# ---------------------------------------------------------------------------
# Poll mode — incremental extraction
# ---------------------------------------------------------------------------

def load_poll_state() -> Dict:
    """Load the poll state (last-seen timestamp). Defaults to 24h ago."""
    if _POLL_STATE_PATH.exists():
        try:
            with open(_POLL_STATE_PATH, "r") as f:
                state = json.load(f)
            print(f"Poll state loaded: last_seen = {state.get('last_seen', 'unknown')}")
            return state
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Warning: Could not read poll state ({e}), defaulting to 24h ago.")

    # Default: 24 hours ago
    default_since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d")
    return {"last_seen": default_since, "last_seen_epoch": 0}


def save_poll_state(state: Dict):
    """Save the poll state with updated high-water mark."""
    _POLL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_POLL_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
    print(f"Poll state saved: last_seen = {state.get('last_seen')}")


def extract_poll(service) -> List[Dict]:
    """
    Poll for new email threads since the last-seen timestamp.
    Returns list of {text, metadata} dicts ready for bulk_ingest.py.
    Updates the poll state file with the new high-water mark.
    """
    state = load_poll_state()
    since_date = state.get("last_seen", "")

    if not since_date:
        since_date = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d")

    # Build query — use after: for Gmail date filtering
    query_parts = [f"after:{since_date}"]
    query_parts.append(config.gmail.default_query)
    query = " ".join(query_parts)

    print(f"\nPoll query: {query}")

    # Fetch thread IDs
    print(f"Fetching new threads since {since_date}...")
    thread_ids = fetch_thread_ids(service, query, limit=None)

    if not thread_ids:
        print("No new threads found.")
        # Still update the state to today
        new_state = {
            "last_seen": datetime.now().strftime("%Y-%m-%d"),
            "last_seen_epoch": int(time.time()),
            "last_poll": datetime.now().isoformat(),
            "threads_found": 0,
            "threads_kept": 0,
        }
        save_poll_state(new_state)
        return []

    print(f"Found {len(thread_ids)} threads since {since_date}.")

    # Fetch and process threads
    texts = []
    noise_count = 0
    empty_count = 0
    error_count = 0
    latest_date = None

    for i, tid in enumerate(thread_ids):
        if (i + 1) % 50 == 0:
            print(f"  Processing thread {i+1}/{len(thread_ids)}...")

        thread = fetch_thread_detail(service, tid)
        if not thread:
            error_count += 1
            continue

        messages = thread.get("messages", [])

        # Noise filter
        is_noise, reason = is_noise_thread(messages)
        if is_noise:
            noise_count += 1
            continue

        # Limit messages per thread
        if len(messages) > config.gmail.max_messages_per_thread:
            messages = messages[:config.gmail.max_messages_per_thread]

        # Format
        formatted = format_thread(thread, messages)
        if formatted:
            texts.append(formatted)

            # Track latest date for high-water mark
            thread_date_str = formatted["metadata"].get("date", "")
            if thread_date_str and thread_date_str != "unknown":
                try:
                    thread_dt = datetime.strptime(thread_date_str, "%Y-%m-%d")
                    if latest_date is None or thread_dt > latest_date:
                        latest_date = thread_dt
                except ValueError:
                    pass
        else:
            empty_count += 1

        # Rate limit
        if (i + 1) % 10 == 0:
            time.sleep(0.5)

    print(f"\nPoll extraction complete:")
    print(f"  Total threads fetched: {len(thread_ids)}")
    print(f"  Noise filtered: {noise_count}")
    print(f"  Empty/too-short: {empty_count}")
    print(f"  Fetch errors: {error_count}")
    print(f"  New substantive threads: {len(texts)}")

    # Update high-water mark
    # Use today's date as the new baseline (Gmail after: is date-level, not second-level)
    new_high_water = datetime.now().strftime("%Y-%m-%d")
    if latest_date:
        # Use the latest thread date if it's more recent than today
        # (shouldn't happen, but be safe)
        latest_str = latest_date.strftime("%Y-%m-%d")
        if latest_str > new_high_water:
            new_high_water = latest_str

    new_state = {
        "last_seen": new_high_water,
        "last_seen_epoch": int(time.time()),
        "last_poll": datetime.now().isoformat(),
        "threads_found": len(thread_ids),
        "threads_kept": len(texts),
    }
    save_poll_state(new_state)

    return texts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Baker AI — Extract Gmail email threads",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["historical", "poll"],
        required=True,
        help="Extraction mode: 'historical' for bulk backfill, 'poll' for incremental",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only include threads on or after this date (YYYY-MM-DD). "
             "Defaults to 6 months ago.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max threads to fetch (default: no limit)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be extracted without writing files",
    )
    args = parser.parse_args()

    # Default --since to 6 months ago (only for historical mode)
    if args.mode == "historical" and not args.since:
        six_months_ago = datetime.now() - timedelta(days=180)
        args.since = six_months_ago.strftime("%Y-%m-%d")
        print(f"No --since provided, defaulting to 6 months ago: {args.since}")

    print(f"\n{'='*60}")
    print(f"Baker AI — Gmail Extraction ({args.mode} mode)")
    print(f"{'='*60}")

    # --- Authenticate ---
    creds = authenticate()
    service = build("gmail", "v1", credentials=creds)
    print("Gmail API connected.")

    # --- Extract ---
    texts = []

    if args.mode == "historical":
        texts = extract_historical(
            service,
            since=args.since,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            return
        output_filename = "gmail_threads.json"

    elif args.mode == "poll":
        texts = extract_poll(service)
        output_filename = "gmail_incremental.json"

    if not texts:
        print("\nNo threads to save.")
        return

    # --- Build output ---
    output = {"texts": texts}

    # --- Stats ---
    total_chars = sum(len(item["text"]) for item in texts)
    approx_tokens = total_chars // 4
    print(f"\nFormatted {len(texts)} email threads.")
    print(f"Total text: {total_chars:,} chars (~{approx_tokens:,} tokens)")

    # --- Save ---
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = _OUTPUT_DIR / output_filename

    if args.mode == "poll" and output_path.exists():
        # Append to existing incremental file
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing_texts = existing.get("texts", [])
            # Deduplicate by thread_id
            existing_ids = {t["metadata"]["thread_id"] for t in existing_texts
                           if "metadata" in t and "thread_id" in t["metadata"]}
            new_texts = [t for t in texts
                         if t.get("metadata", {}).get("thread_id") not in existing_ids]
            if new_texts:
                existing_texts.extend(new_texts)
                output = {"texts": existing_texts}
                print(f"Appended {len(new_texts)} new threads "
                      f"(skipped {len(texts) - len(new_texts)} duplicates). "
                      f"Total in file: {len(existing_texts)}")
            else:
                print("All threads already in incremental file. Nothing new to append.")
                return
        except (json.JSONDecodeError, IOError):
            print("  Warning: Could not read existing incremental file, overwriting.")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to: {output_path}")
    print(f"\nNext step — ingest into Qdrant:")
    print(f"  cd 01_build")
    print(f"  python scripts/bulk_ingest.py \\")
    print(f"    --source \"{output_path}\" \\")
    print(f"    --collection {config.gmail.collection}")


if __name__ == "__main__":
    main()
