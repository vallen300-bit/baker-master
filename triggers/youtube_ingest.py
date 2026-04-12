"""
Baker — YouTube Transcript Ingestion
YOUTUBE-GEMMA-INGEST-1: Fetch transcript, summarize with Gemma 4, store in meeting_transcripts.
"""
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("sentinel.youtube")

# ---------------------------------------------------------------------------
# YouTube URL parsing
# ---------------------------------------------------------------------------

_YT_PATTERNS = [
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})'),
]


def extract_video_id(text: str) -> str | None:
    """Extract YouTube video ID from a URL or text containing a URL.
    Returns 11-char video ID or None.
    """
    for pattern in _YT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def detect_youtube_urls(text: str) -> list[str]:
    """Find all YouTube video IDs in a block of text."""
    ids = []
    for pattern in _YT_PATTERNS:
        for match in pattern.finditer(text):
            vid = match.group(1)
            if vid not in ids:
                ids.append(vid)
    return ids


# ---------------------------------------------------------------------------
# Transcript fetching
# ---------------------------------------------------------------------------

def fetch_youtube_transcript(video_id: str, languages: list[str] = None) -> dict:
    """Fetch transcript for a YouTube video.
    Returns {"text": str, "language": str, "segments": list} or {"error": str}.
    No API key required.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return {"error": "youtube-transcript-api not installed"}

    if languages is None:
        languages = ["en", "de", "fr", "ru", "es", "it"]

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try manual transcripts first (more accurate), then auto-generated
        transcript = None
        for method in ["find_manually_created_transcript", "find_generated_transcript"]:
            try:
                transcript = getattr(transcript_list, method)(languages)
                break
            except Exception:
                continue

        if not transcript:
            # Fallback: get any available transcript
            for t in transcript_list:
                transcript = t
                break

        if not transcript:
            return {"error": f"No transcript available for video {video_id}"}

        segments = transcript.fetch()
        full_text = " ".join(seg.get("text", "") for seg in segments)
        language = transcript.language_code if hasattr(transcript, "language_code") else "unknown"

        return {
            "text": full_text,
            "language": language,
            "segments": segments,
            "video_id": video_id,
        }
    except Exception as e:
        return {"error": f"Failed to fetch transcript for {video_id}: {e}"}


# ---------------------------------------------------------------------------
# Gemma 4 summarization (local, free)
# ---------------------------------------------------------------------------

_OLLAMA_ENDPOINTS = [
    "http://localhost:11434",
    "https://ollama.brisen-infra.com",
]


def _call_gemma(prompt: str, timeout: int = 180) -> str | None:
    """Call local Gemma 4 via Ollama. Returns response text or None."""
    import httpx

    for endpoint in _OLLAMA_ENDPOINTS:
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{endpoint}/api/chat",
                    json={
                        "model": "gemma4:latest",
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", {}).get("content", "")
        except Exception as e:
            logger.debug(f"Gemma call to {endpoint} failed: {e}")
            continue

    logger.warning("Gemma 4 unavailable on all endpoints — falling back to Flash")
    return None


def summarize_with_gemma(transcript_text: str, title: str = "") -> str:
    """Summarize a YouTube transcript using Gemma 4 (local, free).
    Falls back to Gemini Flash if Gemma is unavailable.
    """
    # Truncate to ~6000 chars for Gemma context
    excerpt = transcript_text[:6000]

    prompt = f"""Summarize this YouTube video transcript concisely.

Title: {title}

Transcript:
{excerpt}

Provide:
1. **Summary** (3-5 sentences)
2. **Key Points** (bullet list, max 7)
3. **Action Items** (if any mentioned)
4. **People Mentioned** (if any)

Be concise and factual. Only include what's actually in the transcript."""

    result = _call_gemma(prompt)

    if result:
        return result

    # Fallback: Gemini Flash
    try:
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.text.strip() if resp else ""
    except Exception as e:
        logger.warning(f"Flash fallback also failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Full ingest pipeline
# ---------------------------------------------------------------------------

def ingest_youtube_video(video_id: str, title: str = "", requested_by: str = "director") -> dict:
    """Full pipeline: fetch transcript → summarize with Gemma → store in DB.
    Returns {"status": "ok", "title": ..., "summary": ..., "transcript_id": ...}
    or {"status": "error", "error": ...}.
    """
    # 1. Fetch transcript
    result = fetch_youtube_transcript(video_id)
    if "error" in result:
        return {"status": "error", "error": result["error"]}

    transcript_text = result["text"]
    language = result.get("language", "unknown")

    if not transcript_text or len(transcript_text.strip()) < 20:
        return {"status": "error", "error": "Transcript too short or empty"}

    # 2. Get video metadata if title not provided
    if not title:
        title = f"YouTube video {video_id}"
        try:
            import httpx
            resp = httpx.get(
                f"https://noembed.com/embed?url=https://www.youtube.com/watch?v={video_id}",
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("title", title)
        except Exception:
            pass

    # 3. Summarize with Gemma 4 (free, local)
    summary = summarize_with_gemma(transcript_text, title)

    # 4. Build full text block (matches Fireflies/Plaud format)
    source_id = f"youtube_{video_id}"
    full_text = f"Meeting: {title}\nSource: YouTube\nLanguage: {language}\nURL: https://www.youtube.com/watch?v={video_id}\n\n"
    if summary:
        full_text += f"Summary:\n{summary}\n\n"
    full_text += f"Transcript:\n{transcript_text}"

    # 5. Store in meeting_transcripts (same table as Fireflies/Plaud)
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        store.store_meeting_transcript(
            transcript_id=source_id,
            title=title,
            meeting_date=datetime.now(timezone.utc).isoformat(),
            duration="",
            organizer=requested_by,
            participants="",
            summary=summary,
            full_transcript=full_text,
            source="youtube",
        )
    except Exception as e:
        logger.warning(f"Failed to store YouTube transcript {source_id}: {e}")

    # 6. Mark processed (dedup)
    try:
        from triggers.state import trigger_state
        trigger_state.mark_processed("youtube", source_id)
    except Exception:
        pass

    # 7. Extract deadlines (cheap, no LLM)
    try:
        from orchestrator.deadline_manager import extract_deadlines
        extract_deadlines(
            content=full_text[:8000],
            source_type="youtube",
            source_id=source_id,
            sender_name="",
        )
    except Exception:
        pass

    logger.info(f"YouTube video ingested: {title} ({video_id}), {len(transcript_text)} chars")

    return {
        "status": "ok",
        "title": title,
        "video_id": video_id,
        "language": language,
        "transcript_length": len(transcript_text),
        "summary": summary,
        "transcript_id": source_id,
    }
