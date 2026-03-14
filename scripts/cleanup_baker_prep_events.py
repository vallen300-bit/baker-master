"""
One-time cleanup: Delete all [Baker Prep] events from Google Calendar.

The calendar cascade bug created hundreds of nested [Baker Prep] events.
This script finds and deletes them all.

Usage: python scripts/cleanup_baker_prep_events.py [--dry-run]
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from datetime import datetime, timezone, timedelta


def cleanup_baker_prep_events(dry_run: bool = False):
    from scripts.extract_gmail import authenticate
    from googleapiclient.discovery import build

    creds = authenticate()
    service = build("calendar", "v3", credentials=creds)

    # Search a wide window: 30 days back to 30 days forward
    time_min = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    time_max = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    page_token = None
    total_found = 0
    total_deleted = 0

    while True:
        events_result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            maxResults=250,
            pageToken=page_token,
            q="Baker Prep",  # Pre-filter by text search
        ).execute()

        events = events_result.get("items", [])
        for event in events:
            summary = event.get("summary", "")
            if "[Baker Prep]" not in summary:
                continue

            total_found += 1
            event_id = event["id"]
            start = event.get("start", {}).get("dateTime", "?")

            if dry_run:
                print(f"  [DRY RUN] Would delete: {summary[:80]} ({start})")
            else:
                try:
                    service.events().delete(
                        calendarId="primary",
                        eventId=event_id,
                    ).execute()
                    total_deleted += 1
                    print(f"  Deleted: {summary[:80]} ({start})")
                except Exception as e:
                    print(f"  FAILED to delete {event_id}: {e}")

        page_token = events_result.get("nextPageToken")
        if not page_token:
            break

    print(f"\nDone. Found {total_found} [Baker Prep] events, deleted {total_deleted}.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        print("=== DRY RUN MODE ===\n")
    cleanup_baker_prep_events(dry_run=dry)
