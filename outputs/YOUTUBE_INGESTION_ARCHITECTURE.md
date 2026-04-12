# Baker YouTube Ingestion — Architecture Reference

## Overview

Baker can ingest YouTube video transcripts, summarize them with **Gemma 4** (local, free via Ollama), and store them in the same `meeting_transcripts` table used by Fireflies and Plaud. Zero API key required for transcript fetching. Zero cost for summarization when Gemma is available.

---

## Data Flow

```
YouTube URL
    │
    ├── [LOCAL PATH] MacBook fetches transcript via youtube-transcript-api
    │       │
    │       └── POST /api/youtube/ingest { url, transcript }
    │
    └── [CLOUD PATH] Render fetches directly (blocked by YouTube IP filtering)
            │
            └── ingest_youtube_video(video_id)
                    │
                    ▼
            ┌─────────────────────────┐
            │  1. Transcript text      │ ← youtube-transcript-api v1.x (free, no API key)
            │  2. Title lookup         │ ← noembed.com (free)
            │  3. Summarize            │ ← Gemma 4 via Ollama (free) → Flash fallback ($0.005)
            │  4. Store                │ ← meeting_transcripts (source='youtube')
            │  5. Dedup mark           │ ← trigger_log (source_id='youtube_{video_id}')
            │  6. Extract deadlines    │ ← deadline_manager (cheap, no LLM)
            └─────────────────────────┘
```

**Critical constraint:** YouTube blocks Render's cloud IP. Transcripts must be fetched locally (MacBook) and POSTed with the `transcript` field. If Render can fetch directly (e.g., some videos work), it does.

---

## Files

| File | Role |
|------|------|
| `triggers/youtube_ingest.py` | Core module — URL parsing, transcript fetch, Gemma summarization, full pipeline |
| `outputs/dashboard.py` ~line 694 | `/api/youtube/ingest` endpoint |
| `outputs/dashboard.py` ~line 7099 | Auto-detect YouTube URLs in `/api/scan` flow |
| `triggers/waha_webhook.py` | Auto-detect YouTube URLs in WhatsApp (Director messages only) |
| `requirements.txt` | `youtube-transcript-api>=1.2.0` |

---

## Key Functions (`triggers/youtube_ingest.py`)

### `extract_video_id(text: str) -> str | None`
Extracts 11-char YouTube video ID from any URL format. Supports:
- `youtube.com/watch?v=...`
- `youtu.be/...`
- `youtube.com/embed/...`
- `youtube.com/shorts/...`

### `detect_youtube_urls(text: str) -> list[str]`
Finds ALL YouTube video IDs in a block of text. Used by scan and WhatsApp auto-detection.

### `fetch_youtube_transcript(video_id: str, languages: list[str] = None) -> dict`
Fetches transcript using `youtube-transcript-api` v1.x.

**v1.x API pattern** (instance-based, NOT class-method):
```python
ytt_api = YouTubeTranscriptApi()
fetched = ytt_api.fetch(video_id, languages=["en", "de", "fr", "ru", "es", "it"])
# FetchedTranscript is iterable
for snippet in fetched:
    snippet.text      # str
    snippet.start     # float (seconds)
    snippet.duration  # float (seconds)
# Language: fetched.language_code
```

Returns: `{"text": str, "language": str, "segments": list, "video_id": str}` or `{"error": str}`

### `_call_gemma(prompt: str, timeout: int = 180) -> str | None`
Calls Gemma 4 via Ollama. Tries two endpoints in order:
1. `http://localhost:11434` (MacBook local)
2. `https://ollama.brisen-infra.com` (Cloudflare tunnel to MacBook)

Uses Ollama `/api/chat` endpoint:
```python
POST {endpoint}/api/chat
{
    "model": "gemma4:latest",
    "messages": [{"role": "user", "content": prompt}],
    "stream": False
}
# Response: data["message"]["content"]
```

Returns `None` if both endpoints fail (triggers Flash fallback).

### `summarize_with_gemma(transcript_text: str, title: str = "") -> str`
Summarizes transcript. **Gemma 4 first, Gemini Flash fallback.**

- Truncates input to 6,000 chars (Gemma context limit)
- Prompt extracts: Summary (3-5 sentences), Key Points (max 7), Action Items, People Mentioned
- Fallback: `call_flash(messages=[...])` from `orchestrator.gemini_client`

### `ingest_youtube_video(video_id, title="", requested_by="director", pre_fetched_transcript=None) -> dict`
**Full pipeline.** Steps:
1. Use `pre_fetched_transcript` if provided, else `fetch_youtube_transcript()`
2. Title lookup via `noembed.com` (free, no API key)
3. Summarize with Gemma 4 → Flash fallback
4. Build full text block (header + summary + transcript)
5. Store in `meeting_transcripts` via `store.store_meeting_transcript()` with `source="youtube"`
6. Mark processed in `trigger_log` (dedup)
7. Extract deadlines via `deadline_manager`

Returns: `{"status": "ok", "title": ..., "summary": ..., "transcript_id": "youtube_{video_id}", ...}`

---

## API Endpoint

```
POST /api/youtube/ingest
Headers: X-Baker-Key: bakerbhavanga, Content-Type: application/json
```

**Request body:**
```json
{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "title": "Optional title override",
    "transcript": "Optional pre-fetched transcript text (for cloud IP workaround)"
}
```

**Response:**
```json
{
    "status": "ok",
    "title": "Video Title",
    "video_id": "erV_8yrGMA8",
    "language": "en",
    "transcript_length": 25858,
    "summary": "**Summary**\n...",
    "transcript_id": "youtube_erV_8yrGMA8"
}
```

If already ingested: `{"status": "already_ingested", "title": ..., "summary": ..., "video_id": ...}`

---

## Storage

### Table: `meeting_transcripts`
Same table as Fireflies and Plaud. Key fields:
- `id` = `youtube_{video_id}` (e.g., `youtube_erV_8yrGMA8`)
- `source` = `'youtube'`
- `title` = video title from noembed.com
- `summary` = Gemma 4 output
- `full_transcript` = header block + summary + full transcript text
- `meeting_date` = ingestion timestamp (UTC)

### Dedup: `trigger_log`
- `source` = `'youtube'`
- `source_id` = `youtube_{video_id}`

---

## Auto-Detection Entry Points

### 1. Baker Scan (`/api/scan`)
When Director types/pastes a YouTube URL in Baker chat:
- `detect_youtube_urls(question)` finds video IDs
- Max 2 per query
- Non-fatal — scan continues if fetch fails
- Transcript available to agent for that query

### 2. WhatsApp (`triggers/waha_webhook.py`)
When Director sends YouTube URL via WhatsApp:
- Only Director messages (`is_director_msg`)
- Max 1 per message
- Non-fatal

---

## LLM Cost Model

| Component | Cost | Provider |
|-----------|------|----------|
| Transcript fetch | Free | youtube-transcript-api (public captions) |
| Title lookup | Free | noembed.com |
| Summarization (Gemma 4) | Free | Local Ollama |
| Summarization (Flash fallback) | ~$0.005/video | Gemini Flash (only when Gemma unavailable) |
| Deadline extraction | Free | Regex-based, no LLM |
| Storage | Negligible | 1 row in PostgreSQL |

**Net cost per video: $0.00 when Gemma available, ~$0.005 on Flash fallback.**

---

## Ollama Endpoints

Gemma 4 is accessed via Ollama. Two endpoints are tried in order:

1. **`http://localhost:11434`** — Director's MacBook (direct)
2. **`https://ollama.brisen-infra.com`** — Cloudflare tunnel to MacBook

Ollama model: `gemma4:latest` (Gemma 4 E4B, ~52 tokens/sec local)

**Note:** Render does NOT have local Ollama. On Render, Gemma calls fail and the system falls back to Gemini Flash automatically. This is by design.

---

## Gotchas / Known Issues

1. **youtube-transcript-api v1.x breaking change**: The old class-method API (`YouTubeTranscriptApi.list_transcripts()`) no longer exists. Must use instance-based: `YouTubeTranscriptApi().fetch()`. Snippets have `.text`, `.start`, `.duration` attributes (not dict keys).

2. **YouTube blocks Render cloud IPs**: Most videos return IP-blocked errors from Render. Workaround: fetch locally, POST with `transcript` field.

3. **Gemma context limit**: Transcript truncated to 6,000 chars for summarization. Full transcript still stored in DB.

4. **No commitment extraction**: Unlike Fireflies/Plaud meeting transcripts, YouTube videos typically aren't meetings with personal commitments. Only deadline extraction runs (regex-based, cheap).
