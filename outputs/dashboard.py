"""
Baker AI — CEO Dashboard API Server
FastAPI app serving REST endpoints for the Baker Dashboard.
Reads from PostgreSQL via existing store_back + retriever.
Serves static frontend from outputs/static/.
Includes /api/scan SSE endpoint for interactive Baker chat.
"""
import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config.settings import config
from document_generator import generate_document, get_file, cleanup_old_files
from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT
from orchestrator import action_handler as _ah
from tools.ingest.pipeline import ingest_file
from tools.ingest.extractors import SUPPORTED_EXTENSIONS
from tools.ingest.classifier import VALID_COLLECTIONS
from triggers.embedded_scheduler import start_scheduler, stop_scheduler, get_scheduler_status

logger = logging.getLogger("sentinel.dashboard")

# ============================================================
# Authentication
# ============================================================

_BAKER_API_KEY = os.getenv("BAKER_API_KEY", "")


async def verify_api_key(x_baker_key: str = Header(None, alias="X-Baker-Key")):
    """Validate API key from X-Baker-Key header."""
    if not _BAKER_API_KEY:
        logger.error("BAKER_API_KEY not configured — API disabled")
        raise HTTPException(
            status_code=503,
            detail="API key not configured — service disabled",
        )
    if x_baker_key != _BAKER_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "X-Baker-Key"},
        )


# ============================================================
# Logging — must be module-level so uvicorn outputs.dashboard:app picks it up
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
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

from triggers.waha_webhook import router as waha_router
app.include_router(waha_router)

from outputs.email_router import router as email_router
app.include_router(email_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Baker-Key"],
)

# ============================================================
# Singletons (initialized on startup)
# ============================================================

_store = None
_retriever = None
_clickup_client = None
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


def _get_clickup_client():
    """Lazy-initialize the ClickUp client singleton."""
    global _clickup_client
    if _clickup_client is None:
        from clickup_client import ClickUpClient
        _clickup_client = ClickUpClient._get_global_instance()
    return _clickup_client


# ============================================================
# Request models
# ============================================================

class ScanRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    history: list = Field(default_factory=list)  # [{role, content}, ...]
    project: Optional[str] = None   # scope search to project (e.g. "rg7")
    role: Optional[str] = None      # scope search to role (e.g. "chairman")


class CreateTaskRequest(BaseModel):
    list_id: str
    name: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=4)
    status: Optional[str] = None


class UpdateTaskRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[int] = Field(None, ge=1, le=4)
    name: Optional[str] = None
    description: Optional[str] = None


class CommentRequest(BaseModel):
    comment_text: str = Field(..., min_length=1, max_length=5000)


class DocumentRequest(BaseModel):
    content: str = Field(..., description="Markdown or JSON content for document body")
    format: str = Field(..., pattern=r"^(docx|xlsx|pdf|pptx)$")
    title: str = Field("Baker Document", max_length=200)


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

    # Start Sentinel trigger scheduler (BackgroundScheduler)
    try:
        start_scheduler()
        logger.info("Sentinel scheduler started (BackgroundScheduler)")
    except Exception as e:
        logger.error(f"Scheduler failed to start: {e}")

    # FIREFLIES-FETCH-1: Backfill last 30 days of Fireflies history on deploy
    try:
        from triggers.fireflies_trigger import backfill_fireflies
        backfill_fireflies()
    except Exception as e:
        logger.warning(f"Fireflies backfill failed on startup (non-fatal): {e}")

    # Mount static files if directory exists
    if _static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
        logger.info(f"Static files mounted from {_static_dir}")


@app.on_event("shutdown")
async def shutdown():
    """Graceful shutdown of scheduler."""
    try:
        stop_scheduler()
        logger.info("Sentinel scheduler stopped")
    except Exception as e:
        logger.warning(f"Scheduler shutdown error: {e}")


@app.get("/api/client-config", include_in_schema=False)
async def client_config():
    return {"apiKey": _BAKER_API_KEY}

    logger.info("Baker Dashboard ready on port 8080")


@app.get("/api/scheduler-status", tags=["health"], dependencies=[Depends(verify_api_key)])
async def scheduler_status():
    """Return scheduler health and registered jobs."""
    return get_scheduler_status()


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


# --- Deadlines (DEADLINE-SYSTEM-1) ---

@app.get("/api/deadlines", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def get_deadlines(
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Get active deadlines for the dashboard."""
    try:
        from models.deadlines import get_active_deadlines
        deadlines = get_active_deadlines(limit=limit)
        deadlines = [_serialize(d) for d in deadlines]
        return {"deadlines": deadlines, "count": len(deadlines)}
    except Exception as e:
        logger.error(f"/api/deadlines failed: {e}")
        return {"deadlines": [], "count": 0, "error": str(e)}


@app.post("/api/deadlines/{deadline_id}/dismiss", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def dismiss_deadline_api(deadline_id: int):
    """Dismiss a deadline."""
    try:
        from models.deadlines import update_deadline, get_deadline_by_id
        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")
        update_deadline(deadline_id, status="dismissed", dismissed_reason="Dismissed via dashboard")
        return {"status": "dismissed", "id": deadline_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/dismiss failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/deadlines/{deadline_id}/complete", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def complete_deadline_api(deadline_id: int):
    """Mark a deadline as completed."""
    try:
        from models.deadlines import update_deadline, get_deadline_by_id
        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")
        update_deadline(deadline_id, status="completed", dismissed_reason="Completed via dashboard")
        return {"status": "completed", "id": deadline_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/complete failed: {e}")
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


# --- Semantic Search ---

@app.get("/api/search", tags=["search"], dependencies=[Depends(verify_api_key)])
async def search_memory(
    q: str = Query(None, min_length=2, max_length=500),
    limit: int = Query(20, ge=1, le=50),
    threshold: float = Query(0.3, ge=0.0, le=1.0),
    project: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
):
    """
    Semantic search across all of Baker's memory (Qdrant vector collections).
    Searches documents, emails, meetings, WhatsApp, contacts, ClickUp tasks.
    Optional project/role filters scope results to tagged documents only.
    """
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required (min 2 characters)")

    try:
        retriever = _get_retriever()
        contexts = retriever.search_all_collections(
            query=q.strip(),
            limit_per_collection=limit,
            score_threshold=threshold,
            project=project,
            role=role,
        )
        results = [
            {
                "content": ctx.content,
                "source": ctx.source,
                "score": round(ctx.score, 4),
                "metadata": ctx.metadata,
            }
            for ctx in contexts
        ][:limit]
        return {
            "query": q.strip(),
            "result_count": len(results),
            "results": results,
        }
    except Exception as e:
        logger.error(f"/api/search failed: {e}")
        raise HTTPException(status_code=500, detail="Search service unavailable")


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

        status_data = {
            "system": "operational",
            "alerts_pending": len(alerts),
            "alerts_tier1": tier1_count,
            "alerts_tier2": tier2_count,
            "deals_active": len(deals),
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }

        # Email watermark health
        email_wm = None
        email_wm_age_hours = None
        email_wm_healthy = True
        try:
            from triggers.state import trigger_state
            wm = trigger_state.get_watermark("email_poll")
            if wm:
                email_wm = wm.isoformat()
                email_wm_age_hours = round(
                    (datetime.now(timezone.utc) - wm).total_seconds() / 3600, 1
                )
                email_wm_healthy = email_wm_age_hours < 24
        except Exception:
            pass

        status_data["email_watermark"] = email_wm
        status_data["email_watermark_age_hours"] = email_wm_age_hours
        status_data["email_watermark_healthy"] = email_wm_healthy

        return status_data
    except Exception as e:
        logger.error(f"/api/status failed: {e}")
        return {
            "system": "degraded",
            "error": str(e),
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }


# ============================================================
# ClickUp Endpoints (Read + Write)
# ============================================================

_BAKER_SPACE_ID = "901510186446"


@app.get("/api/clickup/tasks", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def get_clickup_tasks(
    workspace_id: Optional[str] = Query(None),
    space_id: Optional[str] = Query(None),
    list_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Query ClickUp tasks from PostgreSQL with optional filters."""
    try:
        store = _get_store()
        tasks = store.get_clickup_tasks(
            workspace_id=workspace_id,
            space_id=space_id,
            list_id=list_id,
            status=status,
            priority=priority,
            limit=limit,
            offset=offset,
        )
        tasks = [_serialize(t) for t in tasks]
        return {"tasks": tasks, "count": len(tasks)}
    except Exception as e:
        logger.error(f"/api/clickup/tasks failed: {e}")
        return {"tasks": [], "count": 0, "error": str(e)}


@app.get("/api/clickup/tasks/{task_id}", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def get_clickup_task(task_id: str):
    """Get a single ClickUp task detail + comments."""
    try:
        store = _get_store()
        task = store.get_clickup_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

        result = _serialize(task)

        # Fetch live comments from ClickUp API
        try:
            client = _get_clickup_client()
            comments = client.get_task_comments(task_id)
            result["comments"] = comments or []
        except Exception as e:
            logger.warning(f"Failed to fetch comments for task {task_id}: {e}")
            result["comments"] = []

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/clickup/tasks/{task_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/clickup/sync-status", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def get_clickup_sync_status():
    """Get ClickUp sync health: last poll per workspace, total count."""
    try:
        store = _get_store()
        status = store.get_clickup_sync_status()
        # Serialize datetime fields in workspace rows
        if status.get("workspaces"):
            status["workspaces"] = [_serialize(w) for w in status["workspaces"]]
        return status
    except Exception as e:
        logger.error(f"/api/clickup/sync-status failed: {e}")
        return {"workspaces": [], "total_tasks": 0, "health": "error", "error": str(e)}


@app.post("/api/clickup/tasks", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def create_clickup_task(req: CreateTaskRequest):
    """Create a task in ClickUp — BAKER space only."""
    try:
        client = _get_clickup_client()

        # Validate list belongs to BAKER space
        space_id = client._resolve_space_id_for_list(req.list_id)
        if str(space_id) != _BAKER_SPACE_ID:
            raise HTTPException(
                status_code=403,
                detail=f"Write rejected: list {req.list_id} is not in BAKER space",
            )

        result = client.create_task(
            list_id=req.list_id,
            name=req.name,
            description=req.description,
            priority=req.priority,
            status=req.status,
        )
        if result is None:
            raise HTTPException(status_code=502, detail="ClickUp API returned no result")
        return {"task": result, "status": "created"}
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"POST /api/clickup/tasks failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/clickup/tasks/{task_id}", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def update_clickup_task(task_id: str, req: UpdateTaskRequest):
    """Update a task in ClickUp — BAKER space only."""
    try:
        client = _get_clickup_client()

        # Build update kwargs from non-None fields
        update_fields = {}
        if req.status is not None:
            update_fields["status"] = req.status
        if req.priority is not None:
            update_fields["priority"] = req.priority
        if req.name is not None:
            update_fields["name"] = req.name
        if req.description is not None:
            update_fields["description"] = req.description

        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        result = client.update_task(task_id, **update_fields)
        if result is None:
            raise HTTPException(status_code=502, detail="ClickUp API returned no result")
        return {"task": result, "status": "updated"}
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"PUT /api/clickup/tasks/{task_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clickup/tasks/{task_id}/comments", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def create_clickup_comment(task_id: str, req: CommentRequest):
    """Post a comment on a ClickUp task — BAKER space only."""
    try:
        client = _get_clickup_client()

        result = client.post_comment(task_id, req.comment_text)
        if result is None:
            raise HTTPException(status_code=502, detail="ClickUp API returned no result")
        return {"comment": result, "status": "created"}
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"POST /api/clickup/tasks/{task_id}/comments failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


def _chunk_conversation(text, max_chars=8000):
    """Split long conversation text by paragraphs, respecting max_chars. (CONV-MEM-1)"""
    paragraphs = text.split('\n\n')
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars:
            if current:
                chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current:
        chunks.append(current.strip())
    return chunks if chunks else [text[:max_chars]]


def _action_stream_response(text: str, question: str) -> StreamingResponse:
    """
    Wrap an action result as a single-token SSE response (bypasses RAG pipeline).
    Also fires the Type 2 scan result email so the Director gets a copy.
    """
    async def _stream():
        payload = json.dumps({"token": text})
        yield f"data: {payload}\n\n"
        yield "data: [DONE]\n\n"
        # EMAIL-REFORM-1: Type 2 email only when Director explicitly requests it
        try:
            from outputs.email_alerts import has_email_intent, send_scan_result_email
            if has_email_intent(question):
                send_scan_result_email(question, text)
                logger.info("Scan result emailed (explicit request detected)")
        except Exception as _e:
            logger.warning(f"Action email notification failed (non-fatal): {_e}")

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/scan", tags=["scan"], dependencies=[Depends(verify_api_key)])
async def scan_chat(req: ScanRequest):
    """
    Baker Scan — interactive chat with SSE streaming.
    Retrieves cross-source context, streams Claude response,
    and logs the interaction to store-back.
    """
    start = time.time()

    # SCAN-ACTION-1: Email action routing — check before RAG pipeline
    draft_action = _ah.check_pending_draft(req.question)
    if draft_action == "confirm":
        return _action_stream_response(_ah.handle_confirmation(), req.question)
    elif draft_action and draft_action.startswith("edit:"):
        return _action_stream_response(
            _ah.handle_edit(draft_action[5:], _get_retriever(), req.project, req.role),
            req.question,
        )
    elif draft_action is None:
        # No pending draft — classify intent for new actions
        intent = _ah.classify_intent(req.question)
        if intent.get("type") == "email_action":
            return _action_stream_response(
                _ah.handle_email_action(intent, _get_retriever(), req.project, req.role),
                req.question,
            )
        elif intent.get("type") == "deadline_action":
            return _action_stream_response(
                _ah.handle_deadline_action(intent),
                req.question,
            )
        elif intent.get("type") == "vip_action":
            return _action_stream_response(
                _ah.handle_vip_action(intent),
                req.question,
            )
        elif intent.get("type") == "fireflies_fetch":
            return _action_stream_response(
                _ah.handle_fireflies_fetch(
                    req.question, _get_retriever(), req.project, req.role,
                    channel="scan",
                ),
                req.question,
            )
    # draft_action == "dismiss" or regular question → fall through to RAG pipeline

    # 1. Retrieve context
    try:
        retriever = _get_retriever()
        contexts = retriever.search_all_collections(
            query=req.question,
            limit_per_collection=8,
            score_threshold=0.3,
            project=req.project,
            role=req.role,
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

        # 5b. Store full Q+A in Qdrant for conversation memory (CONV-MEM-1)
        try:
            store = _get_store()
            conversation_content = (
                f"[CONVERSATION]\n"
                f"Question: {req.question}\n\n"
                f"Answer: {full_response}"
            )
            conv_metadata = {
                "type": "conversation",
                "source": "scan",
                "question": req.question[:500],
                "project": req.project or "general",
                "role": req.role or "ceo",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "answer_length": len(full_response),
                "token_estimate": len(full_response) // 4,
            }

            if len(conversation_content) <= 8000:
                store.store_document(
                    content=conversation_content,
                    metadata=conv_metadata,
                    collection="baker-conversations",
                )
                chunk_count = 1
            else:
                chunks = _chunk_conversation(conversation_content, max_chars=8000)
                for i, chunk in enumerate(chunks):
                    chunk_meta = {
                        **conv_metadata,
                        "chunk_index": i,
                        "chunk_count": len(chunks),
                    }
                    store.store_document(
                        content=chunk,
                        metadata=chunk_meta,
                        collection="baker-conversations",
                    )
                chunk_count = len(chunks)

            store.log_conversation(
                question=req.question,
                answer_length=len(full_response),
                project=req.project or "general",
                chunk_count=chunk_count,
            )
            logger.info("Conversation stored in Baker's memory (CONV-MEM-1)")
        except Exception as e:
            logger.warning(f"Conversation store-back failed (non-fatal): {e}")

        # 5c. Email scan result to Director (EMAIL-REFORM-1 Type 2 — opt-in only)
        if full_response:
            try:
                from outputs.email_alerts import has_email_intent, send_scan_result_email
                if has_email_intent(req.question):
                    send_scan_result_email(req.question, full_response)
                    logger.info("Scan result emailed (explicit request detected)")
            except Exception as e:
                logger.warning(f"Scan email failed (non-fatal): {e}")

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
# Document generation endpoints (SCAN-OUTPUT-1)
# ============================================================

@app.post("/api/scan/generate-document", tags=["scan"], dependencies=[Depends(verify_api_key)])
async def generate_doc_endpoint(req: DocumentRequest):
    """Generate a downloadable document from Baker Scan output."""
    try:
        metadata = {
            "generated_by": "Baker Scan",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        file_id, filename, size_bytes = generate_document(
            content=req.content,
            fmt=req.format,
            title=req.title,
            metadata=metadata,
        )
        return {
            "file_id": file_id,
            "filename": filename,
            "size_bytes": size_bytes,
            "download_url": f"/api/scan/download/{file_id}",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Document generation failed: {e}")
        raise HTTPException(status_code=500, detail="Document generation failed")


@app.get("/api/scan/download/{file_id}", tags=["scan"])
async def download_document(file_id: str):
    """Download a generated document. No auth — UUID acts as token."""
    info = get_file(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found or expired")
    if not os.path.exists(info["filepath"]):
        raise HTTPException(status_code=410, detail="File no longer available")

    media_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return FileResponse(
        path=info["filepath"],
        filename=info["filename"],
        media_type=media_types.get(info["format"], "application/octet-stream"),
    )


# ============================================================
# Ingest endpoints (INGEST-2)
# ============================================================

@app.post("/api/ingest", tags=["ingest"], dependencies=[Depends(verify_api_key)])
async def ingest_document(
    file: UploadFile = File(...),
    collection: str = Query(None, description="Target collection override"),
    image_type: str = Form(None, description="Image mode: card, whiteboard, or auto"),
    project: str = Form(None, description="Project tag: rg7, hagenauer, movie-hotel-asset-management"),
    role: str = Form(None, description="Role tag: chairman, network, private, travel"),
):
    """Ingest a single document or image via dashboard upload."""

    # 0. Validate project/role tags
    ALLOWED_PROJECTS = {"rg7", "hagenauer", "movie-hotel-asset-management"}
    ALLOWED_ROLES = {"chairman", "network", "private", "travel"}

    if project and project not in ALLOWED_PROJECTS:
        raise HTTPException(400, f"Invalid project: {project}. Valid: {', '.join(sorted(ALLOWED_PROJECTS))}")
    if role and role not in ALLOWED_ROLES:
        raise HTTPException(400, f"Invalid role: {role}. Valid: {', '.join(sorted(ALLOWED_ROLES))}")

    # 1. Validate file extension
    ext = Path(file.filename).suffix.lower()
    if ext == ".doc":
        raise HTTPException(
            status_code=400,
            detail=".doc files are not supported. Please save as .docx in Word and re-upload."
        )
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # 2. Validate collection if provided
    if collection and collection not in VALID_COLLECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown collection: {collection}. Valid: {', '.join(sorted(VALID_COLLECTIONS))}"
        )

    # 3. Validate image_type if provided
    if image_type and image_type not in ("card", "whiteboard", "auto"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid image_type: {image_type}. Valid: card, whiteboard, auto"
        )

    # 4. Validate file size (100MB max)
    contents = await file.read()
    if len(contents) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum size: 100MB.")

    # 5. Write to temp file (preserve original filename for classifier heuristics)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=ext,
            prefix=Path(file.filename).stem + "_",
        ) as tmp:
            tmp.write(contents)
            tmp_path = Path(tmp.name)

        # 6. Run pipeline in thread to avoid blocking event loop
        result = await asyncio.to_thread(
            ingest_file,
            filepath=tmp_path,
            collection=collection,
            image_type=image_type,
            project=project,
            role=role,
        )

        # 7. Return result
        if result.error:
            raise HTTPException(status_code=500, detail=f"Ingestion failed: {result.error}")

        response = {
            "status": "skipped" if result.skipped else "success",
            "filename": file.filename,
            "collection": result.collection,
            "chunks": result.chunk_count,
            "dedup": result.skipped and "duplicate" in (result.skip_reason or "").lower(),
            "skip_reason": result.skip_reason,
            "project": project,
            "role": role,
        }

        # Include card extraction data if present
        if result.card_data:
            response["card_data"] = result.card_data
        if result.contact_result:
            response["contact_result"] = result.contact_result

        return response
    finally:
        # 8. Clean up temp file
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


@app.get("/api/ingest/collections", tags=["ingest"], dependencies=[Depends(verify_api_key)])
async def list_collections():
    """Return available collections for the upload dropdown."""
    return {"collections": sorted(VALID_COLLECTIONS)}


# ============================================================
# RSS Feed Management (RSS-1)
# ============================================================

@app.post("/api/rss/import-opml", tags=["rss"], dependencies=[Depends(verify_api_key)])
async def rss_import_opml(request: Request):
    """Accept raw OPML XML body, parse, populate rss_feeds table."""
    body = await request.body()
    opml_text = body.decode("utf-8")
    if not opml_text.strip():
        raise HTTPException(status_code=400, detail="Empty OPML body")
    from triggers.rss_trigger import import_opml
    result = import_opml(opml_text)
    return {"status": "ok", **result}


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
