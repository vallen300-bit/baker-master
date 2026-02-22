"""
Baker AI — CEO Dashboard API Server
FastAPI app serving REST endpoints for the Baker Dashboard.
Reads from PostgreSQL via existing store_back + retriever.
Serves static frontend from outputs/static/.
Includes /api/scan SSE endpoint for interactive Baker chat.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config.settings import config
from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT

logger = logging.getLogger("sentinel.dashboard")

# ============================================================
# Authentication
# ============================================================

_BAKER_API_KEY = os.getenv("BAKER_API_KEY", "")


async def verify_api_key(x_baker_key: str = Header(None, alias="X-Baker-Key")):
    """Validate API key from X-Baker-Key header."""
    if not _BAKER_API_KEY:
        # If no key configured, log warning but allow (dev mode)
        logger.warning("BAKER_API_KEY not set — API is unauthenticated!")
        return
    if x_baker_key != _BAKER_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "X-Baker-Key"},
        )


# ============================================================
# App setup
# ============================================================

app = FastAPI(
    title="Baker CEO Dashboard",
    description="REST API for the Baker AI CEO cockpit",
    version="1.0.0",
)

# CORS — restricted to known origins
_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8080").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Baker-Key"],
)

# ============================================================
# Singletons (initialized on startup)
# ============================================================

_store = None
_retriever = None
_static_dir = Path(__file__).parent / "static"
_briefing_dir = Path(__file__).resolve().parent.parent.parent / "04_outputs" / "briefings"


def _get_store():
    """Lazy-initialize the store singleton."""
    global _store
    if _store is None:
        from memory.store_back import SentinelStoreBack
        _store = SentinelStoreBack._get_global_instance()
    return _store


def _get_retriever():
    """Lazy-initialize the retriever singleton."""
    global _retriever
    if _retriever is None:
        from memory.retriever import SentinelRetriever
        _retriever = SentinelRetriever()
    return _retriever


# ============================================================
# Scan request model
# ============================================================

class ScanRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    history: list = Field(default_factory=list)  # [{role, content}, ...]


def _serialize(obj: dict) -> dict:
    """Convert datetime fields to ISO strings for JSON serialization."""
    out = {}
    for k, v in obj.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, memoryview):
            out[k] = bytes(v).decode("utf-8", errors="replace")
        else:
            out[k] = v
    return out


# ============================================================
# Startup
# ============================================================

@app.on_event("startup")
async def startup():
    """Initialize shared resources on server start."""
    logger.info("Baker Dashboard starting...")
    # Pre-warm the store connection
    try:
        store = _get_store()
        logger.info("PostgreSQL store initialized")
    except Exception as e:
        logger.warning(f"PostgreSQL connection failed on startup (will retry): {e}")

    # Mount static files if directory exists
    if _static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
        logger.info(f"Static files mounted from {_static_dir}")

    logger.info("Baker Dashboard ready on port 8080")


# ============================================================
# Root — serve index.html
# ============================================================

@app.get("/", include_in_schema=False)
async def root():
    """Serve the dashboard frontend."""
    index_path = _static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Baker Dashboard — no frontend deployed yet"}


# ============================================================
# API Endpoints
# ============================================================

# --- Alerts ---

@app.get("/api/alerts", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def get_alerts(tier: Optional[int] = Query(None, ge=1, le=3)):
    """
    Get pending alerts. Optionally filter by tier (1=URGENT, 2=IMPORTANT, 3=INFO).
    """
    try:
        store = _get_store()
        alerts = store.get_pending_alerts(tier=tier)
        alerts = [_serialize(a) for a in alerts]
        return {"alerts": alerts, "count": len(alerts)}
    except Exception as e:
        logger.error(f"/api/alerts failed: {e}")
        return {"alerts": [], "count": 0, "error": str(e)}


@app.post("/api/alerts/{alert_id}/acknowledge", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def acknowledge_alert(alert_id: int):
    """Mark an alert as acknowledged."""
    try:
        store = _get_store()
        store.acknowledge_alert(alert_id)
        return {"status": "acknowledged", "id": alert_id}
    except Exception as e:
        logger.error(f"/api/alerts/{alert_id}/acknowledge failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/alerts/{alert_id}/resolve", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def resolve_alert(alert_id: int):
    """Mark an alert as resolved."""
    try:
        store = _get_store()
        store.resolve_alert(alert_id)
        return {"status": "resolved", "id": alert_id}
    except Exception as e:
        logger.error(f"/api/alerts/{alert_id}/resolve failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Deals ---

@app.get("/api/deals", tags=["deals"], dependencies=[Depends(verify_api_key)])
async def get_deals():
    """Get all active deals."""
    try:
        store = _get_store()
        deals = store.get_active_deals()
        deals = [_serialize(d) for d in deals]
        return {"deals": deals, "count": len(deals)}
    except Exception as e:
        logger.error(f"/api/deals failed: {e}")
        return {"deals": [], "count": 0, "error": str(e)}


# --- Contacts ---

@app.get("/api/contacts/{name}", tags=["contacts"], dependencies=[Depends(verify_api_key)])
async def get_contact(name: str):
    """Look up a contact by name (fuzzy match)."""
    try:
        store = _get_store()
        contact = store.get_contact_by_name(name)
        if not contact:
            raise HTTPException(status_code=404, detail=f"Contact '{name}' not found")
        return _serialize(contact)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/contacts/{name} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Decisions ---

@app.get("/api/decisions", tags=["decisions"], dependencies=[Depends(verify_api_key)])
async def get_decisions(limit: int = Query(10, ge=1, le=50)):
    """Get recent decisions from the pipeline."""
    try:
        store = _get_store()
        decisions = store.get_recent_decisions(limit=limit)
        decisions = [_serialize(d) for d in decisions]
        return {"decisions": decisions, "count": len(decisions)}
    except Exception as e:
        logger.error(f"/api/decisions failed: {e}")
        return {"decisions": [], "count": 0, "error": str(e)}


# --- Briefing ---

@app.get("/api/briefing/latest", tags=["briefing"], dependencies=[Depends(verify_api_key)])
async def get_latest_briefing():
    """Get the most recent morning briefing content."""
    # Check multiple possible briefing directories
    search_dirs = [_briefing_dir]

    # Also check the path used by briefing_trigger.py
    alt_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "04_outputs" / "briefings"
    )
    if alt_dir != _briefing_dir:
        search_dirs.append(alt_dir)

    for d in search_dirs:
        if d.exists():
            files = sorted(d.glob("briefing_*.md"), reverse=True)
            if files:
                try:
                    content = files[0].read_text(encoding="utf-8")
                    return {
                        "date": files[0].stem.replace("briefing_", ""),
                        "content": content,
                        "filename": files[0].name,
                    }
                except Exception as e:
                    logger.error(f"Failed to read briefing file {files[0]}: {e}")

    return {"date": None, "content": "No briefings found.", "filename": None}


# --- System Status ---

@app.get("/api/status", tags=["system"], dependencies=[Depends(verify_api_key)])
async def get_status():
    """System health summary for the dashboard header."""
    try:
        store = _get_store()
        alerts = store.get_pending_alerts()
        tier1_count = sum(1 for a in alerts if a.get("tier") == 1)
        tier2_count = sum(1 for a in alerts if a.get("tier") == 2)
        deals = store.get_active_deals()

        return {
            "system": "operational",
            "alerts_pending": len(alerts),
            "alerts_tier1": tier1_count,
            "alerts_tier2": tier2_count,
            "deals_active": len(deals),
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"/api/status failed: {e}")
        return {
            "system": "degraded",
            "error": str(e),
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }


# ============================================================
# Scan (Baker Chat) — SSE Streaming
# ============================================================

def _format_scan_context(contexts) -> str:
    """Format retrieved contexts into a compact block for the scan system prompt."""
    if not contexts:
        return "[No relevant context found in memory]"

    sections = {}
    for ctx in contexts:
        source = ctx.source.upper()
        if source not in sections:
            sections[source] = []
        sections[source].append(ctx)

    blocks = []
    for source, items in sections.items():
        blocks.append(f"\n--- {source} ({len(items)} items) ---")
        for item in items:
            label = item.metadata.get("label", "unknown")
            date_str = item.metadata.get("date", "")
            meta = f" [{date_str}]" if date_str else ""
            blocks.append(f"[{source}] {label}{meta}: {item.content[:600]}")

    return "\n".join(blocks)


@app.post("/api/scan", tags=["scan"], dependencies=[Depends(verify_api_key)])
async def scan_chat(req: ScanRequest):
    """
    Baker Scan — interactive chat with SSE streaming.
    Retrieves cross-source context, streams Claude response,
    and logs the interaction to store-back.
    """
    start = time.time()

    # 1. Retrieve context
    try:
        retriever = _get_retriever()
        contexts = retriever.search_all_collections(
            query=req.question,
            limit_per_collection=8,
            score_threshold=0.3,
        )
        logger.info(f"Scan: retrieved {len(contexts)} contexts for: {req.question[:80]}")
    except Exception as e:
        logger.error(f"Scan retrieval failed: {e}")
        contexts = []

    # 2. Build system prompt with context
    context_block = _format_scan_context(contexts)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    system_prompt = (
        f"{SCAN_SYSTEM_PROMPT}\n"
        f"## CURRENT TIME\n{now}\n\n"
        f"## RETRIEVED CONTEXT\n{context_block}"
    )

    # 3. Build messages (include history for follow-ups)
    messages = []
    for msg in (req.history or [])[-10:]:  # last 10 messages max
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    # Current question
    messages.append({"role": "user", "content": req.question})

    # 4. Stream Claude response via SSE
    async def event_stream():
        full_response = ""
        try:
            claude = anthropic.Anthropic(api_key=config.claude.api_key)
            with claude.messages.stream(
                model=config.claude.model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    # SSE format: data: <json>\n\n
                    payload = json.dumps({"token": text})
                    yield f"data: {payload}\n\n"
        except Exception as e:
            logger.error(f"Scan stream error: {e}")
            err_payload = json.dumps({"error": str(e)})
            yield f"data: {err_payload}\n\n"

        # Send [DONE] signal
        yield "data: [DONE]\n\n"

        # 5. Store-back (non-blocking, fire-and-forget)
        elapsed_ms = int((time.time() - start) * 1000)
        try:
            store = _get_store()
            store.log_decision(
                decision=f"Scan answer: {req.question[:100]}",
                reasoning=full_response[:500],
                confidence="medium",
                trigger_type="scan",
            )
            logger.info(f"Scan complete: {elapsed_ms}ms, {len(full_response)} chars")
        except Exception as e:
            logger.warning(f"Scan store-back failed (non-fatal): {e}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# CLI runner
# ============================================================

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    uvicorn.run(
        "outputs.dashboard:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info",
    )
