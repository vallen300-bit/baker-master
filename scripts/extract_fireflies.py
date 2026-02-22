"""
Baker AI — Fireflies Transcript Extractor
Pulls meeting transcripts from Fireflies.ai GraphQL API and saves them
as JSON files ready for bulk_ingest.py.

Usage:
    python scripts/extract_fireflies.py
    python scripts/extract_fireflies.py --since 2025-01-01 --limit 50

Output:
    03_data/fireflies/fireflies_transcripts.json
    (relative to Baker Master root, i.e. two levels up from 01_build/)
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import config

# Output directory: 15_Baker_Master/03_data/fireflies/
# (two levels up from 01_build, then into 03_data)
_BAKER_MASTER_ROOT = _PROJECT_ROOT.parent
_OUTPUT_DIR = _BAKER_MASTER_ROOT / "03_data" / "fireflies"

# ---------------------------------------------------------------------------
# Fireflies GraphQL
# ---------------------------------------------------------------------------

TRANSCRIPTS_QUERY = """
query Transcripts($limit: Int) {
    transcripts(limit: $limit) {
        id
        title
        date
        duration
        organizer_email
        participants
        sentences {
            speaker_name
            text
        }
        summary {
            overview
            action_items
        }
    }
}
"""


def fetch_transcripts(api_key: str, limit: int = 50) -> list[dict]:
    """Fetch transcripts from Fireflies GraphQL API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": TRANSCRIPTS_QUERY,
        "variables": {"limit": limit},
    }

    print(f"Fetching up to {limit} transcripts from Fireflies...")

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            config.fireflies.endpoint,
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()

    data = resp.json()

    if "errors" in data:
        print(f"ERROR: Fireflies API returned errors:")
        for err in data["errors"]:
            print(f"  - {err.get('message', err)}")
        sys.exit(1)

    transcripts = data.get("data", {}).get("transcripts", [])
    print(f"Received {len(transcripts)} transcripts.")
    return transcripts


# ---------------------------------------------------------------------------
# Transcript formatting
# ---------------------------------------------------------------------------

def format_date(timestamp) -> str:
    """Convert Fireflies timestamp (epoch ms or ISO string) to readable date."""
    if timestamp is None:
        return "unknown"
    try:
        # Fireflies returns epoch milliseconds as a number or string
        ts = int(timestamp) / 1000 if int(timestamp) > 1e12 else int(timestamp)
        return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError, OSError):
        return str(timestamp)


def format_duration(duration) -> str:
    """Format duration (in minutes or seconds) into human-readable string."""
    if duration is None:
        return "unknown"
    try:
        mins = float(duration)
        if mins > 0:
            return f"{int(mins)}min"
    except (ValueError, TypeError):
        pass
    return str(duration)


def format_transcript(t: dict) -> dict:
    """
    Convert a single Fireflies transcript into a {text, metadata} object
    ready for bulk_ingest.py.
    """
    title = t.get("title") or "Untitled Meeting"
    date_str = format_date(t.get("date"))
    participants = t.get("participants") or []
    if isinstance(participants, list):
        participants_str = ", ".join(str(p) for p in participants)
    else:
        participants_str = str(participants)
    duration_str = format_duration(t.get("duration"))

    # Summary
    summary = t.get("summary") or {}
    overview = summary.get("overview") or ""
    action_items = summary.get("action_items") or ""

    # Build the transcript body from sentences
    sentences = t.get("sentences") or []
    transcript_lines = []
    for s in sentences:
        speaker = s.get("speaker_name") or "Unknown"
        text = s.get("text") or ""
        if text.strip():
            transcript_lines.append(f"{speaker}: {text.strip()}")

    # Assemble the full text block
    parts = [
        f"Meeting: {title}",
        f"Date: {date_str}",
        f"Participants: {participants_str}",
        f"Duration: {duration_str}",
        "",
    ]

    if overview:
        parts.append(f"Summary: {overview}")
        parts.append("")

    if action_items:
        parts.append(f"Action Items: {action_items}")
        parts.append("")

    if transcript_lines:
        parts.append("Transcript:")
        parts.extend(transcript_lines)

    text_block = "\n".join(parts)

    metadata = {
        "meeting_title": title,
        "date": date_str,
        "participants": participants_str,
        "organizer": t.get("organizer_email") or "",
        "duration": duration_str,
        "fireflies_id": t.get("id") or "",
        "source": "fireflies",
    }

    return {"text": text_block, "metadata": metadata}


# ---------------------------------------------------------------------------
# Date filtering
# ---------------------------------------------------------------------------

def parse_date_filter(date_str: str) -> datetime:
    """Parse a YYYY-MM-DD date string."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def transcript_date(t: dict) -> Optional[datetime]:
    """Extract datetime from a transcript's date field."""
    ts = t.get("date")
    if ts is None:
        return None
    try:
        epoch = int(ts) / 1000 if int(ts) > 1e12 else int(ts)
        return datetime.utcfromtimestamp(epoch)
    except (ValueError, TypeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Baker AI — Extract Fireflies meeting transcripts",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only include transcripts on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max transcripts to fetch from Fireflies API (default: 50)",
    )
    args = parser.parse_args()

    # --- Check API key ---
    api_key = config.fireflies.api_key
    if not api_key:
        print("WARNING: FIREFLIES_API_KEY is empty in config/.env")
        print("  Add your Fireflies API key to config/.env:")
        print("  FIREFLIES_API_KEY=your-key-here")
        print("")
        print("  You can find your key at: https://app.fireflies.ai/integrations")
        sys.exit(1)

    # --- Fetch ---
    transcripts = fetch_transcripts(api_key, limit=args.limit)

    if not transcripts:
        print("No transcripts returned. Nothing to extract.")
        return

    # --- Filter by date ---
    if args.since:
        cutoff = parse_date_filter(args.since)
        before_count = len(transcripts)
        transcripts = [
            t for t in transcripts
            if (td := transcript_date(t)) is not None and td >= cutoff
        ]
        print(f"Filtered by --since {args.since}: {before_count} → {len(transcripts)} transcripts.")

    if not transcripts:
        print("No transcripts match the date filter. Nothing to extract.")
        return

    # --- Format ---
    texts = []
    for t in transcripts:
        formatted = format_transcript(t)
        texts.append(formatted)

    output = {"texts": texts}

    # --- Stats ---
    total_chars = sum(len(item["text"]) for item in texts)
    approx_tokens = total_chars // 4
    print(f"\nFormatted {len(texts)} transcripts.")
    print(f"Total text: {total_chars:,} chars (~{approx_tokens:,} tokens)")

    # --- Save ---
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = _OUTPUT_DIR / "fireflies_transcripts.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved to: {output_path}")
    print(f"\nNext step — ingest into Qdrant:")
    print(f"  cd 01_build")
    print(f"  python scripts/bulk_ingest.py \\")
    print(f"    --source \"{output_path}\" \\")
    print(f"    --collection sentinel-meetings")


if __name__ == "__main__":
    main()
