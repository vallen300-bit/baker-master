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
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
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

from triggers.slack_events import router as slack_events_router
app.include_router(slack_events_router, prefix="/webhook")

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


class AlertReplyRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class SpecialistScanRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    capability_slug: str = Field(..., min_length=1, max_length=50)
    history: list = Field(default_factory=list)


class AlertTagRequest(BaseModel):
    action: str = Field(..., pattern=r"^(add|remove)$")
    tag: str = Field(..., min_length=1, max_length=30, pattern=r"^[a-z0-9-]+$")


class FollowupRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    answer: str = Field(..., min_length=1, max_length=2000)


class AlertAssignRequest(BaseModel):
    matter_slug: str = Field(..., min_length=1, max_length=50)
    new_name: Optional[str] = Field(None, max_length=200)


class SaveArtifactRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100000)
    title: str = Field("Baker Result", max_length=200)
    matter_slug: Optional[str] = None
    alert_id: Optional[int] = None
    format: str = Field("md", pattern=r"^(md|txt)$")


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
        # COCKPIT-ALERT-UI: ensure structured_actions column exists
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS structured_actions JSONB")
                conn.commit()
                cur.close()
                logger.info("COCKPIT-ALERT-UI: structured_actions column ensured")
            except Exception as me:
                conn.rollback()
                logger.warning(f"COCKPIT-ALERT-UI migration (non-fatal): {me}")
            finally:
                store._put_conn(conn)
    except Exception as e:
        logger.warning(f"PostgreSQL connection failed on startup (will retry): {e}")

    # Start Sentinel trigger scheduler (BackgroundScheduler)
    try:
        start_scheduler()
        logger.info("Sentinel scheduler started (BackgroundScheduler)")
    except Exception as e:
        logger.error(f"Scheduler failed to start: {e}")

    # Backfills in background threads — delayed 60s to let scheduler stabilize (OOM fix)
    import threading

    def _delayed_backfills():
        time.sleep(60)
        logger.info("Starting delayed backfills (60s after startup)...")
        try:
            from triggers.fireflies_trigger import backfill_fireflies
            backfill_fireflies()
        except Exception as e:
            logger.warning(f"Fireflies backfill failed (non-fatal): {e}")
        try:
            from scripts.extract_whatsapp import backfill_whatsapp
            backfill_whatsapp()
        except Exception as e:
            logger.warning(f"WhatsApp backfill failed (non-fatal): {e}")

    threading.Thread(
        target=_delayed_backfills,
        name="delayed-backfills",
        daemon=True,
    ).start()
    logger.info("Backfills scheduled (60s delay, sequential to limit memory)")

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


@app.get("/api/fireflies/status", tags=["fireflies"], dependencies=[Depends(verify_api_key)])
async def fireflies_status():
    """Diagnostic: check Fireflies API connectivity, watermark, and meeting_transcripts count."""
    import asyncio
    result = {}

    # 1. Check API key
    from config.settings import config as _cfg
    result["api_key_set"] = bool(_cfg.fireflies.api_key)
    result["api_key_preview"] = _cfg.fireflies.api_key[:8] + "..." if _cfg.fireflies.api_key else "NOT SET"

    # 2. Check watermark
    try:
        from triggers.state import trigger_state
        wm = trigger_state.get_watermark("fireflies")
        result["watermark"] = wm.isoformat()
    except Exception as e:
        result["watermark"] = f"error: {e}"

    # 3. Check meeting_transcripts row count
    try:
        store = _get_store()
        conn = store._get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM meeting_transcripts")
            result["meeting_transcripts_count"] = cur.fetchone()[0]
            cur.execute("SELECT id, title, meeting_date FROM meeting_transcripts ORDER BY ingested_at DESC LIMIT 5")
            rows = cur.fetchall()
            result["latest_transcripts"] = [{"id": r[0], "title": r[1], "date": str(r[2])} for r in rows]
            cur.close()
            store._put_conn(conn)
    except Exception as e:
        result["meeting_transcripts_count"] = f"error: {e}"

    # 4. Try fetching from Fireflies API directly
    try:
        from scripts.extract_fireflies import fetch_transcripts, transcript_date
        raw = await asyncio.to_thread(fetch_transcripts, _cfg.fireflies.api_key, 5)
        result["api_fetch_count"] = len(raw) if raw else 0
        if raw:
            result["api_latest"] = [
                {"id": t.get("id","?"), "title": t.get("title","?"), "date": str(transcript_date(t))}
                for t in raw[:3]
            ]
    except Exception as e:
        result["api_fetch_error"] = str(e)

    return result


@app.post("/api/fireflies/backfill", tags=["fireflies"], dependencies=[Depends(verify_api_key)])
async def fireflies_backfill_endpoint():
    """Trigger a one-time Fireflies transcript backfill to PostgreSQL."""
    import asyncio
    try:
        from triggers.fireflies_trigger import backfill_transcripts_only
        await asyncio.to_thread(backfill_transcripts_only)
        return {"status": "ok", "message": "Backfill completed — check /api/fireflies/status for results"}
    except Exception as e:
        logger.error(f"Fireflies backfill endpoint failed: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/emails/backfill", tags=["emails"], dependencies=[Depends(verify_api_key)])
async def email_backfill_endpoint(days: int = Query(14, ge=1, le=90)):
    """Backfill last N days of emails from Gmail API to PostgreSQL + Qdrant."""
    import asyncio
    try:
        from triggers.email_trigger import backfill_emails
        await asyncio.to_thread(backfill_emails, days)

        # Check count
        try:
            store = _get_store()
            conn = store._get_conn()
            if conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM email_messages")
                count = cur.fetchone()[0]
                cur.close()
                store._put_conn(conn)
                return {"status": "ok", "message": f"Backfill completed — {count} emails in PostgreSQL", "days": days}
        except Exception:
            pass
        return {"status": "ok", "message": "Backfill completed", "days": days}
    except Exception as e:
        logger.error(f"Email backfill endpoint failed: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/whatsapp/backfill", tags=["whatsapp"], dependencies=[Depends(verify_api_key)])
async def whatsapp_backfill_endpoint(
    days: int = Query(90, ge=1, le=365),
    background_tasks: BackgroundTasks = None,
):
    """Backfill last N days of WhatsApp messages from WAHA API to Qdrant + PostgreSQL.
    Runs in background — returns immediately with job status.
    """
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    def _run_backfill():
        try:
            from scripts.extract_whatsapp import extract_historical, ingest_to_qdrant
            items = extract_historical(since=since, limit=None, chat_id=None, dry_run=False, download_media=True)
            if items:
                ingest_to_qdrant(items)
            logger.info(f"WhatsApp backfill complete: {len(items)} chats ingested ({days} days)")
        except Exception as e:
            logger.error(f"WhatsApp backfill failed: {e}")

    if background_tasks:
        background_tasks.add_task(_run_backfill)
        return {"status": "started", "message": f"Backfill started in background ({days} days from {since})", "days": days}
    else:
        # Fallback: run inline (for testing)
        import asyncio
        try:
            count = await asyncio.to_thread(lambda: (
                extract_historical(since=since, limit=None, chat_id=None, dry_run=False, download_media=True)
            ))
            return {"status": "ok", "message": f"Backfill completed — {len(count)} chats", "days": days}
        except Exception as e:
            logger.error(f"WhatsApp backfill endpoint failed: {e}")
            return {"status": "error", "message": str(e)}


# ============================================================
# Insights (INSIGHT-1 — Claude Code → Baker memory)
# ============================================================

class MatterRequest(BaseModel):
    matter_name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    people: list = Field(default_factory=list)
    keywords: list = Field(default_factory=list)
    projects: list = Field(default_factory=list)


class MatterUpdateRequest(BaseModel):
    matter_name: Optional[str] = None
    description: Optional[str] = None
    people: Optional[list] = None
    keywords: Optional[list] = None
    projects: Optional[list] = None
    status: Optional[str] = None


class PreferenceRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=100)
    key: str = Field(..., min_length=1, max_length=200)
    value: str = Field(..., min_length=1)


class InsightRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    tags: list = Field(default_factory=list)
    source: str = Field(default="claude-code")
    project: Optional[str] = None


@app.post("/api/insights", tags=["insights"], dependencies=[Depends(verify_api_key)])
async def store_insight_endpoint(req: InsightRequest):
    """Store a strategic insight/analysis into Baker's permanent memory (PostgreSQL + Qdrant)."""
    try:
        store = _get_store()
        insight_id = store.store_insight(
            title=req.title,
            content=req.content,
            tags=req.tags,
            source=req.source,
            project=req.project,
        )
        if insight_id:
            return {"status": "stored", "id": insight_id, "title": req.title}
        return {"status": "error", "message": "Failed to store insight"}
    except Exception as e:
        logger.error(f"POST /api/insights failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/insights", tags=["insights"], dependencies=[Depends(verify_api_key)])
async def get_insights_endpoint(
    q: Optional[str] = Query(None),
    project: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """Search insights by keyword or project."""
    try:
        store = _get_store()
        results = store.get_insights(query=q, project=project, limit=limit)
        results = [_serialize(r) for r in results]
        return {"insights": results, "count": len(results)}
    except Exception as e:
        logger.error(f"GET /api/insights failed: {e}")
        return {"insights": [], "count": 0, "error": str(e)}


# ============================================================
# RETRIEVAL-FIX-1: Matter Registry API
# ============================================================

@app.get("/api/matters", tags=["matters"], dependencies=[Depends(verify_api_key)])
async def get_matters_endpoint(
    status: str = Query("active"),
):
    """List all matters, filtered by status."""
    try:
        store = _get_store()
        matters = store.get_matters(status=status)
        matters = [_serialize(m) for m in matters]
        return {"matters": matters, "count": len(matters)}
    except Exception as e:
        logger.error(f"GET /api/matters failed: {e}")
        return {"matters": [], "count": 0, "error": str(e)}


@app.post("/api/matters", tags=["matters"], dependencies=[Depends(verify_api_key)])
async def create_matter_endpoint(req: MatterRequest):
    """Create a new matter in the registry."""
    try:
        store = _get_store()
        matter_id = store.create_matter(
            matter_name=req.matter_name,
            description=req.description,
            people=req.people,
            keywords=req.keywords,
            projects=req.projects,
        )
        if matter_id:
            return {"status": "created", "id": matter_id, "matter_name": req.matter_name}
        raise HTTPException(status_code=409, detail=f"Matter '{req.matter_name}' already exists or creation failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/matters failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/matters/{matter_id}", tags=["matters"], dependencies=[Depends(verify_api_key)])
async def update_matter_endpoint(matter_id: int, req: MatterUpdateRequest):
    """Update an existing matter by ID."""
    try:
        store = _get_store()
        updates = req.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        ok = store.update_matter(matter_id, **updates)
        if ok:
            return {"status": "updated", "id": matter_id}
        raise HTTPException(status_code=404, detail=f"Matter id={matter_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PUT /api/matters/{matter_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# STEP3: Director Preferences API
# ============================================================

@app.get("/api/preferences", tags=["preferences"], dependencies=[Depends(verify_api_key)])
async def get_preferences_endpoint(
    category: Optional[str] = Query(None),
):
    """Get Director preferences, optionally filtered by category."""
    try:
        store = _get_store()
        prefs = store.get_preferences(category=category)
        prefs = [_serialize(p) for p in prefs]
        return {"preferences": prefs, "count": len(prefs)}
    except Exception as e:
        logger.error(f"GET /api/preferences failed: {e}")
        return {"preferences": [], "count": 0, "error": str(e)}


@app.post("/api/preferences", tags=["preferences"], dependencies=[Depends(verify_api_key)])
async def upsert_preference_endpoint(req: PreferenceRequest):
    """Store or update a Director preference (UPSERT by category + key)."""
    try:
        store = _get_store()
        ok = store.upsert_preference(
            category=req.category,
            key=req.key,
            value=req.value,
        )
        if ok:
            return {"status": "upserted", "category": req.category, "key": req.key}
        raise HTTPException(status_code=500, detail="Failed to upsert preference")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/preferences failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/preferences/{category}/{key}", tags=["preferences"], dependencies=[Depends(verify_api_key)])
async def delete_preference_endpoint(category: str, key: str):
    """Delete a Director preference by category and key."""
    try:
        store = _get_store()
        ok = store.delete_preference(category=category, key=key)
        if ok:
            return {"status": "deleted", "category": category, "key": key}
        raise HTTPException(status_code=404, detail=f"Preference {category}/{key} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DELETE /api/preferences/{category}/{key} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# AGENT-FRAMEWORK-1: Capability Observability API
# ============================================================

@app.get("/api/capabilities", tags=["capabilities"], dependencies=[Depends(verify_api_key)])
async def get_capabilities_endpoint(
    active_only: bool = Query(True),
):
    """List all capability sets."""
    try:
        store = _get_store()
        caps = store.get_capability_sets(active_only=active_only)
        caps = [_serialize(c) for c in caps]
        return {"capabilities": caps, "count": len(caps)}
    except Exception as e:
        logger.error(f"GET /api/capabilities failed: {e}")
        return {"capabilities": [], "count": 0, "error": str(e)}


@app.get("/api/capability-runs", tags=["capabilities"], dependencies=[Depends(verify_api_key)])
async def get_capability_runs_endpoint(
    capability: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Recent capability run history. Optional filter by capability slug."""
    try:
        store = _get_store()
        runs = store.get_capability_runs(capability_slug=capability, limit=limit)
        runs = [_serialize(r) for r in runs]
        return {"runs": runs, "count": len(runs)}
    except Exception as e:
        logger.error(f"GET /api/capability-runs failed: {e}")
        return {"runs": [], "count": 0, "error": str(e)}


@app.get("/api/decompositions", tags=["capabilities"], dependencies=[Depends(verify_api_key)])
async def get_decompositions_endpoint(
    domain: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Recent decomposition log entries with feedback status."""
    try:
        store = _get_store()
        logs = store.get_decomposition_logs(domain=domain, limit=limit)
        logs = [_serialize(l) for l in logs]
        return {"decompositions": logs, "count": len(logs)}
    except Exception as e:
        logger.error(f"GET /api/decompositions failed: {e}")
        return {"decompositions": [], "count": 0, "error": str(e)}


@app.get("/api/scheduler-status", tags=["health"], dependencies=[Depends(verify_api_key)])
async def scheduler_status():
    """Return scheduler health and registered jobs."""
    return get_scheduler_status()


# ============================================================
# Root — serve index.html
# ============================================================

@app.get("/health", tags=["system"], include_in_schema=False)
async def health_check():
    """Public health endpoint for Render + monitoring. No auth required."""
    try:
        store = _get_store()
        conn = store._get_conn()
        db_ok = conn is not None
        if conn:
            store._put_conn(conn)
    except Exception:
        db_ok = False

    scheduler_ok = False
    job_count = 0
    try:
        from triggers.embedded_scheduler import _scheduler
        if _scheduler and _scheduler.running:
            scheduler_ok = True
            job_count = len(_scheduler.get_jobs())
    except Exception:
        pass

    # Sentinel health summary
    sentinels_healthy = 0
    sentinels_down = 0
    sentinels_down_list = []
    try:
        from triggers.sentinel_health import get_all_sentinel_health
        for s in get_all_sentinel_health():
            if s.get("status") == "healthy":
                sentinels_healthy += 1
            elif s.get("status") == "down":
                sentinels_down += 1
                sentinels_down_list.append(s.get("source", "?"))
    except Exception:
        pass

    status = "healthy"
    if not db_ok or not scheduler_ok or sentinels_down > 0:
        status = "degraded"
    return {
        "status": status,
        "database": "connected" if db_ok else "disconnected",
        "scheduler": "running" if scheduler_ok else "stopped",
        "scheduled_jobs": job_count,
        "sentinels_healthy": sentinels_healthy,
        "sentinels_down": sentinels_down,
        "sentinels_down_list": sentinels_down_list,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/sentinel-health", tags=["system"], dependencies=[Depends(verify_api_key)])
async def get_sentinel_health():
    """Sentinel health status for all monitored triggers."""
    try:
        from triggers.sentinel_health import get_all_sentinel_health
        rows = get_all_sentinel_health()
    except Exception:
        rows = []

    sentinels = []
    summary = {"healthy": 0, "degraded": 0, "down": 0, "unknown": 0}
    for r in rows:
        st = r.get("status", "unknown")
        sentinels.append({
            "source": r.get("source"),
            "status": st,
            "last_success": _serialize_val(r.get("last_success_at")),
            "last_error": r.get("last_error_msg"),
            "consecutive_failures": r.get("consecutive_failures", 0),
        })
        if st in summary:
            summary[st] += 1
        else:
            summary["unknown"] += 1

    return {"sentinels": sentinels, "summary": summary}


def _serialize_val(v):
    """Serialize a single value for JSON."""
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


@app.get("/api/health", tags=["system"], include_in_schema=True)
async def api_health():
    """Public health endpoint — no auth required.
    Returns per-sentinel status for the Cowork nightly health check.
    """
    try:
        from triggers.sentinel_health import get_all_sentinel_health
        rows = get_all_sentinel_health()
    except Exception:
        rows = []

    sentinels = []
    any_down = False
    for r in rows:
        st = r.get("status", "unknown")
        if st in ("down", "degraded"):
            any_down = True
        sentinels.append({
            "name": r.get("source"),
            "status": st,
            "last_poll": _serialize_val(r.get("last_success_at")),
            "issue": r.get("last_error_msg") or "",
            "fail_count": r.get("consecutive_failures", 0),
        })

    return {
        "status": "degraded" if any_down else "healthy",
        "sentinels": sentinels,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


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
async def get_alerts(
    tier: Optional[int] = Query(None, ge=1, le=4),
    min_tier: Optional[int] = Query(None, ge=1, le=4),
):
    """
    Get pending alerts. Filter by exact tier, or min_tier (T2+ = upcoming, excludes T1).
    """
    try:
        store = _get_store()
        alerts = store.get_pending_alerts(tier=tier)
        alerts = [_serialize(a) for a in alerts]
        if min_tier:
            alerts = [a for a in alerts if a.get('tier', 1) >= min_tier]
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


@app.post("/api/alerts/{alert_id}/dismiss", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def dismiss_alert(alert_id: int):
    """Dismiss alert without acting."""
    try:
        store = _get_store()
        store.dismiss_alert(alert_id)
        return {"status": "dismissed", "id": alert_id}
    except Exception as e:
        logger.error(f"/api/alerts/{alert_id}/dismiss failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/alerts/reassign-matters", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def reassign_matters():
    """Re-run matter matching on all pending alerts with NULL matter_slug."""
    try:
        store = _get_store()
        from orchestrator.pipeline import _match_matter_slug
        import psycopg2.extras

        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")

        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, title, body FROM alerts
                WHERE status = 'pending' AND matter_slug IS NULL
            """)
            rows = cur.fetchall()

            updated = 0
            for row in rows:
                slug = _match_matter_slug(row["title"], row.get("body") or "", store)
                if slug:
                    cur.execute(
                        "UPDATE alerts SET matter_slug = %s WHERE id = %s",
                        (slug, row["id"]),
                    )
                    updated += 1

            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)

        return {"reassigned": updated, "total_checked": len(rows)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"reassign-matters failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# V3 Dashboard endpoints
# ============================================================

# Morning narrative cache (module-level, invalidated on T1 alert creation)
_morning_narrative_cache: dict = {"text": None, "generated_at": 0}


def invalidate_morning_narrative():
    """Called from store_back.create_alert() when a T1 alert is created."""
    global _morning_narrative_cache
    _morning_narrative_cache = {"text": None, "generated_at": 0}


@app.get("/api/dashboard/morning-brief", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_morning_brief():
    """
    Aggregated morning brief: stats, narrative, top fires, deadlines, activity.
    Narrative generated by Haiku, cached 30 min.
    """
    try:
        store = _get_store()
        import psycopg2.extras

        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Stats: unanswered WhatsApp conversations (DASHBOARD-STATS-1)
            cur.execute("""
                SELECT COUNT(DISTINCT sender_name) AS cnt
                FROM whatsapp_messages wm
                WHERE wm.is_director = FALSE
                  AND wm.timestamp > NOW() - INTERVAL '24 hours'
                  AND NOT EXISTS (
                      SELECT 1 FROM whatsapp_messages reply
                      WHERE reply.chat_id = wm.chat_id
                        AND reply.is_director = TRUE
                        AND reply.timestamp > wm.timestamp
                  )
            """)
            unanswered_count = cur.fetchone()["cnt"]

            # Stats: fire count
            cur.execute("SELECT COUNT(*) AS cnt FROM alerts WHERE status = 'pending' AND tier = 1")
            fire_count = cur.fetchone()["cnt"]

            # Stats: deadlines this week
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM deadlines
                WHERE status = 'active' AND due_date <= NOW() + INTERVAL '7 days'
            """)
            deadline_count = cur.fetchone()["cnt"]

            # Stats: processed overnight (alerts created in last 24h)
            cur.execute("SELECT COUNT(*) AS cnt FROM alerts WHERE created_at >= NOW() - INTERVAL '24 hours'")
            processed_overnight = cur.fetchone()["cnt"]

            # Stats: actions completed (capability_runs in last 24h)
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM capability_runs
                WHERE created_at >= NOW() - INTERVAL '24 hours' AND status = 'completed'
            """)
            actions_completed = cur.fetchone()["cnt"]

            # Top fires (T1 alerts, most recent per matter, limit 5)
            cur.execute("""
                SELECT * FROM (
                    SELECT DISTINCT ON (COALESCE(matter_slug, id::text)) *
                    FROM alerts
                    WHERE status = 'pending' AND tier = 1
                    ORDER BY COALESCE(matter_slug, id::text), created_at DESC
                ) deduped
                ORDER BY created_at DESC
                LIMIT 5
            """)
            top_fires = [_serialize(dict(r)) for r in cur.fetchall()]

            # Deadlines this week (exclude source_snippet — can be 80KB per row)
            cur.execute("""
                SELECT id, description, due_date, source_type, confidence,
                       priority, status, created_at
                FROM deadlines
                WHERE status = 'active' AND due_date <= NOW() + INTERVAL '7 days'
                ORDER BY due_date ASC LIMIT 10
            """)
            deadlines = [_serialize(dict(r)) for r in cur.fetchall()]

            # Activity feed (recent capability runs)
            cur.execute("""
                SELECT capability_slug, status, created_at, completed_at, iterations
                FROM capability_runs
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC LIMIT 10
            """)
            activity = [_serialize(dict(r)) for r in cur.fetchall()]

            cur.close()
        finally:
            store._put_conn(conn)

        # Generate narrative (Haiku, cached 30 min) — Phase 3B: includes per-fire proposals
        # 20s timeout: if Haiku is slow/unreachable after restart, return stats without narrative
        proposals = []
        try:
            narr_result = await asyncio.wait_for(
                asyncio.to_thread(
                    _get_morning_narrative, fire_count, deadline_count,
                    processed_overnight, top_fires, deadlines,
                ),
                timeout=20.0,
            )
            if isinstance(narr_result, dict):
                narrative = narr_result.get("narrative", "")
                proposals = narr_result.get("proposals", [])
            else:
                narrative = narr_result  # legacy cached string
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"Morning narrative timed out or failed: {e}")
            narrative = "Baker is online — narrative generation is warming up."

        # Phase 3A: Fetch today's meetings (graceful — returns [] if Calendar API unavailable)
        meetings_today = []
        try:
            from triggers.calendar_trigger import poll_upcoming_meetings
            from triggers.state import trigger_state
            raw_meetings = poll_upcoming_meetings(hours_ahead=16)  # rest of today
            for m in raw_meetings:
                wk = f"calendar_prep_{m.get('id', '')}"
                prepped = trigger_state.watermark_exists(wk)
                attendee_names = [a.get('name', '') or a.get('email', '') for a in m.get('attendees', [])]
                meetings_today.append({
                    "title": m['title'],
                    "start": m['start'],
                    "attendees": attendee_names[:5],
                    "prepped": prepped,
                })
        except Exception as e:
            logger.warning(f"Morning brief: calendar unavailable: {e}")

        return {
            "unanswered_count": unanswered_count,
            "fire_count": fire_count,
            "deadline_count": deadline_count,
            "processed_overnight": processed_overnight,
            "actions_completed": actions_completed,
            "narrative": narrative,
            "proposals": proposals,
            "top_fires": top_fires,
            "deadlines": deadlines,
            "activity": activity,
            "meetings_today": meetings_today,
            "meeting_count": len(meetings_today),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/dashboard/morning-brief failed: {e}")
        return {
            "fire_count": 0, "deadline_count": 0, "processed_overnight": 0,
            "actions_completed": 0, "narrative": "Baker is loading...",
            "proposals": [],
            "top_fires": [], "deadlines": [], "activity": [],
            "meetings_today": [], "meeting_count": 0,
        }


def _get_morning_narrative(fire_count: int, deadline_count: int,
                           processed: int, top_fires: list,
                           deadlines: list = None) -> str:
    """Generate morning narrative via Haiku. Cached 30 min. Phase 3B: includes per-fire proposals."""
    global _morning_narrative_cache
    now = time.time()
    if _morning_narrative_cache["text"] and (now - _morning_narrative_cache["generated_at"]) < 1800:
        return _morning_narrative_cache["text"]

    try:
        fire_titles = [f.get("title", "") for f in top_fires[:3]]
        prompt = (
            f"You are Baker, chief of staff for Dimitry Vallen. "
            f"Write a 2-3 sentence status summary. Be warm but direct.\n\n"
            f"IMPORTANT: Do NOT start with 'Good morning' or any greeting — "
            f"the page header already shows the greeting. Jump straight to content.\n\n"
            f"Stats: {fire_count} fires, {deadline_count} deadlines this week, "
            f"{processed} items processed overnight.\n"
            f"Top fires: {'; '.join(fire_titles) if fire_titles else 'None'}\n\n"
            f"If zero fires: 'All clear. No fires overnight.' then mention routine updates.\n"
            f"If fires exist: lead with the top issue and deadline, then mention others.\n"
            f"Keep it under 50 words. No bullet points. Plain text only."
        )
        client = anthropic.Anthropic(
            api_key=config.claude.api_key,
            timeout=15.0,
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="morning_narrative")
        except Exception:
            pass
        narrative = resp.content[0].text.strip()

        # Phase 3B: Generate per-fire proposals (returned separately as structured data)
        proposals = []
        if top_fires:
            proposals = _generate_morning_proposals(client, top_fires[:3], deadlines or [])

        result = {"narrative": narrative, "proposals": proposals}
        _morning_narrative_cache = {"text": result, "generated_at": now}
        return result
    except Exception as e:
        logger.error(f"Morning narrative generation failed: {e}")
        return {"narrative": "Baker is analyzing your latest updates.", "proposals": []}


_MORNING_PROPOSALS_PROMPT = """You are Baker. Given the Director's top fires and upcoming deadlines, propose ONE specific action for each fire.

Rules:
- One line per fire.
- Be specific: name the person, document, or action.
- Format EXACTLY as: PROPOSAL|<short label>|<full Baker instruction>
  - <short label> = 2-5 word button text (e.g., "Draft email to Ofenheimer")
  - <full Baker instruction> = what Baker should do if the Director clicks (a question/instruction Baker can execute)
- Max 3 proposals.
- If a deadline is attached to a fire, mention the timeline in the instruction.

Examples:
PROPOSAL|Draft email to Ofenheimer|Draft a status update email to Ofenheimer about the Hagenauer filing deadline this Friday
PROPOSAL|Schedule BCOMM kickoff|Prepare a meeting request email to Benjamin Schuster for the BCOMM M365 kickoff
PROPOSAL|Prepare Cupial position|Analyze the FM List counter-proposal for Cupial and prepare our negotiation position
"""


def _generate_morning_proposals(client, top_fires: list, deadlines: list) -> list:
    """Generate per-fire action proposals. Returns list of {label, instruction} dicts."""
    try:
        fires_text = ""
        for f in top_fires:
            title = f.get("title", "")
            body = (f.get("body") or "")[:200]
            fires_text += f"- {title}: {body}\n"

        deadlines_text = ""
        for dl in deadlines[:5]:
            desc = dl.get("description", "")
            due = dl.get("due_date", "")
            deadlines_text += f"- {desc} (due {due})\n"

        context = f"Top fires:\n{fires_text}"
        if deadlines_text:
            context += f"\nUpcoming deadlines:\n{deadlines_text}"

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_MORNING_PROPOSALS_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="morning_proposals")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
        proposals = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("PROPOSAL|"):
                parts = line.split("|", 2)
                if len(parts) == 3:
                    proposals.append({"label": parts[1].strip(), "instruction": parts[2].strip()})
        return proposals
    except Exception as e:
        logger.warning(f"Morning proposals generation failed: {e}")
        return []


@app.get("/api/dashboard/matters-summary", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_matters_summary():
    """
    List matters with alert counts and worst active tier, for sidebar rendering.
    """
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Get matters with their alert stats
            cur.execute("""
                SELECT
                    COALESCE(a.matter_slug, '_ungrouped') AS matter_slug,
                    COUNT(*) AS item_count,
                    MIN(a.tier) AS worst_tier,
                    COUNT(*) FILTER (WHERE a.created_at >= NOW() - INTERVAL '24 hours') AS new_count
                FROM alerts a
                WHERE a.status = 'pending'
                GROUP BY COALESCE(a.matter_slug, '_ungrouped')
                ORDER BY MIN(a.tier), COALESCE(a.matter_slug, '_ungrouped')
            """)
            matters = [dict(r) for r in cur.fetchall()]
            cur.close()
            return {"matters": matters, "count": len(matters)}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/dashboard/matters-summary failed: {e}")
        return {"matters": [], "count": 0}


@app.get("/api/activity", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_activity_feed(hours: int = Query(24, ge=1, le=168)):
    """
    Unified activity feed: capability runs, alerts generated, emails processed.
    """
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"activity": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Capability runs
            cur.execute("""
                SELECT 'capability_run' AS type, capability_slug AS label,
                       status, created_at AS timestamp, iterations
                FROM capability_runs
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                ORDER BY created_at DESC LIMIT 20
            """, (hours,))
            runs = [_serialize(dict(r)) for r in cur.fetchall()]

            # Alerts generated
            cur.execute("""
                SELECT 'alert_created' AS type, title AS label,
                       tier, created_at AS timestamp
                FROM alerts
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                ORDER BY created_at DESC LIMIT 20
            """, (hours,))
            alerts = [_serialize(dict(r)) for r in cur.fetchall()]

            cur.close()
            # Merge and sort by timestamp
            combined = runs + alerts
            combined.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return {"activity": combined[:30]}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/activity failed: {e}")
        return {"activity": []}


# ============================================================
# V3 Phase C2 — RSS articles + feeds (Media tab)
# ============================================================

@app.get("/api/rss/articles", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_rss_articles(
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """List recent RSS articles, optionally filtered by feed category."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"articles": [], "count": 0}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if category:
                cur.execute("""
                    SELECT a.*, f.title AS feed_title, f.category
                    FROM rss_articles a JOIN rss_feeds f ON a.feed_id = f.id
                    WHERE f.is_active = true AND f.category = %s
                    ORDER BY a.published_at DESC NULLS LAST LIMIT %s
                """, (category, limit))
            else:
                cur.execute("""
                    SELECT a.*, f.title AS feed_title, f.category
                    FROM rss_articles a JOIN rss_feeds f ON a.feed_id = f.id
                    WHERE f.is_active = true
                    ORDER BY a.published_at DESC NULLS LAST LIMIT %s
                """, (limit,))
            articles = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"articles": articles, "count": len(articles)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/rss/articles failed: {e}")
        return {"articles": [], "count": 0}


@app.get("/api/rss/feeds", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_rss_feeds_list():
    """List active RSS feeds with categories for the filter dropdown."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"feeds": [], "count": 0}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT f.id, f.title, f.category, f.feed_url,
                       COUNT(a.id) AS article_count
                FROM rss_feeds f LEFT JOIN rss_articles a ON a.feed_id = f.id
                WHERE f.is_active = true
                GROUP BY f.id, f.title, f.category, f.feed_url
                ORDER BY f.category, f.title
            """)
            feeds = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"feeds": feeds, "count": len(feeds)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/rss/feeds failed: {e}")
        return {"feeds": [], "count": 0}


# ============================================================
# V3 Phase C1 — People + Search
# ============================================================

@app.get("/api/people", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def list_people():
    """List all people — merge vip_contacts + contacts, deduplicate by name."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"people": [], "count": 0}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            vips = {}
            try:
                cur.execute("SELECT name, role, email, whatsapp_id, tier, domain, role_context FROM vip_contacts ORDER BY tier, name")
                vips = {r["name"].lower(): {**dict(r), "is_vip": True} for r in cur.fetchall()}
            except Exception:
                pass  # vip_contacts may not exist

            cur.execute("SELECT name, email, company, role, relationship, last_contact FROM contacts ORDER BY name")
            contacts = {r["name"].lower(): dict(r) for r in cur.fetchall()}

            merged = {}
            for key, c in contacts.items():
                merged[key] = {**c, "is_vip": False, "tier": None}
            for key, v in vips.items():
                if key in merged:
                    merged[key].update(v)
                else:
                    merged[key] = v

            people = sorted(merged.values(), key=lambda p: (
                0 if p.get("tier") == 1 else 1 if p.get("tier") == 2 else 2,
                (p.get("name") or "").lower()
            ))
            people = [_serialize(p) for p in people]
            cur.close()
            return {"people": people, "count": len(people)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/people failed: {e}")
        return {"people": [], "count": 0}


@app.get("/api/people/{name}/activity", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_person_activity(name: str, limit: int = Query(20, ge=1, le=100)):
    """Get recent activity for a person across emails, WhatsApp, meetings."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"name": name, "activity": [], "matters": [], "count": 0}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            activity = []
            pattern = f"%{name}%"

            cur.execute("""
                SELECT subject, sender_name, sender_email, received_date
                FROM email_messages WHERE sender_name ILIKE %s OR sender_email ILIKE %s
                ORDER BY received_date DESC LIMIT %s
            """, (pattern, pattern, limit))
            for r in cur.fetchall():
                activity.append({"type": "email", "title": r["subject"] or "",
                    "date": r["received_date"].isoformat() if r["received_date"] else "",
                    "preview": f"From: {r['sender_name'] or ''}"})

            cur.execute("""
                SELECT sender_name, full_text, timestamp FROM whatsapp_messages
                WHERE sender_name ILIKE %s ORDER BY timestamp DESC LIMIT %s
            """, (pattern, limit))
            for r in cur.fetchall():
                activity.append({"type": "whatsapp", "title": f"WhatsApp from {r['sender_name'] or ''}",
                    "date": r["timestamp"].isoformat() if r.get("timestamp") else "",
                    "preview": (r["full_text"] or "")[:200]})

            try:
                cur.execute("""
                    SELECT title, organizer, participants, meeting_date FROM meeting_transcripts
                    WHERE organizer ILIKE %s OR participants::text ILIKE %s
                    ORDER BY meeting_date DESC LIMIT %s
                """, (pattern, pattern, limit))
                for r in cur.fetchall():
                    activity.append({"type": "meeting", "title": r["title"] or "Meeting",
                        "date": r["meeting_date"].isoformat() if r.get("meeting_date") else "",
                        "preview": f"Organizer: {r['organizer'] or ''}"})
            except Exception:
                pass

            activity.sort(key=lambda x: x.get("date", ""), reverse=True)

            cur.execute("""
                SELECT DISTINCT matter_slug FROM alerts
                WHERE matter_slug IS NOT NULL AND (title ILIKE %s OR body ILIKE %s)
            """, (pattern, pattern))
            matters = [r["matter_slug"] for r in cur.fetchall()]
            cur.close()
            return {"name": name, "activity": activity[:limit], "matters": matters, "count": len(activity)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/people/{name}/activity failed: {e}")
        return {"name": name, "activity": [], "matters": [], "count": 0}


# ============================================================
# NETWORKING-PHASE-1: Networking Tab Endpoints
# ============================================================

@app.get("/api/networking/contacts", tags=["networking"], dependencies=[Depends(verify_api_key)])
async def get_networking_contacts(
    contact_type: Optional[str] = Query(None),
    tier: Optional[int] = Query(None),
):
    """List contacts with networking fields. Filterable by type and tier."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"contacts": [], "count": 0}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            sql = """
                SELECT id, name, role, email, tier, domain, contact_type,
                       relationship_score, net_worth_tier, last_contact_date,
                       sentiment_trend, role_context, expertise, gatekeeper_name
                FROM vip_contacts
                WHERE 1=1
            """
            params = []
            if contact_type:
                sql += " AND contact_type = %s"
                params.append(contact_type)
            if tier:
                sql += " AND tier = %s"
                params.append(tier)
            sql += " ORDER BY tier, relationship_score DESC NULLS LAST, name"
            cur.execute(sql, params)
            rows = [_serialize(dict(r)) for r in cur.fetchall()]

            # Compute health dot for each contact
            now = datetime.now(timezone.utc)
            for c in rows:
                c["health"] = _compute_contact_health(c, now)

                # Fetch connected matters
                try:
                    name_pattern = f"%{c.get('name', '')}%"
                    cur.execute("""
                        SELECT DISTINCT matter_slug FROM alerts
                        WHERE matter_slug IS NOT NULL AND (title ILIKE %s OR body ILIKE %s)
                        LIMIT 5
                    """, (name_pattern, name_pattern))
                    c["matters"] = [r["matter_slug"] for r in cur.fetchall()]
                except Exception:
                    c["matters"] = []

            cur.close()
            return {"contacts": rows, "count": len(rows)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/networking/contacts failed: {e}")
        return {"contacts": [], "count": 0}


def _compute_contact_health(contact: dict, now) -> str:
    """Compute health dot color: red, amber, green, grey."""
    tier = contact.get("tier") or 3
    last_contact = contact.get("last_contact_date")

    if tier >= 4:
        return "grey"

    if not last_contact:
        return "red" if tier <= 2 else "grey"

    if isinstance(last_contact, str):
        try:
            last_contact = datetime.fromisoformat(last_contact)
        except (ValueError, TypeError):
            return "grey"

    days_since = (now - last_contact).days
    threshold = 14 if tier == 1 else 30 if tier == 2 else 60
    warning_buffer = 7

    if days_since >= threshold:
        return "red"
    elif days_since >= (threshold - warning_buffer):
        return "amber"
    else:
        return "green"


@app.get("/api/networking/alerts", tags=["networking"], dependencies=[Depends(verify_api_key)])
async def get_networking_alerts():
    """Networking alerts: contacts going cold, unreciprocated outreach, upcoming events."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"going_cold": [], "unreciprocated": [], "upcoming_events": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            now = datetime.now(timezone.utc)

            # Going cold: T1 no contact 14+ days, T2 no contact 30+ days
            cur.execute("""
                SELECT id, name, tier, last_contact_date FROM vip_contacts
                WHERE tier <= 2 AND (
                    (tier = 1 AND last_contact_date < NOW() - INTERVAL '14 days')
                    OR (tier = 2 AND last_contact_date < NOW() - INTERVAL '30 days')
                    OR (tier <= 2 AND last_contact_date IS NULL)
                )
                ORDER BY tier, last_contact_date NULLS FIRST
            """)
            going_cold = [_serialize(dict(r)) for r in cur.fetchall()]

            # Unreciprocated: 2+ outbound with no inbound reply in 14 days
            unreciprocated = []
            try:
                cur.execute("""
                    SELECT ci.contact_id, vc.name, COUNT(*) as outbound_count
                    FROM contact_interactions ci
                    JOIN vip_contacts vc ON ci.contact_id = vc.id
                    WHERE ci.direction = 'outbound'
                      AND ci.timestamp > NOW() - INTERVAL '14 days'
                      AND ci.contact_id NOT IN (
                          SELECT contact_id FROM contact_interactions
                          WHERE direction = 'inbound'
                            AND timestamp > NOW() - INTERVAL '14 days'
                      )
                    GROUP BY ci.contact_id, vc.name
                    HAVING COUNT(*) >= 2
                    ORDER BY COUNT(*) DESC
                """)
                unreciprocated = [_serialize(dict(r)) for r in cur.fetchall()]
            except Exception:
                pass

            # Upcoming events (next 90 days)
            upcoming_events = []
            try:
                cur.execute("""
                    SELECT id, event_name, dates_start, dates_end, location, category
                    FROM networking_events
                    WHERE dates_start >= CURRENT_DATE AND dates_start <= CURRENT_DATE + INTERVAL '90 days'
                    ORDER BY dates_start
                    LIMIT 10
                """)
                upcoming_events = [_serialize(dict(r)) for r in cur.fetchall()]
            except Exception:
                pass

            cur.close()
            return {
                "going_cold": going_cold,
                "going_cold_count": len(going_cold),
                "unreciprocated": unreciprocated,
                "unreciprocated_count": len(unreciprocated),
                "upcoming_events": upcoming_events,
                "upcoming_events_count": len(upcoming_events),
            }
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/networking/alerts failed: {e}")
        return {"going_cold": [], "unreciprocated": [], "upcoming_events": []}


@app.get("/api/networking/events", tags=["networking"], dependencies=[Depends(verify_api_key)])
async def get_networking_events():
    """List upcoming networking events."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"events": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, event_name, dates_start, dates_end, location, category,
                       brisen_relevance_score, source_url, notes
                FROM networking_events
                ORDER BY dates_start NULLS LAST
                LIMIT 50
            """)
            events = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"events": events, "count": len(events)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/networking/events failed: {e}")
        return {"events": [], "count": 0}


class NetworkingEventRequest(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=300)
    dates_start: Optional[str] = None
    dates_end: Optional[str] = None
    location: Optional[str] = None
    category: Optional[str] = None
    brisen_relevance_score: Optional[int] = 5
    source_url: Optional[str] = None
    notes: Optional[str] = None


@app.post("/api/networking/events", tags=["networking"], dependencies=[Depends(verify_api_key)])
async def create_networking_event(req: NetworkingEventRequest):
    """Create a networking event."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO networking_events
                    (event_name, dates_start, dates_end, location, category,
                     brisen_relevance_score, source_url, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (req.event_name, req.dates_start, req.dates_end, req.location,
                  req.category, req.brisen_relevance_score, req.source_url, req.notes))
            event_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            return {"id": event_id, "status": "created"}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/networking/events failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/networking/contact/{contact_id}/interactions", tags=["networking"],
         dependencies=[Depends(verify_api_key)])
async def get_contact_interactions(contact_id: int, limit: int = Query(10, ge=1, le=50)):
    """Recent interactions for a contact."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"interactions": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT channel, direction, timestamp, subject, sentiment, source_ref
                FROM contact_interactions
                WHERE contact_id = %s
                ORDER BY timestamp DESC LIMIT %s
            """, (contact_id, limit))
            rows = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"interactions": rows, "count": len(rows)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/networking/contact/{contact_id}/interactions failed: {e}")
        return {"interactions": [], "count": 0}


class NetworkingActionRequest(BaseModel):
    action: str = Field(..., min_length=1)
    # Values: new_topic, engaged_by_brisen, engaged_by_person,
    #         possible_connector, possible_place, possible_date


_NETWORKING_ACTION_PROMPTS = {
    "new_topic": "Suggest a new conversation topic for {name} based on their interests and recent news. "
                 "Profile: {profile}",
    "engaged_by_brisen": "What topics has Dimitry previously discussed with {name}? "
                         "Search emails, meetings, WhatsApp. Profile: {profile}",
    "engaged_by_person": "What topics has {name} shown interest in? "
                         "Search their messages and meeting contributions. Profile: {profile}",
    "possible_connector": "Who in my network could introduce me to {name} or strengthen this relationship? "
                          "Profile: {profile}",
    "possible_place": "Where could I naturally meet {name}? Check upcoming events, shared locations, "
                      "industry conferences. Profile: {profile}",
    "possible_date": "When would be a good time to meet {name}? Check calendar availability and "
                     "their timezone/travel patterns. Profile: {profile}",
}


@app.post("/api/networking/contact/{contact_id}/action", tags=["networking"],
          dependencies=[Depends(verify_api_key)])
async def networking_contact_action(contact_id: int, req: NetworkingActionRequest):
    """Route an action button to Baker scan with contact context pre-loaded."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM vip_contacts WHERE id = %s", (contact_id,))
            contact = cur.fetchone()
            cur.close()
            if not contact:
                raise HTTPException(status_code=404, detail="Contact not found")
        finally:
            store._put_conn(conn)

        contact = dict(contact)
        name = contact.get("name", "Unknown")
        profile_parts = [f"Name: {name}"]
        if contact.get("role"):
            profile_parts.append(f"Role: {contact['role']}")
        if contact.get("expertise"):
            profile_parts.append(f"Expertise: {contact['expertise']}")
        if contact.get("investment_thesis"):
            profile_parts.append(f"Investment thesis: {contact['investment_thesis']}")
        if contact.get("personal_interests"):
            profile_parts.append(f"Interests: {', '.join(contact['personal_interests'] or [])}")
        if contact.get("domain"):
            profile_parts.append(f"Domain: {contact['domain']}")
        profile = "; ".join(profile_parts)

        template = _NETWORKING_ACTION_PROMPTS.get(req.action)
        if not template:
            raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

        question = template.format(name=name, profile=profile)

        # Route to scan_chat via internal call
        scan_req = ScanRequest(question=question)
        return await scan_chat(scan_req)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/networking/contact/{contact_id}/action failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Phase 3A: Calendar — Upcoming Meetings
# ============================================================

@app.get("/api/calendar/upcoming", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_upcoming_meetings(hours: int = Query(48, ge=1, le=168)):
    """
    Upcoming meetings with prep status.
    Polls Google Calendar and cross-references trigger_watermarks for prep state.
    Returns meetings with prepped flag + alert_id if available.
    """
    try:
        from triggers.calendar_trigger import poll_upcoming_meetings
        from triggers.state import trigger_state

        try:
            meetings = poll_upcoming_meetings(hours_ahead=hours)
        except Exception as e:
            logger.warning(f"Calendar API unavailable: {e}")
            return {"meetings": [], "count": 0, "prepped_count": 0, "error": str(e)}

        store = _get_store()
        result_meetings = []
        prepped_count = 0

        for m in meetings:
            event_id = m.get('id', '')
            watermark_key = f"calendar_prep_{event_id}"
            prepped = trigger_state.watermark_exists(watermark_key)

            # Look up alert_id if prepped
            alert_id = None
            if prepped:
                prepped_count += 1
                try:
                    conn = store._get_conn()
                    if conn:
                        try:
                            import psycopg2.extras
                            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                            cur.execute(
                                "SELECT id FROM alerts WHERE title LIKE %s ORDER BY created_at DESC LIMIT 1",
                                (f"Meeting prep: {m['title']}%",),
                            )
                            row = cur.fetchone()
                            if row:
                                alert_id = row['id']
                            cur.close()
                        finally:
                            store._put_conn(conn)
                except Exception:
                    pass

            attendee_names = [a.get('name', '') or a.get('email', '') for a in m.get('attendees', [])]
            result_meetings.append({
                "title": m['title'],
                "start": m['start'],
                "end": m['end'],
                "attendees": attendee_names,
                "location": m.get('location', ''),
                "prepped": prepped,
                "alert_id": alert_id,
            })

        return {
            "meetings": result_meetings,
            "count": len(result_meetings),
            "prepped_count": prepped_count,
        }
    except Exception as e:
        logger.error(f"GET /api/calendar/upcoming failed: {e}")
        return {"meetings": [], "count": 0, "prepped_count": 0}


# ============================================================
# Phase 3C: Commitments
# ============================================================

@app.get("/api/commitments", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_commitments(
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """List commitments with status/assignee filters."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"commitments": [], "count": 0, "overdue_count": 0}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            conditions = []
            params = []
            if status:
                # Map frontend filter names to DB values
                if status == "active":
                    conditions.append("status IN ('open', 'overdue')")
                elif status == "overdue":
                    # Include both explicit 'overdue' and open items past due
                    conditions.append("(status = 'overdue' OR (status = 'open' AND due_date < NOW()))")
                elif status == "completed":
                    conditions.append("status IN ('completed', 'dismissed')")
                else:
                    conditions.append("status = %s")
                    params.append(status)
            if assigned_to:
                conditions.append("LOWER(assigned_to) ILIKE %s")
                params.append(f"%{assigned_to.lower()}%")
            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.append(limit)
            cur.execute(
                f"SELECT * FROM commitments {where} ORDER BY COALESCE(due_date, '9999-12-31') ASC, created_at DESC LIMIT %s",
                params,
            )
            rows = [_serialize(dict(r)) for r in cur.fetchall()]

            cur.execute("SELECT COUNT(*) AS cnt FROM commitments WHERE status = 'overdue' OR (status = 'open' AND due_date < NOW())")
            overdue_count = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) AS cnt FROM commitments")
            total_count = cur.fetchone()["cnt"]

            cur.close()
            return {"commitments": rows, "count": len(rows), "total": total_count, "overdue_count": overdue_count}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/commitments failed: {e}")
        return {"commitments": [], "count": 0, "overdue_count": 0}


@app.post("/api/commitments/extract", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def extract_commitments_retroactive(background_tasks: BackgroundTasks):
    """Retroactive commitment extraction from existing meetings and emails."""
    def _run_extraction():
        import psycopg2.extras
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            logger.error("Commitment extraction: no DB connection")
            return
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # 1. Extract from meeting transcripts
            cur.execute("SELECT id, title, participants, full_transcript FROM meeting_transcripts WHERE full_transcript IS NOT NULL")
            meetings = cur.fetchall()
            m_count = 0
            for m in meetings:
                try:
                    from triggers.fireflies_trigger import _extract_commitments_from_meeting
                    _extract_commitments_from_meeting(
                        transcript_text=m["full_transcript"],
                        meeting_title=m.get("title", "Untitled"),
                        participants=m.get("participants", ""),
                        source_id=str(m["id"]),
                    )
                    m_count += 1
                except Exception as e:
                    logger.warning(f"Commitment extraction failed for meeting {m['id']}: {e}")
            logger.info(f"Retroactive commitment extraction: processed {m_count} meetings")

            # 2. Extract from emails
            cur.execute("SELECT thread_id, subject, full_body, sender_name FROM email_messages WHERE full_body IS NOT NULL ORDER BY received_date DESC LIMIT 200")
            emails = cur.fetchall()
            e_count = 0
            for em in emails:
                try:
                    from triggers.email_trigger import _extract_commitments_from_email
                    _extract_commitments_from_email(
                        email_text=em["full_body"],
                        subject=em.get("subject", ""),
                        sender=em.get("sender_name", ""),
                        source_id=em["thread_id"],
                    )
                    e_count += 1
                except Exception as e:
                    logger.warning(f"Commitment extraction failed for email {em['thread_id']}: {e}")
            logger.info(f"Retroactive commitment extraction: processed {e_count} emails")
        finally:
            store._put_conn(conn)

    background_tasks.add_task(_run_extraction)
    return {"status": "started", "message": "Retroactive commitment extraction running in background. Check /api/commitments for results."}


# ============================================================
# PHASE-4A: Cost Monitor + Agent Metrics API
# ============================================================

@app.get("/api/cost/today", tags=["phase-4a"], dependencies=[Depends(verify_api_key)])
async def get_cost_today():
    """Get today's API cost breakdown."""
    from orchestrator.cost_monitor import get_daily_breakdown
    return get_daily_breakdown()


@app.get("/api/cost/history", tags=["phase-4a"], dependencies=[Depends(verify_api_key)])
async def get_cost_history(days: int = Query(7, ge=1, le=90)):
    """Get daily cost totals for the last N days."""
    from orchestrator.cost_monitor import get_cost_history
    return {"days": days, "history": get_cost_history(days)}


@app.get("/api/agent-metrics", tags=["phase-4a"], dependencies=[Depends(verify_api_key)])
async def get_agent_metrics(hours: int = Query(24, ge=1, le=168)):
    """Get tool call metrics for the last N hours."""
    from orchestrator.agent_metrics import get_tool_metrics, get_source_metrics
    return {
        "tool_metrics": get_tool_metrics(hours),
        "source_metrics": get_source_metrics(hours),
    }


@app.get("/api/agent-metrics/errors", tags=["phase-4a"], dependencies=[Depends(verify_api_key)])
async def get_agent_errors(limit: int = Query(20, ge=1, le=100)):
    """Get recent tool call errors."""
    from orchestrator.agent_metrics import get_recent_errors
    return {"errors": get_recent_errors(limit)}


@app.get("/api/alerts/search", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def search_alerts(
    q: str = Query("", max_length=500),
    matter: Optional[str] = None,
    tag: Optional[str] = None,
    tier: Optional[int] = Query(None, ge=1, le=4),
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    """Structured alert search with filters. All SQL parameterized — no string concatenation."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"items": [], "count": 0}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            conditions = []
            params = []
            if q and q.strip():
                conditions.append("(title ILIKE %s OR body ILIKE %s)")
                params.extend([f"%{q}%", f"%{q}%"])
            if matter:
                conditions.append("matter_slug = %s")
                params.append(matter)
            if tag:
                conditions.append("tags ? %s")
                params.append(tag)
            if tier:
                conditions.append("tier = %s")
                params.append(tier)
            if status:
                conditions.append("status = %s")
                params.append(status)
            if date_from:
                conditions.append("created_at >= %s")
                params.append(date_from)
            if date_to:
                conditions.append("created_at <= %s")
                params.append(date_to)
            where = " AND ".join(conditions) if conditions else "TRUE"
            cur.execute(
                f"SELECT * FROM alerts WHERE {where} ORDER BY created_at DESC LIMIT %s",
                tuple(params + [limit]),
            )
            items = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"items": items, "count": len(items)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/alerts/search failed: {e}")
        return {"items": [], "count": 0}


# ============================================================
# V3 Phase B1 — Tags, ungrouped assignment
# ============================================================

@app.get("/api/tags", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_tags():
    """List distinct tags with item counts from pending alerts."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"tags": [], "total": 0}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT tag, COUNT(*) AS count
                FROM alerts, jsonb_array_elements_text(tags) AS tag
                WHERE status = 'pending'
                GROUP BY tag
                ORDER BY count DESC
            """)
            tags = [dict(r) for r in cur.fetchall()]
            total = sum(t["count"] for t in tags)
            cur.close()
            return {"tags": tags, "total": total}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/tags failed: {e}")
        return {"tags": [], "total": 0}


@app.post("/api/alerts/{alert_id}/tag", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def tag_alert(alert_id: int, req: AlertTagRequest):
    """Add or remove a tag on an alert."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if req.action == "add":
                cur.execute(
                    "UPDATE alerts SET tags = tags || to_jsonb(%s::text) WHERE id = %s AND NOT tags ? %s RETURNING tags",
                    (req.tag, alert_id, req.tag),
                )
            else:
                cur.execute(
                    "UPDATE alerts SET tags = tags - %s WHERE id = %s RETURNING tags",
                    (req.tag, alert_id),
                )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if not row:
                return {"ok": True, "tags": []}
            return {"ok": True, "tags": row["tags"]}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/alerts/{alert_id}/tag failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/alerts/{alert_id}/assign", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def assign_alert(alert_id: int, req: AlertAssignRequest):
    """Assign an ungrouped alert to a matter (existing or new)."""
    import re
    try:
        store = _get_store()
        slug = req.matter_slug

        if slug == "_new":
            if not req.new_name:
                raise HTTPException(status_code=400, detail="new_name required when matter_slug is '_new'")
            # Slugify: lowercase, replace spaces with _, strip special chars
            slug = re.sub(r'[^a-z0-9_-]', '', req.new_name.lower().replace(' ', '_'))[:50]
            if not slug:
                raise HTTPException(status_code=400, detail="Invalid project name")
            # Create new matter
            store.create_matter(matter_name=slug, description=req.new_name)
        else:
            # Validate slug format
            if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
                raise HTTPException(status_code=400, detail="Invalid matter_slug format")

        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("UPDATE alerts SET matter_slug = %s WHERE id = %s", (slug, alert_id))
            conn.commit()
            cur.close()
            return {"ok": True, "matter_slug": slug}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/alerts/{alert_id}/assign failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/alerts/by-tag/{tag}", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_alerts_by_tag(tag: str):
    """Get pending alerts filtered by tag."""
    import re
    if not re.match(r'^[a-z0-9-]+$', tag):
        raise HTTPException(status_code=400, detail="Invalid tag format")
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"items": [], "count": 0, "tag": tag}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT * FROM alerts WHERE status = 'pending' AND tags ? %s ORDER BY tier, created_at DESC",
                (tag,),
            )
            items = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"items": items, "count": len(items), "tag": tag}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/alerts/by-tag/{tag} failed: {e}")
        return {"items": [], "count": 0, "tag": tag}


# ============================================================
# V3 Phase B2 — Ask Specialist + Command bar detection
# ============================================================

@app.post("/api/scan/specialist", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def scan_specialist(req: SpecialistScanRequest):
    """
    SPECIALIST-DEEP-1: Force-route to a specific capability with deep context.
    Pre-stuffs relevant emails, WA, meetings, decisions, cross-session memory
    so the specialist starts with maximum context.
    """
    start = time.time()
    from orchestrator.capability_registry import CapabilityRegistry
    from orchestrator.capability_router import RoutingPlan

    registry = CapabilityRegistry.get_instance()
    cap = registry.get_by_slug(req.capability_slug)
    if not cap or not cap.active:
        raise HTTPException(status_code=404, detail=f"Capability '{req.capability_slug}' not found or inactive")

    # --- Pre-fetch context (same pattern as _scan_chat_deep) ---
    pre_parts = []

    # Entity context (people + matters)
    try:
        from orchestrator.scan_prompt import build_entity_context
        entity_ctx = build_entity_context(req.question)
        if entity_ctx:
            pre_parts.append(entity_ctx)
    except Exception:
        pass

    # Relevant emails
    try:
        retriever = _get_retriever()
        emails = retriever.get_email_messages(req.question, limit=5)
        recent_emails = retriever.get_recent_emails(limit=3)
        seen = {c.metadata.get("message_id") for c in emails}
        for r in recent_emails:
            if r.metadata.get("message_id") not in seen:
                emails.append(r)
        if emails:
            lines = [f"[EMAIL: {e.metadata.get('label', '')} | {e.metadata.get('date', '')}]\n{e.content[:2000]}"
                     for e in emails[:6]]
            pre_parts.append("## PRE-FETCHED EMAILS\n" + "\n\n".join(lines))
    except Exception:
        pass

    # Relevant WhatsApp
    try:
        retriever = _get_retriever()
        wa = retriever.get_whatsapp_messages(req.question, limit=5)
        if wa:
            lines = [f"[WA: {w.metadata.get('label', '')} | {w.metadata.get('date', '')}]\n{w.content[:1000]}"
                     for w in wa[:6]]
            pre_parts.append("## PRE-FETCHED WHATSAPP\n" + "\n\n".join(lines))
    except Exception:
        pass

    # Relevant meetings
    try:
        retriever = _get_retriever()
        meetings = retriever.get_meeting_transcripts(req.question, limit=3)
        if meetings:
            lines = [f"[MEETING: {m.metadata.get('label', '')} | {m.metadata.get('date', '')}]\n{m.content[:3000]}"
                     for m in meetings[:3]]
            pre_parts.append("## PRE-FETCHED MEETINGS\n" + "\n\n".join(lines))
    except Exception:
        pass

    # Cross-session memory
    try:
        store = _get_store()
        prior = store.get_relevant_conversations(req.question, limit=5)
        if prior:
            lines = []
            for c in prior:
                d = c.get("created_at")
                ds = d.strftime("%Y-%m-%d %H:%M") if hasattr(d, "strftime") else str(d)[:16]
                lines.append(f"[{ds}] Director: {(c.get('question') or '')[:200]}\nBaker: {(c.get('answer') or '')[:800]}")
            pre_parts.append("## PRIOR CONVERSATIONS ON THIS TOPIC\n" + "\n---\n".join(lines))
    except Exception:
        pass

    entity_context = "\n\n".join(pre_parts)
    logger.info(f"Specialist pre-fetch: {len(pre_parts)} blocks, {len(entity_context)} chars for {req.capability_slug}")

    plan = RoutingPlan(mode="fast", capabilities=[cap])
    scan_req = ScanRequest(question=req.question, history=req.history)
    return _scan_chat_capability(scan_req, start, {"plan": plan},
                                  entity_context=entity_context)


@app.get("/api/scan/detect", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def detect_capability(q: str = Query("", max_length=500)):
    """
    Lightweight capability detection — runs regex match only, no LLM call.
    Returns matched capability slug and name. Does NOT expose trigger patterns or system prompts.
    """
    if len(q.strip()) < 3:
        return {"detected": False}
    from orchestrator.capability_registry import CapabilityRegistry
    cap = CapabilityRegistry.get_instance().match_trigger(q)
    if cap:
        return {"detected": True, "capability_slug": cap.slug, "capability_name": cap.name}
    return {"detected": False}


@app.post("/api/scan/followups", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def generate_followups(req: FollowupRequest):
    """FOLLOWUP-SUGGESTIONS-1: Generate 3 follow-up questions after a Baker/Specialist response."""
    try:
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=config.claude.api_key)

        prompt = (
            f"Based on this conversation, suggest exactly 3 brief follow-up questions "
            f"the Director might want to ask next. Each should be a different angle: "
            f"one action-oriented (draft/send/create), one analytical (analyze/compare/assess), "
            f"one exploratory (what about/any updates on/related to).\n\n"
            f"Return ONLY a JSON array of 3 strings, no other text.\n"
            f"Keep each under 50 characters.\n\n"
            f"Question: {req.question[:300]}\n"
            f"Answer: {req.answer[:1000]}"
        )

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens,
                         resp.usage.output_tokens, source="followup_suggestions")
        except Exception:
            pass

        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        suggestions = json.loads(raw)
        if isinstance(suggestions, list) and len(suggestions) >= 2:
            return {"suggestions": suggestions[:3]}
        return {"suggestions": []}

    except Exception as e:
        logger.debug(f"Followup generation failed (non-fatal): {e}")
        return {"suggestions": []}


# V3 Phase B3 — Artifact storage
# ============================================================

@app.post("/api/artifacts/save", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def save_artifact(req: SaveArtifactRequest):
    """Save a Baker result as an artifact (PostgreSQL storage)."""
    import re
    # Security: validate matter_slug format (defense in depth for future Dropbox sync)
    if req.matter_slug and not re.match(r'^[a-zA-Z0-9_-]+$', req.matter_slug):
        raise HTTPException(status_code=400, detail="Invalid matter_slug format")
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO alert_artifacts (alert_id, matter_slug, title, content, format)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (req.alert_id, req.matter_slug, req.title, req.content, req.format),
            )
            artifact_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            return {"ok": True, "artifact_id": artifact_id}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/artifacts/save failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/artifacts", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_artifacts(matter_slug: Optional[str] = None, limit: int = Query(50, ge=1, le=200)):
    """List saved artifacts, optionally filtered by matter."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"artifacts": [], "count": 0}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if matter_slug:
                cur.execute(
                    "SELECT * FROM alert_artifacts WHERE matter_slug = %s ORDER BY created_at DESC LIMIT %s",
                    (matter_slug, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM alert_artifacts ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            artifacts = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"artifacts": artifacts, "count": len(artifacts)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/artifacts failed: {e}")
        return {"artifacts": [], "count": 0}


# ============================================================
# V3 Phase A2 — Reply threads, matters detail, inline actions
# ============================================================

@app.get("/api/alerts/{alert_id}/threads", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_alert_threads(alert_id: int):
    """Get thread messages for an alert card."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"threads": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT id, role, content, created_at FROM alert_threads WHERE alert_id = %s ORDER BY created_at",
                (alert_id,),
            )
            threads = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"threads": threads, "count": len(threads)}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/alerts/{alert_id}/threads failed: {e}")
        return {"threads": [], "count": 0}


@app.post("/api/alerts/{alert_id}/reply", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def reply_to_alert(alert_id: int, req: AlertReplyRequest):
    """
    Reply to an alert card. Director's message is stored, then routed through
    the existing agentic RAG pipeline (/api/scan) for Baker's response.
    CRITICAL: Uses the same pipeline as Ask Baker — no separate Claude call.
    """
    try:
        store = _get_store()
        import psycopg2.extras

        # 1. Verify alert exists and get context
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Check reply count limit (max 50 per brief spec)
            cur.execute("SELECT COUNT(*) AS cnt FROM alert_threads WHERE alert_id = %s", (alert_id,))
            thread_count = cur.fetchone()["cnt"]
            if thread_count >= 50:
                cur.close()
                raise HTTPException(
                    status_code=429,
                    detail="Thread limit reached (50). Continue in Ask Baker for extended conversation."
                )

            # Get alert context
            cur.execute("SELECT id, tier, title, body, matter_slug, structured_actions FROM alerts WHERE id = %s", (alert_id,))
            alert = cur.fetchone()
            if not alert:
                cur.close()
                raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
            alert = dict(alert)

            # Get existing thread for conversation history
            cur.execute(
                "SELECT role, content FROM alert_threads WHERE alert_id = %s ORDER BY created_at",
                (alert_id,),
            )
            existing_thread = [dict(r) for r in cur.fetchall()]

            # 2. Store director's message
            cur.execute(
                "INSERT INTO alert_threads (alert_id, role, content) VALUES (%s, 'director', %s)",
                (alert_id, req.content),
            )
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)

        # 3. Build context and route through existing /api/scan pipeline
        # Construct the question with full alert context (same as Ask Baker)
        context_parts = [
            f"[Context: Alert T{alert['tier']} — {alert['title']}]",
        ]
        if alert.get("body"):
            context_parts.append(f"[Alert body: {alert['body'][:500]}]")
        if alert.get("matter_slug"):
            context_parts.append(f"[Matter: {alert['matter_slug']}]")

        # Build conversation history from thread
        history = []
        for msg in existing_thread:
            role = "user" if msg["role"] == "director" else "assistant"
            history.append({"role": role, "content": msg["content"]})

        # The director's new message is the question
        question = req.content
        if not existing_thread:
            # First reply — prepend alert context so Baker knows what this is about
            question = "\n".join(context_parts) + "\n\n" + req.content

        # Route through the SAME /api/scan pipeline — build a ScanRequest
        scan_req = ScanRequest(
            question=question,
            history=history[-25:],  # RICHER-CONTEXT-1: 25 turns
            project=alert.get("matter_slug"),
        )

        # Call the scan endpoint internally — returns StreamingResponse (SSE)
        streaming_resp = await scan_chat(scan_req)

        # Wrap the SSE stream to capture Baker's response and store in alert_threads.
        # Brief spec (COCKPIT_V3 §4): "Both messages are inserted into alert_threads."
        async def _capture_and_store_reply():
            baker_tokens = []
            async for chunk in streaming_resp.body_iterator:
                yield chunk
                if isinstance(chunk, str) and chunk.startswith("data: "):
                    payload = chunk[6:].strip()
                    if payload and payload != "[DONE]":
                        try:
                            d = json.loads(payload)
                            if "token" in d:
                                baker_tokens.append(d["token"])
                        except (ValueError, KeyError):
                            pass
            # Store Baker's complete response (fault-tolerant)
            full_reply = "".join(baker_tokens)
            if full_reply.strip():
                try:
                    _s = _get_store()
                    _c = _s._get_conn()
                    if _c:
                        try:
                            _cur = _c.cursor()
                            _cur.execute(
                                "INSERT INTO alert_threads (alert_id, role, content) VALUES (%s, 'baker', %s)",
                                (alert_id, full_reply),
                            )
                            _c.commit()
                            _cur.close()
                        finally:
                            _s._put_conn(_c)
                except Exception as store_err:
                    logger.debug(f"Failed to store baker reply for alert {alert_id}: {store_err}")

        return StreamingResponse(
            _capture_and_store_reply(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/alerts/{alert_id}/reply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/matters/{matter_slug}/items", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_matter_items(matter_slug: str):
    """
    Get all pending alerts for a specific matter, sorted by tier then date.
    T1/T2 include structured_actions for expanded display.
    """
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if matter_slug == '_ungrouped':
                cur.execute("""
                    SELECT * FROM alerts
                    WHERE status = 'pending' AND matter_slug IS NULL
                    ORDER BY tier, created_at DESC
                """)
            else:
                cur.execute("""
                    SELECT * FROM alerts
                    WHERE status = 'pending' AND matter_slug = %s
                    ORDER BY tier, created_at DESC
                """, (matter_slug,))
            items = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"items": items, "count": len(items), "matter_slug": matter_slug}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/matters/{matter_slug}/items failed: {e}")
        return {"items": [], "count": 0, "matter_slug": matter_slug}


# --- Debug: Action Handler Log (EMAIL-DELIVERY-1 diagnosis) ---

@app.get("/api/debug/action-log", tags=["debug"], dependencies=[Depends(verify_api_key)])
async def get_action_log():
    """Return the in-memory action handler event log for diagnosis."""
    from orchestrator.action_handler import _action_log
    return {"events": list(_action_log), "count": len(_action_log)}


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


@app.post("/api/deadlines/{deadline_id}/reschedule", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def reschedule_deadline_api(deadline_id: int, body: dict = None):
    """Reschedule a deadline to a new due_date."""
    try:
        from models.deadlines import update_deadline, get_deadline_by_id
        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")
        new_date = (body or {}).get("due_date")
        if not new_date:
            raise HTTPException(status_code=400, detail="due_date required")
        update_deadline(deadline_id, due_date=new_date)
        return {"status": "rescheduled", "id": deadline_id, "new_due_date": new_date}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/reschedule failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/commitments/{commitment_id}/dismiss", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def dismiss_commitment(commitment_id: int):
    """Dismiss a commitment."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("UPDATE commitments SET status = 'dismissed' WHERE id = %s", (commitment_id,))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
        return {"status": "dismissed", "id": commitment_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"dismiss commitment {commitment_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/commitments/{commitment_id}/reschedule", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def reschedule_commitment(commitment_id: int, body: dict = None):
    """Reschedule a commitment to a new due_date."""
    try:
        new_date = (body or {}).get("due_date")
        if not new_date:
            raise HTTPException(status_code=400, detail="due_date required")
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("UPDATE commitments SET due_date = %s, status = 'open' WHERE id = %s", (new_date, commitment_id))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
        return {"status": "rescheduled", "id": commitment_id, "new_due_date": new_date}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"reschedule commitment {commitment_id} failed: {e}")
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

        # Email poll last checked (PHASE-4A: separate from watermark)
        try:
            checked_wm = trigger_state.get_watermark("email_poll_checked")
            if checked_wm:
                status_data["email_last_polled"] = checked_wm.isoformat()
        except Exception:
            pass

        # Email poll diagnostics (from sentinel_health table)
        try:
            from triggers.sentinel_health import get_all_sentinel_health
            email_rows = [r for r in get_all_sentinel_health() if r.get("source") == "email"]
            if email_rows:
                eh = email_rows[0]
                if eh.get("last_error_msg"):
                    status_data["email_poll_error"] = eh["last_error_msg"]
                if eh.get("last_success_at"):
                    ts = eh["last_success_at"]
                    status_data["email_poll_last_success"] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        except Exception:
            pass

        # PHASE-4A: Today's API cost
        try:
            from orchestrator.cost_monitor import get_daily_cost, COST_ALERT_EUR, COST_HARD_STOP_EUR
            daily_cost = get_daily_cost()
            status_data["cost_today_eur"] = round(daily_cost, 4)
            status_data["cost_alert_threshold_eur"] = COST_ALERT_EUR
            status_data["cost_hard_stop_eur"] = COST_HARD_STOP_EUR
        except Exception:
            pass

        # Scheduler job count
        try:
            from triggers.embedded_scheduler import _scheduler
            if _scheduler and _scheduler.running:
                status_data["scheduled_jobs"] = len(_scheduler.get_jobs())
        except Exception:
            pass

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


@app.get("/api/trigger-watermarks", tags=["system"], dependencies=[Depends(verify_api_key)])
async def get_trigger_watermarks():
    """Diagnostic: show all trigger watermarks for polling health checks."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return {"error": "no db connection"}
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT source, last_seen, updated_at FROM trigger_watermarks ORDER BY source"
            )
            rows = cur.fetchall()
            cur.close()
            now = datetime.now(timezone.utc)
            return {
                "watermarks": [
                    {
                        "source": r[0],
                        "last_seen": r[1].isoformat() if r[1] else None,
                        "updated_at": r[2].isoformat() if r[2] else None,
                        "age_hours": round((now - r[1]).total_seconds() / 3600, 1) if r[1] else None,
                    }
                    for r in rows
                ]
            }
        finally:
            store._put_conn(conn)
    except Exception as e:
        return {"error": str(e)}


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
    Also logs to conversation_memory and fires Type 2 email if requested.
    """
    async def _stream():
        payload = json.dumps({"token": text})
        yield f"data: {payload}\n\n"
        yield "data: [DONE]\n\n"
        # Log to conversation memory so Baker remembers action results
        try:
            store = _get_store()
            store.log_conversation(question, text, answer_length=len(text))
        except Exception as _e:
            logger.warning(f"Action conversation log failed (non-fatal): {_e}")
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

    # CLICKUP-V2: Check for pending ClickUp plan interaction first
    try:
        plan_action = _ah.check_pending_plan(req.question, channel="scan")
        if plan_action == "confirm":
            return _action_stream_response(
                _ah.execute_pending_plan(channel="scan"), req.question,
            )
        elif plan_action and plan_action.startswith("revise:"):
            return _action_stream_response(
                _ah.revise_pending_plan(plan_action[7:], _get_retriever(), channel="scan"),
                req.question,
            )
    except Exception as e:
        logger.warning(f"Pending plan check failed (continuing): {e}")

    # SCAN-ACTION-1: Email action routing — check before RAG pipeline
    logger.info(f"SCAN_DEBUG: question={req.question[:200]}")
    draft_action = _ah.check_pending_draft(req.question)
    logger.info(f"SCAN_DEBUG: draft_action={draft_action}")
    if draft_action == "confirm":
        logger.info("SCAN_DEBUG: routing to handle_confirmation")
        return _action_stream_response(_ah.handle_confirmation(), req.question)
    elif draft_action and draft_action.startswith("confirm_to:"):
        new_recipients = draft_action[11:]  # everything after "confirm_to:"
        logger.info(f"SCAN_DEBUG: routing to handle_confirmation with recipients={new_recipients}")
        return _action_stream_response(
            _ah.handle_confirmation(recipient_override=new_recipients), req.question,
        )
    elif draft_action and draft_action.startswith("edit:"):
        return _action_stream_response(
            _ah.handle_edit(draft_action[5:], _get_retriever(), req.project, req.role),
            req.question,
        )
    elif draft_action is None:
        # No pending draft — classify intent for new actions
        # WA-SEND-1: Fetch recent conversation turns for short-term memory
        _conv_history = ""
        try:
            store = _get_store()
            recent_turns = store.get_recent_conversations(limit=15)
            if recent_turns:
                # Build a compact history string (newest-first → reverse for chronological)
                lines = []
                for turn in reversed(recent_turns):
                    q = (turn.get("question") or "")[:200]
                    a = (turn.get("answer") or "")[:300]
                    lines.append(f"Director: {q}")
                    if a:
                        lines.append(f"Baker: {a}")
                _conv_history = "\n".join(lines)
        except Exception as e:
            logger.debug(f"Conversation history fetch failed (non-fatal): {e}")

        intent = _ah.classify_intent(req.question, conversation_history=_conv_history)
        logger.info(f"SCAN_DEBUG: intent_type={intent.get('type')}, recipient={intent.get('recipient')}")
        if intent.get("type") == "email_action":
            logger.info("SCAN_DEBUG: routing to handle_email_action")
            return _action_stream_response(
                _ah.handle_email_action(intent, _get_retriever(), req.project, req.role),
                req.question,
            )
        elif intent.get("type") == "whatsapp_action":
            logger.info("SCAN_DEBUG: routing to handle_whatsapp_action")
            intent["original_question"] = req.question  # pass full text for phone extraction
            return _action_stream_response(
                _ah.handle_whatsapp_action(
                    intent, _get_retriever(), channel="scan",
                    conversation_history=_conv_history,
                ),
                req.question,
            )
        elif intent.get("type") == "deadline_action":
            return _action_stream_response(
                _ah.handle_deadline_action(intent),
                req.question,
            )
        elif intent.get("type") in ("vip_action", "contact_action"):
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
        elif intent.get("type") == "clickup_action":
            return _action_stream_response(
                _ah.handle_clickup_action(intent, _get_retriever(), channel="scan"),
                req.question,
            )
        elif intent.get("type") == "clickup_fetch":
            return _action_stream_response(
                _ah.handle_clickup_fetch(
                    req.question, _get_retriever(), channel="scan",
                ),
                req.question,
            )
        elif intent.get("type") == "clickup_plan":
            return _action_stream_response(
                _ah.handle_clickup_plan(
                    req.question, _get_retriever(), channel="scan",
                ),
                req.question,
            )
        elif intent.get("type") == "capability_task":
            # AGENT-FRAMEWORK-1: Explicit capability invocation
            return _scan_chat_capability(req, start, intent)
    # draft_action == "dismiss" or regular question → fall through to RAG pipeline

    # DEEP-MODE-1: All Ask Baker questions go straight to deep agentic path.
    # No capability routing, no tier/mode routing. Pre-stuffed context + tools.
    # Action routing (email/WA/ClickUp) already handled above.

    # Create baker_task (non-fatal tracking)
    _task_id = None
    try:
        store = _get_store()
        _task_id = store.create_baker_task(
            domain="projects", task_type="question",
            title=req.question[:200], description=req.question,
            sender="director", source="scan", channel="scan",
            status="in_progress",
        )
    except Exception as _te:
        logger.warning(f"baker_task creation failed (non-fatal): {_te}")

    return _scan_chat_deep(req, start, task_id=_task_id)


def _scan_chat_deep(req, start: float, task_id: int = None):
    """DEEP-MODE-1: Deep agentic path for all Ask Baker questions.

    Pre-stuffs recent emails, WhatsApp, meetings, decisions, and analyses
    into the system prompt, PLUS gives the agent all tools for deeper search.
    90s timeout, 15 iterations, full session history. No capability routing.
    """
    from orchestrator.agent import run_agent_loop_streaming
    from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT, build_mode_aware_prompt

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # --- Pre-stuff context from DB (fault-tolerant, each block independent) ---
    context_blocks = []

    # Entity context (people + matters mentioned in question)
    try:
        from orchestrator.scan_prompt import build_entity_context
        entity_ctx = build_entity_context(req.question)
        if entity_ctx:
            context_blocks.append(entity_ctx)
    except Exception:
        pass

    # Recent emails (keyword + recent)
    try:
        retriever = _get_retriever()
        emails = retriever.get_email_messages(req.question, limit=5)
        recent_emails = retriever.get_recent_emails(limit=5)
        seen = {c.metadata.get("message_id") for c in emails}
        for r in recent_emails:
            if r.metadata.get("message_id") not in seen:
                emails.append(r)
        if emails:
            lines = ["## RECENT EMAILS"]
            for e in emails[:8]:
                label = e.metadata.get("label", "email")
                date = e.metadata.get("date", "")
                lines.append(f"[EMAIL: {label} | {date}]\n{e.content[:1500]}")
            context_blocks.append("\n\n".join(lines))
    except Exception:
        pass

    # Recent WhatsApp
    try:
        retriever = _get_retriever()
        wa = retriever.get_whatsapp_messages(req.question, limit=5)
        recent_wa = retriever.get_recent_whatsapp(limit=5)
        seen = {c.metadata.get("msg_id") for c in wa}
        for r in recent_wa:
            if r.metadata.get("msg_id") not in seen:
                wa.append(r)
        if wa:
            lines = ["## RECENT WHATSAPP"]
            for w in wa[:8]:
                label = w.metadata.get("label", w.metadata.get("sender_name", ""))
                date = w.metadata.get("date", "")
                lines.append(f"[WA: {label} | {date}]\n{w.content[:1000]}")
            context_blocks.append("\n\n".join(lines))
    except Exception:
        pass

    # Meeting transcripts
    try:
        retriever = _get_retriever()
        meetings = retriever.get_meeting_transcripts(req.question, limit=3)
        recent_meetings = retriever.get_recent_meeting_transcripts(limit=3)
        seen = {c.metadata.get("meeting_id") for c in meetings}
        for r in recent_meetings:
            if r.metadata.get("meeting_id") not in seen:
                meetings.append(r)
        if meetings:
            lines = ["## MEETING TRANSCRIPTS"]
            for m in meetings[:5]:
                label = m.metadata.get("label", "meeting")
                date = m.metadata.get("date", "")
                lines.append(f"[MEETING: {label} | {date}]\n{m.content[:2000]}")
            context_blocks.append("\n\n".join(lines))
    except Exception:
        pass

    # Recent decisions
    try:
        retriever = _get_retriever()
        decisions = retriever.get_recent_decisions(limit=5)
        if decisions:
            lines = ["## RECENT DECISIONS"]
            for d in decisions:
                date = d.metadata.get("date", "")
                lines.append(f"[DECISION | {date}]\n{d.content[:800]}")
            context_blocks.append("\n\n".join(lines))
    except Exception:
        pass

    # Deep analyses (from Cowork/Claude Code)
    try:
        store = _get_store()
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT title, summary, created_at FROM deep_analyses
                    ORDER BY created_at DESC LIMIT 5
                """)
                rows = cur.fetchall()
                cur.close()
                if rows:
                    lines = ["## STORED ANALYSES"]
                    for title, summary, created in rows:
                        date = created.strftime("%Y-%m-%d") if created else ""
                        lines.append(f"[ANALYSIS: {title} | {date}]\n{(summary or '')[:1000]}")
                    context_blocks.append("\n\n".join(lines))
            finally:
                store._put_conn(conn)
    except Exception:
        pass

    # Deadlines
    try:
        from models.deadlines import get_active_deadlines
        deadlines = get_active_deadlines(limit=15)
        if deadlines:
            dl_lines = ["## ACTIVE DEADLINES"]
            for dl in deadlines:
                due = dl.get("due_date")
                due_str = due.strftime("%Y-%m-%d") if due else "TBD"
                priority = dl.get("priority", "normal")
                desc = dl.get("description", "")
                dl_lines.append(f"- [{priority.upper()}] {due_str}: {desc}")
            context_blocks.append("\n".join(dl_lines))
    except Exception:
        pass

    # DEEP-MODE-2: Prior Baker conversations relevant to this question
    try:
        store = _get_store()
        prior_convos = store.get_relevant_conversations(req.question, limit=5)
        if prior_convos:
            lines = ["## PRIOR BAKER CONVERSATIONS"]
            for conv in prior_convos:
                date = conv.get("created_at", "")
                date_str = date.strftime("%Y-%m-%d %H:%M") if hasattr(date, "strftime") else str(date)[:16]
                q = (conv.get("question") or "")[:200]
                a = (conv.get("answer") or "")[:800]
                lines.append(f"[{date_str}] Director: {q}")
                if a:
                    lines.append(f"Baker: {a}")
            context_blocks.append("\n\n".join(lines))
    except Exception:
        pass

    pre_stuffed = "\n\n".join(context_blocks) if context_blocks else ""

    # Build system prompt: base + pre-stuffed context + preferences
    system_prompt = (
        f"{SCAN_SYSTEM_PROMPT}\n\n"
        f"## CURRENT TIME\n{now}\n\n"
        f"{pre_stuffed}"
    )
    system_prompt = build_mode_aware_prompt(system_prompt, domain=None, mode="delegate")

    logger.info(f"DEEP-MODE: system prompt {len(system_prompt)} chars, "
                f"{len(context_blocks)} context blocks pre-stuffed")

    # Full session history — no cap
    history = []
    for msg in (req.history or []):
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": content})

    async def event_stream():
        full_response = ""
        agent_result = None

        import queue as _queue
        item_queue = _queue.Queue()

        def _run_agent():
            try:
                gen = run_agent_loop_streaming(
                    question=req.question,
                    system_prompt=system_prompt,
                    history=history,
                    max_iterations=15,
                    timeout_override=90.0,
                )
                for item in gen:
                    item_queue.put(item)
            except Exception as e:
                item_queue.put({"error": str(e)})
            finally:
                item_queue.put(None)

        agent_thread = asyncio.get_event_loop().run_in_executor(None, _run_agent)

        try:
            while True:
                try:
                    item = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, lambda: item_queue.get(timeout=8)
                        ),
                        timeout=10,
                    )
                except (asyncio.TimeoutError, Exception):
                    yield ": keepalive\n\n"
                    continue

                if item is None:
                    break

                if "_agent_result" in item:
                    agent_result = item["_agent_result"]
                elif "token" in item:
                    full_response += item["token"]
                    payload = json.dumps({"token": item["token"]})
                    yield f"data: {payload}\n\n"
                elif "tool_call" in item:
                    yield f"data: {json.dumps({'tool_call': item['tool_call']})}\n\n"
                elif "error" in item:
                    logger.error(f"Deep scan error: {item['error']}")
                    yield f"data: {json.dumps({'error': item['error']})}\n\n"
        except Exception as e:
            logger.error(f"Deep scan error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        await agent_thread
        yield "data: [DONE]\n\n"

        extra_meta = {"deep_mode": True}
        if agent_result:
            extra_meta.update({
                "agentic": True,
                "agent_iterations": agent_result.iterations,
                "agent_tool_calls": len(agent_result.tool_calls),
                "agent_input_tokens": agent_result.total_input_tokens,
                "agent_output_tokens": agent_result.total_output_tokens,
                "agent_elapsed_ms": agent_result.elapsed_ms,
            })
            logger.info(
                f"DEEP-MODE scan: {agent_result.iterations} iter, "
                f"{len(agent_result.tool_calls)} tools, "
                f"{agent_result.total_input_tokens}+{agent_result.total_output_tokens} tokens, "
                f"{agent_result.elapsed_ms}ms"
            )
        _scan_store_back(req, full_response, start, extra_meta, task_id=task_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_scan_system_prompt(deadline_only: bool = False, contexts=None,
                              domain_context: str = "") -> str:
    """Build the system prompt with time + optional context + deadlines.
    DECISION-ENGINE-1A: domain_context injected from score_trigger."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Deadlines (included in both agentic and legacy paths)
    deadline_block = ""
    try:
        from models.deadlines import get_active_deadlines
        deadlines = get_active_deadlines(limit=15)
        if deadlines:
            dl_lines = []
            for dl in deadlines:
                due = dl.get("due_date")
                due_str = due.strftime("%Y-%m-%d") if due else "TBD"
                priority = dl.get("priority", "normal")
                status = dl.get("status", "active")
                desc = dl.get("description", "")
                dl_lines.append(f"- [{priority.upper()}] {due_str}: {desc} ({status})")
            deadline_block = "\n\n## ACTIVE DEADLINES\n" + "\n".join(dl_lines)
    except Exception:
        pass

    if deadline_only:
        # Agentic mode: no pre-fetched context, tools provide context
        return (
            f"{SCAN_SYSTEM_PROMPT}\n"
            f"## CURRENT TIME\n{now}\n"
            f"{domain_context}"
            f"{deadline_block}"
        )
    else:
        # Legacy mode: context stuffed into prompt
        context_block = _format_scan_context(contexts)
        return (
            f"{SCAN_SYSTEM_PROMPT}\n"
            f"## CURRENT TIME\n{now}\n\n"
            f"{domain_context}"
            f"## RETRIEVED CONTEXT\n{context_block}"
            f"{deadline_block}"
        )


def _scan_store_back(req, full_response: str, start: float,
                     extra_meta: Optional[dict] = None, task_id: int = None):
    """Store-back logic shared by both agentic and legacy paths."""
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

    # Store full Q+A in Qdrant for conversation memory (CONV-MEM-1)
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
        if extra_meta:
            conv_metadata.update(extra_meta)
            # NOTE: Agent metadata (tokens, iterations, tool counts) lives in Qdrant
            # payload only.  Phase 2 observability should add a dedicated PostgreSQL
            # table (agent_tool_calls) for queryable analytics.

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
            answer=full_response,
            answer_length=len(full_response),
            project=req.project or "general",
            chunk_count=chunk_count,
        )
        logger.info("Conversation stored in Baker's memory (CONV-MEM-1)")
    except Exception as e:
        logger.warning(f"Conversation store-back failed (non-fatal): {e}")

    # STEP1C: Close baker_task with deliverable + agent metadata
    if task_id:
        try:
            store = _get_store()
            agent_meta = extra_meta or {}
            store.update_baker_task(
                task_id, status="completed",
                deliverable=full_response[:5000],
                agent_iterations=agent_meta.get("agent_iterations"),
                agent_tool_calls=agent_meta.get("agent_tool_calls"),
                agent_input_tokens=agent_meta.get("agent_input_tokens"),
                agent_output_tokens=agent_meta.get("agent_output_tokens"),
                agent_elapsed_ms=agent_meta.get("agent_elapsed_ms"),
            )
        except Exception as e:
            logger.warning(f"baker_task update failed (non-fatal): {e}")

    # Email scan result to Director (EMAIL-REFORM-1 Type 2 — opt-in only)
    if full_response:
        try:
            from outputs.email_alerts import has_email_intent, send_scan_result_email
            if has_email_intent(req.question):
                send_scan_result_email(req.question, full_response)
                logger.info("Scan result emailed (explicit request detected)")
        except Exception as e:
            logger.warning(f"Scan email failed (non-fatal): {e}")


def _scan_chat_capability(req, start: float, intent_or_plan: dict = None,
                          task_id: int = None, domain: str = None, mode: str = None,
                          entity_context: str = ""):
    """AGENT-FRAMEWORK-1: Route through capability framework.
    Handles both explicit ('have the finance agent...') and implicit (router match) paths.
    SPECIALIST-DEEP-1: entity_context forwarded to capability runner for pre-stuffed context."""
    import json as _json

    from orchestrator.capability_router import CapabilityRouter, RoutingPlan
    from orchestrator.capability_runner import CapabilityRunner

    # Build routing plan
    plan = intent_or_plan.get("plan") if isinstance(intent_or_plan, dict) else None
    if plan is None:
        # Explicit intent — route via hint
        hint = intent_or_plan.get("capability_hint", "") if isinstance(intent_or_plan, dict) else ""
        router = CapabilityRouter()
        plan = router.route(req.question, domain, mode)
        if not plan or not plan.capabilities:
            # No capability match — fall through to generic agentic
            logger.info("Capability routing: no match, falling through to agentic")
            return _scan_chat_agentic(req, start, "", task_id=task_id,
                                      mode=mode, domain=domain)

    cap_slugs = [c.slug for c in plan.capabilities]
    logger.info(f"Capability routing: mode={plan.mode}, capabilities={cap_slugs}")

    # Update baker_task with capability info
    try:
        store = _get_store()
        if task_id:
            store.update_baker_task(task_id,
                                    capability_slugs=_json.dumps(cap_slugs))
    except Exception:
        pass

    runner = CapabilityRunner()

    if plan.mode == "fast" and len(plan.capabilities) == 1:
        # Fast path — single capability, stream SSE
        cap = plan.capabilities[0]

        async def _cap_stream():
            import asyncio
            import queue as _queue
            q = _queue.Queue()
            _agent_result = [None]

            def _run():
                try:
                    for chunk in runner.run_streaming(cap, req.question,
                                                      history=req.history,
                                                      domain=domain, mode=mode,
                                                      entity_context=entity_context):
                        if "_agent_result" in chunk:
                            _agent_result[0] = chunk["_agent_result"]
                        elif "token" in chunk:
                            q.put_nowait(("token", chunk["token"]))
                        elif "tool_call" in chunk:
                            q.put_nowait(("tool_call", chunk["tool_call"]))
                except Exception as e:
                    logger.error(f"Capability stream error: {e}")
                finally:
                    q.put_nowait(StopIteration)

            import threading
            t = threading.Thread(target=_run, daemon=True)
            t.start()

            # SSE event: which capabilities are active
            yield f"data: {_json.dumps({'capabilities': cap_slugs})}\n\n"

            while True:
                try:
                    item = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, lambda: q.get(timeout=8)),
                        timeout=10.0,
                    )
                except (asyncio.TimeoutError, Exception):
                    # queue.Empty from q.get(timeout=8) or asyncio timeout
                    yield ": keepalive\n\n"
                    continue

                if item is StopIteration:
                    break
                if isinstance(item, tuple):
                    kind, value = item
                    if kind == "tool_call":
                        yield f"data: {_json.dumps({'tool_call': value})}\n\n"
                    else:
                        yield f"data: {_json.dumps({'token': value})}\n\n"
                else:
                    yield ": keepalive\n\n"

            # Log capability run
            ar = _agent_result[0]
            if ar:
                try:
                    store = _get_store()
                    run_id = store.insert_capability_run(
                        baker_task_id=task_id,
                        capability_slug=cap.slug,
                        sub_task=req.question[:500],
                        status="completed" if not ar.timed_out else "timed_out",
                    )
                    if run_id:
                        store.update_capability_run(
                            run_id, answer=ar.answer[:2000],
                            tools_used=_json.dumps([tc["name"] for tc in ar.tool_calls]),
                            iterations=ar.iterations,
                            input_tokens=ar.total_input_tokens,
                            output_tokens=ar.total_output_tokens,
                            elapsed_ms=ar.elapsed_ms,
                            status="completed" if not ar.timed_out else "timed_out",
                        )
                    if task_id:
                        store.update_baker_task(
                            task_id, status="completed",
                            deliverable=ar.answer[:2000],
                            capability_slug=cap.slug,
                            agent_iterations=ar.iterations,
                            agent_tool_calls=len(ar.tool_calls),
                            agent_input_tokens=ar.total_input_tokens,
                            agent_output_tokens=ar.total_output_tokens,
                            agent_elapsed_ms=ar.elapsed_ms,
                        )
                except Exception as _e:
                    logger.warning(f"Capability run logging failed (non-fatal): {_e}")

            # Yield task_id for frontend feedback buttons (LEARNING-LOOP)
            if task_id:
                yield f"data: {_json.dumps({'task_id': task_id})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_cap_stream(), media_type="text/event-stream")

    elif plan.mode == "delegate":
        # Delegate path — multi-capability, blocking then stream result
        result = runner.run_multi(plan, req.question, history=req.history,
                                  domain=domain, mode=mode,
                                  entity_context=entity_context)

        async def _delegate_stream():
            yield f"data: {_json.dumps({'capabilities': cap_slugs, 'phase': 'synthesizing'})}\n\n"
            if result.answer:
                yield f"data: {_json.dumps({'token': result.answer})}\n\n"
            # Log
            try:
                store = _get_store()
                for i, st in enumerate(plan.sub_tasks or []):
                    store.insert_capability_run(
                        baker_task_id=task_id,
                        capability_slug=st.get("capability_slug", ""),
                        sub_task=st.get("sub_task", "")[:500],
                        status="completed",
                    )
                if task_id:
                    store.update_baker_task(
                        task_id, status="completed",
                        deliverable=result.answer[:2000],
                        decomposition=_json.dumps(plan.sub_tasks),
                        agent_iterations=result.iterations,
                        agent_tool_calls=len(result.tool_calls),
                        agent_input_tokens=result.total_input_tokens,
                        agent_output_tokens=result.total_output_tokens,
                        agent_elapsed_ms=result.elapsed_ms,
                    )
            except Exception as _e:
                logger.warning(f"Delegate logging failed (non-fatal): {_e}")
            yield "data: [DONE]\n\n"

        return StreamingResponse(_delegate_stream(), media_type="text/event-stream")

    else:
        # Fallback to agentic
        return _scan_chat_agentic(req, start, "", task_id=task_id,
                                  mode=mode, domain=domain)


def _scan_chat_agentic(req, start: float, domain_context: str = "",
                       task_id: int = None, mode: str = None, domain: str = None):
    """AGENTIC-RAG-1 + STEP1C: Agent loop with tool use for Scan SSE."""
    from orchestrator.agent import run_agent_loop_streaming
    from orchestrator.scan_prompt import build_mode_aware_prompt

    base_prompt = _build_scan_system_prompt(deadline_only=True, domain_context=domain_context)
    system_prompt = build_mode_aware_prompt(base_prompt, domain, mode)

    # STEP1C: delegate mode gets more iterations + longer timeout
    _max_iter = 7 if mode == "delegate" else 5
    _timeout = 20.0 if mode == "delegate" else None

    # Build history
    history = []
    for msg in (req.history or [])[-25:]:
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": content})

    async def event_stream():
        full_response = ""
        agent_result = None

        # Run sync agent generator in a thread, bridge via asyncio.Queue.
        # This lets us send SSE keepalive pings while Claude API calls block.
        import queue as _queue
        item_queue = _queue.Queue()

        def _run_agent():
            try:
                gen = run_agent_loop_streaming(
                    question=req.question,
                    system_prompt=system_prompt,
                    history=history,
                    max_iterations=_max_iter,
                    timeout_override=_timeout,
                )
                for item in gen:
                    item_queue.put(item)
            except Exception as e:
                item_queue.put({"error": str(e)})
            finally:
                item_queue.put(None)  # sentinel: generator done

        # Start agent in background thread
        agent_thread = asyncio.get_event_loop().run_in_executor(None, _run_agent)

        try:
            while True:
                # Poll queue with short timeout; send keepalive if idle
                try:
                    item = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, lambda: item_queue.get(timeout=8)
                        ),
                        timeout=10,
                    )
                except (asyncio.TimeoutError, Exception):
                    # No data for 8-10s — send SSE comment to keep connection alive
                    yield ": keepalive\n\n"
                    continue

                if item is None:
                    break  # generator done

                if "_agent_result" in item:
                    agent_result = item["_agent_result"]
                    if agent_result.timed_out:
                        logger.warning("Agent timed out — falling back to single-pass")
                        yield f"data: {json.dumps({'token': '[Searching further...] '})}\n\n"
                        async for sse in _scan_chat_legacy_stream(
                            req, start, domain_context,
                            task_id=task_id, mode=mode, domain=domain,
                        ):
                            yield sse
                        return
                elif "token" in item:
                    full_response += item["token"]
                    payload = json.dumps({"token": item["token"]})
                    yield f"data: {payload}\n\n"
                elif "tool_call" in item:
                    # Send tool name as SSE data (acts as keepalive + UI hint)
                    yield f"data: {json.dumps({'tool_call': item['tool_call']})}\n\n"
                elif "error" in item:
                    logger.error(f"Agentic scan error: {item['error']}")
                    yield f"data: {json.dumps({'error': item['error']})}\n\n"
        except Exception as e:
            logger.error(f"Agentic scan error: {e}")
            err_payload = json.dumps({"error": str(e)})
            yield f"data: {err_payload}\n\n"

        # Wait for thread to finish
        await agent_thread

        yield "data: [DONE]\n\n"

        # Store-back with agent metadata (PM review item #5: log tokens)
        extra_meta = {}
        if agent_result:
            extra_meta = {
                "agentic": True,
                "agent_iterations": agent_result.iterations,
                "agent_tool_calls": len(agent_result.tool_calls),
                "agent_input_tokens": agent_result.total_input_tokens,
                "agent_output_tokens": agent_result.total_output_tokens,
                "agent_elapsed_ms": agent_result.elapsed_ms,
            }
            logger.info(
                f"AGENTIC-RAG scan: {agent_result.iterations} iterations, "
                f"{len(agent_result.tool_calls)} tools, "
                f"{agent_result.total_input_tokens}+{agent_result.total_output_tokens} tokens, "
                f"{agent_result.elapsed_ms}ms"
            )
        _scan_store_back(req, full_response, start, extra_meta, task_id=task_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _scan_chat_legacy_stream(req, start: float, domain_context: str = "",
                                   task_id: int = None, mode: str = None, domain: str = None):
    """Legacy single-pass RAG as an async generator (used as fallback from agentic)."""
    full_response = ""
    try:
        retriever = _get_retriever()
        contexts = retriever.search_all_collections(
            query=req.question, limit_per_collection=8, score_threshold=0.3,
            project=req.project, role=req.role,
        )
    except Exception as e:
        logger.error(f"Scan retrieval failed: {e}")
        contexts = []

    try:
        retriever = _get_retriever()
        transcripts = retriever.get_meeting_transcripts(req.question, limit=3)
        if transcripts:
            contexts.extend(transcripts)
        recent = retriever.get_recent_meeting_transcripts(limit=3)
        existing_ids = {c.metadata.get("meeting_id") for c in transcripts}
        for r in recent:
            if r.metadata.get("meeting_id") not in existing_ids:
                contexts.append(r)
    except Exception:
        pass

    try:
        retriever = _get_retriever()
        emails = retriever.get_email_messages(req.question, limit=3)
        if emails:
            contexts.extend(emails)
        recent_emails = retriever.get_recent_emails(limit=3)
        existing_eids = {c.metadata.get("message_id") for c in emails}
        for r in recent_emails:
            if r.metadata.get("message_id") not in existing_eids:
                contexts.append(r)
        wa_msgs = retriever.get_whatsapp_messages(req.question, limit=3)
        if wa_msgs:
            contexts.extend(wa_msgs)
        recent_wa = retriever.get_recent_whatsapp(limit=3)
        existing_wids = {c.metadata.get("msg_id") for c in wa_msgs}
        for r in recent_wa:
            if r.metadata.get("msg_id") not in existing_wids:
                contexts.append(r)
    except Exception:
        pass

    from orchestrator.scan_prompt import build_mode_aware_prompt
    base_prompt = _build_scan_system_prompt(
        deadline_only=False, contexts=contexts, domain_context=domain_context,
    )
    system_prompt = build_mode_aware_prompt(base_prompt, domain, mode)

    messages = []
    for msg in (req.history or [])[-25:]:
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": req.question})

    try:
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        with claude.messages.stream(
            model=config.claude.model, max_tokens=4096,
            system=system_prompt, messages=messages,
        ) as stream:
            for text in stream.text_stream:
                full_response += text
                payload = json.dumps({"token": text})
                yield f"data: {payload}\n\n"
    except Exception as e:
        logger.error(f"Scan stream error: {e}")
        err_payload = json.dumps({"error": str(e)})
        yield f"data: {err_payload}\n\n"

    yield "data: [DONE]\n\n"
    _scan_store_back(req, full_response, start, task_id=task_id)


def _scan_chat_legacy(req, start: float, domain_context: str = "",
                      task_id: int = None, mode: str = None, domain: str = None):
    """Legacy single-pass RAG — unchanged behavior, refactored into own function."""

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

    # 1b. ARCH-3: Also search full meeting transcripts from PostgreSQL
    try:
        retriever = _get_retriever()
        transcripts = retriever.get_meeting_transcripts(req.question, limit=3)
        if transcripts:
            contexts.extend(transcripts)
            logger.info(f"Scan: added {len(transcripts)} keyword-matched transcripts")
        recent = retriever.get_recent_meeting_transcripts(limit=3)
        existing_ids = {c.metadata.get("meeting_id") for c in transcripts}
        added = 0
        for r in recent:
            if r.metadata.get("meeting_id") not in existing_ids:
                contexts.append(r)
                added += 1
        if added:
            logger.info(f"Scan: added {added} recent meeting transcripts")
    except Exception as e:
        logger.warning(f"Meeting transcript retrieval failed (non-fatal): {e}")

    # 1c. ARCH-6/7: Also search full emails + WhatsApp from PostgreSQL
    try:
        retriever = _get_retriever()
        emails = retriever.get_email_messages(req.question, limit=3)
        if emails:
            contexts.extend(emails)
            logger.info(f"Scan: added {len(emails)} email messages from PostgreSQL")
        recent_emails = retriever.get_recent_emails(limit=3)
        existing_eids = {c.metadata.get("message_id") for c in emails}
        for r in recent_emails:
            if r.metadata.get("message_id") not in existing_eids:
                contexts.append(r)

        wa_msgs = retriever.get_whatsapp_messages(req.question, limit=3)
        if wa_msgs:
            contexts.extend(wa_msgs)
            logger.info(f"Scan: added {len(wa_msgs)} WhatsApp messages from PostgreSQL")
        recent_wa = retriever.get_recent_whatsapp(limit=3)
        existing_wids = {c.metadata.get("msg_id") for c in wa_msgs}
        for r in recent_wa:
            if r.metadata.get("msg_id") not in existing_wids:
                contexts.append(r)
    except Exception as e:
        logger.warning(f"Email/WhatsApp retrieval failed (non-fatal): {e}")

    # 2. Build system prompt with context (STEP1C: mode-aware prompt)
    from orchestrator.scan_prompt import build_mode_aware_prompt
    base_prompt = _build_scan_system_prompt(
        deadline_only=False, contexts=contexts, domain_context=domain_context,
    )
    system_prompt = build_mode_aware_prompt(base_prompt, domain, mode)

    # 3. Build messages (include history for follow-ups)
    messages = []
    for msg in (req.history or [])[-25:]:
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

        # 5. Store-back (STEP1C: pass task_id for closure)
        _scan_store_back(req, full_response, start, task_id=task_id)

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


@app.post("/api/documents/upload", tags=["documents"], dependencies=[Depends(verify_api_key)])
async def upload_document(file: UploadFile = File(...)):
    """Upload a document for full-text storage + classification + extraction.

    SPECIALIST-UPGRADE-1B: Stores complete text in documents table,
    runs classify + extract pipeline synchronously, returns results.
    Document immediately available via search_documents tool.
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    contents = await file.read()
    if len(contents) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large. Maximum size: 100MB.")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=ext,
            prefix=Path(file.filename).stem + "_",
        ) as tmp:
            tmp.write(contents)
            tmp_path = Path(tmp.name)

        # Extract full text
        from tools.ingest.extractors import extract
        full_text = await asyncio.to_thread(extract, tmp_path)
        if not full_text or len(full_text.strip()) < 10:
            raise HTTPException(status_code=400, detail="Could not extract text from file.")

        # Compute hash + store full text
        from tools.ingest.dedup import compute_file_hash
        file_hash = compute_file_hash(tmp_path)

        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        doc_id = store.store_document_full(
            source_path=f"upload:{file.filename}",
            filename=file.filename,
            file_hash=file_hash,
            full_text=full_text,
            token_count=len(full_text) // 4,
        )
        if not doc_id:
            raise HTTPException(status_code=500, detail="Failed to store document.")

        # Run classify + extract synchronously (user is waiting)
        from tools.document_pipeline import classify_document, extract_document
        classification = await asyncio.to_thread(classify_document, doc_id, full_text)

        extraction_summary = None
        if classification and classification.get("document_type", "other") != "other":
            import time
            time.sleep(1)
            extraction = await asyncio.to_thread(
                extract_document, doc_id, full_text,
                classification["document_type"],
            )
            if extraction:
                extraction_summary = extraction

        return {
            "document_id": doc_id,
            "filename": file.filename,
            "document_type": classification.get("document_type") if classification else None,
            "matter_slug": classification.get("matter_slug") if classification else None,
            "parties": classification.get("parties", []) if classification else [],
            "tags": classification.get("tags", []) if classification else [],
            "token_count": len(full_text) // 4,
            "extraction_summary": extraction_summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


# ============================================================
# STEP1C: Baker Tasks API (Task Ledger)
# ============================================================

@app.get("/api/tasks", tags=["tasks"], dependencies=[Depends(verify_api_key)])
async def get_baker_tasks_endpoint(
    status: Optional[str] = Query(None, description="Filter by status"),
    mode: Optional[str] = Query(None, description="Filter by mode"),
    limit: int = Query(20, le=100, description="Max results"),
):
    """Query the baker_tasks ledger."""
    store = _get_store()
    tasks = store.get_baker_tasks(status=status, mode=mode, limit=limit)
    # Serialize datetimes for JSON
    for t in tasks:
        for k, v in t.items():
            if isinstance(v, datetime):
                t[k] = v.isoformat()
    return {"tasks": tasks, "count": len(tasks)}


class TaskFeedbackRequest(BaseModel):
    feedback: str = Field(..., pattern="^(accepted|rejected|revised)$")
    comment: Optional[str] = None


@app.post("/api/tasks/{task_id}/feedback", tags=["tasks"], dependencies=[Depends(verify_api_key)])
async def task_feedback_endpoint(task_id: int, body: TaskFeedbackRequest):
    """Director feedback on a completed baker_task."""
    store = _get_store()
    task = store.get_baker_task_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    ok = store.update_baker_task(
        task_id,
        director_feedback=body.feedback,
        feedback_comment=body.comment,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update task")
    return {"status": "updated", "task_id": task_id, "feedback": body.feedback}


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
# Browser Task Management (BROWSER-1)
# ============================================================


class BrowserTaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1)
    mode: str = Field("simple")
    task_prompt: Optional[str] = None
    css_selectors: Optional[dict] = None
    category: Optional[str] = None


class BrowserTaskUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    mode: Optional[str] = None
    task_prompt: Optional[str] = None
    css_selectors: Optional[dict] = None
    is_active: Optional[bool] = None
    category: Optional[str] = None


@app.get("/api/browser/tasks", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def list_browser_tasks(active_only: bool = True):
    """List all browser monitoring tasks."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        sql = """SELECT id, name, url, mode, task_prompt, css_selectors, category,
                        is_active, consecutive_failures, last_polled, last_content_hash,
                        created_at, updated_at
                 FROM browser_tasks"""
        if active_only:
            sql += " WHERE is_active = TRUE"
        sql += " ORDER BY id"
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        # Fetch latest result per task (DASHBOARD-DATA-LAYER)
        for row in rows:
            cur.execute("""
                SELECT content, structured_data, created_at, mode_used
                FROM browser_results
                WHERE task_id = %s
                ORDER BY created_at DESC LIMIT 1
            """, (row["id"],))
            result = cur.fetchone()
            if result:
                row["latest_result"] = {
                    "content": (result[0] or "")[:300],
                    "structured_data": result[1],
                    "created_at": result[2].isoformat() if result[2] else None,
                    "mode_used": result[3],
                }
            else:
                row["latest_result"] = None
        cur.close()
        # Convert datetimes
        for row in rows:
            for k in ("last_polled", "created_at", "updated_at"):
                if row.get(k):
                    row[k] = row[k].isoformat()
        return {"tasks": rows, "count": len(rows)}
    finally:
        store._put_conn(conn)


@app.post("/api/browser/tasks", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def create_browser_task(req: BrowserTaskCreate):
    """Create a new browser monitoring task."""
    if req.mode not in ("simple", "browser"):
        raise HTTPException(status_code=400, detail="mode must be 'simple' or 'browser'")
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO browser_tasks (name, url, mode, task_prompt, css_selectors, category)
               VALUES (%s, %s, %s, %s, %s::jsonb, %s)
               RETURNING id, created_at""",
            (
                req.name, req.url, req.mode, req.task_prompt,
                json.dumps(req.css_selectors) if req.css_selectors else "{}",
                req.category,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return {"status": "created", "id": row[0], "created_at": row[1].isoformat()}
    finally:
        store._put_conn(conn)


@app.get("/api/browser/tasks/{task_id}", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def get_browser_task(task_id: int):
    """Get a browser task with recent results."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, name, url, mode, task_prompt, css_selectors, category,
                      is_active, consecutive_failures, last_polled, last_content_hash,
                      created_at, updated_at
               FROM browser_tasks WHERE id = %s""",
            (task_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        cols = [d[0] for d in cur.description]
        task = dict(zip(cols, row))
        for k in ("last_polled", "created_at", "updated_at"):
            if task.get(k):
                task[k] = task[k].isoformat()

        # Fetch recent results
        cur.execute(
            """SELECT id, content_hash, content, structured_data, mode_used,
                      steps_count, cost_usd, duration_ms, created_at
               FROM browser_results WHERE task_id = %s
               ORDER BY created_at DESC LIMIT 10""",
            (task_id,),
        )
        rcols = [d[0] for d in cur.description]
        results = [dict(zip(rcols, r)) for r in cur.fetchall()]
        for r in results:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("cost_usd"):
                r["cost_usd"] = float(r["cost_usd"])
            # Truncate content for list view
            if r.get("content"):
                r["content_preview"] = r["content"][:500]
                del r["content"]
        cur.close()

        task["recent_results"] = results
        return task
    finally:
        store._put_conn(conn)


@app.put("/api/browser/tasks/{task_id}", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def update_browser_task(task_id: int, req: BrowserTaskUpdate):
    """Update a browser task configuration."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        updates = []
        params = []
        if req.name is not None:
            updates.append("name = %s")
            params.append(req.name)
        if req.url is not None:
            updates.append("url = %s")
            params.append(req.url)
        if req.mode is not None:
            if req.mode not in ("simple", "browser"):
                raise HTTPException(status_code=400, detail="mode must be 'simple' or 'browser'")
            updates.append("mode = %s")
            params.append(req.mode)
        if req.task_prompt is not None:
            updates.append("task_prompt = %s")
            params.append(req.task_prompt)
        if req.css_selectors is not None:
            updates.append("css_selectors = %s::jsonb")
            params.append(json.dumps(req.css_selectors))
        if req.is_active is not None:
            updates.append("is_active = %s")
            params.append(req.is_active)
            if req.is_active:
                updates.append("consecutive_failures = 0")
        if req.category is not None:
            updates.append("category = %s")
            params.append(req.category)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        updates.append("updated_at = NOW()")
        params.append(task_id)

        cur = conn.cursor()
        cur.execute(
            f"UPDATE browser_tasks SET {', '.join(updates)} WHERE id = %s RETURNING id",
            params,
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "updated", "id": task_id}
    finally:
        store._put_conn(conn)


@app.delete("/api/browser/tasks/{task_id}", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def delete_browser_task(task_id: int):
    """Soft-delete (deactivate) a browser task."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE browser_tasks SET is_active = FALSE, updated_at = NOW() WHERE id = %s RETURNING id",
            (task_id,),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "deactivated", "id": task_id}
    finally:
        store._put_conn(conn)


@app.get("/api/browser/results/{task_id}", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def list_browser_results(task_id: int, limit: int = 20):
    """List recent results for a browser task."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, task_id, content_hash, content, structured_data, mode_used,
                      steps_count, cost_usd, duration_ms, created_at
               FROM browser_results WHERE task_id = %s
               ORDER BY created_at DESC LIMIT %s""",
            (task_id, min(limit, 100)),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("cost_usd"):
                r["cost_usd"] = float(r["cost_usd"])
        return {"results": rows, "count": len(rows), "task_id": task_id}
    finally:
        store._put_conn(conn)


@app.post("/api/browser/tasks/{task_id}/run", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def run_browser_task_now(task_id: int, background_tasks: BackgroundTasks):
    """Trigger an immediate run of a specific browser task.
    Browser-mode tasks run in background (up to 120s) to avoid Render HTTP timeout.
    Simple-mode tasks run synchronously (fast, <30s).
    """
    from triggers.browser_trigger import run_single_task, _get_task_by_id
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    task = _get_task_by_id(store, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.get("mode") == "browser":
        # Browser mode can take up to 120s — run in background
        background_tasks.add_task(run_single_task, task_id)
        return {"status": "running", "task_id": task_id, "mode": "browser",
                "message": "Browser task submitted. Check GET /api/browser/results/{id} for output."}
    else:
        # Simple mode is fast — run synchronously
        result = run_single_task(task_id)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])
        return result


@app.get("/api/browser/status", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def browser_status():
    """Browser sentinel health: active tasks, last poll, cloud API status."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM browser_tasks WHERE is_active = TRUE")
        active_count = cur.fetchone()[0]
        cur.execute("SELECT MAX(last_polled) FROM browser_tasks")
        last_poll = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM browser_results")
        total_results = cur.fetchone()[0]
        cur.close()

        from config.settings import config
        return {
            "status": "healthy",
            "active_tasks": active_count,
            "total_results": total_results,
            "last_poll": last_poll.isoformat() if last_poll else None,
            "cloud_api_configured": bool(config.browser.cloud_api_key),
            "poll_interval_seconds": config.triggers.browser_check_interval,
        }
    finally:
        store._put_conn(conn)


# ============================================================
# Capability Quality (LEARNING-LOOP Part 4)
# ============================================================

@app.get("/api/capability-quality", tags=["learning-loop"], dependencies=[Depends(verify_api_key)])
async def get_capability_quality():
    """Aggregate feedback quality per capability."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return {"capabilities": []}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT capability_slug,
                   COUNT(*) as total_tasks,
                   SUM(CASE WHEN director_feedback = 'accepted' THEN 1 ELSE 0 END) as accepted,
                   SUM(CASE WHEN director_feedback = 'revised' THEN 1 ELSE 0 END) as revised,
                   SUM(CASE WHEN director_feedback = 'rejected' THEN 1 ELSE 0 END) as rejected,
                   SUM(CASE WHEN director_feedback IS NULL THEN 1 ELSE 0 END) as no_feedback
            FROM baker_tasks
            WHERE capability_slug IS NOT NULL
              AND status = 'completed'
            GROUP BY capability_slug
            ORDER BY total_tasks DESC
        """)
        rows = cur.fetchall()
        cur.close()
        caps = []
        for slug, total, acc, rev, rej, nf in rows:
            rated = acc + rev + rej
            quality = round(acc / rated * 100) if rated > 0 else None
            caps.append({
                "slug": slug, "total_tasks": total,
                "accepted": acc, "revised": rev, "rejected": rej,
                "no_feedback": nf, "quality_pct": quality,
            })
        return {"capabilities": caps}
    except Exception as e:
        return {"capabilities": [], "error": str(e)}
    finally:
        store._put_conn(conn)


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
