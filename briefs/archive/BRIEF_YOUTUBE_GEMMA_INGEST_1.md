# BRIEF: YOUTUBE_GEMMA_INGEST_1 — YouTube transcript ingestion via Gemma 4

## Context
Director wants to paste a YouTube URL and have Baker automatically fetch the transcript, summarize it with local Gemma 4 (free), and store it for future retrieval. YouTube URLs should also be auto-detected in WhatsApp messages and the Baker scan flow.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: `youtube-transcript-api` pip package. Gemma 4 running on Ollama (already deployed).

---

## Feature 1: YouTube transcript fetcher

### Problem
No way to extract YouTube transcripts in Baker's backend.

### Current State
`youtube-transcript-api` is not in `requirements.txt`. No YouTube-related code exists server-side.

### Implementation

**Step 1a: Add dependency** — append to `requirements.txt`:

```
youtube-transcript-api>=1.2.0
```

**Step 1b: Create `triggers/youtube_ingest.py`:**

```python
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
```

### Key Constraints
- `_call_gemma()` tries localhost first, then Cloudflare tunnel — works on both Director's MacBook and Render (via tunnel)
- Falls back to Gemini Flash if Gemma unavailable (Render doesn't have local Ollama)
- Transcript truncated to 6000 chars for Gemma context window
- `noembed.com` for free title lookup — no YouTube API key needed
- Dedup via `trigger_state.mark_processed("youtube", source_id)` — re-ingesting same video is a no-op
- No commitment extraction (most YouTube videos aren't meetings with personal commitments) — only deadlines

---

## Feature 2: API endpoint

### Problem
No way to trigger YouTube ingestion from the dashboard or programmatically.

### Current State
`outputs/dashboard.py` has all API endpoints. Search for a good insertion point after existing endpoints.

### Implementation

**Step 2a: Add endpoint** — in `outputs/dashboard.py`, after the email endpoints (search for `@router.post("/api/email`):

```python
# ---------------------------------------------------------------------------
# YouTube Transcript Ingestion (YOUTUBE-GEMMA-INGEST-1)
# ---------------------------------------------------------------------------
@app.post("/api/youtube/ingest")
async def youtube_ingest(request: Request):
    """Ingest a YouTube video: fetch transcript, summarize with Gemma 4, store."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    url = body.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    from triggers.youtube_ingest import extract_video_id, ingest_youtube_video

    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail=f"Could not extract video ID from: {url}")

    # Check dedup
    from triggers.state import trigger_state
    source_id = f"youtube_{video_id}"
    if trigger_state.is_processed("youtube", source_id):
        # Already ingested — return existing data
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT title, summary FROM meeting_transcripts WHERE id = %s LIMIT 1",
                        (source_id,),
                    )
                    row = cur.fetchone()
                    cur.close()
                    if row:
                        return {"status": "already_ingested", "title": row[0], "summary": row[1], "video_id": video_id}
                finally:
                    store._put_conn(conn)
        except Exception:
            pass
        return {"status": "already_ingested", "video_id": video_id}

    result = ingest_youtube_video(video_id, title=body.get("title", ""))
    return result
```

**Step 2b: Add API key protection** — wrap with `verify_api_key` dependency (search for how other endpoints use it):

```python
@app.post("/api/youtube/ingest", dependencies=[Depends(verify_api_key)])
```

### Key Constraints
- Dedup at endpoint level — returns `already_ingested` with existing summary instead of re-processing
- Protected by API key (same as all Baker endpoints)
- Accepts both full YouTube URLs and plain video IDs

---

## Feature 3: Auto-detect YouTube URLs in scan flow

### Problem
When Director pastes a YouTube URL in Baker scan (chat), it should auto-detect and offer to ingest.

### Current State
`orchestrator/pipeline.py` or `outputs/dashboard.py` `/api/scan` endpoint processes user queries.

### Implementation

**Step 3: Add YouTube detection to scan preprocessing** — in the scan endpoint handler (search for `/api/scan` in `dashboard.py`), before sending to the agent, add:

```python
    # YOUTUBE-GEMMA-INGEST-1: Auto-detect YouTube URLs in scan input
    from triggers.youtube_ingest import detect_youtube_urls, ingest_youtube_video
    yt_ids = detect_youtube_urls(question)
    if yt_ids:
        for vid in yt_ids[:2]:  # Max 2 videos per query
            source_id = f"youtube_{vid}"
            if not trigger_state.is_processed("youtube", source_id):
                try:
                    result = ingest_youtube_video(vid)
                    if result.get("status") == "ok":
                        logger.info(f"Auto-ingested YouTube video from scan: {result.get('title')}")
                except Exception as e:
                    logger.debug(f"YouTube auto-ingest failed (non-fatal): {e}")
```

Place this BEFORE the main scan logic so the transcript is available in Baker's memory by the time the agent responds. The agent can then reference it when answering.

### Key Constraints
- Max 2 videos per query — prevents abuse
- Non-fatal — if YouTube fetch fails, scan continues normally
- Only triggers for new videos (dedup check)
- The ingested transcript becomes available to the agent via `meeting_transcripts` table

---

## Feature 4: Auto-detect YouTube URLs in WhatsApp

### Problem
When Director sends a YouTube link via WhatsApp, Baker should auto-ingest the transcript.

### Current State
`triggers/waha_webhook.py` processes incoming WhatsApp messages. URLs in message body are not currently scanned for YouTube links.

### Implementation

**Step 4: Add YouTube detection to WhatsApp handler** — in `triggers/waha_webhook.py`, after the message body is assembled but before PM signal detection (search for `detect_relevant_pms_whatsapp`), add:

```python
    # YOUTUBE-GEMMA-INGEST-1: Auto-detect YouTube URLs in WhatsApp messages
    if message_body and is_director_msg:
        try:
            from triggers.youtube_ingest import detect_youtube_urls, ingest_youtube_video
            yt_ids = detect_youtube_urls(message_body)
            for vid in yt_ids[:1]:  # Max 1 per message
                source_id = f"youtube_{vid}"
                from triggers.state import trigger_state as _yt_ts
                if not _yt_ts.is_processed("youtube", source_id):
                    result = ingest_youtube_video(vid)
                    if result.get("status") == "ok":
                        logger.info(f"Auto-ingested YouTube from WhatsApp: {result.get('title')}")
        except Exception as e:
            logger.debug(f"YouTube WhatsApp auto-ingest failed (non-fatal): {e}")
```

### Key Constraints
- **Director messages only** (`is_director_msg`) — don't ingest random YouTube links from other contacts
- Max 1 per message — WhatsApp messages rarely have multiple YouTube links
- Non-fatal — WhatsApp processing continues regardless
- Runs before PM signal detection so transcript is available for PM context

---

## Files Modified
- `requirements.txt` — add `youtube-transcript-api>=1.2.0`
- `triggers/youtube_ingest.py` — **NEW** — transcript fetcher + Gemma summarizer + ingest pipeline
- `outputs/dashboard.py` — add `/api/youtube/ingest` endpoint
- `outputs/dashboard.py` — add YouTube URL detection in `/api/scan` handler
- `triggers/waha_webhook.py` — add YouTube URL detection in WhatsApp handler

## Do NOT Touch
- `triggers/fireflies_trigger.py` — unrelated
- `triggers/plaud_trigger.py` — unrelated
- `memory/store_back.py` — `meeting_transcripts` table + `store_meeting_transcript()` works as-is with `source='youtube'`
- `outputs/static/app.js` — no frontend changes needed (scan already shows results)

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('triggers/youtube_ingest.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`
3. `python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"`
4. After deploy: `curl -X POST "https://baker-master.onrender.com/api/youtube/ingest" -H "X-Baker-Key: bakerbhavanga" -H "Content-Type: application/json" -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'`
5. Verify DB record with Verification SQL below
6. Test WhatsApp: Director sends a YouTube link → check logs for "Auto-ingested YouTube"
7. Test scan: Type YouTube URL in Baker chat → verify transcript available in response

## Verification SQL
```sql
-- Check YouTube transcripts ingested
SELECT id, title, source, meeting_date, LEFT(summary, 200) as summary_preview
FROM meeting_transcripts
WHERE source = 'youtube'
ORDER BY ingested_at DESC LIMIT 10;

-- Check dedup
SELECT source, source_id, processed_at
FROM trigger_log
WHERE source_id LIKE 'youtube_%'
ORDER BY processed_at DESC LIMIT 10;
```

## Cost Impact
- **Gemma 4 (primary)**: Free — runs locally via Ollama
- **Gemini Flash (fallback)**: ~$0.005 per summary — only if Gemma unavailable (i.e., on Render without Cloudflare tunnel)
- **YouTube transcript fetch**: Free — no API key, uses public caption data
- **Title lookup**: Free — noembed.com public API
- **PostgreSQL**: Negligible — one row per video in `meeting_transcripts`
