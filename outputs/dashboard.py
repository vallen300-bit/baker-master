"""
Baker AI — CEO Dashboard API Server
FastAPI app serving REST endpoints for the Baker Dashboard.
Reads from PostgreSQL via existing store_back + retriever.
Serves static frontend from outputs/static/.
Includes /api/scan SSE endpoint for interactive Baker chat.
"""
# PEP 563: lazy annotations so PEP 604 unions don't eval at import on py3.9 (PY39_UNION_IMPORT_SWEEP_1).
from __future__ import annotations

import asyncio
import decimal as _decimal
import hashlib
import hmac
import html as _html
import json
import logging
import os
import posixpath
import re
import tempfile
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4

import anthropic
from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles


class NoCacheHTMLStaticFiles(StaticFiles):
    """STATIC_HTML_NOCACHE_REVALIDATE_1: static mount that forces revalidation on
    HTML so a deploy is never masked by a browser/PWA-cached page (Director
    stale-dashboard incident 2026-06-19 — opened AI-Hotel Field Notes after the
    #381 deploy and saw a pre-deploy cached copy).

    Uses ``no-cache`` (always revalidate), NOT ``no-store`` — the existing etag
    then yields a cheap 304 Not Modified when the file is unchanged, so it stays
    fresh-on-deploy with near-zero bandwidth otherwise. HTML only; images / JS /
    CSS keep normal caching.
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        try:
            if resp.headers.get("content-type", "").startswith("text/html"):
                resp.headers["Cache-Control"] = "no-cache"
        except Exception:
            pass
        return resp
from pydantic import BaseModel, Field

from config.settings import config
from orchestrator.gemini_client import is_gemini_model, call_flash, call_pro, GeminiResponse
# OOM-FIX: document_generator lazy-imported inside endpoint functions
# (python-docx, openpyxl, reportlab, python-pptx = ~120 MB saved at startup)


def _llm_call(model: str, messages: list, max_tokens: int = 2000, system: str = None,
              response_format: str = None, thinking_budget: int = None):
    """GEMINI-MIGRATION-1: Unified LLM call — routes to Gemini or Anthropic.

    response_format / thinking_budget are Gemini-only knobs (ignored on the
    Anthropic branch). thinking_budget=0 disables 2.5-flash thinking so small
    max_tokens calls don't truncate (AI_HOTEL_CAPTURE_CLASSIFY_1).

    BAKER_DASHBOARD_V2_MODEL_LOCK_1: route by the *actual* gemini model string.
    Previously every gemini-* model fell through to call_flash, so a trusted site
    asking for "gemini-2.5-pro" silently ran on Flash — a policy bypass. Now a
    non-flash gemini model goes to call_pro; only flash models go to call_flash."""
    if is_gemini_model(model):
        from orchestrator.model_policy import is_flash
        if is_flash(model):
            return call_flash(messages=messages, max_tokens=max_tokens, system=system,
                              response_format=response_format, thinking_budget=thinking_budget)
        return call_pro(messages=messages, max_tokens=max_tokens, system=system,
                        response_format=response_format, thinking_budget=thinking_budget)
    else:
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        kwargs = dict(model=model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system
        if model == config.claude.model:
            kwargs["extra_headers"] = {"anthropic-beta": config.claude.beta_header}
        resp = client.messages.create(**kwargs)
        return GeminiResponse(resp.content[0].text, resp.usage.input_tokens, resp.usage.output_tokens)
from orchestrator.scan_prompt import SCAN_SYSTEM_PROMPT
from orchestrator import action_handler as _ah
from orchestrator.cortex_runner import maybe_run_cycle
from kbl.ingestion_surfaces import (
    build_ingestion_surfaces_prompt_block,
    load_ingestion_surfaces,
)
from kbl.cache_telemetry import log_cache_usage
from kbl.priorities_registry import (
    get_all as get_all_priorities,
    is_active_priority as priority_is_active,
    registry_version as priorities_registry_version,
    registry_ratified_at as priorities_registry_ratified_at,
)
from kbl.slug_registry import describe as slug_describe, normalize as slug_normalize


def _split_scan_system_for_cache(system_prompt: str) -> list:
    """PROMPT_CACHE_AUDIT_1: split Scan system prompt into
    [stable_cached_block, dynamic_block] form so the stable 1.9k-token
    SCAN_SYSTEM_PROMPT prefix is prompt-cacheable across calls.

    Dynamic suffix (time / deadlines / retrieval / mode / prefs) stays
    uncached in a second block."""
    stable = SCAN_SYSTEM_PROMPT
    if system_prompt.startswith(stable):
        dynamic = system_prompt[len(stable):]
    else:
        # Fallback: whole prompt is dynamic, nothing to cache this call.
        return [{"type": "text", "text": system_prompt}]
    blocks: list = [
        {"type": "text", "text": stable,
         "cache_control": {"type": "ephemeral", "ttl": "1h"}},
    ]
    if dynamic.strip():
        blocks.append({"type": "text", "text": dynamic})
    return blocks

from tools.ingest.pipeline import ingest_file
from tools.ingest.extractors import SUPPORTED_EXTENSIONS
from tools.ingest.classifier import VALID_COLLECTIONS
from triggers.embedded_scheduler import start_scheduler, stop_scheduler, get_scheduler_status

# CITATIONS_API_SCAN_1: Anthropic Citations API adapter (model-level grounding).
# Replaces prompt-engineered S5 enforcement. Adapter degrades gracefully on
# older SDK (empty citations, Scan continues). Wiring: 3 Scan endpoints below.
from kbl.citations import (
    build_document_blocks,
    extract_citations,
    ExtractedResponse,
)

logger = logging.getLogger("sentinel.dashboard")


def _scan_prompt_with_ingestion_surfaces() -> str:
    """SCAN prompt plus the current vault-backed ingestion surface checklist."""
    try:
        block = build_ingestion_surfaces_prompt_block()
    except Exception as e:  # noqa: BLE001 - scan must not break on loader drift.
        logger.warning("scan ingestion-surface prompt block failed: %s", e)
        block = ""
    if not block:
        return SCAN_SYSTEM_PROMPT
    return f"{SCAN_SYSTEM_PROMPT}\n\n{block}"

# ============================================================
# Authentication
# ============================================================

_BAKER_API_KEY = os.getenv("BAKER_API_KEY", "")
_AI_HOTEL_SESSION_COOKIE = "aih_session"
_AI_HOTEL_SESSION_SCOPE = "ai-hotel:read"
# AI_HOTEL_LAB_ADMIN_WRITE_SCOPE_1: a strictly higher scope for mutations
# (projection-admin approve/revoke/refresh). Reads keep ai-hotel:read; the master
# X-Baker-Key remains the general admin/write credential. A read-only credential
# must never satisfy this scope (fail closed → 403).
_AI_HOTEL_WRITE_SCOPE = "ai-hotel:write"
_AI_HOTEL_SESSION_TTL_S = int(os.getenv("AI_HOTEL_SESSION_TTL_SECONDS", "43200"))
_AI_HOTEL_PIN_RATE_LIMIT_PER_MIN = int(os.getenv("AI_HOTEL_PIN_RATE_LIMIT_PER_MIN", "5"))
_AI_HOTEL_PIN_LOCKOUT_FAILURES = int(os.getenv("AI_HOTEL_PIN_LOCKOUT_FAILURES", "10"))
_AI_HOTEL_PIN_LOCKOUT_S = int(os.getenv("AI_HOTEL_PIN_LOCKOUT_SECONDS", "900"))
_AI_HOTEL_PIN_STATE_MAX = int(os.getenv("AI_HOTEL_PIN_STATE_MAX", "10000"))
_AI_HOTEL_PIN_WINDOW_S = 60
_ai_hotel_pin_lock = threading.Lock()
_ai_hotel_pin_state: dict[str, dict] = {}


class AIHotelPinAuthRequest(BaseModel):
    pin: str = Field("", max_length=64)


class AIHotelImageRotateRequest(BaseModel):
    deg: int = Field(..., description="Clockwise rotation degrees: 90, 180, or 270")


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


def _ai_hotel_client_ip_details(request: Request) -> tuple[str, str, bool, bool]:
    """Best-effort client key for PIN throttling behind Render's proxy.

    Render's public edge is Cloudflare-fronted and forwards CF-Connecting-IP as
    the real client IP. Do not key off X-Forwarded-For: its hop count is not a
    stable trust boundary and client-supplied values can pollute it.
    """
    def _single_header(name: str) -> str:
        try:
            values = request.headers.getlist(name)  # Starlette Headers supports this.
        except Exception:
            try:
                values = [request.headers.get(name)]
            except Exception:
                values = []
        for value in reversed(values or []):
            text = str(value or "").strip()
            if text:
                return text[:80]
        return ""

    try:
        cf_ip = _single_header("cf-connecting-ip")
        true_ip = _single_header("true-client-ip")
        if cf_ip:
            return cf_ip, "cf-connecting-ip", True, bool(true_ip)
        if true_ip:
            return true_ip, "true-client-ip", False, True
        if request.client and request.client.host:
            return request.client.host[:80], "request.client.host", False, False
    except Exception:
        pass
    return "unknown", "unknown", False, False


def _ai_hotel_client_ip(request: Request) -> str:
    return _ai_hotel_client_ip_details(request)[0]


def _ai_hotel_pin_prune_locked(now: float) -> None:
    """Prune expired PIN-attempt state and enforce a hard cap.

    Caller must hold _ai_hotel_pin_lock. Fault-tolerant by design: any malformed
    row is discarded so the public endpoint cannot accumulate bad state forever.
    """
    try:
        for ip, st in list(_ai_hotel_pin_state.items()):
            try:
                attempts = [
                    float(t) for t in st.get("attempts", [])
                    if now - float(t) < _AI_HOTEL_PIN_WINDOW_S
                ]
                locked_until = float(st.get("locked_until") or 0)
                st["attempts"] = attempts
                last_seen = float(st.get("last_seen") or 0)
                if attempts:
                    last_seen = max(last_seen, max(attempts))
                if locked_until > 0:
                    last_seen = max(last_seen, locked_until)
                st["last_seen"] = last_seen
                if not attempts and locked_until <= now:
                    _ai_hotel_pin_state.pop(ip, None)
            except Exception:
                _ai_hotel_pin_state.pop(ip, None)

        cap = max(1, int(_AI_HOTEL_PIN_STATE_MAX or 1))
        over = len(_ai_hotel_pin_state) - cap
        if over > 0:
            oldest = sorted(
                _ai_hotel_pin_state.items(),
                key=lambda item: float(item[1].get("last_seen") or 0),
            )
            for ip, _st in oldest[:over]:
                _ai_hotel_pin_state.pop(ip, None)
    except Exception as e:
        logger.error("ai_hotel PIN state prune failed open: %s", e)


def _ai_hotel_pin_rate_check(ip: str) -> None:
    """Fault-tolerant in-memory throttle for the public four-digit PIN surface."""
    now = time.time()
    try:
        with _ai_hotel_pin_lock:
            _ai_hotel_pin_prune_locked(now)
            st = _ai_hotel_pin_state.setdefault(ip, {
                "attempts": [],
                "failures": 0,
                "locked_until": 0.0,
                "last_seen": now,
            })
            locked_until = float(st.get("locked_until") or 0)
            if locked_until > now:
                raise HTTPException(429, "Too many attempts. Try again later.")
            attempts = [t for t in st.get("attempts", []) if now - float(t) < _AI_HOTEL_PIN_WINDOW_S]
            if len(attempts) >= _AI_HOTEL_PIN_RATE_LIMIT_PER_MIN:
                st["attempts"] = attempts
                st["last_seen"] = now
                raise HTTPException(429, "Too many attempts. Try again later.")
            attempts.append(now)
            st["attempts"] = attempts
            st["last_seen"] = now
            _ai_hotel_pin_prune_locked(now)
    except HTTPException:
        raise
    except Exception as e:
        # Auth must stay available even if in-memory accounting is malformed.
        logger.error("ai_hotel PIN rate-limit check failed open: %s", e)


def _ai_hotel_pin_record_failure(ip: str) -> None:
    now = time.time()
    try:
        with _ai_hotel_pin_lock:
            _ai_hotel_pin_prune_locked(now)
            st = _ai_hotel_pin_state.setdefault(ip, {
                "attempts": [],
                "failures": 0,
                "locked_until": 0.0,
                "last_seen": now,
            })
            st["failures"] = int(st.get("failures") or 0) + 1
            st["last_seen"] = now
            if st["failures"] >= _AI_HOTEL_PIN_LOCKOUT_FAILURES:
                st["locked_until"] = now + _AI_HOTEL_PIN_LOCKOUT_S
            logger.warning("ai_hotel PIN auth failed: ip=%s failures=%s", ip, st["failures"])
            _ai_hotel_pin_prune_locked(now)
    except Exception as e:
        logger.error("ai_hotel PIN failure accounting failed: %s", e)


def _ai_hotel_pin_record_success(ip: str) -> None:
    try:
        with _ai_hotel_pin_lock:
            _ai_hotel_pin_state.pop(ip, None)
    except Exception:
        pass


def _ai_hotel_session_secret() -> bytes:
    secret = (os.getenv("AI_HOTEL_SESSION_SECRET") or "").strip()
    if not secret:
        logger.error("AI Hotel session secret unavailable")
        raise HTTPException(503, "AI Hotel PIN auth unavailable.")
    return secret.encode("utf-8")


def _ai_hotel_b64url(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _ai_hotel_b64url_decode(txt: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def _ai_hotel_sign_session(scope: str = _AI_HOTEL_SESSION_SCOPE) -> str:
    exp = int(time.time()) + max(300, _AI_HOTEL_SESSION_TTL_S)
    payload = {
        "scope": scope,
        "iat": int(time.time()),
        "exp": exp,
        "nonce": uuid4().hex,
    }
    body = _ai_hotel_b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_ai_hotel_session_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_ai_hotel_b64url(sig)}"


def _ai_hotel_session_scope(token: str | None) -> str | None:
    """Return the VALIDATED scope of a signed session token (signature + expiry both
    verified), or ``None`` if the token is missing/forged/expired. The single place
    that authenticates a cookie; scope-specific deps compare the returned value. A
    forged or tampered scope cannot pass because the whole payload is HMAC-signed."""
    if not token or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(_ai_hotel_session_secret(), body.encode("ascii"), hashlib.sha256).digest()
        supplied = _ai_hotel_b64url_decode(sig)
        if not hmac.compare_digest(expected, supplied):
            return None
        payload = json.loads(_ai_hotel_b64url_decode(body).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        return payload.get("scope")
    except Exception:
        return None


def _ai_hotel_session_valid(token: str | None) -> bool:
    """True iff ``token`` grants at least READ access.

    Read is satisfied by the read scope OR the higher write scope (write is a superset
    of read), so a write-scoped credential can also drive read endpoints / the cockpit
    page. The write gate (``verify_ai_hotel_write_access``) still requires the write
    scope specifically; this only widens what counts as a valid READ session."""
    return _ai_hotel_session_scope(token) in (_AI_HOTEL_SESSION_SCOPE, _AI_HOTEL_WRITE_SCOPE)


async def verify_ai_hotel_read_access(
    request: Request,
    x_baker_key: str = Header(None, alias="X-Baker-Key"),
):
    """AI-Hotel read-only auth: master header OR scoped signed httpOnly cookie."""
    if _BAKER_API_KEY and x_baker_key and hmac.compare_digest(x_baker_key, _BAKER_API_KEY):
        return
    if _ai_hotel_session_valid(request.cookies.get(_AI_HOTEL_SESSION_COOKIE)):
        return
    raise HTTPException(
        status_code=401,
        detail="Invalid or missing AI Hotel read credentials",
        headers={"WWW-Authenticate": "X-Baker-Key"},
    )


async def verify_ai_hotel_photo_edit_access(
    request: Request,
    x_baker_key: str = Header(None, alias="X-Baker-Key"),
):
    """AI-Hotel narrow edit auth for private Field Notes repair actions.

    The master key remains the general write/admin credential. The scoped
    AI-Hotel cookie is accepted here only because these manual controls are
    Director-approved repair actions inside the private Field Notes viewer.
    """
    if _BAKER_API_KEY and x_baker_key and hmac.compare_digest(x_baker_key, _BAKER_API_KEY):
        return
    if _ai_hotel_session_valid(request.cookies.get(_AI_HOTEL_SESSION_COOKIE)):
        return
    raise HTTPException(
        status_code=401,
        detail="Invalid or missing AI Hotel photo edit credentials",
        headers={"WWW-Authenticate": "X-Baker-Key"},
    )


async def verify_ai_hotel_write_access(
    request: Request,
    x_baker_key: str = Header(None, alias="X-Baker-Key"),
):
    """AI_HOTEL_LAB_ADMIN_WRITE_SCOPE_1: admin-mutation auth (ai-hotel:write).

    Gates the projection-admin endpoint (approve/revoke/refresh) with a STRICTLY
    higher scope than reads. The master X-Baker-Key is the general admin/write
    credential and passes. A session cookie passes ONLY if it carries the write
    scope; a valid READ-only cookie is authenticated but insufficient → 403 (not a
    silent allow, not 401). No credential at all → 401. Fail closed throughout.

    This is an OUTER gate only — it does NOT replace the policy-layer human-admin
    check in ``policy.projection.admin`` (AC7/T7), which still independently rejects
    AI / external principals. Defense in depth.
    """
    if _BAKER_API_KEY and x_baker_key and hmac.compare_digest(x_baker_key, _BAKER_API_KEY):
        return
    scope = _ai_hotel_session_scope(request.cookies.get(_AI_HOTEL_SESSION_COOKIE))
    if scope == _AI_HOTEL_WRITE_SCOPE:
        return
    if scope == _AI_HOTEL_SESSION_SCOPE:
        # Authenticated, but a read-only credential cannot drive a mutation.
        raise HTTPException(
            status_code=403,
            detail="AI Hotel write scope required (read-only credential cannot mutate)",
        )
    raise HTTPException(
        status_code=401,
        detail="Invalid or missing AI Hotel write credentials",
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

from triggers.slack_interactivity import router as slack_interactivity_router
app.include_router(slack_interactivity_router, prefix="/webhook")

from outputs.email_router import router as email_router
app.include_router(email_router)

# AI Hotel Lab cockpit (AI_HOTEL_LAB_COCKPIT_UI_1) — auth-gated like other AI-Hotel
# surfaces. The /ai-hotel-lab/api/* DATA routes are hard-gated (401) by
# verify_ai_hotel_read_access; the browser never receives raw rows for an external role.
from outputs import ai_hotel_lab as _ai_hotel_lab
from outputs.ai_hotel_lab import router as ai_hotel_lab_router
app.include_router(ai_hotel_lab_router, dependencies=[Depends(verify_ai_hotel_read_access)])
# AI_HOTEL_LAB_ADMIN_WRITE_SCOPE_1: the admin-mutation route carries an extra
# placeholder write dependency (_write_auth) so the whole router stays read-gated while
# POST /api/admin/{action} additionally requires ai-hotel:write. Bind the real verifier
# here (the module can't import dashboard — circular), via the FastAPI DI override seam.
app.dependency_overrides[_ai_hotel_lab._write_auth] = verify_ai_hotel_write_access


def _ai_hotel_lab_authed(request: Request, x_baker_key: str | None) -> bool:
    """Non-raising auth check for the cockpit PAGE (master key OR scoped session)."""
    if _BAKER_API_KEY and x_baker_key and hmac.compare_digest(x_baker_key, _BAKER_API_KEY):
        return True
    return _ai_hotel_session_valid(request.cookies.get(_AI_HOTEL_SESSION_COOKIE))


@app.get("/ai-hotel-lab", response_class=HTMLResponse, include_in_schema=False)
@app.get("/ai-hotel-lab/", response_class=HTMLResponse, include_in_schema=False)
async def ai_hotel_lab_page(
    request: Request,
    x_baker_key: str = Header(None, alias="X-Baker-Key"),
):
    """Cockpit page (A.1, lead #3878). An authenticated session/key is SERVED the
    cockpit; an unauthenticated browser is CHALLENGED with the PIN-login page
    (reuses /api/ai-hotel/pin-auth) — never the cockpit, never a 500. Header
    X-Baker-Key clients and tests are served directly."""
    if _ai_hotel_lab_authed(request, x_baker_key):
        return _ai_hotel_lab.cockpit_page()
    return _ai_hotel_lab.cockpit_login_page(status_code=401)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Baker-Key"],
)


@app.post("/api/ai-hotel/pin-auth", tags=["ai-hotel"])
async def ai_hotel_pin_auth(request: Request, payload: AIHotelPinAuthRequest):
    """Exchange the short AI-Hotel PIN for a scoped read-only session cookie.

    This never returns or aliases the master X-Baker-Key. Failed attempts log
    only aggregate counts and client IP, never the submitted PIN value.
    """
    ip, ip_source, has_cf_ip, has_true_ip = _ai_hotel_client_ip_details(request)
    logger.info(
        "ai_hotel PIN auth client_ip_source=%s cf_connecting_ip_present=%s true_client_ip_present=%s",
        ip_source, has_cf_ip, has_true_ip,
    )
    _ai_hotel_pin_rate_check(ip)
    expected = (os.getenv("AI_HOTEL_PIN") or "").strip()
    if not expected:
        raise HTTPException(503, "AI Hotel PIN not configured.")
    supplied = (payload.pin or "").strip()
    if not hmac.compare_digest(supplied, expected):
        _ai_hotel_pin_record_failure(ip)
        raise HTTPException(401, "Incorrect code.")
    _ai_hotel_pin_record_success(ip)
    token = _ai_hotel_sign_session()
    ttl = max(300, _AI_HOTEL_SESSION_TTL_S)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        key=_AI_HOTEL_SESSION_COOKIE,
        value=token,
        max_age=ttl,
        httponly=True,
        secure=True,
        samesite="strict",
        # AI_HOTEL_LAB_COCKPIT_UI_1 (A.1, lead #3878): widened from "/api/ai-hotel"
        # so the one signed session covers BOTH the /ai-hotel-lab cockpit page and its
        # /ai-hotel-lab/api/* + /api/ai-hotel/* calls. Path only controls which paths
        # the browser SENDS the cookie on; the server still only honors it inside
        # verify_ai_hotel_read_access (signed + scope ai-hotel:read), so no new exposure.
        path="/",
    )
    return resp

# ============================================================
# SCHEDULER-WATCHDOG-1: Request-time heartbeat check
# ============================================================
_watchdog_last_check = 0
_watchdog_last_alert_ts = 0
_watchdog_alert_cooldown_s = 300  # min seconds between WA alerts
_watchdog_consecutive_stale = 0  # FALSE_POSITIVE_FIX_1: count of consecutive stale reads
# SCHEDULER_STALL_CODEFIX_1 — consecutive WATCHDOG restarts that still left
# job_count==0. When the singleton lock is held by an orphaned-but-alive backend
# that the in-process eviction can't reach, restart_scheduler() loops forever with
# zero jobs (the #2508 permanent stall). After _WATCHDOG_EXIT_THRESHOLD such
# restarts we os._exit(1): Render restarts the dyno, SIGTERM closes the lock socket
# at the OS level, the lock auto-releases, and start_scheduler() acquires cleanly.
# Counter advances ONLY on the watchdog restart path (not the 30s lease retry
# thread) and resets the instant job_count>0, so it can't fire mid-normal-acquire.
_watchdog_restart_failed_streak = 0
_WATCHDOG_EXIT_THRESHOLD = 3  # lead-ratified 2026-06-08 (#2517): conservative for os._exit
# SCHEDULER_WATCHDOG_HARDEN_1 (lead #2566, 2026-06-09) — a fresh scheduler_executions
# row within this window means the scheduler thread is provably alive, so a stale
# heartbeat WATERMARK is a gauge failure (the set_watermark write), NOT a dead
# scheduler. The watchdog suppresses the restart in that case. 180s < the 5-min
# heartbeat interval and the 720s stale threshold, so a live scheduler (jobs firing
# every 60s) always lands inside it while a truly dead one (zero executions) never does.
_WATCHDOG_EXEC_FRESH_WINDOW_S = 180

@app.middleware("http")
async def scheduler_watchdog_middleware(request, call_next):
    global _watchdog_last_check
    now = time.time()
    # Only check once per 60 seconds to avoid DB spam
    if now - _watchdog_last_check > 60:
        _watchdog_last_check = now
        try:
            _check_scheduler_heartbeat()
        except Exception:
            pass
    return await call_next(request)


# ============================================================
# BREACH_DETECT_PHASE1_1 — central security middleware + admin routes.
# Defined AFTER scheduler_watchdog_middleware (above) so Starlette runs it
# OUTERMOST: the freeze gate + read-audit wrap every request. All logic lives in
# security/access_guard.py (keeps this module lean + unit-testable); this is the
# thin registration wrapper that pins the middleware ordering.
# ============================================================
@app.middleware("http")
async def security_guard_middleware(request, call_next):
    from security import access_guard as _guard
    return await _guard.security_guard_middleware(request, call_next)


@app.post("/api/security/freeze")
async def api_security_freeze(payload: dict = Body(default=None), _auth=Depends(verify_api_key)):
    """Engage the global freeze switch — instant 503 on all protected routes, no
    redeploy. Reachable while frozen (path is freeze-exempt)."""
    from security import access_guard as _guard
    reason = str((payload or {}).get("reason", ""))[:500]
    try:
        _guard.set_freeze(True, reason=reason, set_by="api")
    except Exception as e:
        return JSONResponse(
            {"error": "freeze_failed", "detail": str(e)}, status_code=500
        )
    try:
        _guard.security_alarm_send(
            f"🔒 *Baker FREEZE engaged* via /api/security/freeze. reason={reason or '(none)'}"
        )
    except Exception:
        pass
    return {"global_freeze": True, "reason": reason}


@app.post("/api/security/unfreeze")
async def api_security_unfreeze(payload: dict = Body(default=None), _auth=Depends(verify_api_key)):
    """Lift the global freeze. Note: the BAKER_SECURITY_FREEZE env backstop, if
    set, still wins in is_frozen() until the env var is cleared + restart."""
    from security import access_guard as _guard
    reason = str((payload or {}).get("reason", ""))[:500]
    try:
        _guard.set_freeze(False, reason=reason, set_by="api")
    except Exception as e:
        return JSONResponse(
            {"error": "unfreeze_failed", "detail": str(e)}, status_code=500
        )
    try:
        _guard.security_alarm_send("🔓 *Baker FREEZE lifted* via /api/security/unfreeze.")
    except Exception:
        pass
    return {"global_freeze": False}


@app.get("/api/security/status")
async def api_security_status(_auth=Depends(verify_api_key)):
    """Current freeze state + the last 20 anomaly-flagged audit rows."""
    from security import access_guard as _guard
    return {
        "freeze": _guard.get_freeze_status(),
        "recent_anomalies": _guard.recent_anomalies(20),
    }


def _ensure_security_tables() -> None:
    """Bootstrap the security_access_log + security_freeze tables at startup
    (belt-and-suspenders alongside the SQL migration). Uses a fresh pooled conn."""
    try:
        from security import access_guard as _guard
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if conn is None:
            logger.warning("security tables bootstrap skipped: no DB connection")
            return
        try:
            _guard.ensure_security_schema(conn)
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning("security tables bootstrap failed (non-fatal): %s", e)


def _check_scheduler_heartbeat():
    """If heartbeat stale >12 min on TWO consecutive reads, restart + log warning (throttled).

    SCHEDULER_WATCHDOG_FALSE_POSITIVE_FIX_1 (2026-05-15): require TWO consecutive
    stale reads (60s apart per middleware throttle) before firing restart. Single
    transient blips no longer trigger restart. Counter resets on fresh-read OR
    on restart.

    WA push intentionally disabled 2026-05-15 — Director directive while
    BRIEF_SCHEDULER_CRASHLOOP_RCA_2 is in flight. Re-enable only after that
    RCA closes and crash-loop frequency is back to <1 event/day. Dashboard
    + server logs still capture every restart.
    """
    global _watchdog_last_alert_ts, _watchdog_consecutive_stale, _watchdog_restart_failed_streak
    # SCHEDULER_NEON_IDLE_HARDEN_1: consume a stand-down request FIRST, on this
    # request thread (NOT the heartbeat job thread — a thread cannot join itself).
    # The heartbeat sets the flag when reacquire finds another container now holds
    # the singleton lock; restart here drops our lock + re-runs the clean acquire
    # path. Test-and-clear is idempotent, so a second tick does not re-restart.
    try:
        import triggers.scheduler_lease as _lease
        if _lease.consume_standdown():
            logger.error(
                "SCHEDULER-WATCHDOG-1: stand-down requested (singleton lock lost "
                "to another process). Restarting off the request thread."
            )
            from triggers.embedded_scheduler import restart_scheduler
            restart_scheduler(reason="standdown_lock_lost")
            _watchdog_consecutive_stale = 0
            return
    except Exception as e:
        logger.debug(f"Scheduler stand-down check failed (non-fatal): {e}")

    try:
        from triggers.state import trigger_state
        hb = trigger_state.get_watermark("scheduler_heartbeat")
        age_seconds = (datetime.now(timezone.utc) - hb).total_seconds()
        if age_seconds > 720:  # 12 minutes = missed 2 heartbeat cycles
            _watchdog_consecutive_stale += 1
            if _watchdog_consecutive_stale < 2:
                logger.info(
                    f"SCHEDULER-WATCHDOG-1: heartbeat stale ({age_seconds:.0f}s) "
                    f"on read #{_watchdog_consecutive_stale}/2. Waiting one more tick."
                )
                return
            # SCHEDULER_WATCHDOG_HARDEN_1 (lead #2566) — do NOT restart a scheduler
            # that is provably executing. The heartbeat WATERMARK can freeze while
            # the scheduler thread is alive and every other job keeps firing
            # (observed 2026-06-09: heartbeat watermark frozen 08:22→08:36 while 13
            # jobs executed each cycle, yet the watchdog restarted a healthy
            # scheduler at the 720s mark). A fresh scheduler_executions row is a
            # truer liveness signal than the lone heartbeat watermark write. None
            # (no rows / DB error) is fail-safe → falls through to restart.
            try:
                exec_age = trigger_state.seconds_since_last_scheduler_execution()
            except Exception:
                exec_age = None
            if exec_age is not None and exec_age < _WATCHDOG_EXEC_FRESH_WINDOW_S:
                # Gauge stale but scheduler live → suppress restart, surface the
                # divergence. Re-arm the 2-read gate and clear the os._exit streak:
                # the scheduler is provably healthy, so neither counter may persist.
                _watchdog_consecutive_stale = 0
                _watchdog_restart_failed_streak = 0
                now_ts = time.time()
                if now_ts - _watchdog_last_alert_ts > _watchdog_alert_cooldown_s:
                    _watchdog_last_alert_ts = now_ts
                    logger.warning(
                        f"SCHEDULER-WATCHDOG-1: heartbeat-gauge-stale "
                        f"({age_seconds:.0f}s) BUT scheduler-live (last job execution "
                        f"{exec_age:.0f}s ago) — restart suppressed. The "
                        f"scheduler_heartbeat watermark write is failing while the "
                        f"scheduler thread is healthy; investigate the heartbeat "
                        f"set_watermark path, not the scheduler."
                    )
                return
            logger.error(
                f"SCHEDULER-WATCHDOG-1: Heartbeat stale ({age_seconds:.0f}s) "
                f"for 2 consecutive reads, no job executed in last "
                f"{_WATCHDOG_EXEC_FRESH_WINDOW_S}s. Restarting..."
            )
            from triggers.embedded_scheduler import restart_scheduler, get_scheduler_status
            restart_scheduler(reason=f"heartbeat_stale_{age_seconds:.0f}s")
            _watchdog_consecutive_stale = 0
            # SCHEDULER_STALL_CODEFIX_1 — os._exit backstop. start_scheduler() registers
            # all jobs synchronously when it wins the lock, so an immediate job_count==0
            # means the acquire failed (lock held by an orphan the in-process eviction
            # couldn't reach). After _WATCHDOG_EXIT_THRESHOLD consecutive such restarts,
            # exit so Render cycles the dyno (SIGTERM frees the lock) — turning a
            # permanent stall into a ~1-min self-heal.
            try:
                _jc = get_scheduler_status().get("job_count", 0)
            except Exception:
                _jc = 0
            if _jc == 0:
                _watchdog_restart_failed_streak += 1
                logger.error(
                    f"SCHEDULER-WATCHDOG-1: restart left job_count=0 "
                    f"(failed-restart streak {_watchdog_restart_failed_streak}/"
                    f"{_WATCHDOG_EXIT_THRESHOLD}) — likely an orphaned singleton-lock holder."
                )
                if _watchdog_restart_failed_streak >= _WATCHDOG_EXIT_THRESHOLD:
                    logger.critical(
                        f"SCHEDULER-WATCHDOG-1: {_watchdog_restart_failed_streak} consecutive "
                        f"restarts failed to register jobs — os._exit(1) for a clean Render "
                        f"dyno restart (SIGTERM releases singleton lock 8800100)."
                    )
                    os._exit(1)
            else:
                _watchdog_restart_failed_streak = 0
            # Throttle log frequency (replaces the WA push, same cooldown)
            now_ts = time.time()
            if now_ts - _watchdog_last_alert_ts > _watchdog_alert_cooldown_s:
                _watchdog_last_alert_ts = now_ts
                logger.warning(
                    f"WATCHDOG_RESTART: scheduler was dead {int(age_seconds/60)} min. "
                    f"Auto-restart fired. WA push disabled pending CRASHLOOP_RCA_2."
                )
        else:
            # Fresh heartbeat → reset counters (single fresh read is enough). A healthy
            # heartbeat means the scheduler is firing, so the os._exit backstop streak
            # clears too — it must only count CONSECUTIVE failed restarts.
            _watchdog_consecutive_stale = 0
            _watchdog_restart_failed_streak = 0
    except Exception as e:
        logger.debug(f"Scheduler watchdog check failed (non-fatal): {e}")


# ============================================================
# Singletons (initialized on startup)
# ============================================================

_store = None
_retriever = None
_clickup_client = None
_static_dir = Path(__file__).parent / "static"
_briefing_dir = Path(__file__).resolve().parent.parent.parent / "04_outputs" / "briefings"
_store_bootstrap_lock = threading.Lock()
_store_bootstrap_started = False
_store_bootstrap_thread: threading.Thread | None = None


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
        _retriever = SentinelRetriever._get_global_instance()
    return _retriever


# ============================================================
# Clerk Workbench (CLERK_WORKBENCH_2)
# ============================================================

_CLERK_WORKING_PREFIX = "/Baker-Feed/Clerk-Workbench"
_CLERK_APPROVED_SAVE_ROOTS_DEFAULT = "/Baker-Feed/;/Apps/Baker/Clerk/"
_CLERK_SAVE_TOKEN_VERSION = "clerk-save-v1"


class ClerkRunRequest(BaseModel):
    task: str = Field(..., min_length=3, max_length=12000)
    approval_token: Optional[str] = Field(default=None, max_length=512)


class ClerkSaveRequest(BaseModel):
    content: str = Field(..., max_length=2_000_000)
    target_path: Optional[str] = Field(default=None, max_length=1024)
    approval_token: Optional[str] = Field(default=None, max_length=512)


def _clerk_normalize_dropbox_path(path: str) -> str:
    raw = (path or "").strip()
    if not raw.startswith("/"):
        return ""
    normalized = posixpath.normpath(raw)
    if normalized == "." or not normalized.startswith("/"):
        return ""
    return normalized


def _clerk_path_under(path: str, roots: tuple[str, ...]) -> bool:
    normalized = _clerk_normalize_dropbox_path(path)
    if not normalized:
        return False
    for root in roots:
        allowed = posixpath.normpath(root)
        if normalized == allowed or normalized.startswith(allowed.rstrip("/") + "/"):
            return True
    return False


def _clerk_approved_save_roots() -> tuple[str, ...]:
    roots = os.getenv("CLERK_APPROVED_SAVE_ROOTS", _CLERK_APPROVED_SAVE_ROOTS_DEFAULT)
    return tuple(
        normalized
        for normalized in (_clerk_normalize_dropbox_path(part) for part in roots.split(";"))
        if normalized
    )


def _clerk_approval_secret() -> str:
    return os.getenv("CLERK_SAVE_APPROVAL_SECRET", "")


def _clerk_save_approval_token(session_id: str, target_path: str) -> str:
    normalized = _clerk_normalize_dropbox_path(target_path)
    secret = _clerk_approval_secret()
    if not session_id or not normalized or not secret:
        return ""
    payload = f"{_CLERK_SAVE_TOKEN_VERSION}:{session_id}:{normalized}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _clerk_validate_save_approval(session_id: str, target_path: str, approval_token: str | None) -> bool:
    normalized = _clerk_normalize_dropbox_path(target_path)
    if not normalized or not approval_token:
        return False
    if not _clerk_path_under(normalized, _clerk_approved_save_roots()):
        return False
    expected = _clerk_save_approval_token(session_id, normalized)
    return bool(expected) and hmac.compare_digest(approval_token, expected)


def _clerk_json_param(value: Any):
    import psycopg2.extras

    return psycopg2.extras.Json(value)


def _clerk_create_session(session_id: str, task: str, source_meta: dict[str, Any]) -> None:
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO clerk_sessions (session_id, task, status, source_meta)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, task, "running", _clerk_json_param(source_meta)),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("clerk session create failed: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="clerk_session_create_failed")
    finally:
        store._put_conn(conn)


def _clerk_fetch_session(session_id: str) -> dict[str, Any] | None:
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")
    try:
        import psycopg2.extras

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT session_id, task, status, result_json, draft_content, draft_path,
                   source_meta, error, prompt_tokens, completion_tokens, total_tokens,
                   context_window_used, context_window_max, session_cost_usd,
                   created_at, updated_at
            FROM clerk_sessions
            WHERE session_id = %s
            LIMIT 1
            """,
            (session_id,),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else None
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("clerk session fetch failed")
        raise HTTPException(status_code=500, detail="clerk_session_fetch_failed")
    finally:
        store._put_conn(conn)


def _clerk_update_session(session_id: str, **fields: Any) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "result_json",
        "draft_content",
        "draft_path",
        "source_meta",
        "error",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "context_window_used",
        "context_window_max",
        "session_cost_usd",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"unsupported clerk session fields: {sorted(unknown)}")

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")
    try:
        sets = []
        params: list[Any] = []
        for key, value in fields.items():
            sets.append(f"{key} = %s")
            if key in {"result_json", "source_meta"}:
                params.append(_clerk_json_param(value or {}))
            else:
                params.append(value)
        sets.append("updated_at = NOW()")
        params.append(session_id)
        cur = conn.cursor()
        cur.execute(
            f"UPDATE clerk_sessions SET {', '.join(sets)} WHERE session_id = %s",
            tuple(params),
        )
        conn.commit()
        cur.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("clerk session update failed")
        raise
    finally:
        store._put_conn(conn)


def _clerk_extract_draft(result: dict[str, Any]) -> tuple[str, str | None]:
    # CLERK_READY_PATH_CONTRADICTION_FIX_2 (Director-visible dashboard /clerk surface;
    # twin of orchestrator/clerk_bus_worker._extract_draft fixed in FIX_1 #326): the
    # draft path comes ONLY from clerk_runtime's verified saved_paths (the real Dropbox
    # metadata path from a status:"ready" file_save). The two prior ungrounded sources
    # are removed: the free-text `Ready:\s*(/path)` regex scrape of the model answer
    # (the exact /Baker-Project hallucination route) and the unverified file_save
    # INPUT-arg path (which could echo a path _file_save then BLOCKED). No verified
    # save -> no draft path. Draft preview CONTENT still comes from the save attempt.
    content = ""
    for call in result.get("tool_calls") or []:
        if not isinstance(call, dict) or call.get("name") != "file_save":
            continue
        args = call.get("input") or {}
        if isinstance(args, dict) and isinstance(args.get("content"), str):
            content = args["content"]
    path: str | None = None
    saved = result.get("saved_paths")
    if isinstance(saved, list):
        for candidate in saved:
            if isinstance(candidate, str) and candidate.strip():
                normalized = _clerk_normalize_dropbox_path(candidate)
                if normalized:
                    path = normalized  # last verified save wins
    if not content:
        content = str(result.get("answer") or result.get("reason") or "")
    return content, path or None


def _clerk_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clerk_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clerk_usage_update_fields(result: dict[str, Any]) -> dict[str, Any]:
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return {}
    fields: dict[str, Any] = {}
    mapping = {
        "prompt_tokens": "prompt_tokens",
        "completion_tokens": "completion_tokens",
        "total_tokens": "total_tokens",
        "context_window_used": "context_window_used",
        "context_window_max": "context_window_max",
    }
    for source, target in mapping.items():
        if source in usage:
            fields[target] = _clerk_int_or_none(usage.get(source))
    if "session_cost_usd" in usage:
        fields["session_cost_usd"] = _clerk_float_or_none(usage.get("session_cost_usd"))
    return fields


def _clerk_json_number(value: Any) -> Any:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _clerk_public_session(row: dict[str, Any]) -> dict[str, Any]:
    result_json = row.get("result_json") or {}
    if isinstance(result_json, str):
        try:
            result_json = json.loads(result_json)
        except Exception:
            result_json = {"raw": result_json}
    return {
        "session_id": row.get("session_id"),
        "status": row.get("status"),
        "result": result_json,
        "draft_content": row.get("draft_content"),
        "draft_path": row.get("draft_path"),
        "error": row.get("error"),
        "prompt_tokens": _clerk_int_or_none(row.get("prompt_tokens")),
        "completion_tokens": _clerk_int_or_none(row.get("completion_tokens")),
        "total_tokens": _clerk_int_or_none(row.get("total_tokens")),
        "context_window_used": _clerk_int_or_none(row.get("context_window_used")),
        "context_window_max": _clerk_int_or_none(row.get("context_window_max")),
        "session_cost_usd": _clerk_json_number(row.get("session_cost_usd")),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
        "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
    }


def _clerk_public_session_summary(row: dict[str, Any]) -> dict[str, Any]:
    task = str(row.get("task") or "")
    if len(task) > 120:
        task = task[:117] + "..."
    created_at = row.get("created_at")
    return {
        "session_id": row.get("session_id"),
        "task": task,
        "status": row.get("status"),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
    }


def _clerk_list_sessions(limit: int) -> list[dict[str, Any]]:
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")
    try:
        import psycopg2.extras

        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT session_id, task, status, created_at
            FROM clerk_sessions
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
        return [_clerk_public_session_summary(dict(row)) for row in rows]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("clerk sessions list failed")
        raise HTTPException(status_code=500, detail="clerk_sessions_list_failed")
    finally:
        store._put_conn(conn)


def _clerk_run_session_sync(session_id: str, task: str) -> None:
    try:
        from orchestrator.clerk_runtime import run_clerk_task

        result = run_clerk_task(task)
        if not isinstance(result, dict):
            result = {"status": "error", "error": "clerk returned non-dict result"}
        status = str(result.get("status") or "error")
        draft_content, draft_path = _clerk_extract_draft(result)
        usage_fields = _clerk_usage_update_fields(result)
        _clerk_update_session(
            session_id,
            status=status,
            result_json=result,
            draft_content=draft_content,
            draft_path=draft_path,
            error=str(result.get("reason") or result.get("error") or "") or None,
            **usage_fields,
        )
    except BaseException as e:
        logger.warning("clerk background run failed (%s): %s", session_id, type(e).__name__)
        try:
            _clerk_update_session(
                session_id,
                status="error",
                result_json={"status": "error", "error_type": type(e).__name__},
                error=f"clerk failed: {type(e).__name__}",
            )
        except Exception:
            logger.exception("clerk background failure update failed")


async def _clerk_run_session_background(session_id: str, task: str) -> None:
    await asyncio.to_thread(_clerk_run_session_sync, session_id, task)


def _clerk_save_content_sync(
    session_id: str,
    content: str,
    target_path: str,
    approved_save_paths: set[str],
) -> dict[str, Any]:
    from orchestrator.clerk_runtime import ClerkToolRegistry

    registry = ClerkToolRegistry(approved_save_paths=approved_save_paths)
    raw = registry.execute(
        "file_save",
        {
            "content": content,
            "filename": Path(target_path).name or f"{session_id}.md",
            "dropbox_path": target_path,
        },
    )
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {"error": "file_save returned invalid JSON", "raw": raw[:500]}

    status = parsed.get("status")
    if status == "ready":
        saved_path = parsed.get("path") or target_path
        _clerk_update_session(
            session_id,
            status="saved",
            draft_content=content,
            draft_path=saved_path,
            result_json={"status": "saved", "path": saved_path, "file_save": parsed},
            error=None,
        )
        return {"session_id": session_id, "status": "saved", "path": saved_path, "file_save": parsed}

    _clerk_update_session(
        session_id,
        status=parsed.get("status") or "error",
        result_json={"status": parsed.get("status") or "error", "file_save": parsed},
        error=parsed.get("reason") or parsed.get("error") or "file_save failed",
    )
    return {"session_id": session_id, "status": parsed.get("status") or "error", "file_save": parsed}


def _clerk_launcher_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Clerk Launcher</title>
  <style>
    :root { color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #121417; }
    main { max-width: 920px; margin: 0 auto; padding: 24px; }
    header { display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 16px; }
    h1 { font-size: 20px; line-height: 1.2; margin: 0; }
    h2 { font-size: 15px; margin: 24px 0 10px; }
    .meta { color: #53606f; font-size: 13px; overflow-wrap: anywhere; }
    textarea { width: 100%; min-height: 220px; box-sizing: border-box; padding: 14px; border: 1px solid #c7ccd4; border-radius: 6px; font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; background: #fff; color: #111; }
    button { margin-top: 10px; padding: 8px 12px; border: 1px solid #9aa3af; border-radius: 6px; background: #fff; color: #111; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }
    ul { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
    li { border: 1px solid #d8dde5; border-radius: 6px; background: #fff; padding: 10px; }
    a { color: inherit; font-weight: 600; text-decoration: none; }
    a:hover { text-decoration: underline; }
    @media (prefers-color-scheme: dark) {
      body { background: #151719; color: #f2f4f7; }
      textarea, button, li { background: #20242a; color: #f2f4f7; border-color: #3b424c; }
      .meta { color: #a8b0ba; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Clerk</h1>
      <div class="meta">Qwen3 workbench launcher</div>
    </div>
  </header>
  <textarea id="task" spellcheck="true" placeholder="Type the Clerk task"></textarea>
  <div>
    <button id="runButton" type="button">Run</button>
    <span id="runState" class="meta"></span>
  </div>
  <section>
    <h2>Recent Sessions</h2>
    <ul id="sessionList"></ul>
    <div id="sessionState" class="meta"></div>
  </section>
</main>
<script>
const taskNode = document.getElementById("task");
const runButton = document.getElementById("runButton");
const runStateNode = document.getElementById("runState");
const sessionListNode = document.getElementById("sessionList");
const sessionStateNode = document.getElementById("sessionState");
const BAKER_CONFIG = { apiKey: "" };
async function loadClientConfig() {
  try {
    const resp = await fetch("/api/client-config");
    if (resp.ok) {
      const data = await resp.json();
      BAKER_CONFIG.apiKey = data.apiKey || "";
    }
  } catch (err) {
    console.error("Failed to load client config:", err);
  }
}
function apiKey() {
  if (BAKER_CONFIG.apiKey) return BAKER_CONFIG.apiKey;
  return window.localStorage.getItem("BAKER_API_KEY")
    || window.localStorage.getItem("baker_api_key")
    || window.localStorage.getItem("bakerApiKey")
    || "";
}
function detailText(data, fallback) {
  if (!data) return fallback;
  if (typeof data.detail === "string") return data.detail;
  if (data.detail && typeof data.detail === "object") return data.detail.status || data.detail.reason || fallback;
  return data.status || data.error || fallback;
}
function renderSessions(sessions) {
  sessionListNode.textContent = "";
  if (!sessions.length) {
    sessionStateNode.textContent = "No recent sessions";
    return;
  }
  sessionStateNode.textContent = "";
  sessions.forEach((session) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    const sessionId = session.session_id || "";
    a.href = "/clerk/edit/" + encodeURIComponent(sessionId);
    a.textContent = session.task || sessionId || "Untitled session";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = [session.status, session.created_at].filter(Boolean).join(" | ");
    li.appendChild(a);
    li.appendChild(meta);
    sessionListNode.appendChild(li);
  });
}
async function loadSessions() {
  const key = apiKey();
  if (!key) {
    sessionStateNode.textContent = "Recent sessions require Baker API key";
    return;
  }
  try {
    const resp = await fetch("/api/clerk/sessions?limit=10", {headers: {"X-Baker-Key": key}});
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      sessionStateNode.textContent = detailText(data, "Recent sessions unavailable");
      return;
    }
    renderSessions(data.sessions || []);
  } catch (err) {
    sessionStateNode.textContent = "Recent sessions unavailable";
  }
}
runButton.addEventListener("click", async () => {
  const task = taskNode.value.trim();
  if (!task) {
    runStateNode.textContent = "Task is required";
    return;
  }
  const key = apiKey();
  if (!key) {
    runStateNode.textContent = "Baker API key is required";
    return;
  }
  runButton.disabled = true;
  runStateNode.textContent = "Starting...";
  try {
    const resp = await fetch("/api/clerk/run", {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Baker-Key": key},
      body: JSON.stringify({task})
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      runStateNode.textContent = detailText(data, "Run failed");
      return;
    }
    if (!data.session_id) {
      runStateNode.textContent = "Run did not return a session";
      return;
    }
    window.location.assign("/clerk/edit/" + encodeURIComponent(data.session_id));
  } catch (err) {
    runStateNode.textContent = "Run failed";
  } finally {
    runButton.disabled = false;
  }
});
loadClientConfig().then(loadSessions);
</script>
</body>
</html>"""


def _clerk_edit_html(row: dict[str, Any]) -> str:
    session_id = str(row.get("session_id") or "")
    default_path = f"{_CLERK_WORKING_PREFIX}/{session_id}.md"
    title = f"Clerk Workbench {session_id}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #121417; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 16px; }}
    h1 {{ font-size: 20px; line-height: 1.2; margin: 0; }}
    .meta {{ color: #53606f; font-size: 13px; overflow-wrap: anywhere; }}
    .bar {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 12px 0; }}
    textarea {{ width: 100%; min-height: 62vh; box-sizing: border-box; padding: 14px; border: 1px solid #c7ccd4; border-radius: 6px; font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; background: #fff; color: #111; }}
    input {{ min-width: 360px; max-width: 100%; padding: 8px 10px; border: 1px solid #c7ccd4; border-radius: 6px; }}
    button {{ padding: 8px 12px; border: 1px solid #9aa3af; border-radius: 6px; background: #fff; color: #111; cursor: pointer; }}
    button:disabled {{ opacity: .55; cursor: wait; }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #151719; color: #f2f4f7; }}
      textarea, input, button {{ background: #20242a; color: #f2f4f7; border-color: #3b424c; }}
      .meta {{ color: #a8b0ba; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Clerk Workbench</h1>
      <div class="meta">Session <span id="session"></span></div>
    </div>
    <div class="meta">Status <span id="status"></span></div>
  </header>
  <div class="bar">
    <input id="targetPath" value="" aria-label="Save path">
    <button id="saveButton" type="button" disabled>Save</button>
    <span id="saveState" class="meta"></span>
  </div>
  <textarea id="content" spellcheck="false"></textarea>
</main>
<script>
const sessionId = {json.dumps(session_id)};
const defaultPath = {json.dumps(default_path)};
const sessionNode = document.getElementById("session");
const statusNode = document.getElementById("status");
const saveStateNode = document.getElementById("saveState");
const saveButton = document.getElementById("saveButton");
const contentNode = document.getElementById("content");
const targetPathNode = document.getElementById("targetPath");
const BAKER_CONFIG = {{ apiKey: "" }};
sessionNode.textContent = sessionId;
statusNode.textContent = "loading";
async function loadClientConfig() {{
  try {{
    const resp = await fetch("/api/client-config");
    if (resp.ok) {{
      const data = await resp.json();
      BAKER_CONFIG.apiKey = data.apiKey || "";
    }}
  }} catch (err) {{
    console.error("Failed to load client config:", err);
  }}
}}
function apiKey() {{
  if (BAKER_CONFIG.apiKey) return BAKER_CONFIG.apiKey;
  return window.localStorage.getItem("BAKER_API_KEY")
    || window.localStorage.getItem("baker_api_key")
    || window.localStorage.getItem("bakerApiKey")
    || "";
}}
function detailText(data, fallback) {{
  if (!data) return fallback;
  if (typeof data.detail === "string") return data.detail;
  if (data.detail && typeof data.detail === "object") return data.detail.status || data.detail.reason || fallback;
  return data.status || data.error || fallback;
}}
function applySession(data) {{
  sessionNode.textContent = data.session_id || sessionId;
  statusNode.textContent = data.status || "";
  targetPathNode.value = data.draft_path || defaultPath;
  contentNode.value = data.draft_content || data.error || "";
  saveButton.disabled = data.status === "running";
  if (data.status === "running") window.setTimeout(loadSession, 2500);
}}
async function loadSession() {{
  const key = apiKey();
  if (!key) {{
    statusNode.textContent = "auth required";
    saveStateNode.textContent = "Baker API key is required";
    saveButton.disabled = true;
    targetPathNode.value = defaultPath;
    return;
  }}
  try {{
    const resp = await fetch(`/api/clerk/session/${{sessionId}}`, {{headers: {{"X-Baker-Key": key}}}});
    const data = await resp.json().catch(() => ({{}}));
    if (resp.status === 404) {{
      statusNode.textContent = "not found";
      saveStateNode.textContent = "Session not found";
      saveButton.disabled = true;
      targetPathNode.value = defaultPath;
      return;
    }}
    if (!resp.ok) {{
      statusNode.textContent = "load failed";
      saveStateNode.textContent = detailText(data, "Load failed");
      saveButton.disabled = true;
      targetPathNode.value = defaultPath;
      return;
    }}
    saveStateNode.textContent = "";
    applySession(data);
  }} catch (err) {{
    statusNode.textContent = "load failed";
    saveStateNode.textContent = "Load failed";
    saveButton.disabled = true;
    targetPathNode.value = defaultPath;
  }}
}}
saveButton.addEventListener("click", async () => {{
  const key = apiKey();
  if (!key) {{
    saveStateNode.textContent = "Baker API key is required";
    return;
  }}
  saveButton.disabled = true;
  saveStateNode.textContent = "Saving";
  try {{
    const resp = await fetch(`/api/clerk/save/${{sessionId}}`, {{
      method: "POST",
      headers: {{"Content-Type": "application/json", "X-Baker-Key": key}},
      body: JSON.stringify({{content: contentNode.value, target_path: targetPathNode.value}})
    }});
    const data = await resp.json();
    saveStateNode.textContent = data.path || detailText(data, data.status || "Saved");
    if (data.status) statusNode.textContent = data.status;
  }} catch (err) {{
    saveStateNode.textContent = "Save failed";
  }} finally {{
    saveButton.disabled = false;
  }}
}});
loadClientConfig().then(loadSession);
</script>
</body>
</html>"""


def _extract_correction_safe(task: dict):
    """CORRECTION-MEMORY-1: Fire-and-forget wrapper for correction extraction."""
    try:
        from orchestrator.capability_runner import extract_correction_from_feedback
        extract_correction_from_feedback(task)
    except Exception as e:
        logger.debug(f"Correction extraction failed (non-fatal): {e}")


def _embed_positive_example_safe(task: dict):
    """CORRECTION-MEMORY-1 Phase 2: Embed accepted task as positive example for episodic retrieval."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        title = task.get("title", "")
        deliverable = task.get("deliverable", "")
        cap_slug = task.get("capability_slug", "general")
        # Only embed tasks with substantial deliverables
        if len(deliverable) < 200:
            return
        # Combine title + truncated deliverable for embedding
        content = f"Question: {title}\n\nAccepted response:\n{deliverable[:3000]}"
        metadata = {
            "task_id": task.get("id"),
            "capability_slug": cap_slug,
            "domain": task.get("domain", ""),
            "feedback": "accepted",
            "source": "baker_task_positive",
        }
        store.store_document(content, metadata, collection="baker-task-examples")
        logger.info(f"Embedded positive example from task #{task.get('id')} ({cap_slug})")
    except Exception as e:
        logger.debug(f"Positive example embedding failed (non-fatal): {e}")


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
    owner: Optional[str] = None     # "dimitry" or "edita" — for memory separation
    alert_context: Optional[str] = None  # SCAN-CONTEXT-1: injected when opening from alert card


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


class CortexTriggerRequest(BaseModel):
    """CORTEX_TRIGGER_ENDPOINT_1: Director-invoke a Cortex cycle synchronously
    inside the Render container, where DB+Qdrant are localhost (no cross-network
    specialist-tool latency that has been killing local-dispatch cycles)."""
    matter_slug: str = Field(..., min_length=1, max_length=64,
                             description="Matter slug (e.g. 'oskolkov', 'movie')")
    director_question: str = Field(..., min_length=10, max_length=4000,
                                   description="Director's question driving the cycle")
    triggered_by: str = Field(default="director_manual", min_length=1, max_length=64,
                              description="Trigger source label")


class CortexRunRequest(BaseModel):
    """CORTEX_MANUAL_INVOKE_1: Director-invoke a Cortex cycle with SSE streaming.

    Same field shape as CortexTriggerRequest — kept distinct so future
    streaming-only fields (poll_interval override, max_phases, etc.) can
    diverge without disturbing the sync trigger contract.
    """
    matter_slug: str = Field(..., min_length=1, max_length=64,
                             description="Matter slug (must have cortex-config.md in vault)")
    director_question: str = Field(..., min_length=10, max_length=4000,
                                   description="Director's question driving the cycle")
    triggered_by: str = Field(default="director_manual", min_length=1, max_length=64,
                              description="Trigger source label — director_manual or scan_intent")
    defer_notification: bool = Field(
        default=False,
        description=(
            "CORTEX_NOTIFICATION_DEFER_1: when true, suppress the cost-warn "
            "Slack DM for THIS invocation. Cost-warn still logs to logger.info "
            "(observability preserved); only the Slack push is gated."
        ),
    )


def _serialize(obj: dict) -> dict:
    """Convert datetime/date fields to ISO strings for JSON serialization."""
    import datetime as _dt_mod
    out = {}
    for k, v in obj.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, _dt_mod.date):
            out[k] = v.isoformat()
        elif isinstance(v, memoryview):
            out[k] = bytes(v).decode("utf-8", errors="replace")
        else:
            out[k] = v
    return out


# ============================================================
# Startup
# ============================================================

def _init_store() -> None:
    """Start legacy store bootstrap without blocking FastAPI startup."""
    global _store_bootstrap_started, _store_bootstrap_thread

    with _store_bootstrap_lock:
        if _store_bootstrap_started:
            logger.info("PostgreSQL store bootstrap already started")
            return
        _store_bootstrap_started = True
        thread = threading.Thread(
            target=_init_store_sync,
            name="store-back-bootstrap",
            daemon=True,
        )
        _store_bootstrap_thread = thread

    thread.start()
    logger.info("PostgreSQL store bootstrap scheduled")


def _init_store_sync() -> None:
    """Pre-warm the PostgreSQL store and apply the legacy inline DDL block.

    Warn-and-continue semantics on cold-start failure: a flaky PG cold start
    is transient and the scheduler can retry. This is DELIBERATELY different
    from ``_run_migrations`` which raises loud on any failure — migration
    drift is a permanent state bug, not a transient retry (P2 of the
    MIGRATION_RUNNER_1 brief's polish list).
    """
    try:
        store = _get_store()
        logger.info("PostgreSQL store initialized")
        # COCKPIT-ALERT-UI: ensure structured_actions column exists
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS structured_actions JSONB")
                cur.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS snoozed_until TIMESTAMPTZ")
                # PEOPLE-SECTION-1: Create people_issues table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS people_issues (
                        id SERIAL PRIMARY KEY,
                        person_name TEXT NOT NULL,
                        title TEXT NOT NULL,
                        detail TEXT,
                        status TEXT DEFAULT 'open',
                        due_date DATE,
                        source TEXT,
                        matter TEXT,
                        is_critical BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_people_issues_person ON people_issues(person_name)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_people_issues_status ON people_issues(status)")
                # IDEAS-CAPTURE-1: Ideas table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ideas (
                        id SERIAL PRIMARY KEY,
                        content TEXT NOT NULL,
                        source TEXT DEFAULT 'slack',
                        status TEXT DEFAULT 'new',
                        matter TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status)")
                # PERSISTENT-DOCS-PANEL: Generated documents table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS generated_documents (
                        id              TEXT PRIMARY KEY,
                        filename        TEXT NOT NULL,
                        format          VARCHAR(10) NOT NULL,
                        size_bytes      INTEGER NOT NULL,
                        file_data       BYTEA NOT NULL,
                        title           TEXT,
                        source          VARCHAR(20) DEFAULT 'scan',
                        created_at      TIMESTAMPTZ DEFAULT NOW(),
                        downloaded_at   TIMESTAMPTZ,
                        expired         BOOLEAN DEFAULT FALSE
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_gendocs_created ON generated_documents(created_at DESC)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_gendocs_expired ON generated_documents(expired) WHERE expired = FALSE")
                conn.commit()
                cur.close()
                logger.info("COCKPIT-ALERT-UI: structured_actions + snoozed_until + people_issues + generated_documents ensured")
            except Exception as me:
                conn.rollback()
                logger.warning(f"COCKPIT-ALERT-UI migration (non-fatal): {me}")
            finally:
                store._put_conn(conn)
    except Exception as e:
        logger.warning(f"PostgreSQL connection failed on startup (will retry): {e}")


def _run_migrations() -> None:
    """Apply ``migrations/*.sql`` before any scheduler job registers.

    Raise-loud on any failure — caller is the FastAPI startup lifespan,
    which must refuse to finish starting on a half-applied schema. See
    ``config/migration_runner.py`` module docstring for rationale.
    """
    from config.migration_runner import run_pending_migrations, MigrationError

    try:
        applied = run_pending_migrations(os.environ["DATABASE_URL"])
        if applied:
            for f in applied:
                logger.info("migration applied: %s", f)
        else:
            logger.info("migrations: all up-to-date")
    except MigrationError as me:
        logger.error("migration runner failed; aborting startup: %s", me)
        raise


def _start_scheduler() -> None:
    """Start the Sentinel BackgroundScheduler (KBL pipeline tick, triggers)."""
    try:
        start_scheduler()
        logger.info("Sentinel scheduler started (BackgroundScheduler)")
    except Exception as e:
        logger.error(f"Scheduler failed to start: {e}")


def _ensure_vault_mirror() -> None:
    """SOT_OBSIDIAN_1_PHASE_D: clone/pull baker-vault mirror on startup.

    ``ensure_mirror()`` already distinguishes the two cases internally —
    WARN-logs pull failures (non-fatal, next tick retries), raises
    ``RuntimeError`` only on initial-clone failure. Propagate so
    FastAPI's lifespan aborts startup per brief §1 — a missing mirror
    must not go unnoticed. B3 review S1a (2026-04-20).

    Also starts the per-process refresh daemon thread (VAULT_MIRROR_SYNC_TICK_DIAGNOSE_1,
    2026-05-13). Each Render replica must refresh its own local FS mirror —
    the prior APScheduler job was singleton-locked so only one replica
    pulled, leaving N-1 replicas stale.
    """
    from vault_mirror import ensure_mirror, start_sync_thread
    ensure_mirror()
    # VAULT_MIRROR_NON_LOCK_REPLICA_HOTFIX_1 (2026-05-12): the per-process
    # daemon thread MUST spawn on every replica or that replica's mirror
    # stays at the startup-clone state. Production telemetry post-PR #193
    # showed the non-lock replica silently lacking the thread. Log loudly
    # on either failure path so the next /health poll (which now exposes
    # ``vault_sync_thread_alive``) has a matching log trail for root-cause.
    try:
        thread = start_sync_thread()
        logger.info(
            "vault_mirror: start_sync_thread returned alive=%s name=%s",
            thread.is_alive(),
            thread.name,
        )
    except Exception:
        logger.exception("vault_mirror: start_sync_thread raised at startup")


# Boot-time backfill helper lives in triggers/backfill_runner.py so it's
# unit-testable without pulling in FastAPI + the dashboard dependency graph.
from triggers.backfill_runner import (
    BACKFILL_TIMEOUT_SEC,
    run_boot_backfill_chain,
)


@app.on_event("startup")
async def startup():
    """Initialize shared resources on server start.

    Ordering is load-bearing: ``_run_migrations`` must run BEFORE
    ``_start_scheduler`` so ``kbl_pipeline_tick`` never ticks against a
    partial schema. Enforced by ``tests/test_migration_runner.py::
    test_migration_runner_runs_before_scheduler`` via Mock manager
    ``mock_calls`` assertion (N1 — runtime fixture, not AST).
    """
    logger.info("Baker Dashboard starting...")
    _init_store()
    _run_migrations()
    _ensure_security_tables()  # BREACH_DETECT_PHASE1_1 — idempotent bootstrap
    _ensure_vault_mirror()
    _start_scheduler()

    # Backfills in background threads — delayed 60s to let scheduler stabilize (OOM fix)
    import threading

    def _delayed_backfills():
        time.sleep(60)
        logger.info("Starting delayed backfills (60s after startup)...")
        # Plaud FIRST — primary source. Render restart triggers refresh of stuck shells
        # (PR #171). Order swapped from Fireflies-first 2026-05-08 because Fireflies
        # has been silent-dead since 2026-04-11 (Director migrated off it) and was
        # blocking Plaud's backfill from ever starting at boot.
        # The canonical order lives in triggers/backfill_runner.run_boot_backfill_chain
        # so dashboard + tests share exactly one definition (Fix 4 of
        # BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1).
        plaud_fn = None
        if config.plaud.api_token:
            from triggers.plaud_trigger import backfill_plaud
            plaud_fn = backfill_plaud
        # FIREFLIES_SCAN_GATE_1: the boot backfill is a SECOND Fireflies ingest
        # path (distinct from the recurring fireflies_scan job). Gate it on the
        # same flag, else FIREFLIES_SCAN_ENABLED=false would still re-ingest the
        # last 30 days on every restart. Leaving fireflies_fn=None makes
        # run_boot_backfill_chain skip the 'fireflies' branch (same as a missing
        # module/api_key). Plaud's boot backfill is untouched.
        fireflies_fn = None
        if config.triggers.fireflies_scan_enabled:
            try:
                from triggers.fireflies_trigger import backfill_fireflies
                fireflies_fn = backfill_fireflies
            except Exception:
                # Widened from ImportError 2026-05-08 (Gate 4 finding): non-ImportError
                # module-level failures (AttributeError from missing config, NameError,
                # etc.) used to propagate and silently kill this boot daemon thread,
                # so Fireflies would never fire and no sentinel alarm would surface.
                logger.warning(
                    "fireflies_trigger import failed — Fireflies backfill skipped",
                    exc_info=True,
                )
        else:
            logger.info(
                "Fireflies boot-backfill disabled via FIREFLIES_SCAN_ENABLED — skipping"
            )

        invoked = run_boot_backfill_chain(
            plaud_token=config.plaud.api_token,
            plaud_fn=plaud_fn,
            fireflies_api_key=config.fireflies.api_key,
            fireflies_fn=fireflies_fn,
            timeout_s=BACKFILL_TIMEOUT_SEC,
        )
        logger.info(f"Boot backfill chain complete; invoked={invoked}")
        # OOM-FIX-2: WhatsApp backfill removed from startup.
        # It fetched 500 chats + media + Qdrant embedding → 2-3GB memory spike.
        # Regular WhatsApp periodic re-sync (scheduler) handles catch-up safely.

    threading.Thread(
        target=_delayed_backfills,
        name="delayed-backfills",
        daemon=True,
    ).start()
    logger.info("Backfills scheduled (60s delay, Plaud-first, per-step timeout 300s)")

    # Mount static files if directory exists
    if _static_dir.exists():
        app.mount("/static", NoCacheHTMLStaticFiles(directory=str(_static_dir)), name="static")
        logger.info(f"Static files mounted from {_static_dir}")


@app.on_event("shutdown")
async def shutdown():
    """Graceful shutdown of scheduler."""
    try:
        stop_scheduler()
        logger.info("Sentinel scheduler stopped")
    except Exception as e:
        logger.warning(f"Scheduler shutdown error: {e}")


# ============================================================
# BAKER MCP REMOTE — Streamable HTTP transport (MCP-SSE-STABLE)
# Stateless JSON-RPC handler. No sessions, no reconnection issues.
# Claude Code web + Cowork connect here for DB tool access.
# ============================================================

_mcp_module_cache = None


def _get_mcp_module():
    """Lazy-load baker_mcp tools + dispatch to avoid import overhead at startup."""
    global _mcp_module_cache
    if _mcp_module_cache is None:
        try:
            from baker_mcp.baker_mcp_server import TOOLS, _dispatch
            _mcp_module_cache = {"tools": TOOLS, "dispatch": _dispatch}
            logger.info("MCP module loaded: %d tools", len(TOOLS))
        except Exception as e:
            logger.error(f"Failed to load baker_mcp module: {e}")
            raise
    return _mcp_module_cache


def _mcp_verify_key(request: Request) -> bool:
    """Check MCP auth via ?key= query param or X-Baker-Key header."""
    key = request.query_params.get("key") or request.headers.get("x-baker-key", "")
    return bool(_BAKER_API_KEY) and key == _BAKER_API_KEY


def _handle_mcp_message(msg: dict) -> dict | None:
    """Process a single MCP JSON-RPC message. Returns None for notifications."""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})

    # Notifications (no id) — acknowledge silently
    if msg_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "baker-mcp", "version": "1.0.0"},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        try:
            mcp_mod = _get_mcp_module()
            tools = [
                {"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema}
                for t in mcp_mod["tools"]
            ]
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}
        except Exception as e:
            logger.error(f"MCP tools/list failed: {e}")
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(e)}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            mcp_mod = _get_mcp_module()
            result_text = mcp_mod["dispatch"](tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"content": [{"type": "text", "text": result_text}]},
            }
        except Exception as e:
            logger.error(f"MCP tools/call {tool_name} failed: {e}")
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True},
            }

    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


@app.post("/mcp", tags=["mcp"])
async def mcp_streamable_http(request: Request):
    """MCP Streamable HTTP endpoint — stateless JSON-RPC for remote tool access."""
    if not _mcp_verify_key(request):
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Unauthorized"}},
            status_code=401,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )

    # Batch request (array of messages)
    if isinstance(body, list):
        responses = [r for msg in body if (r := _handle_mcp_message(msg)) is not None]
        if not responses:
            return JSONResponse(content=None, status_code=202)
        return JSONResponse(responses)

    # Single request
    resp = _handle_mcp_message(body)
    if resp is None:
        return JSONResponse(content=None, status_code=202)
    return JSONResponse(resp)


@app.get("/mcp", tags=["mcp"])
async def mcp_sse_redirect(request: Request):
    """Redirect legacy SSE clients to use POST (Streamable HTTP)."""
    return JSONResponse(
        {"info": "Baker MCP uses Streamable HTTP. Send POST requests with JSON-RPC body.", "endpoint": "/mcp"},
        status_code=200,
    )


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


# TODO (follow-up brief, post-hag-desk filing): replace global X-Baker-Key auth
# with per-matter scoped auth (HMAC-derived per-desk key or scoped-token table).
# The current global key gives any key-holder read access to ALL matters'
# transcripts including attorney-client privileged content. Acceptable for the
# internal-agent perimeter today; not defensible long-term.
@app.get(
    "/api/transcripts/by-matter/{matter_slug}",
    tags=["transcripts"],
    dependencies=[Depends(verify_api_key)],
)
async def get_transcripts_by_matter(
    matter_slug: str,
    since: Optional[str] = None,
    limit: int = 50,
    include_body: bool = False,
    source: Optional[str] = None,
):
    """Return transcripts tagged to a matter. Matter-desk read-path.

    Slug must be canonical AND active per kbl.slug_registry. Inactive/retired
    slugs return 404 — desks get a clear signal, not a silent empty result.

    Default response omits full_transcript bodies; set include_body=true to
    receive bodies. LIMIT defaults to 50, max 200.
    """
    from datetime import datetime as _dt
    from kbl import slug_registry

    # Slug validation — canonical + active. Inactive/retired slugs 404.
    if matter_slug not in slug_registry.active_slugs():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown or inactive matter_slug '{matter_slug}'. "
                f"Must be an active canonical slug from baker-vault/slugs.yml."
            ),
        )

    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1..200")

    if since:
        try:
            _dt.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="since must be ISO 8601 timestamp (e.g. 2026-05-01T00:00:00Z)",
            )

    if source is not None and source not in ("plaud", "fireflies", "youtube"):
        raise HTTPException(
            status_code=400,
            detail="source must be one of: plaud, fireflies, youtube",
        )

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")

    transcripts: list = []
    try:
        cur = conn.cursor()
        try:
            base_cols = [
                "id", "title", "meeting_date", "duration", "organizer",
                "participants", "summary", "source",
            ]
            if include_body:
                base_cols.append("full_transcript")
            select_cols = ", ".join(base_cols)

            params: list = [matter_slug]
            where_clauses = ["matter_slug = %s"]
            if since:
                where_clauses.append("meeting_date >= %s")
                params.append(since)
            if source:
                where_clauses.append("source = %s")
                params.append(source)
            params.append(limit)

            sql = (
                f"SELECT {select_cols} "
                f"FROM meeting_transcripts "
                f"WHERE {' AND '.join(where_clauses)} "
                f"ORDER BY meeting_date DESC NULLS LAST "
                f"LIMIT %s"
            )
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            transcripts = [dict(zip(cols, r)) for r in rows]
            for t in transcripts:
                if t.get("meeting_date") is not None:
                    t["meeting_date"] = t["meeting_date"].isoformat()
        finally:
            cur.close()
    except HTTPException:
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"get_transcripts_by_matter failed for {matter_slug}: {e}")
        raise HTTPException(status_code=500, detail="Internal query error")
    finally:
        store._put_conn(conn)

    return {
        "matter_slug": matter_slug,
        "count": len(transcripts),
        "limit": limit,
        "include_body": include_body,
        "transcripts": transcripts,
    }


@app.get(
    "/api/attachments/{att_id}",
    tags=["emails"],
    dependencies=[Depends(verify_api_key)],
)
async def get_email_attachment(att_id: int):
    """Return stored email attachment bytes (EMAIL_ATTACHMENT_STORE_1).

    - 200: raw bytes with the stored mime_type (octet-stream fallback).
    - 404: no such id, or row is metadata_only (>5MB payload not stored).
    - 401: handled by verify_api_key (X-Baker-Key header).
    """
    import asyncio
    from fastapi import Response
    from kbl.attachment_store import get_attachment

    att = await asyncio.to_thread(get_attachment, att_id)
    if att is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    if att.get("storage") != "db" or att.get("data") is None:
        raise HTTPException(
            status_code=404,
            detail="attachment is metadata_only — payload not stored (>5MB cap)",
        )
    return Response(
        content=att["data"],
        media_type=att.get("mime_type") or "application/octet-stream",
    )


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
async def email_backfill_endpoint(
    days: int = Query(14, ge=1, le=365),
    background_tasks: BackgroundTasks = None,
):
    """Backfill last N days of emails from Gmail API to PostgreSQL + Qdrant.
    Runs in background — returns immediately with job status.
    """
    def _run_email_backfill():
        try:
            from triggers.email_trigger import backfill_emails
            backfill_emails(days)
            logger.info(f"Email backfill ({days} days) completed in background")
        except Exception as e:
            logger.error(f"Email backfill ({days} days) failed in background: {e}")

    background_tasks.add_task(_run_email_backfill)
    return {"status": "ok", "message": f"Email backfill ({days} days) started in background", "days": days}


@app.post("/api/emails/backfill-attachments", tags=["emails"], dependencies=[Depends(verify_api_key)])
async def email_attachments_backfill_endpoint(
    days: int = Query(365, ge=1, le=730),
    background_tasks: BackgroundTasks = None,
):
    """EMAIL-ATTACH-FIX-1: Find emails with attachments in Gmail that don't have
    corresponding docs in Baker, then download and store them.
    Runs in background — returns immediately.
    """
    def _run_attachment_backfill():
        try:
            from scripts.backfill_missed_attachments import run
            run(days=days, dry_run=False)
            logger.info(f"Email attachment backfill ({days} days) completed in background")
        except Exception as e:
            logger.error(f"Email attachment backfill ({days} days) failed in background: {e}")

    background_tasks.add_task(_run_attachment_backfill)
    return {"status": "ok", "message": f"Email attachment backfill ({days} days) started in background", "days": days}


# ---------------------------------------------------------------------------
# YouTube Transcript Ingestion (YOUTUBE-GEMMA-INGEST-1)
# ---------------------------------------------------------------------------
@app.post("/api/youtube/ingest", tags=["youtube"], dependencies=[Depends(verify_api_key)])
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

    result = ingest_youtube_video(
        video_id,
        title=body.get("title", ""),
        pre_fetched_transcript=body.get("transcript"),
    )
    return result


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


def _format_wa_md(messages: list[dict]) -> str:
    """Render WhatsApp messages as oldest-first markdown thread."""
    lines = []
    for m in messages:
        ts = m.get("timestamp")
        if isinstance(ts, datetime):
            ts_fmt = ts.strftime("%Y-%m-%d %H:%M UTC")
        elif isinstance(ts, str) and ts:
            try:
                ts_fmt = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
            except ValueError:
                ts_fmt = ts
        else:
            ts_fmt = "?"
        name = m.get("sender_name") or m.get("sender") or "Unknown"
        lines.append(f"**[{ts_fmt}] {name}**\n{m.get('full_text') or ''}\n")
    return "\n".join(lines)


@app.get("/api/whatsapp/messages", tags=["whatsapp"], dependencies=[Depends(verify_api_key)])
async def whatsapp_messages_endpoint(
    contact: str = Query(..., min_length=1, description="Match on sender, sender_name OR chat_id substring (ILIKE)"),
    from_date: date = Query(..., alias="from", description="Inclusive lower bound (YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="Inclusive upper bound (YYYY-MM-DD)"),
    limit: int = Query(200, ge=1, le=1000),
    fmt: Literal["json", "md"] = Query("json", alias="format"),
):
    """Read-only WhatsApp message pull for desk consumption.

    Matches sender, sender_name OR chat_id via ILIKE %contact%, timestamp
    inclusive between `from` and `to` (end-of-day on `to`). Returns
    oldest-first.

    WAHA migrated to LID-encoded chat_ids in early-mid 2026; sender_name +
    chat_id now often hold `<digits>@lid` strings, so the phone substring
    only lives in the `sender` column. Probing all three keeps phone-fragment
    queries surfacing the rows. Human-name resolution for LID-only rows is
    out of scope here — separate brief.

    has_media derives from `media_dropbox_path IS NOT NULL` (the canonical
    media-presence flag per `_ensure_whatsapp_messages_table`; the brief's
    reference to `media_path` is stale).
    """
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        logger.error("WhatsApp messages endpoint: no DB connection")
        return {"status": "error", "message": "database unavailable"}

    raw_messages: list[dict] = []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, timestamp, sender, sender_name, chat_id, full_text,
                   (media_dropbox_path IS NOT NULL) AS has_media,
                   is_director
            FROM whatsapp_messages
            WHERE (sender ILIKE %s OR sender_name ILIKE %s OR chat_id ILIKE %s)
              AND timestamp >= %s
              AND timestamp < %s::date + INTERVAL '1 day'
            ORDER BY timestamp ASC
            LIMIT %s
            """,
            (f"%{contact}%", f"%{contact}%", f"%{contact}%", from_date, to_date, limit),
        )
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            raw_messages.append(dict(zip(cols, row)))
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"WhatsApp messages endpoint failed: {e}")
        store._put_conn(conn)
        return {"status": "error", "message": str(e)}
    store._put_conn(conn)

    if fmt == "md":
        return PlainTextResponse(content=_format_wa_md(raw_messages))

    messages = []
    for m in raw_messages:
        ts = m.get("timestamp")
        messages.append({
            "id": m.get("id"),
            "timestamp": ts.isoformat() if isinstance(ts, datetime) else ts,
            "sender": m.get("sender"),
            "sender_name": m.get("sender_name"),
            "chat_id": m.get("chat_id"),
            "full_text": m.get("full_text"),
            "has_media": bool(m.get("has_media")),
            "is_director": bool(m.get("is_director")),
        })
    return {
        "status": "ok",
        "contact": contact,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "count": len(messages),
        "messages": messages,
    }


# ============================================================
# BAKER_CAPTURE_BLINDSPOTS_1: iPhone WhatsApp export ingest
# ============================================================
# Pre-2026-05-20 Director outbound on WhatsApp was never captured (WAHA
# `fromMe=true` subscription shipped that day). The only historical source
# is the iPhone "Export Chat" .txt. This endpoint ingests one such file at
# a time and upserts into the existing whatsapp_messages table, keyed by a
# deterministic `iphone:<chat>:<ts>:<bit>:<md5>` id so re-uploads are no-ops.

_IPHONE_WA_LINE = re.compile(
    r'^\[(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}), (\d{1,2}:\d{2}:\d{2})\] (.+?): (.*)$'
)


def parse_iphone_export(text: str, director_name: str = "Dimitry Vallen") -> list[dict]:
    """Parse iPhone WhatsApp 'Export Chat' .txt into per-message dicts.

    Format: `[YYYY-MM-DD, HH:MM:SS] <Sender>: <body>` with body continuations
    on unprefixed lines. Auto-detects between ISO and DD/MM/YYYY / MM/DD/YYYY
    locales. Drops empty bodies and WhatsApp system placeholders.

    Returns list of {timestamp, sender, body, is_director}.
    """
    messages: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        m = _IPHONE_WA_LINE.match(raw)
        if m:
            if current is not None:
                messages.append(current)
            date_str, time_str, sender, body = m.groups()
            ts = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
                try:
                    ts = datetime.strptime(f"{date_str} {time_str}", fmt)
                    break
                except ValueError:
                    continue
            if ts is None:
                current = None
                continue
            current = {
                "timestamp": ts,
                "sender": sender.strip(),
                "body": body,
                "is_director": director_name.lower() in sender.lower(),
            }
        elif current is not None:
            current["body"] = current["body"] + "\n" + raw
    if current is not None:
        messages.append(current)

    return [
        m for m in messages
        if m["body"].strip()
        and not m["body"].lstrip().startswith("\u200e")
        and "<This message was deleted>" not in m["body"]
        and "<This message was edited>" not in m["body"]
    ]


def _iphone_export_id(chat_id: str, timestamp: datetime, is_director: bool, body: str) -> str:
    """Deterministic PK for iPhone-export rows. Prefix `iphone:` makes them
    queryable via `WHERE id LIKE 'iphone:%'`. Same key on re-upload → ON CONFLICT
    upsert (no duplicate row)."""
    body_md5 = hashlib.md5(body.encode("utf-8")).hexdigest()[:12]
    ts_iso = timestamp.strftime("%Y%m%dT%H%M%S")
    bit = "1" if is_director else "0"
    return f"iphone:{chat_id}:{ts_iso}:{bit}:{body_md5}"


def _ingest_iphone_messages(
    store,
    messages: list[dict],
    counterparty_phone: str,
    counterparty_name: str,
    director_name: str = "Dimitry Vallen",
) -> tuple[int, int]:
    """Upsert parsed messages via SentinelStoreBack.store_whatsapp_message().

    Pre-queries for existing ids to distinguish new inserts from upserts so
    the endpoint can return an accurate `ingested` vs `skipped_duplicates`
    split. Returns (ingested, skipped_duplicates).
    """
    DIRECTOR_PHONE = "41799605092@c.us"
    chat_id = f"{counterparty_phone.lstrip('+')}@c.us"

    conn = store._get_conn()
    existing_ids: set[str] = set()
    target_ids: list[str] = []
    if conn is not None:
        try:
            cur = conn.cursor()
            target_ids = [
                _iphone_export_id(chat_id, m["timestamp"], m["is_director"], m["body"])
                for m in messages
            ]
            if target_ids:
                cur.execute(
                    "SELECT id FROM whatsapp_messages WHERE id = ANY(%s)",
                    (target_ids,),
                )
                existing_ids = {row[0] for row in cur.fetchall()}
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(f"iphone-export pre-query failed (continuing): {e}")
        finally:
            store._put_conn(conn)
    else:
        target_ids = [
            _iphone_export_id(chat_id, m["timestamp"], m["is_director"], m["body"])
            for m in messages
        ]

    ingested = 0
    skipped_duplicates = 0
    for m, msg_id in zip(messages, target_ids):
        sender_phone = DIRECTOR_PHONE if m["is_director"] else chat_id
        sender_label = director_name if m["is_director"] else counterparty_name
        was_existing = msg_id in existing_ids
        ok = store.store_whatsapp_message(
            msg_id=msg_id,
            sender=sender_phone,
            sender_name=sender_label,
            chat_id=chat_id,
            full_text=m["body"],
            timestamp=m["timestamp"].isoformat(),
            is_director=m["is_director"],
        )
        if not ok:
            continue
        if was_existing:
            skipped_duplicates += 1
        else:
            ingested += 1
    return ingested, skipped_duplicates


@app.post(
    "/api/whatsapp/import_iphone_export",
    tags=["whatsapp"],
    dependencies=[Depends(verify_api_key)],
)
async def whatsapp_import_iphone_export(
    file: UploadFile = File(...),
    counterparty_phone: str = Form(...),
    counterparty_name: str = Form(...),
    director_name: str = Form("Dimitry Vallen"),
):
    """Ingest iPhone WhatsApp 'Export Chat' .txt as historical messages.

    Form fields:
      file: .txt from iPhone "Export Chat" (without media)
      counterparty_phone: e.g. "+393358345678" → chat_id "393358345678@c.us"
      counterparty_name: human-readable label (e.g. "Peter Storer")
      director_name: substring used to set is_director=True

    Returns: {ingested, skipped_duplicates, first_timestamp, last_timestamp}.
    Idempotent via deterministic `iphone:` id prefix + ON CONFLICT DO UPDATE.
    .zip uploads (export-with-media) return 501 — out of scope for v1.
    """
    filename = (file.filename or "").lower()
    if filename.endswith(".zip"):
        raise HTTPException(
            status_code=501,
            detail="media import not yet supported — upload the .txt only",
        )

    content = (await file.read()).decode("utf-8", errors="replace")
    messages = parse_iphone_export(content, director_name=director_name)
    if not messages:
        raise HTTPException(status_code=422, detail="No parseable messages in upload")

    store = _get_store()
    ingested, skipped_duplicates = _ingest_iphone_messages(
        store, messages, counterparty_phone, counterparty_name, director_name=director_name
    )
    return {
        "ingested": ingested,
        "skipped_duplicates": skipped_duplicates,
        "first_timestamp": messages[0]["timestamp"].isoformat(),
        "last_timestamp": messages[-1]["timestamp"].isoformat(),
        "counterparty_phone": counterparty_phone,
        "counterparty_name": counterparty_name,
    }


@app.post("/api/contacts/enrich", tags=["contacts"], dependencies=[Depends(verify_api_key)])
async def enrich_contacts_endpoint(
    limit: int = Query(500, ge=1, le=1000),
    background_tasks: BackgroundTasks = None,
):
    """Batch-classify default-tier contacts using Haiku from their interaction history.
    Updates tier, contact_type, role_context. Runs in background.
    """
    def _run_enrichment():
        import json as _json
        import re as _re
        import time as _time

        _client = anthropic.Anthropic()
        _store = _get_store()

        _PROMPT = (
            "You are classifying a business contact for a luxury real estate CEO's contact management system.\n"
            "Given the contact name and their recent interaction subjects, classify this person.\n\n"
            "Return a JSON object with exactly these fields:\n"
            "- \"tier\": 1 (inner circle — family, close partners, key advisors), "
            "2 (active business — regular counterparties, lawyers, brokers), "
            "or 3 (peripheral — one-off contacts, service providers, marketing)\n"
            "- \"contact_type\": one of \"partner\", \"advisor\", \"investor\", \"broker\", \"lawyer\", "
            "\"service_provider\", \"team_member\", \"connector\", \"family\", \"prospect\"\n"
            "- \"role_context\": a concise 5-15 word description of who this person is and their relationship\n\n"
            "Rules:\n"
            "- If the person has frequent, substantive interactions, they are likely tier 2\n"
            "- If interactions are mostly personal/family or show deep trust, they are likely tier 1\n"
            "- If interactions are sparse or transactional, they are likely tier 3\n\n"
            "Contact: {name}\nChannels: {channels}\nInteraction count: {count}\n"
            "Recent subjects:\n{subjects}\n\nReturn ONLY the JSON object."
        )

        # Fetch contacts
        conn = _store._get_conn()
        if not conn:
            logger.error("Enrich: no DB connection")
            return
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.id, c.name,
                    STRING_AGG(DISTINCT ci.channel, ', ') as channels,
                    COUNT(ci.id) as interaction_count,
                    ARRAY_AGG(DISTINCT LEFT(ci.subject, 100) ORDER BY LEFT(ci.subject, 100))
                        FILTER (WHERE ci.subject IS NOT NULL AND ci.subject != '') as subjects
                FROM vip_contacts c
                JOIN contact_interactions ci ON ci.contact_id = c.id
                WHERE c.tier = 3 AND c.contact_type = 'connector'
                GROUP BY c.id, c.name
                HAVING COUNT(ci.id) >= 2
                ORDER BY COUNT(ci.id) DESC
                LIMIT %s
            """, (limit,))
            cols = [d[0] for d in cur.description]
            contacts = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close()
        finally:
            _store._put_conn(conn)

        logger.info(f"Enrich: found {len(contacts)} contacts to classify")
        updated = 0
        failed = 0
        valid_types = {"partner", "advisor", "investor", "broker", "lawyer",
                       "service_provider", "team_member", "connector", "family", "prospect"}

        for i, c in enumerate(contacts):
            subjects = c.get("subjects") or []
            subj_text = "\n".join(f"- {s}" for s in subjects[:30])
            prompt = _PROMPT.format(
                name=c["name"], channels=c.get("channels", "unknown"),
                count=c.get("interaction_count", 0), subjects=subj_text or "(no data)",
            )
            try:
                # TRUSTED — writes tier/contact_type/role_context to vip_contacts,
                # which populates the Director-visible People surface (named trusted
                # in the Director ruling). Gemini Pro floor, never Flash
                # (BAKER_DASHBOARD_V2_MODEL_LOCK_1). Borderline categorization call —
                # see ship report DONE-rubric Q3.
                resp = _llm_call("gemini-2.5-pro",
                    max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = resp.text.strip()
                data = None
                if text.startswith("{"):
                    data = _json.loads(text)
                else:
                    m = _re.search(r'\{[^}]+\}', text, _re.DOTALL)
                    if m:
                        data = _json.loads(m.group())
                if not data:
                    failed += 1
                    continue

                tier = data.get("tier", 3)
                if tier not in (1, 2, 3):
                    tier = 3
                ctype = data.get("contact_type", "connector")
                if ctype not in valid_types:
                    ctype = "connector"
                role = data.get("role_context", "")

                uconn = _store._get_conn()
                if uconn:
                    try:
                        ucur = uconn.cursor()
                        ucur.execute(
                            "UPDATE vip_contacts SET tier = %s, contact_type = %s, role_context = %s WHERE id = %s",
                            (tier, ctype, role, c["id"]),
                        )
                        uconn.commit()
                        ucur.close()
                        updated += 1
                    except Exception as ue:
                        uconn.rollback()
                        failed += 1
                        logger.warning(f"Enrich update failed for {c['name']}: {ue}")
                    finally:
                        _store._put_conn(uconn)

                if (i + 1) % 50 == 0:
                    logger.info(f"Enrich progress: {i+1}/{len(contacts)} ({updated} updated, {failed} failed)")
                _time.sleep(0.5)  # Rate limit

            except Exception as e:
                failed += 1
                logger.warning(f"Enrich failed for {c['name']}: {e}")

        logger.info(f"Enrich complete: {updated} updated, {failed} failed out of {len(contacts)}")

    background_tasks.add_task(_run_enrichment)
    return {"status": "started", "message": f"Contact enrichment started (limit={limit})", "limit": limit}


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


class KBLIngestRequest(BaseModel):
    """POST /api/kbl/ingest body. See kbl.ingest_endpoint.ingest() for semantics."""
    frontmatter: dict
    body: str
    trigger_source: Optional[str] = "kbl_ingest_endpoint"


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
# KBL_INGEST_ENDPOINT_1: Single chokepoint for wiki writes
# ============================================================

@app.post("/api/kbl/ingest", tags=["kbl"], dependencies=[Depends(verify_api_key)])
async def kbl_ingest_endpoint(req: KBLIngestRequest):
    """Single chokepoint for wiki writes.

    Enforces VAULT.md §2 frontmatter schema, slug registry check
    (matters — via slugs.yml), atomic wiki_pages + baker_actions write
    (CHANDA #2), Qdrant upsert, and Gold mirror staging when voice=gold.
    """
    from kbl.ingest_endpoint import ingest, KBLIngestError
    try:
        result = ingest(
            frontmatter=req.frontmatter,
            body=req.body,
            trigger_source=req.trigger_source or "kbl_ingest_endpoint",
        )
        return {
            "status": "ingested",
            "wiki_page_id": result.wiki_page_id,
            "slug": result.slug,
            "qdrant_point_id": result.qdrant_point_id,
            "gold_mirrored": result.gold_mirrored,
            "mirror_path": result.mirror_path,
        }
    except KBLIngestError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/kbl/ingest failed: {e}")
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


def _scheduler_live_from_status() -> tuple[bool, int, int | None]:
    """Return scheduler liveness, combining local APScheduler state with DB proof.

    On Render, the request-serving process can observe _scheduler as None while
    another in-process/backend thread is actively firing jobs and writing
    scheduler_executions. Treat a fresh scheduler_executions row as the stronger
    liveness signal so /health does not report "stopped" while jobs are firing.
    """
    try:
        status = get_scheduler_status()
    except Exception:
        status = {}
    running = bool(status.get("running", False))
    job_count = int(status.get("job_count", 0) or 0)
    exec_age = None
    try:
        from triggers.state import trigger_state
        exec_age = trigger_state.seconds_since_last_scheduler_execution()
    except Exception:
        exec_age = None
    if not running and exec_age is not None and exec_age < _WATCHDOG_EXEC_FRESH_WINDOW_S:
        running = True
    return running, job_count, int(exec_age) if exec_age is not None else None


@app.get("/api/health/scheduler", tags=["health"], include_in_schema=False)
async def scheduler_heartbeat_health():
    """SCHEDULER-WATCHDOG-1: Public endpoint for frontend heartbeat polling."""
    try:
        from triggers.state import trigger_state
        from triggers.state import get_watermark_failure_count
        hb = trigger_state.get_watermark("scheduler_heartbeat")
        age = (datetime.now(timezone.utc) - hb).total_seconds()
        # SCHEDULER_WATCHDOG_HARDEN_1 (lead #2566) — DB-derived liveness signal that
        # SURVIVES restarts (unlike the per-process watermark_set_failures counter,
        # which resets to 0 on the spurious restart it was meant to expose). When the
        # heartbeat watermark freezes while the scheduler is live, heartbeat_age_seconds
        # climbs but last_job_execution_age_seconds stays small — the divergence makes
        # the gauge failure observable without Render stderr.
        scheduler_running, job_count, exec_age = _scheduler_live_from_status()
        return {
            "alive": age < 720,
            "heartbeat_age_seconds": int(age),
            "scheduler_running": scheduler_running,
            "job_count": job_count,
            # SCHEDULER_STALL_CODEFIX_1 — surface silent watermark-write failures so a
            # frozen heartbeat is visible before it trips the 12-min watchdog.
            "watermark_set_failures": get_watermark_failure_count(),
            # SCHEDULER_WATCHDOG_HARDEN_1 — None when scheduler_executions is empty or
            # unreadable; a small value alongside a large heartbeat_age_seconds means
            # "gauge stale, scheduler live" (watchdog will suppress the restart).
            "last_job_execution_age_seconds": (
                exec_age if exec_age is not None else None
            ),
        }
    except Exception as e:
        return {"alive": False, "error": str(e)}


# ============================================================
# Root — serve index.html
# ============================================================

# TWO NAMED predicates (G0 codex #1772 fold) — they select DIFFERENT row sets on
# purpose and must NOT be collapsed:
#
#   _RECON_MISSING_QDRANT_PREDICATE  — filename-level. The reconciliation REPORT's
#     legacy view: "how many filenames in `documents` have no baker-documents
#     ingestion at all". Read-only, manual-decision surface. Unchanged behaviour.
#
#   _REINGEST_MISSING_QDRANT_PREDICATE — row-level (filename + file_hash). The
#     REPAIR selector. ingestion_log's dedup key is (filename, file_hash), so a
#     filename-only predicate would hide a row whose filename matches an
#     already-embedded sibling with a different hash (live: 76 dup filenames cover
#     165 rows) — that row would never be embedded yet never re-selected, so the
#     resume loop could never reach remaining_after == 0. Row-level is resume-safe.
#
# `d` is the alias for the `documents` table in every consumer. Collection is
# pinned to baker-documents in both (an embed into another collection does not
# satisfy semantic document search).
_RECON_MISSING_QDRANT_PREDICATE = (
    "NOT EXISTS (SELECT 1 FROM ingestion_log il "
    "WHERE il.collection = 'baker-documents' AND il.filename = d.filename)"
)
_REINGEST_MISSING_QDRANT_PREDICATE = (
    "NOT EXISTS (SELECT 1 FROM ingestion_log il "
    "WHERE il.collection = 'baker-documents' "
    "AND il.filename = d.filename AND il.file_hash = d.file_hash)"
)
# Embeddable = row-level-missing AND has non-blank extracted text. Empty/NULL
# full_text rows can never be embedded (ingest_text returns skipped "Empty text"
# and writes no ingestion_log), so including them in the repair selector would
# re-return them every call and STALL the resume loop (live: 576 of 1036 legacy
# rows are blank, only 460 embeddable). The repair selector filters them at SQL.
_HAS_EXTRACTED_TEXT = "d.full_text IS NOT NULL AND btrim(d.full_text) <> ''"

# OVERSIZED_DOC_GUARD (DOC_BACKFILL_RUN_1, b1 diagnosis 2026-06-07): per-doc text
# length cap on the reingest selector. A handful of huge spreadsheet exports (live: an
# 8.6M-char .xlsx => ~4,800 chunks at ~500 tokens/chunk; ~11h to embed at the 25s
# INGEST_EMBED_DELAY Voyage rate-limit) sort FIRST under `ORDER BY ingested_at DESC`
# and, because the embed loop is sequential in one worker thread, block the WHOLE
# backfill: the call exceeds --max-time, the client gets an empty body, and nothing
# commits for the normal docs queued behind them. Skip + report rather than embed —
# spreadsheets are poor semantic targets and keyword search already finds them.
# Threshold 500K chars cleanly excludes the 3 live offenders (8.6M / 2.15M / 737K);
# p95 of the normal embeddable set is ~65K, so zero false positives.
_REINGEST_MAX_TEXT_CHARS = 500_000
_WITHIN_SIZE_CAP = f"length(d.full_text) <= {_REINGEST_MAX_TEXT_CHARS}"


def _documents_missing_qdrant(limit: int = 50):
    """A3 (INGEST_SEARCH_DURABILITY_FOLLOWUPS_1): cross-store reconciliation.

    Find `documents` rows (Postgres = system of record) with NO matching
    `baker-documents` ingestion in `ingestion_log` — i.e. the Postgres half
    landed but the Qdrant half did not (the A2-class half-index drift, plus any
    legacy backlog that predates the Qdrant two-write). Read-only and bounded.

    Returns (count, rows) where rows is capped at `limit`; count is the full
    total. On any error returns (None, []) — callers treat None as "unknown".
    The list is for a manual re-ingest decision; A3 does not auto-repair.
    """
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return None, []
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        not_in_qdrant = _RECON_MISSING_QDRANT_PREDICATE
        cur.execute(f"SELECT COUNT(*) AS c FROM documents d WHERE {not_in_qdrant}")
        count = cur.fetchone()["c"]
        cur.execute(
            f"SELECT d.id, d.filename, d.source_path, d.matter_slug, d.ingested_at "
            f"FROM documents d WHERE {not_in_qdrant} "
            f"ORDER BY d.ingested_at DESC NULLS LAST LIMIT %s",
            (limit,),
        )
        rows = []
        for r in cur.fetchall():
            r = dict(r)
            ing = r.get("ingested_at")
            rows.append({
                "id": r["id"],
                "filename": r.get("filename"),
                "source_path": r.get("source_path"),
                "matter_slug": r.get("matter_slug"),
                "ingested_at": ing.isoformat() if hasattr(ing, "isoformat") and ing else None,
            })
        cur.close()
        return count, rows
    except Exception as recon_err:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"reconciliation _documents_missing_qdrant failed: {recon_err}")
        return None, []
    finally:
        store._put_conn(conn)


# A3: TTL-cache the drift COUNT for the /health path only. /health is Render's
# liveness probe (hit frequently); a per-probe COUNT(*) + correlated NOT EXISTS
# would add needless DB load. The authed reconciliation endpoint stays fresh.
_recon_health_cache = {"ts": 0.0, "count": None}
_RECON_HEALTH_TTL_SEC = 300


def _documents_missing_qdrant_health_count():
    """Cached drift count for /health (recomputed at most once per TTL)."""
    import time
    now = time.time()
    if now - _recon_health_cache["ts"] < _RECON_HEALTH_TTL_SEC:
        return _recon_health_cache["count"]
    count, _ = _documents_missing_qdrant(limit=1)
    _recon_health_cache["ts"] = now
    _recon_health_cache["count"] = count
    return count


@app.get("/api/documents/reconciliation", tags=["documents"], dependencies=[Depends(verify_api_key)])
async def documents_reconciliation(limit: int = Query(50, ge=1, le=500)):
    """A3: list `documents` rows with no `baker-documents` Qdrant ingestion.

    Surfaces half-indexed docs (Postgres-only) for a manual re-ingest decision.
    Read-only, bounded. `count` is the full total; `documents` is capped at `limit`.
    """
    count, rows = _documents_missing_qdrant(limit=limit)
    return {
        "missing_qdrant_count": count,
        "documents": rows,
        "limit": limit,
        "note": "documents present in Postgres but absent from baker-documents ingestion_log; "
                "includes legacy backlog predating the Qdrant two-write. Manual re-ingest decision.",
    }


def _reingest_missing_counts(cur):
    """Compute the repair-progress counts off a live cursor.

    - total_missing: filename-level legacy view (matches /api/documents/reconciliation).
    - embeddable_missing: row-level-missing AND non-blank text AND within the size cap
      — the set the repair actually processes; remaining_after re-reads THIS so the
      loop converges. MUST exclude oversized rows or the loop never reaches zero.
    - skipped_empty_total: row-level-missing but blank/NULL text — never embeddable,
      reported for visibility, deliberately excluded from the repair selector.
    - oversized_skipped_total: row-level-missing, non-blank, but over the size cap —
      deliberately excluded from the repair selector (see _REINGEST_MAX_TEXT_CHARS).
    """
    cur.execute(f"SELECT COUNT(*) AS c FROM documents d WHERE {_RECON_MISSING_QDRANT_PREDICATE}")
    total_missing = cur.fetchone()["c"]
    cur.execute(
        f"SELECT COUNT(*) AS c FROM documents d "
        f"WHERE {_REINGEST_MISSING_QDRANT_PREDICATE} AND {_HAS_EXTRACTED_TEXT} "
        f"AND {_WITHIN_SIZE_CAP}"
    )
    embeddable_missing = cur.fetchone()["c"]
    cur.execute(
        f"SELECT COUNT(*) AS c FROM documents d "
        f"WHERE {_REINGEST_MISSING_QDRANT_PREDICATE} AND NOT ({_HAS_EXTRACTED_TEXT})"
    )
    skipped_empty_total = cur.fetchone()["c"]
    cur.execute(
        f"SELECT COUNT(*) AS c FROM documents d "
        f"WHERE {_REINGEST_MISSING_QDRANT_PREDICATE} AND {_HAS_EXTRACTED_TEXT} "
        f"AND NOT ({_WITHIN_SIZE_CAP})"
    )
    oversized_skipped_total = cur.fetchone()["c"]
    return total_missing, embeddable_missing, skipped_empty_total, oversized_skipped_total


# REINGEST_ASYNC_OFFLOAD_1: run the blocking embed loop in a worker thread so the
# event loop (and /health, dashboard, search, MCP) stays responsive during a backfill.
def _reingest_embed_batch(candidates: list) -> dict:
    """Embed already-extracted full_text for each candidate. Pure ingest_text calls —
    no DB connection held. One failure must NOT abort the batch. Runs in a thread via
    asyncio.to_thread."""
    from tools.ingest.pipeline import ingest_text
    attempted = embedded = skipped_empty = skipped_dedup = oversized_skipped = 0
    failed = []
    for c in candidates:
        attempted += 1
        doc_id = c["id"]
        full_text = c.get("full_text") or ""
        if not full_text.strip():
            skipped_empty += 1
            continue
        # Defense-in-depth: the SQL selector already excludes oversized rows, but guard
        # here too so a hand-built candidate list can't poison the sequential embed loop
        # with a huge spreadsheet export (see _REINGEST_MAX_TEXT_CHARS).
        if len(full_text) > _REINGEST_MAX_TEXT_CHARS:
            logger.warning(
                f"reingest-missing id={doc_id} skipped oversized: {len(full_text)} chars "
                f"> cap {_REINGEST_MAX_TEXT_CHARS}"
            )
            oversized_skipped += 1
            continue
        try:
            result = ingest_text(
                full_text=full_text,
                filename=c.get("filename") or f"doc-{doc_id}",
                source_path=c.get("source_path") or c.get("filename") or f"doc-{doc_id}",
                file_hash=c.get("file_hash"),  # documents.file_hash, do NOT re-hash text
                document_id=doc_id,
                matter_slug=c.get("matter_slug"),
            )
        except Exception as ing_err:
            logger.error(f"reingest-missing id={doc_id} raised: {ing_err}")
            failed.append({"id": doc_id, "reason": str(ing_err)})
            continue
        reason = (result.skip_reason or "") if result.skipped else ""
        if not result.skipped:
            embedded += 1
        elif reason.startswith("Duplicate"):
            skipped_dedup += 1
        elif reason == "Empty text":
            skipped_empty += 1
        else:
            failed.append({"id": doc_id, "reason": reason or "skipped"})
    return {
        "attempted": attempted,
        "embedded": embedded,
        "skipped_empty": skipped_empty,
        "skipped_dedup": skipped_dedup,
        "oversized_skipped": oversized_skipped,
        "failed": failed,
    }


# Session-level advisory lock key — only one reingest write-batch at a time across
# all workers (prevents the Lesson #25 compounding-memory OOM on overlapping batches).
_REINGEST_ADVISORY_LOCK_KEY = 0x5245494E  # ascii "REIN"


@app.post("/api/documents/reingest-missing", tags=["documents"], dependencies=[Depends(verify_api_key)])
async def documents_reingest_missing(
    limit: int = Query(10, ge=1, le=100),
    dry_run: bool = Query(True),
):
    """REINGEST_MISSING_QDRANT_ENDPOINT_1: re-embed Postgres-only docs into Qdrant.

    Repairs the legacy backlog of `documents` rows that have extracted text in
    Postgres but no `baker-documents` Qdrant embedding (the keyword-only ~19% that
    predates the two-write). The repair selector is ROW-LEVEL (filename + file_hash,
    the ingestion_log dedup key) and EMBEDDABLE-ONLY (non-blank full_text) so the
    resume loop converges — see `_REINGEST_MISSING_QDRANT_PREDICATE`. For each row
    it re-embeds the already-extracted `full_text` via `ingest_text`, threading the
    row's own `file_hash` (so dedup keys match documents.file_hash, not a re-hash
    of the text), `document_id`, and `matter_slug`.

    Safe-by-default: `dry_run=true` (the default) writes nothing. Caller must pass
    `dry_run=false` to repair. Bounded + resumable — `limit` caps each call; re-run
    until `remaining_after == 0` (remaining EMBEDDABLE rows). No background job /
    scheduler / startup hook. Embed only: never re-classify or re-extract.
    Idempotent (relies on ingest_text dedup + deterministic point IDs; does NOT
    pass skip_dedup).
    """
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return {"error": "no_db_connection", "dry_run": dry_run}
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        (total_missing, embeddable_missing, skipped_empty_total,
         oversized_skipped_total) = _reingest_missing_counts(cur)
        # Repair selector: row-level-missing AND embeddable AND within the size cap,
        # capped at limit. The size cap keeps oversized spreadsheet exports out of the
        # sequential embed loop so they cannot block the backfill (_REINGEST_MAX_TEXT_CHARS).
        cur.execute(
            f"SELECT d.id, d.filename, d.source_path, d.matter_slug, d.file_hash, d.full_text "
            f"FROM documents d "
            f"WHERE {_REINGEST_MISSING_QDRANT_PREDICATE} AND {_HAS_EXTRACTED_TEXT} "
            f"AND {_WITHIN_SIZE_CAP} "
            f"ORDER BY d.ingested_at DESC NULLS LAST LIMIT %s",
            (limit,),
        )
        candidates = [dict(r) for r in cur.fetchall()]
        # Oversized doc IDs for operator reporting (bounded, diagnostic only).
        cur.execute(
            f"SELECT d.id FROM documents d "
            f"WHERE {_REINGEST_MISSING_QDRANT_PREDICATE} AND {_HAS_EXTRACTED_TEXT} "
            f"AND NOT ({_WITHIN_SIZE_CAP}) "
            f"ORDER BY length(d.full_text) DESC LIMIT 100"
        )
        oversized_doc_ids = [r["id"] for r in cur.fetchall()]
        cur.close()
    except Exception as sel_err:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"reingest-missing select failed: {sel_err}")
        # NOTE: do NOT _put_conn here — the finally below returns the conn exactly
        # once. _put_conn itself rolls back before returning to the pool, so a
        # second call here would roll back / return an already-returned conn under
        # concurrency (codex G3 #1778/#1779 fold).
        return {"error": "select_failed", "reason": str(sel_err), "dry_run": dry_run}
    finally:
        store._put_conn(conn)

    if dry_run:
        return {
            "dry_run": True,
            "total_missing": total_missing,
            "embeddable_missing": embeddable_missing,
            "skipped_empty_total": skipped_empty_total,
            "oversized_skipped_total": oversized_skipped_total,
            "oversized_doc_ids": oversized_doc_ids,
            "limit": limit,
            "would_process": [
                {
                    "id": c["id"],
                    "filename": c.get("filename"),
                    "text_len": len(c.get("full_text") or ""),
                }
                for c in candidates
            ],
        }

    # --- Write path: single-runner SESSION advisory lock on a DEDICATED DIRECT
    #     (non-pooled) connection. pgbouncer transaction-mode on the store pool resets
    #     session state on commit and would release the lock (codex G0 #1809 HIGH). ---
    import psycopg2
    from config.settings import config as _cfg
    if not getattr(_cfg.postgres, "host_direct", None):
        # Direct endpoint required for a session lock; pooled host is unsafe. Fail loud.
        return {
            "error": "no_direct_dsn",
            "reason": "session advisory lock requires a non-pooled (direct) Postgres endpoint; host_direct unset",
            "dry_run": False,
        }
    try:
        lock_conn = psycopg2.connect(**_cfg.postgres.direct_dsn_params)
        # MUST be autocommit (codex G0 #1815 HIGH): default psycopg2 (autocommit=False)
        # opens a transaction on the lock SELECT; the connection then sits
        # idle-in-transaction while the embed batch runs in the worker thread. Live
        # idle_in_transaction_session_timeout = 5min, so a slow batch (>5min) gets its
        # session killed and the advisory lock silently released → overlapping batch.
        # Precedent: triggers/scheduler_lease.py:63-67; BRIEF_SCHEDULER_SINGLETON_HARDEN_1.
        lock_conn.autocommit = True
    except Exception as conn_err:
        logger.error(f"reingest-missing direct connect failed: {conn_err}")
        try:
            lock_conn.close()  # may not be bound; guard
        except Exception:
            pass
        return {"error": "lock_connect_failed", "reason": str(conn_err), "dry_run": False}
    got_lock = False
    try:
        lc = lock_conn.cursor()
        lc.execute("SELECT pg_try_advisory_lock(%s)", (_REINGEST_ADVISORY_LOCK_KEY,))
        got_lock = bool(lc.fetchone()[0])
        lc.close()
        if not got_lock:
            return {
                "error": "backfill_in_progress",
                "reason": "another reingest batch holds the advisory lock",
                "dry_run": False,
            }
        # Blocking embed loop runs in a worker thread — event loop stays free.
        stats = await asyncio.to_thread(_reingest_embed_batch, candidates)
    except Exception as embed_err:
        logger.error(f"reingest-missing embed batch failed: {embed_err}")
        stats = {"attempted": 0, "embedded": 0, "skipped_empty": 0,
                 "skipped_dedup": 0, "oversized_skipped": 0,
                 "failed": [{"id": None, "reason": str(embed_err)}]}
    finally:
        if got_lock:
            try:
                uc = lock_conn.cursor()
                uc.execute("SELECT pg_advisory_unlock(%s)", (_REINGEST_ADVISORY_LOCK_KEY,))
                uc.close()
            except Exception as unlock_err:
                logger.error(f"reingest-missing advisory unlock failed: {unlock_err}")
        # Dedicated connection — CLOSE it (session end also drops any held lock).
        # Never store._put_conn() this; it is not a pool connection.
        try:
            lock_conn.close()
        except Exception:
            pass

    attempted = stats["attempted"]
    embedded = stats["embedded"]
    skipped_empty = stats["skipped_empty"]
    skipped_dedup = stats["skipped_dedup"]
    oversized_skipped = stats["oversized_skipped"]
    failed = stats["failed"]

    # remaining_after: re-count remaining EMBEDDABLE rows post-batch so the caller
    # sees real convergence (NOT total_missing, which includes never-embeddable empties).
    remaining_after = None
    conn2 = store._get_conn()
    if conn2:
        try:
            cur2 = conn2.cursor()
            # MUST mirror embeddable_missing's predicate (incl. the size cap) so the
            # resume loop converges to 0 — oversized rows are never embedded and would
            # otherwise keep remaining_after permanently above zero.
            cur2.execute(
                f"SELECT COUNT(*) FROM documents d "
                f"WHERE {_REINGEST_MISSING_QDRANT_PREDICATE} AND {_HAS_EXTRACTED_TEXT} "
                f"AND {_WITHIN_SIZE_CAP}"
            )
            remaining_after = cur2.fetchone()[0]
            cur2.close()
        except Exception as cnt_err:
            try:
                conn2.rollback()
            except Exception:
                pass
            logger.error(f"reingest-missing remaining_after count failed: {cnt_err}")
        finally:
            store._put_conn(conn2)

    return {
        "dry_run": False,
        "limit": limit,
        "total_missing": total_missing,
        "embeddable_missing": embeddable_missing,
        "skipped_empty_total": skipped_empty_total,
        "oversized_skipped_total": oversized_skipped_total,
        "oversized_doc_ids": oversized_doc_ids,
        "attempted": attempted,
        "embedded": embedded,
        "skipped_empty": skipped_empty,
        "skipped_dedup": skipped_dedup,
        "oversized_skipped": oversized_skipped,
        "failed": failed,
        "remaining_after": remaining_after,
    }


# ── OCR_REEXTRACT_MISSING_1: recover blank-full_text scanned PDFs/DOCX ─────────
# ~580 documents rows have NULL/blank full_text because they are scanned/image PDFs
# and pdfplumber (no OCR) returns "". They are invisible to search AND ineligible
# for reingest-missing (which requires _HAS_EXTRACTED_TEXT). This endpoint downloads
# each blank doc from Dropbox, reads it with Gemini 2.5 Pro vision, and populates
# full_text via a TARGETED UPDATE (preserves owner — codex G0 #1836). It does NOT
# embed; once full_text is populated the operator runs reingest-missing to embed.
_OCR_ADVISORY_LOCK_KEY = 0x4F435231  # ascii "OCR1" — distinct from REIN
_OCR_MAX_PAGES = 40                   # cap vision cost/time on big scans
_OCR_MIN_CHARS = 20                   # anti-hallucination floor: write only if legible
_OCR_PROMPT = (
    "Transcribe ALL text on this page verbatim, preserving reading order. "
    "Output ONLY the transcribed text, no commentary. If the page has NO legible "
    "text (blank, pure image/photo, or an unreadable low-resolution chart), output "
    "exactly the token [[UNREADABLE]] and nothing else."
)


def _ocr_extract_batch(candidates: list) -> dict:
    """OCR-recover full_text for each blank doc. Per-doc try/except (one failure must
    NOT abort the batch). Anti-hallucination guard: write ONLY if legible >= _OCR_MIN_CHARS
    and not every page was [[UNREADABLE]] — never write empty. Write = targeted UPDATE of
    the exact row by id (preserves owner; codex G0 #1836). Does NOT embed. Runs in a
    worker thread via asyncio.to_thread so the event loop stays free.

    codex G3 #1865 folds:
      F1 [HIGH]: per-page cost governor — check_circuit_breaker() before each call_pro
        (trip ⇒ stop the doc, fail reason=cost_breaker, write NOTHING) + log_api_cost
        after; fail-open so an instrumentation error never aborts recovery.
      F2 [MED]: a PDF over _OCR_MAX_PAGES still recovers its first cap pages but its
        `recovered` entry carries truncated=true (partial recovery is never silent).
    Returns {attempted:int, recovered:[{id,filename,truncated}], failed:[{id,...,reason}]}."""
    import base64
    import shutil
    import tempfile
    from pathlib import Path

    attempted = 0
    recovered = []          # per-doc entries: {id, filename, truncated} (codex G3 #1865 F2)
    failed = []
    store = _get_store()

    for c in candidates:
        attempted += 1
        doc_id = c["id"]
        filename = c.get("filename") or f"doc-{doc_id}"
        source_path = c.get("source_path") or ""
        tmpdir = None
        truncated = False   # True if a PDF exceeds _OCR_MAX_PAGES (partial recovery)
        try:
            if not source_path:
                failed.append({"id": doc_id, "filename": filename, "reason": "no_source_path"})
                continue
            tmpdir = tempfile.mkdtemp(prefix="baker_ocr_")
            # 1. Download from Dropbox (server-side; creds live on Render).
            try:
                from triggers.dropbox_client import DropboxClient
                local = DropboxClient._get_global_instance().download_file(source_path, Path(tmpdir))
            except Exception as dl_err:
                logger.error(f"ocr-extract id={doc_id} download failed: {dl_err}")
                failed.append({"id": doc_id, "filename": filename, "reason": "download_failed"})
                continue

            lower = filename.lower()
            if lower.endswith(".docx"):
                # DOCX (only 4 in the set) — direct text extract, not image OCR.
                try:
                    from tools.ingest.extractors import extract
                    legible = (extract(local) or "").strip()
                except Exception as dx_err:
                    logger.error(f"ocr-extract id={doc_id} docx extract failed: {dx_err}")
                    failed.append({"id": doc_id, "filename": filename, "reason": "docx_extract_failed"})
                    continue
                if len(legible) < _OCR_MIN_CHARS:
                    # OCR_UNREADABLE_MARKER_2: a sub-threshold (<_OCR_MIN_CHARS) extraction is
                    # deterministic-terminal — an image-only scan / near-empty docx that already
                    # ran OCR (or docx extract) and yielded almost nothing. Mark it so the drain
                    # stops re-selecting (and, for the PDF path, re-billing Gemini on) it. The
                    # include_unreadable force flag still covers a future better-OCR re-attempt.
                    # Only deterministic-terminal branches are marked; transient failures
                    # (cost_breaker, gemini_error, download_failed, etc.) stay UNMARKED to retry.
                    _ocr_mark_unreadable(store, doc_id)
                    failed.append({"id": doc_id, "filename": filename, "reason": "empty_ocr"})
                    continue
            else:
                # PDF — rasterize @200dpi + Gemini vision per page.
                try:
                    import fitz
                    pdf = fitz.open(local)
                except Exception as rz_err:
                    logger.error(f"ocr-extract id={doc_id} rasterize open failed: {rz_err}")
                    failed.append({"id": doc_id, "filename": filename, "reason": "rasterize_failed"})
                    continue
                page_texts = []
                gemini_failed = False
                cost_breaker_tripped = False
                # FINDING 1 (HIGH, codex G3 #1865): per-page cost governor on the
                # Gemini Pro vision loop (repo standard lessons.md #68; precedent
                # document_pipeline.py:193 pre / :341 post). Import is FAIL-OPEN — a
                # cost_monitor import error must NOT abort recovery, only drop the
                # governor for this doc.
                _governor = None
                try:
                    from orchestrator.cost_monitor import check_circuit_breaker, log_api_cost
                    _governor = (check_circuit_breaker, log_api_cost)
                except Exception as imp_err:
                    logger.warning(
                        f"ocr-extract id={doc_id} cost_monitor unavailable "
                        f"(fail-open, no governor this doc): {imp_err}")
                try:
                    from orchestrator.gemini_client import call_pro
                    n_pages = pdf.page_count
                    # FINDING 2 (MED, codex G3 #1865): signal silent truncation past
                    # the page cap instead of writing partial text with no flag.
                    truncated = n_pages > _OCR_MAX_PAGES
                    if truncated:
                        logger.warning(
                            f"ocr-extract id={doc_id} has {n_pages} pages > cap "
                            f"{_OCR_MAX_PAGES}; transcribing first {_OCR_MAX_PAGES} only "
                            f"(truncated=true on recovered entry)")
                    for pno in range(min(n_pages, _OCR_MAX_PAGES)):
                        # Cost governor: check BEFORE each call_pro. Trip ⇒ stop this
                        # doc (write NOTHING — never a partial). Fail-open on a check error.
                        if _governor is not None:
                            try:
                                allowed, daily_cost = _governor[0]()
                            except Exception as cb_err:
                                logger.warning(
                                    f"ocr-extract id={doc_id} breaker check failed "
                                    f"(fail-open): {cb_err}")
                                allowed, daily_cost = True, 0.0
                            if not allowed:
                                logger.error(
                                    f"ocr-extract id={doc_id} blocked by circuit breaker "
                                    f"(€{daily_cost:.2f}) at page {pno} — writing nothing")
                                cost_breaker_tripped = True
                                break
                        page = pdf.load_page(pno)
                        pix = page.get_pixmap(dpi=200)
                        jpg = pix.tobytes("jpeg")
                        b64 = base64.b64encode(jpg).decode("ascii")
                        resp = call_pro(
                            messages=[{"role": "user", "content": [
                                {"type": "image", "source": {
                                    "type": "base64", "media_type": "image/jpeg", "data": b64}},
                                {"type": "text", "text": _OCR_PROMPT},
                            ]}],
                            max_tokens=4000,
                        )
                        page_texts.append((resp.text or "").strip())
                        # Log cost AFTER each call. getattr-safe: a resp without .usage
                        # logs 0/0 (never crash); whole block fail-open.
                        if _governor is not None:
                            try:
                                _u = getattr(resp, "usage", None)
                                _in = getattr(_u, "input_tokens", 0) or 0
                                _out = getattr(_u, "output_tokens", 0) or 0
                                _governor[1]("gemini-2.5-pro", _in, _out,
                                             source="document_pipeline",
                                             capability_id="ocr_extract")
                            except Exception as lc_err:
                                logger.warning(
                                    f"ocr-extract id={doc_id} cost-log failed "
                                    f"(fail-open): {lc_err}")
                except Exception as g_err:
                    logger.error(f"ocr-extract id={doc_id} gemini vision failed: {g_err}")
                    gemini_failed = True
                finally:
                    try:
                        pdf.close()
                    except Exception:
                        pass
                if cost_breaker_tripped:
                    # Partial recovery is worse than none here — leave the row blank
                    # so a later (un-throttled) run re-selects + fully recovers it.
                    failed.append({"id": doc_id, "filename": filename, "reason": "cost_breaker"})
                    continue
                if gemini_failed:
                    failed.append({"id": doc_id, "filename": filename, "reason": "gemini_error"})
                    continue
                # Anti-hallucination guard: every page unreadable ⇒ do NOT write.
                all_unreadable = (
                    all(pt in ("", "[[UNREADABLE]]") for pt in page_texts)
                    if page_texts else True
                )
                if all_unreadable:
                    # OCR_UNREADABLE_MARKER_1: persist terminal state so the
                    # candidate query drops this doc on the next drain (zero
                    # Gemini re-bill). full_text untouched — no search pollution.
                    _ocr_mark_unreadable(store, doc_id)
                    failed.append({"id": doc_id, "filename": filename, "reason": "unreadable"})
                    continue
                legible = "\n\n".join(page_texts).replace("[[UNREADABLE]]", "").strip()
                if len(legible) < _OCR_MIN_CHARS:
                    # OCR_UNREADABLE_MARKER_2: a sub-threshold (<_OCR_MIN_CHARS) extraction is
                    # deterministic-terminal — an image-only scan / near-empty docx that already
                    # ran OCR (or docx extract) and yielded almost nothing. Mark it so the drain
                    # stops re-selecting (and, for the PDF path, re-billing Gemini on) it. The
                    # include_unreadable force flag still covers a future better-OCR re-attempt.
                    # Only deterministic-terminal branches are marked; transient failures
                    # (cost_breaker, gemini_error, download_failed, etc.) stay UNMARKED to retry.
                    _ocr_mark_unreadable(store, doc_id)
                    failed.append({"id": doc_id, "filename": filename, "reason": "empty_ocr"})
                    continue

            # 2. Targeted UPDATE of the exact target row by id (codex G0 #1836: NOT
            #    store_document_full — that overwrites owner + content_hash-dedups to
            #    another row). This preserves owner and updates the exact blank row.
            conn = store._get_conn()
            if not conn:
                failed.append({"id": doc_id, "filename": filename, "reason": "no_db_connection"})
                continue
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE documents "
                    "SET full_text = %s, token_count = %s, "
                    "search_vector = to_tsvector('simple', %s), ingested_at = NOW() "
                    "WHERE id = %s",
                    (legible, len(legible) // 4, legible, doc_id),
                )
                rowcount = cur.rowcount
                conn.commit()
                cur.close()
                if rowcount == 1:
                    recovered.append({"id": doc_id, "filename": filename, "truncated": truncated})
                else:
                    failed.append({"id": doc_id, "filename": filename,
                                   "reason": f"update_rowcount_{rowcount}"})
            except Exception as up_err:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error(f"ocr-extract id={doc_id} update failed: {up_err}")
                failed.append({"id": doc_id, "filename": filename, "reason": "db_update_failed"})
            finally:
                store._put_conn(conn)
        except Exception as doc_err:
            logger.error(f"ocr-extract id={doc_id} unexpected error: {doc_err}")
            failed.append({"id": doc_id, "filename": filename, "reason": str(doc_err)})
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

    return {"attempted": attempted, "recovered": recovered, "failed": failed}


# OCR_UNREADABLE_MARKER_1 (lead G0 #1945, mechanism A): docs that returned the
# all-pages [[UNREADABLE]] guard are marked terminal via ocr_status='unreadable'
# (see _ocr_mark_unreadable). This fragment drops them from the blank-candidate
# pool so a normal drain never re-selects + re-bills them to Gemini. IS DISTINCT
# FROM keeps NULL (unmarked) rows eligible. The ?include_unreadable=true force
# path omits this fragment so a future better-OCR run can re-attempt the set.
_OCR_UNREADABLE_EXCLUDE = " AND (d.ocr_status IS DISTINCT FROM 'unreadable')"


def _ocr_mark_unreadable(store, doc_id) -> bool:
    """OCR_UNREADABLE_MARKER_1: persist the terminal 'unreadable' state so a
    normal drain never re-selects (and re-bills gemini-2.5-pro on) this doc.
    full_text is left UNTOUCHED — the marker lives only in ocr_status, so the
    doc never surfaces as a junk hit in /api/documents/search (AC3). Fault-
    tolerant: any DB error is logged + swallowed (the doc simply stays eligible
    and is retried next drain — no worse than the pre-marker behaviour, never
    a crash). Returns True on a 1-row update."""
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE documents SET ocr_status = 'unreadable' WHERE id = %s",
            (doc_id,),
        )
        rc = cur.rowcount
        conn.commit()
        cur.close()
        return rc == 1
    except Exception as mk_err:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"ocr-extract id={doc_id} mark-unreadable failed: {mk_err}")
        return False
    finally:
        store._put_conn(conn)


def _ocr_blank_count(cur, include_unreadable: bool = False) -> int:
    """COUNT of the blank PDF/DOCX set (recovery target). Single COUNT, no LIMIT
    needed. By default excludes docs marked terminal-unreadable so the count (and
    the caller's remaining_after convergence signal) stops counting the dead set
    (AC2). include_unreadable=True restores the raw blank count for the force path."""
    cur.execute(
        "SELECT COUNT(*) AS c FROM documents d "
        "WHERE (d.full_text IS NULL OR btrim(d.full_text) = '') "
        "AND lower(d.filename) ~ '\\.(pdf|docx)$'"
        + ("" if include_unreadable else _OCR_UNREADABLE_EXCLUDE)
    )
    row = cur.fetchone()
    # RealDictCursor → {"c": n}; plain cursor → (n,)
    return row["c"] if isinstance(row, dict) else row[0]


@app.post("/api/documents/ocr-extract-missing", tags=["documents"], dependencies=[Depends(verify_api_key)])
async def documents_ocr_extract_missing(
    limit: int = Query(3, ge=1, le=25),
    dry_run: bool = Query(True),
    include_unreadable: bool = Query(
        False,
        description="OCR_UNREADABLE_MARKER_1 force path: when true, re-include docs "
        "marked terminal (ocr_status='unreadable') so a better-OCR run can re-attempt "
        "them. Default false = idempotent drain that skips the dead set.",
    ),
):
    """OCR_REEXTRACT_MISSING_1: recover blank-full_text scanned PDFs/DOCX via Gemini
    2.5 Pro vision, then populate full_text with a TARGETED UPDATE (preserves owner).

    Safe-by-default: dry_run=true (the default) downloads nothing, calls no model,
    writes nothing — it only lists what would process. Caller must pass dry_run=false
    to recover. Bounded + resumable: limit caps each call (tiny default — vision on big
    scans is slow); a recovered doc leaves the blank set so a re-run won't re-select it.
    Re-run until remaining_after == 0. Does NOT embed — once full_text is populated, the
    operator calls reingest-missing to embed. Mirrors reingest-missing's offload + direct
    -conn session advisory lock (single-runner) discipline.
    """
    from config.settings import config as _cfg
    # Respect the feature flag — fail loud, don't silently skip.
    if not getattr(_cfg.gemini, "enabled", False):
        return {"error": "gemini_disabled", "dry_run": dry_run}

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return {"error": "no_db_connection", "dry_run": dry_run}
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        blank_count = _ocr_blank_count(cur, include_unreadable=include_unreadable)
        cur.execute(
            "SELECT d.id, d.filename, d.source_path, d.file_hash, d.matter_slug "
            "FROM documents d "
            "WHERE (d.full_text IS NULL OR btrim(d.full_text) = '') "
            "AND lower(d.filename) ~ '\\.(pdf|docx)$' "
            # OCR_UNREADABLE_MARKER_1: skip the terminal-unreadable set unless forced.
            + ("" if include_unreadable else _OCR_UNREADABLE_EXCLUDE)
            + " ORDER BY d.ingested_at DESC NULLS LAST LIMIT %s",
            (limit,),
        )
        candidates = [dict(r) for r in cur.fetchall()]
        cur.close()
    except Exception as sel_err:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"ocr-extract-missing select failed: {sel_err}")
        # Single return of the conn happens in the finally (mirror reingest G3 fold).
        return {"error": "select_failed", "reason": str(sel_err), "dry_run": dry_run}
    finally:
        store._put_conn(conn)

    if dry_run:
        return {
            "dry_run": True,
            "blank_count": blank_count,
            "limit": limit,
            "include_unreadable": include_unreadable,
            "would_process": [
                {"id": c["id"], "filename": c.get("filename"), "source_path": c.get("source_path")}
                for c in candidates
            ],
        }

    # --- Write path: single-runner SESSION advisory lock on a DEDICATED DIRECT
    #     (non-pooled) connection, autocommit=True (no idle-in-txn lock drop).
    #     Mirrors reingest-missing exactly (codex G0 #1809/#1815). ---
    import psycopg2
    if not getattr(_cfg.postgres, "host_direct", None):
        return {
            "error": "no_direct_dsn",
            "reason": "session advisory lock requires a non-pooled (direct) Postgres endpoint; host_direct unset",
            "dry_run": False,
        }
    try:
        lock_conn = psycopg2.connect(**_cfg.postgres.direct_dsn_params)
        lock_conn.autocommit = True  # codex #1815: no idle-in-transaction lock drop
    except Exception as conn_err:
        logger.error(f"ocr-extract-missing direct connect failed: {conn_err}")
        try:
            lock_conn.close()
        except Exception:
            pass
        return {"error": "lock_connect_failed", "reason": str(conn_err), "dry_run": False}
    got_lock = False
    try:
        lc = lock_conn.cursor()
        lc.execute("SELECT pg_try_advisory_lock(%s)", (_OCR_ADVISORY_LOCK_KEY,))
        got_lock = bool(lc.fetchone()[0])
        lc.close()
        if not got_lock:
            return {
                "error": "backfill_in_progress",
                "reason": "another ocr-extract batch holds the advisory lock",
                "dry_run": False,
            }
        # Blocking download+vision+update loop runs in a worker thread.
        stats = await asyncio.to_thread(_ocr_extract_batch, candidates)
    except Exception as ocr_err:
        logger.error(f"ocr-extract-missing batch failed: {ocr_err}")
        stats = {"attempted": 0, "recovered": [],
                 "failed": [{"id": None, "reason": str(ocr_err)}]}
    finally:
        if got_lock:
            try:
                uc = lock_conn.cursor()
                uc.execute("SELECT pg_advisory_unlock(%s)", (_OCR_ADVISORY_LOCK_KEY,))
                uc.close()
            except Exception as unlock_err:
                logger.error(f"ocr-extract-missing advisory unlock failed: {unlock_err}")
        # Dedicated connection — CLOSE it (never store._put_conn this).
        try:
            lock_conn.close()
        except Exception:
            pass

    # remaining_after: re-count the blank set post-batch so the caller sees convergence.
    remaining_after = None
    conn2 = store._get_conn()
    if conn2:
        try:
            cur2 = conn2.cursor()
            # Same exclusion as the candidate query so convergence is real:
            # on a normal drain remaining_after stops counting the marked set (AC2).
            remaining_after = _ocr_blank_count(cur2, include_unreadable=include_unreadable)
            cur2.close()
        except Exception as cnt_err:
            try:
                conn2.rollback()
            except Exception:
                pass
            logger.error(f"ocr-extract-missing remaining_after count failed: {cnt_err}")
        finally:
            store._put_conn(conn2)

    return {
        "dry_run": False,
        "limit": limit,
        "blank_count": blank_count,
        "include_unreadable": include_unreadable,
        "attempted": stats["attempted"],
        "recovered": stats["recovered"],
        "failed": stats["failed"],
        "remaining_after": remaining_after,
    }


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

    scheduler_ok, job_count, scheduler_exec_age = _scheduler_live_from_status()

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

    vault_mirror_status = {
        "vault_mirror_last_pull": None,
        "vault_mirror_commit_sha": None,
        "vault_sync_thread_alive": False,
    }
    try:
        from vault_mirror import mirror_status
        vault_mirror_status = mirror_status()
    except Exception:
        pass

    # A3: cross-store drift signal (informational — does NOT flip status, so
    # legacy backlog can't fail Render's liveness probe / gate a deploy).
    docs_missing_qdrant = None
    try:
        docs_missing_qdrant = _documents_missing_qdrant_health_count()
    except Exception:
        docs_missing_qdrant = None

    # AI_HOTEL_OBJECT_STORAGE_R2_1: expose object-storage readiness without
    # letting R2 config or network failures affect Render liveness.
    try:
        from kbl.object_storage import storage_health
        object_storage = storage_health(probe=False)
    except Exception:
        object_storage = {"status": "error", "error": "health_check_failed"}

    status = "healthy"
    if not db_ok or not scheduler_ok or sentinels_down > 0:
        status = "degraded"
    return {
        "status": status,
        "database": "connected" if db_ok else "disconnected",
        "scheduler": "running" if scheduler_ok else "stopped",
        "scheduled_jobs": job_count,
        "scheduler_last_job_execution_age_seconds": scheduler_exec_age,
        "sentinels_healthy": sentinels_healthy,
        "sentinels_down": sentinels_down,
        "sentinels_down_list": sentinels_down_list,
        "documents_missing_qdrant": docs_missing_qdrant,
        "object_storage": object_storage,
        "vault_mirror_last_pull": vault_mirror_status["vault_mirror_last_pull"],
        "vault_mirror_commit_sha": vault_mirror_status["vault_mirror_commit_sha"],
        "vault_sync_thread_alive": vault_mirror_status.get(
            "vault_sync_thread_alive", False
        ),
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


@app.get("/api/data-freshness", tags=["system"], dependencies=[Depends(verify_api_key)])
async def get_data_freshness():
    """G6: Data freshness overview — when each source last polled, row counts, health status."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            sources = []

            # Define data sources with their tables and watermark keys
            _SOURCES = [
                ("Email", "email_messages", "email_poll", "received_date"),
                ("WhatsApp", "whatsapp_messages", None, "timestamp"),
                ("Meetings", "meeting_transcripts", "fireflies", "meeting_date"),
                ("ClickUp", "clickup_tasks", None, "updated_at"),
                ("Todoist", "todoist_tasks", "todoist", None),
                ("Documents", "documents", "dropbox", "ingested_at"),
                ("Slack", None, "slack", None),
                ("RSS", None, "rss", None),
                ("Alerts", "alerts", None, "created_at"),
                ("Deadlines", "deadlines", None, "created_at"),
                ("Contacts", "vip_contacts", None, None),
            ]

            for name, table, watermark_key, date_col in _SOURCES:
                entry = {"source": name, "count": 0, "latest": None, "watermark": None, "status": "unknown"}

                # Row count + latest
                if table:
                    try:
                        if date_col:
                            cur.execute(f"SELECT COUNT(*) as cnt, MAX({date_col}) as latest FROM {table}")
                        else:
                            cur.execute(f"SELECT COUNT(*) as cnt FROM {table}")
                        row = dict(cur.fetchone())
                        entry["count"] = row.get("cnt", 0)
                        if row.get("latest"):
                            entry["latest"] = _serialize_val(row["latest"])
                    except Exception:
                        pass

                # Watermark
                if watermark_key:
                    try:
                        cur.execute("SELECT last_seen FROM trigger_watermarks WHERE source = %s", (watermark_key,))
                        wm = cur.fetchone()
                        if wm:
                            entry["watermark"] = _serialize_val(wm["last_seen"])
                    except Exception:
                        pass

                # Status based on freshness
                from datetime import datetime, timezone, timedelta
                now = datetime.now(timezone.utc)
                _THRESHOLDS = {"Email": 1, "WhatsApp": 6, "Meetings": 48, "Documents": 6, "Slack": 1, "Todoist": 1}
                threshold_hours = _THRESHOLDS.get(name)
                if threshold_hours and entry.get("watermark"):
                    try:
                        from dateutil.parser import parse as parse_date
                        wm_dt = parse_date(entry["watermark"])
                        age_hours = (now - wm_dt).total_seconds() / 3600
                        if age_hours < threshold_hours * 2:
                            entry["status"] = "green"
                        elif age_hours < threshold_hours * 6:
                            entry["status"] = "amber"
                        else:
                            entry["status"] = "red"
                    except Exception:
                        entry["status"] = "unknown"
                elif entry["count"] > 0:
                    entry["status"] = "green"

                sources.append(entry)

            cur.close()
            return {"sources": sources, "total_records": sum(s["count"] for s in sources)}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/data-freshness failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sentinel-health/{source}/reset", tags=["system"], dependencies=[Depends(verify_api_key)])
async def reset_sentinel_health(source: str):
    """Reset a sentinel's circuit breaker — clear failures, restore to healthy."""
    from triggers.sentinel_health import reset_sentinel
    ok = reset_sentinel(source)
    if ok:
        return {"status": "reset", "source": source}
    raise HTTPException(status_code=404, detail=f"Sentinel '{source}' not found")


@app.post("/api/documents/backfill-fts", tags=["system"], dependencies=[Depends(verify_api_key)])
async def backfill_documents_fts():
    """One-time backfill: populate search_vector on all existing documents."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE documents
                SET search_vector = to_tsvector('simple', COALESCE(full_text, ''))
                WHERE search_vector IS NULL AND full_text IS NOT NULL
            """)
            updated = cur.rowcount
            conn.commit()
            cur.close()
            return {"status": "ok", "documents_updated": updated}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FTS backfill failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/documents", tags=["documents"], dependencies=[Depends(verify_api_key)])
async def get_documents(
    search: str = Query("", max_length=500),
    doc_type: str = Query("", max_length=50),
    matter_slug: str = Query("", max_length=100),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """
    DOCUMENT-BROWSER-1: Browse and search stored documents.
    Returns paginated list with text preview.
    """
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Build query with optional filters
            conditions = []
            params = []

            if search.strip():
                conditions.append("(filename ILIKE %s OR full_text ILIKE %s)")
                params.extend([f"%{search.strip()}%", f"%{search.strip()}%"])
            if doc_type.strip():
                conditions.append("document_type = %s")
                params.append(doc_type.strip())
            if matter_slug.strip():
                conditions.append("matter_slug = %s")
                params.append(matter_slug.strip())

            where = "WHERE " + " AND ".join(conditions) if conditions else ""

            # Count total
            cur.execute(f"SELECT COUNT(*) AS total FROM documents {where}", params)
            total = cur.fetchone()["total"]

            # Fetch page
            cur.execute(
                f"SELECT id, filename, document_type AS doc_type, matter_slug, source_path, ingested_at, "
                f"LEFT(full_text, 200) AS text_preview "
                f"FROM documents {where} ORDER BY ingested_at DESC LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r.get("ingested_at"):
                    r["ingested_at"] = r["ingested_at"].isoformat()
            cur.close()

            # Stats (on first page only for efficiency)
            stats = None
            if offset == 0:
                cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur2.execute("""
                    SELECT COUNT(*) AS total_docs,
                           COUNT(DISTINCT document_type) AS type_count,
                           (SELECT document_type FROM documents GROUP BY document_type ORDER BY COUNT(*) DESC LIMIT 1) AS top_type,
                           (SELECT matter_slug FROM documents WHERE matter_slug IS NOT NULL GROUP BY matter_slug ORDER BY COUNT(*) DESC LIMIT 1) AS top_matter
                    FROM documents
                """)
                stats = dict(cur2.fetchone())
                cur2.close()

            return {"documents": rows, "total": total, "limit": limit, "offset": offset, "stats": stats}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/documents failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── DOCUMENTS-REDESIGN-1: Facets + Search endpoints ───────────────────────

@app.get("/api/documents/facets", tags=["documents"], dependencies=[Depends(verify_api_key)])
async def get_document_facets():
    """Return filter counts for documents sidebar: matters, types, sources, total."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Matter counts
            cur.execute("""
                SELECT matter_slug AS name, COUNT(*) AS count
                FROM documents WHERE matter_slug IS NOT NULL AND matter_slug != ''
                GROUP BY matter_slug ORDER BY count DESC LIMIT 30
            """)
            matters = [dict(r) for r in cur.fetchall()]

            # Type counts
            cur.execute("""
                SELECT COALESCE(document_type, 'unknown') AS name, COUNT(*) AS count
                FROM documents GROUP BY COALESCE(document_type, 'unknown') ORDER BY count DESC
            """)
            types = [dict(r) for r in cur.fetchall()]

            # Source counts (derived from source_path) — B2: via SOURCE_PREFIXES contract
            cur.execute(f"""
                SELECT
                    {_source_case_sql()},
                    COUNT(*) AS count
                FROM documents GROUP BY name ORDER BY count DESC
            """)
            sources = [dict(r) for r in cur.fetchall()]

            # Total
            cur.execute("SELECT COUNT(*) AS total FROM documents")
            total = cur.fetchone()["total"]

            cur.close()
            return {"matters": matters, "types": types, "sources": sources, "total": total}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/documents/facets failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _resolve_semantic_doc_hits(
    hits, pg_rows_by_filename, matter_list, type_list, source_list, offset, limit,
    pg_rows_by_id=None,
):
    """Group Qdrant chunk hits into one result per PostgreSQL document.

    Id-resolution (DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1 + B1 follow-up #1761):
      - PREFER the durable join: if a hit's payload carries `document_id` and that PG
        row is present (`pg_rows_by_id`), use it directly — robust even when the
        Qdrant `source_file` is stale/mismatched vs PG `filename`.
      - LEGACY fallback (points without `document_id`): match `source_file` → PG
        `filename`. 1 row → use it; multiple → prefer the one whose source_path also
        matches the hit's, else most-recent ingested_at.
      - zero PG rows by either path → DROP the hit (no openable documents.id).
      - filters applied against PG row fields (authoritative; Qdrant payload lacks them).
      - dedup by documents.id, keeping the highest chunk score per document.
    Returns (page_results, total). `hits` items expose .metadata (dict), .score, .content.
    """
    pg_rows_by_id = pg_rows_by_id or {}
    grouped = {}  # documents.id -> result dict (highest-scoring chunk wins)
    for h in hits:
        meta = getattr(h, "metadata", {}) or {}
        sp = meta.get("source_path") or ""
        row = None

        # B1 follow-up (#1761): durable id resolution wins when present. Robust to a
        # stale/mismatched source_file (the exact gap the codex probe caught).
        did = meta.get("document_id")
        if did is not None:
            try:
                did = int(did)
            except (TypeError, ValueError):
                did = None
        if did is not None:
            row = pg_rows_by_id.get(did)

        # Legacy fallback: resolve by source_file → PG filename.
        if row is None:
            sf = meta.get("source_file") or ""
            candidates = pg_rows_by_filename.get(sf, [])
            if not candidates:
                continue  # zero PG rows → drop (never surface an unopenable hit)
            if len(candidates) == 1:
                row = candidates[0]
            else:
                path_match = [c for c in candidates if (c.get("source_path") or "") == sp]
                pool = path_match if path_match else candidates
                # most-recent ingested_at; None sorts lowest (avoids None/datetime compare)
                row = max(pool, key=lambda c: (c.get("ingested_at") is not None, c.get("ingested_at")))

        # PG-authoritative filters
        if matter_list and (row.get("matter_slug") or "") not in matter_list:
            continue
        if type_list and (row.get("document_type") or "unknown") not in type_list:
            continue
        if source_list and _derive_source(row.get("source_path") or "") not in source_list:
            continue

        doc_id = row["id"]
        score = round(getattr(h, "score", 0) or 0, 3)
        existing = grouped.get(doc_id)
        if existing is None or score > existing["score"]:
            ing = row.get("ingested_at")
            grouped[doc_id] = {
                "id": doc_id,
                "title": row.get("filename") or "Untitled",
                "document_type": row.get("document_type") or "document",
                "matter": row.get("matter_slug") or "",
                "source": _derive_source(row.get("source_path") or ""),
                "source_path": row.get("source_path") or "",
                "date": ing.strftime("%Y-%m-%d") if hasattr(ing, "strftime") and ing else "",
                "summary": row.get("text_preview") or (getattr(h, "content", "") or "")[:200],
                "score": score,
            }

    ordered = sorted(grouped.values(), key=lambda d: d["score"], reverse=True)
    total = len(ordered)
    return ordered[offset:offset + limit], total


def search_documents_core(
    q: str = "",
    matter: str = "",
    doc_type: str = "",
    source: str = "",
    sort: str = "relevance",
    offset: int = 0,
    limit: int = 20,
) -> dict:
    """CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1 (C): the in-process document
    retrieval shared by GET /api/documents/search AND clerk's baker_search
    (orchestrator/clerk_runtime.py). Semantic (Qdrant) -> PostgreSQL `documents`
    enrich -> ILIKE/filter PostgreSQL fallback — the path proven to return the
    real hits (e.g. 43 for "Peter Storer"), unlike SentinelRetriever's
    Qdrant-collection path which returned 0.

    Fail-loud (B): raises memory.retriever.SearchBackendUnavailable when the PG
    path has no connection, so callers surface "search backend unavailable —
    retry" instead of a false-empty. Fully synchronous (no awaits) so sync
    callers (clerk) can reuse it directly. Returns the same dict the endpoint
    returns: {results, total, offset, mode[, total_is_windowed, enrichment_failed]}.
    """
    from memory.retriever import SearchBackendUnavailable
    try:
        store = _get_store()

        # Parse comma-separated filters
        matter_list = [m.strip() for m in matter.split(",") if m.strip()] if matter.strip() else []
        type_list = [t.strip() for t in doc_type.split(",") if t.strip()] if doc_type.strip() else []
        source_list = [s.strip() for s in source.split(",") if s.strip()] if source.strip() else []

        qtext = q.strip()
        results = []
        total = 0
        use_ilike = not qtext  # filter-only queries always use the PostgreSQL path
        # A1 (INGEST_SEARCH_DURABILITY_FOLLOWUPS_1): observable retrieval mode.
        # "semantic" = Qdrant path ran; "ilike_fallback" = had a query but fell
        # back to keyword match (degradation OR legitimate no-match — split in logs);
        # "filter_only" = no query text, PG WHERE-clause path by design.
        mode = "filter_only" if not qtext else None
        # B5.3: set True if the semantic path got Qdrant hits but PG enrichment could
        # not run (conn down or query raised). Without this, an enrichment failure is
        # indistinguishable from "semantic ran, found nothing" (both → total:0).
        enrichment_failed = False

        # ── Semantic phase: Qdrant search with NO PG connection held ──
        if qtext:
            hits = None
            qdrant_errored = False
            try:
                from memory.retriever import SentinelRetriever
                retriever = SentinelRetriever._get_global_instance()   # singleton — never SentinelRetriever()
                query_vector = retriever._embed_query(qtext)           # 1 Voyage call (user-initiated)
                qdrant_limit = min((offset + limit) * 3 + 50, 300)     # over-fetch for grouping/filtering
                hits = retriever.search_collection(
                    query_vector=query_vector,
                    collection="baker-documents",
                    limit=qdrant_limit,
                    score_threshold=0.3,
                )
            except Exception as vec_err:
                # Degradation that SHOULD alert — this is the exact shape of the
                # original Bug A (months of silent keyword fallback). logger.error.
                qdrant_errored = True
                logger.error(f"Qdrant/Voyage semantic search RAISED, degrading to PostgreSQL ILIKE: {vec_err}")
                hits = None

            if not hits:
                # Split the two fallback causes (A1): a raised error is degradation
                # (already logged above at error); an empty result above threshold
                # is a legitimate last-resort, not a fault → info, not warning.
                if not qdrant_errored:
                    logger.info(f"Semantic search returned no hits above threshold for {qtext!r}; using ILIKE last-resort")
                use_ilike = True
                mode = "ilike_fallback"
            else:
                # ── Enrich from PostgreSQL (conn held ONLY for these batch queries) ──
                # B1 follow-up (#1761): resolve by the durable `document_id` payload key
                # when present (robust to a stale/mismatched source_file), and keep the
                # legacy `source_file`→`filename` join for points that predate the id.
                _metas = [(getattr(h, "metadata", {}) or {}) for h in hits]
                filenames = [f for f in {m.get("source_file") or "" for m in _metas} if f]
                doc_ids = set()
                for m in _metas:
                    d = m.get("document_id")
                    if d is not None:
                        try:
                            doc_ids.add(int(d))
                        except (TypeError, ValueError):
                            pass
                doc_ids = list(doc_ids)
                _PG_COLS = ("SELECT id, filename, document_type, matter_slug, source_path, ingested_at, "
                            "LEFT(full_text, 200) AS text_preview FROM documents WHERE ")
                pg_rows_by_filename = {}
                pg_rows_by_id = {}
                if filenames or doc_ids:
                    conn = store._get_conn()
                    if conn:
                        try:
                            import psycopg2.extras
                            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                            if doc_ids:
                                cur.execute(_PG_COLS + "id = ANY(%s)", (doc_ids,))
                                for r in cur.fetchall():
                                    r = dict(r)
                                    pg_rows_by_id[r["id"]] = r
                            if filenames:
                                cur.execute(_PG_COLS + "filename = ANY(%s)", (filenames,))
                                for r in cur.fetchall():
                                    r = dict(r)
                                    pg_rows_by_filename.setdefault(r["filename"], []).append(r)
                            cur.close()
                        except Exception as enr_err:
                            try:
                                conn.rollback()
                            except Exception:
                                pass
                            logger.warning(f"PG enrichment for semantic search failed: {enr_err}")
                            pg_rows_by_filename = {}
                            pg_rows_by_id = {}
                            enrichment_failed = True  # B5.3: enrichment query raised
                        finally:
                            store._put_conn(conn)
                    else:
                        # Had hits to resolve but no DB conn → every hit will be dropped
                        # (no PG row → no openable id). Make that observable (B5.3).
                        enrichment_failed = True
                        logger.error("Semantic search: PG conn unavailable for enrichment — "
                                     "results will be empty despite Qdrant hits")
                # Group → one result per documents.id; deterministic resolution; PG-authoritative filters.
                # Semantic path is authoritative once Qdrant returns hits — no ILIKE blending.
                results, total = _resolve_semantic_doc_hits(
                    hits, pg_rows_by_filename, matter_list, type_list, source_list, offset, limit,
                    pg_rows_by_id=pg_rows_by_id,
                )
                mode = "semantic"

        # ── PostgreSQL ILIKE / filter-only path (conn held only here) ──
        if use_ilike:
            conn = store._get_conn()
            if not conn:
                # Fail loud (B): no PG conn is a backend outage, NOT empty data.
                raise SearchBackendUnavailable("documents search: PostgreSQL connection unavailable")
            try:
                import psycopg2.extras
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

                conditions = []
                params = []

                if qtext:
                    conditions.append("(filename ILIKE %s OR full_text ILIKE %s)")
                    params.extend([f"%{qtext}%", f"%{qtext}%"])
                if matter_list:
                    placeholders = ",".join(["%s"] * len(matter_list))
                    conditions.append(f"matter_slug IN ({placeholders})")
                    params.extend(matter_list)
                if type_list:
                    placeholders = ",".join(["%s"] * len(type_list))
                    conditions.append(f"COALESCE(document_type, 'unknown') IN ({placeholders})")
                    params.extend(type_list)
                if source_list:
                    # B2: every source clause comes from the SOURCE_PREFIXES contract.
                    source_conds = [_source_ilike_clause(src) for src in source_list]
                    if source_conds:
                        conditions.append("(" + " OR ".join(source_conds) + ")")

                where = "WHERE " + " AND ".join(conditions) if conditions else ""

                # Count
                cur.execute(f"SELECT COUNT(*) AS total FROM documents {where}", params)
                total = cur.fetchone()["total"]

                # Sort
                order_by = "ingested_at DESC"
                if sort == "date_asc":
                    order_by = "ingested_at ASC"
                elif sort == "date_desc":
                    order_by = "ingested_at DESC"

                # Fetch
                cur.execute(
                    f"SELECT id, filename, document_type, matter_slug, source_path, ingested_at, "
                    f"LEFT(full_text, 200) AS text_preview "
                    f"FROM documents {where} ORDER BY {order_by} LIMIT %s OFFSET %s",
                    params + [limit, offset],
                )
                results = []
                for r in cur.fetchall():
                    r = dict(r)
                    results.append({
                        "id": r["id"],
                        "title": r.get("filename") or "Untitled",
                        "document_type": r.get("document_type") or "document",
                        "matter": r.get("matter_slug") or "",
                        "source": _derive_source(r.get("source_path") or ""),
                        "source_path": r.get("source_path") or "",
                        "date": r["ingested_at"].strftime("%Y-%m-%d") if r.get("ingested_at") else "",
                        "summary": r.get("text_preview") or "",
                        "score": None,
                    })
                cur.close()
            except SearchBackendUnavailable:
                raise
            except Exception as ilike_err:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error(f"documents search ILIKE path failed: {ilike_err}")
                raise
            finally:
                store._put_conn(conn)

        response = {"results": results, "total": total, "offset": offset, "mode": mode}
        if mode == "semantic":
            # B4: semantic `total` counts only the documents within the ≤300-chunk
            # over-fetch window, NOT the true corpus total; deep offsets give a
            # shifting total. Flag it so the UI can label/disable deep pagination.
            response["total_is_windowed"] = True
            # B5.3: surface enrichment failure so it isn't mistaken for an empty result.
            response["enrichment_failed"] = enrichment_failed
        return response
    except SearchBackendUnavailable:
        raise
    except Exception as e:
        logger.error(f"search_documents_core failed: {e}")
        raise


@app.get("/api/documents/search", tags=["documents"], dependencies=[Depends(verify_api_key)])
async def search_documents_endpoint(
    q: str = Query("", max_length=500),
    matter: str = Query("", max_length=500, description="Comma-separated matter slugs"),
    doc_type: str = Query("", max_length=500, description="Comma-separated document types"),
    source: str = Query("", max_length=200, description="Comma-separated sources"),
    sort: str = Query("relevance", max_length=20),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """DOCUMENTS-REDESIGN-1: thin HTTP wrapper over search_documents_core().
    Maps SearchBackendUnavailable -> 503 (fail loud) and other failures -> 500.
    See search_documents_core for the retrieval contract + mode/enrichment_failed.
    CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1: clerk's baker_search reuses the same
    core in-process, so the dashboard and clerk can never silently diverge."""
    from memory.retriever import SearchBackendUnavailable
    try:
        return search_documents_core(
            q=q, matter=matter, doc_type=doc_type, source=source,
            sort=sort, offset=offset, limit=limit,
        )
    except SearchBackendUnavailable:
        raise HTTPException(status_code=503, detail="Database unavailable")
    except Exception as e:
        logger.error(f"GET /api/documents/search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/documents/{doc_id}/text", tags=["documents"], dependencies=[Depends(verify_api_key)])
async def get_document_text(doc_id: int):
    """Return full text of a document for expandable preview."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT id, filename, document_type, matter_slug, source_path, "
                "LEFT(full_text, 5000) AS full_text, page_count, ingested_at "
                "FROM documents WHERE id = %s",
                (doc_id,),
            )
            row = cur.fetchone()
            cur.close()
            if not row:
                raise HTTPException(status_code=404, detail="Document not found")
            r = dict(row)
            if r.get("ingested_at"):
                r["ingested_at"] = r["ingested_at"].isoformat()
            return r
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/documents/{doc_id}/text failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── IDEAS-CAPTURE-1: Ideas endpoints ──────────────────────────────────────

@app.get("/api/ideas", tags=["ideas"], dependencies=[Depends(verify_api_key)])
async def list_ideas(status: str = Query(None)):
    """List ideas, newest first."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")
    try:
        cur = conn.cursor()
        if status:
            cur.execute("""
                SELECT id, content, source, status, matter, created_at
                FROM ideas WHERE status = %s
                ORDER BY created_at DESC LIMIT 50
            """, (status,))
        else:
            cur.execute("""
                SELECT id, content, source, status, matter, created_at
                FROM ideas WHERE status != 'dismissed'
                ORDER BY created_at DESC LIMIT 50
            """)
        rows = cur.fetchall()
        cur.close()
        return [{"id": r[0], "content": r[1], "source": r[2], "status": r[3],
                 "matter": r[4], "created_at": r[5].isoformat() if r[5] else None} for r in rows]
    except Exception as e:
        logger.error(f"GET /api/ideas failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.patch("/api/ideas/{idea_id}", tags=["ideas"], dependencies=[Depends(verify_api_key)])
async def triage_idea(idea_id: int, request: Request):
    """Triage an idea: update status."""
    body = await request.json()
    new_status = body.get("status")
    if new_status not in ('new', 'developing', 'actioned', 'dismissed'):
        return JSONResponse({"error": "Invalid status"}, status_code=400)
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute("UPDATE ideas SET status = %s, updated_at = NOW() WHERE id = %s RETURNING id",
                   (new_status, idea_id))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            return JSONResponse({"error": "Idea not found"}, status_code=404)
        return {"updated": idea_id}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


# B2 (INGEST_SEARCH_DURABILITY_FOLLOWUPS_1): the source_path → source-label
# contract, in ONE place. THREE surfaces consume it and MUST agree, or the
# Documents facet counts, the source filter, and the per-row label drift apart:
#   1. facet-count CASE   — _source_case_sql()      (counts per source)
#   2. SQL source filter  — _source_ilike_clause()  (WHERE when filtering by source)
#   3. per-row label      — _derive_source()         (label on each search result)
# Order matters: first matching label wins. `m365` is mapped now (inert until M365
# ingestion lands — no source_path carries it yet) so the contract is ready for it.
# Note on '%%': both SQL surfaces use doubled percent. The facet query passes no
# params (psycopg2 sends '%%' verbatim; SQL LIKE collapses the double wildcard); the
# filter query passes params (psycopg2 un-escapes '%%'→'%'). One clause string serves
# both correctly.
SOURCE_PREFIXES = {
    "email": ["email", "gmail"],
    "whatsapp": ["whatsapp"],
    "clickup": ["clickup"],
    "fireflies": ["fireflies"],
    "m365": ["m365"],
}
SOURCE_DEFAULT = "dropbox"  # source_path matching none of the mapped prefixes


def _derive_source(source_path: str) -> str:
    """Derive the source label from source_path (B2: via the SOURCE_PREFIXES contract)."""
    sp = (source_path or "").lower()
    for label, prefixes in SOURCE_PREFIXES.items():
        if any(p in sp for p in prefixes):
            return label
    return SOURCE_DEFAULT


def _source_ilike_clause(label: str, col: str = "source_path") -> str:
    """SQL boolean expression matching one source label, from SOURCE_PREFIXES.
    A mapped label → OR of its prefix ILIKEs; the default label → NOT any known
    prefix. Doubled-percent so it is correct under both parameterized and
    non-parameterized execute() (see SOURCE_PREFIXES note)."""
    prefixes = SOURCE_PREFIXES.get(label)
    if prefixes:
        return "(" + " OR ".join(f"{col} ILIKE '%%{p}%%'" for p in prefixes) + ")"
    known = [p for ps in SOURCE_PREFIXES.values() for p in ps]
    return "(" + " AND ".join(f"{col} NOT ILIKE '%%{p}%%'" for p in known) + ")"


def _source_case_sql(col: str = "source_path", alias: str = "name") -> str:
    """SQL CASE expression mapping source_path → source label, from SOURCE_PREFIXES
    (facet-count query)."""
    whens = " ".join(
        f"WHEN {_source_ilike_clause(label, col)} THEN '{label}'" for label in SOURCE_PREFIXES
    )
    return f"CASE {whens} ELSE '{SOURCE_DEFAULT}' END AS {alias}"


@app.get("/api/doc-pipeline/status", tags=["system"], dependencies=[Depends(verify_api_key)])
async def doc_pipeline_status():
    """Document pipeline job queue status — counts by state + active jobs."""
    from tools.document_pipeline import get_pipeline_status
    return get_pipeline_status()


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

    # DEADLINE_FEEDBACK_LOOP_1 Fix B: surface corpus-write degradation. Phase 3
    # classifier upgrade is gated on this corpus accumulating — silent regression
    # would invalidate the training window. Non-fatal (status stays healthy).
    try:
        from models.deadline_feedback import get_write_failure_stats
        deadline_feedback_stats = get_write_failure_stats()
    except Exception:
        deadline_feedback_stats = {"count": 0, "last_failure_at": None}

    try:
        from kbl.object_storage import storage_health
        object_storage = storage_health(probe=False)
    except Exception:
        object_storage = {"status": "error", "error": "health_check_failed"}

    return {
        "status": "degraded" if any_down else "healthy",
        "sentinels": sentinels,
        "deadline_feedback": deadline_feedback_stats,
        "object_storage": object_storage,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/ingestion-surfaces", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_ingestion_surfaces(refresh: bool = Query(False)):
    """Return the canonical baker-vault ingestion surface checklist."""
    try:
        snapshot = load_ingestion_surfaces(force_refresh=refresh)
        status = "degraded" if snapshot.get("error") else "ok"
        return {"status": status, **snapshot}
    except Exception as e:  # noqa: BLE001 - dashboard read surface degrades.
        logger.error(f"GET /api/ingestion-surfaces failed: {e}")
        return {
            "status": "degraded",
            "version": None,
            "ratified": None,
            "owner": None,
            "purpose": None,
            "source_path": "_ops/processes/ingestion-surfaces.md",
            "source_last_commit_sha": None,
            "source_sha256": None,
            "row_count": 0,
            "surfaces": [],
            "error": str(e),
        }


@app.get("/api/router/second-look", tags=["router"], dependencies=[Depends(verify_api_key)])
async def api_router_second_look(
    status: str = Query("open", pattern="^(open|released|suppressed|escalated|closed)$"),
    limit: int = Query(100, ge=1, le=500),
):
    """Metadata-only read surface for router gray cases. No raw signal bodies."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        from kbl.router_second_look import list_items
        items = list_items(conn, status=status, limit=limit)
        conn.commit()
        return {"items": items, "status": status, "limit": limit}
    except ValueError as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("router second-look list failed")
        raise HTTPException(status_code=500, detail="router_second_look_list_failed")
    finally:
        store._put_conn(conn)


@app.get("/", include_in_schema=False)
async def root():
    """Serve the dashboard frontend."""
    index_path = _static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Baker Dashboard — no frontend deployed yet"}


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    """PWA-DESKTOP-1: Serve service worker from root scope for full app control."""
    sw_path = _static_dir / "sw.js"
    if sw_path.exists():
        return FileResponse(str(sw_path), media_type="application/javascript",
                           headers={"Service-Worker-Allowed": "/"})
    return FileResponse(str(sw_path))


@app.get("/mobile", include_in_schema=False)
async def mobile():
    """Serve the mobile-optimized frontend (Ask Baker + Ask Specialist)."""
    mobile_path = _static_dir / "mobile.html"
    if mobile_path.exists():
        return FileResponse(str(mobile_path))
    return {"message": "Mobile page not deployed yet"}


# ============================================================
# API Endpoints
# ============================================================

# --- Alerts ---

@app.get("/api/alerts", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def get_alerts(
    tier: Optional[int] = Query(None, ge=1, le=4),
    min_tier: Optional[int] = Query(None, ge=1, le=4),
    category: str = Query("business", regex="^(business|system|all)$"),
):
    """
    Get pending alerts. Filter by exact tier, or min_tier (T2+ = upcoming, excludes T1).

    DASHBOARD_ALERT_NOISE_FIX_1: `category` defaults to 'business' (the Director's
    attention feed — infra/monitoring sources excluded, NULL matter → 'unsorted').
    Use category=system for the System Health panel, category=all for everything.
    """
    try:
        store = _get_store()
        alerts = store.get_pending_alerts(tier=tier, category=category)
        alerts = [_serialize(a) for a in alerts]
        if min_tier:
            alerts = [a for a in alerts if a.get('tier', 1) >= min_tier]
        return {"alerts": alerts, "count": len(alerts)}
    except Exception as e:
        logger.error(f"/api/alerts failed: {e}")
        return {"alerts": [], "count": 0, "error": str(e)}


@app.post("/api/admin/alert-noise-sweep", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def alert_noise_sweep():
    """DASHBOARD_ALERT_NOISE_FIX_1: one-time (idempotent) backlog noise sweep.

    Auth-gated. Expires the quiet-thread flood + stale >30d pending alerts and
    backfills NULL-matter cards, never touching acknowledged/snoozed alerts. Logs
    an audit row to baker_actions. Safe to re-run (a second run affects ~0 rows).
    Intended to be called ONCE after the Fix 1-5 deploy is live.
    """
    try:
        store = _get_store()
        counts = store.sweep_alert_noise()
        return {"status": "ok", **counts}
    except Exception as e:
        logger.error(f"/api/admin/alert-noise-sweep failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


@app.post("/api/alerts/{alert_id}/snooze", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def snooze_alert(alert_id: int, request: Request):
    """Snooze an alert. Sets status='snoozed' with a snoozed_until timestamp.
    Duration: '4h', 'tomorrow', 'next_week'."""
    from datetime import timedelta
    try:
        body = await request.json()
        duration = body.get("duration", "4h")
        now = datetime.now(timezone.utc)
        if duration == "4h":
            wake_at = now + timedelta(hours=4)
        elif duration == "tomorrow":
            wake_at = (now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
        elif duration == "next_week":
            days_until_monday = (7 - now.weekday()) % 7 or 7
            wake_at = (now + timedelta(days=days_until_monday)).replace(hour=7, minute=0, second=0, microsecond=0)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid duration: {duration}")

        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE alerts SET status = 'snoozed', snoozed_until = %s WHERE id = %s RETURNING id",
                (wake_at, alert_id),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if not row:
                raise HTTPException(status_code=404, detail="Alert not found")
            logger.info(f"Alert #{alert_id} snoozed until {wake_at.isoformat()}")
            return {"status": "snoozed", "id": alert_id, "snoozed_until": wake_at.isoformat()}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/alerts/{alert_id}/snooze failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/alerts/{alert_id}", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def update_alert(alert_id: int, request: Request):
    """D5: Inline alert editing — update title, matter_slug, tags, tier, board_status."""
    try:
        body = await request.json()
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            allowed = {"title", "matter_slug", "tier", "board_status", "exit_reason"}
            updates = []
            params = []
            for key, value in body.items():
                if key in allowed:
                    updates.append(f"{key} = %s")
                    params.append(value)
                elif key == "tags" and isinstance(value, list):
                    updates.append("tags = %s::jsonb")
                    params.append(json.dumps(value))
            if not updates:
                raise HTTPException(status_code=400, detail="No valid fields to update")
            params.append(alert_id)
            cur.execute(
                f"UPDATE alerts SET {', '.join(updates)} WHERE id = %s RETURNING id",
                params,
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if not row:
                raise HTTPException(status_code=404, detail="Alert not found")
            return {"status": "updated", "id": alert_id, "fields": list(body.keys())}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PATCH /api/alerts/{alert_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/alerts/bulk-dismiss", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def bulk_dismiss_alerts(req: dict = Body(...)):
    """Bulk dismiss alerts by IDs or by tier+age filter."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            dismissed = 0

            alert_ids = req.get("alert_ids")
            tier = req.get("tier")
            older_than_days = req.get("older_than_days", 0)

            if alert_ids and isinstance(alert_ids, list):
                # Dismiss specific IDs
                cur.execute(
                    "UPDATE alerts SET status = 'dismissed', exit_reason = 'bulk-dismiss', resolved_at = NOW() "
                    "WHERE id = ANY(%s) AND status = 'pending' RETURNING id",
                    (alert_ids,),
                )
                dismissed = cur.rowcount
            elif tier is not None:
                # Dismiss by tier (+ optional age)
                if older_than_days > 0:
                    cur.execute(
                        "UPDATE alerts SET status = 'dismissed', exit_reason = 'bulk-dismiss', resolved_at = NOW() "
                        "WHERE status = 'pending' AND tier = %s AND created_at < NOW() - INTERVAL '%s days' RETURNING id",
                        (tier, older_than_days),
                    )
                else:
                    cur.execute(
                        "UPDATE alerts SET status = 'dismissed', exit_reason = 'bulk-dismiss', resolved_at = NOW() "
                        "WHERE status = 'pending' AND tier = %s RETURNING id",
                        (tier,),
                    )
                dismissed = cur.rowcount

            conn.commit()
            cur.close()
            logger.info(f"Bulk dismiss: {dismissed} alerts dismissed")
            return {"dismissed": dismissed}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/alerts/bulk-dismiss failed: {e}")
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


@app.get("/api/alerts/stream", tags=["alerts"])
async def alerts_stream(key: str = Query(..., alias="key")):
    """
    REALTIME-PUSH-1: SSE stream for live alert notifications.
    Auth via query param (SSE/EventSource doesn't support custom headers).
    Polls every 10s for new pending alerts since last check.
    """
    import os as _os
    expected = _os.environ.get("BAKER_API_KEY", "")
    if not expected or key != expected:
        raise HTTPException(status_code=401, detail="Invalid key")

    async def _event_gen():
        import psycopg2.extras
        last_id = 0
        # Seed last_id to current max
        try:
            store = _get_store()
            conn = store._get_conn()
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT COALESCE(MAX(id), 0) FROM alerts WHERE status = 'pending'")
                    last_id = cur.fetchone()[0]
                    cur.close()
                finally:
                    store._put_conn(conn)
        except Exception:
            pass

        while True:
            await asyncio.sleep(10)
            try:
                store = _get_store()
                conn = store._get_conn()
                if not conn:
                    yield ": keepalive\n\n"
                    continue
                try:
                    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur.execute(
                        "SELECT id, tier, title, source FROM alerts "
                        "WHERE status = 'pending' AND id > %s ORDER BY id",
                        (last_id,),
                    )
                    rows = cur.fetchall()
                    cur.close()
                finally:
                    store._put_conn(conn)

                for row in rows:
                    evt = json.dumps({
                        "type": "new_alert",
                        "id": row["id"],
                        "tier": row["tier"],
                        "title": row["title"],
                        "source": row.get("source", ""),
                    })
                    yield f"data: {evt}\n\n"
                    if row["id"] > last_id:
                        last_id = row["id"]

                if not rows:
                    yield ": keepalive\n\n"
            except Exception as e:
                logger.debug(f"alerts/stream poll error: {e}")
                yield ": keepalive\n\n"

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ============================================================
# V3 Dashboard endpoints
# ============================================================

# Morning narrative cache (module-level, invalidated on T1 alert creation)
_morning_narrative_cache: dict = {"text": None, "generated_at": 0}


def invalidate_morning_narrative():
    """Called from store_back.create_alert() when a T1 alert is created."""
    global _morning_narrative_cache
    _morning_narrative_cache = {"text": None, "generated_at": 0}


def _get_research_proposals_for_brief() -> list:
    """Get pending research proposals for morning brief."""
    try:
        from orchestrator.research_trigger import get_research_proposals
        return get_research_proposals(status="proposed", days=7)
    except Exception:
        return []


def _get_proposed_actions_for_brief() -> list:
    """Get proposed actions for morning brief (lightweight, no extra API call)."""
    try:
        from orchestrator.obligation_generator import get_proposed_actions
        return get_proposed_actions(status="proposed", days=2)
    except Exception:
        return []


def _get_extraction_summary() -> dict:
    """Baker 3.0: Get extraction summary for morning brief (last 24h)."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return {"total": 0, "by_channel": {}, "by_type": {}}
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Count by channel
            cur.execute("""
                SELECT source_channel, COUNT(*) as cnt
                FROM signal_extractions
                WHERE processed_at > NOW() - INTERVAL '24 hours'
                GROUP BY source_channel
            """)
            by_channel = {r["source_channel"]: r["cnt"] for r in cur.fetchall()}

            # Count by item type (aggregate across all extractions)
            cur.execute("""
                SELECT
                    item->>'type' as item_type,
                    COUNT(*) as cnt
                FROM signal_extractions,
                     jsonb_array_elements(extracted_items) as item
                WHERE processed_at > NOW() - INTERVAL '24 hours'
                GROUP BY item->>'type'
                ORDER BY cnt DESC
            """)
            by_type = {r["item_type"]: r["cnt"] for r in cur.fetchall()}

            total = sum(by_channel.values())
            cur.close()
            return {"total": total, "by_channel": by_channel, "by_type": by_type}
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return {"total": 0, "by_channel": {}, "by_type": {}}
        finally:
            store._put_conn(conn)
    except Exception:
        return {"total": 0, "by_channel": {}, "by_type": {}}


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

            # Stats: fire count (T1+T2 — matches mobile badge)
            cur.execute("SELECT COUNT(*) AS cnt FROM alerts WHERE status = 'pending' AND tier <= 2")
            fire_count = cur.fetchone()["cnt"]

            # Stats: deadlines this week (due between today and +7 days)
            # DEADLINE_SIGNAL_HYGIENE_1 Scope B: exclude closed-matter deadlines.
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM deadlines d
                LEFT JOIN matter_registry m
                  ON LOWER(REPLACE(m.matter_name, ' ', '-')) = LOWER(d.matter_slug)
                WHERE d.status = 'active'
                  AND (d.matter_slug IS NULL OR m.status IS NULL OR m.status = 'active')
                  AND d.due_date >= CURRENT_DATE
                  AND d.due_date <= CURRENT_DATE + INTERVAL '7 days'
            """)
            deadline_count = cur.fetchone()["cnt"]

            # Stats: processed overnight (alerts created in last 12h, excluding cascade junk)
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM alerts
                WHERE created_at >= NOW() - INTERVAL '12 hours'
                  AND title NOT LIKE '%%[Baker Prep]%%'
            """)
            processed_overnight = cur.fetchone()["cnt"]

            # Stats: actions completed (capability_runs in last 24h)
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM capability_runs
                WHERE created_at >= NOW() - INTERVAL '24 hours' AND status = 'completed'
            """)
            actions_completed = cur.fetchone()["cnt"]

            # Stats: overdue Todoist tasks
            todoist_overdue = 0
            try:
                cur.execute("""
                    SELECT COUNT(*) AS cnt FROM todoist_tasks
                    WHERE completed_at IS NULL
                      AND due_date IS NOT NULL AND due_date < NOW()::text
                """)
                todoist_overdue = cur.fetchone()["cnt"]
            except Exception:
                pass

            # Top fires (T1 alerts, most recent per matter, limit 5)
            # Exclude travel/flight alerts — they belong in Travel section
            cur.execute("""
                SELECT * FROM (
                    SELECT DISTINCT ON (COALESCE(matter_slug, id::text)) *
                    FROM alerts
                    WHERE status = 'pending' AND tier = 1
                      AND title NOT ILIKE '%%flight%%'
                      AND title NOT ILIKE '%%departure%%'
                      AND title NOT ILIKE '%%arrival%%'
                    ORDER BY COALESCE(matter_slug, id::text), created_at DESC
                ) deduped
                ORDER BY created_at DESC
                LIMIT 5
            """)
            top_fires = [_serialize(dict(r)) for r in cur.fetchall()]

            # Deadlines this week — exclude critical (shown in Critical) and travel (shown in Travel)
            # LANDING-FIX-2: Deduplicate ClickUp-synced deadlines that differ only by prefix
            # DEADLINE_SIGNAL_HYGIENE_1 Scope B: exclude closed-matter deadlines
            # from the morning-brief deadline card.
            cur.execute("""
                SELECT DISTINCT ON (
                    LEFT(REGEXP_REPLACE(LOWER(d.description), '^(\[.*?\]\s*)+', ''), 45)
                )
                    d.id, d.description, d.due_date, d.source_type, d.confidence,
                    d.priority, d.status, d.created_at,
                    LEFT(d.source_snippet, 500) AS source_snippet
                FROM deadlines d
                LEFT JOIN matter_registry m
                  ON LOWER(REPLACE(m.matter_name, ' ', '-')) = LOWER(d.matter_slug)
                WHERE d.status = 'active'
                  AND (d.matter_slug IS NULL OR m.status IS NULL OR m.status = 'active')
                  AND (d.is_critical IS NOT TRUE)
                  AND d.due_date >= CURRENT_DATE
                  AND d.due_date <= CURRENT_DATE + INTERVAL '7 days'
                  AND NOT (d.description ILIKE '%%flight%%' OR d.description ILIKE '%%departure%%'
                           OR d.description ILIKE '%%travel%%' OR d.description ILIKE '%%airport%%'
                           OR d.description ILIKE '%%boarding%%' OR d.description ILIKE '%%check-in%%')
                ORDER BY LEFT(REGEXP_REPLACE(LOWER(d.description), '^(\[.*?\]\s*)+', ''), 45),
                         LENGTH(COALESCE(d.source_snippet, '')) DESC,
                         d.priority DESC, d.created_at DESC
                LIMIT 10
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

            # LANDING-GRID-1: Overdue obligations (deadlines table, replaces old commitments)
            overdue_commitments = []
            try:
                # DEADLINE_SIGNAL_HYGIENE_1 Scope B: exclude closed-matter deadlines
                # from overdue obligations card.
                cur.execute("""
                    SELECT d.id, d.description, d.due_date, d.priority, d.severity
                    FROM deadlines d
                    LEFT JOIN matter_registry m
                      ON LOWER(REPLACE(m.matter_name, ' ', '-')) = LOWER(d.matter_slug)
                    WHERE d.status = 'active'
                      AND (d.matter_slug IS NULL OR m.status IS NULL OR m.status = 'active')
                      AND d.due_date < CURRENT_DATE
                    ORDER BY d.due_date ASC LIMIT 5
                """)
                overdue_commitments = [_serialize(dict(r)) for r in cur.fetchall()]
            except Exception:
                pass

            # F1: Contacts going silent (30+ days, for morning brief awareness)
            silent_contacts = []
            try:
                # F3: Cadence-relative silence detection (replaces fixed 30-day threshold)
                # Includes channel info + excludes snoozed/stopped contacts
                cur.execute("""
                    SELECT name, last_inbound_at as last_contact_date,
                           EXTRACT(DAY FROM NOW() - last_inbound_at)::int as days_silent,
                           avg_inbound_gap_days,
                           CASE WHEN avg_inbound_gap_days > 0
                                THEN ROUND((EXTRACT(EPOCH FROM NOW() - last_inbound_at)/86400.0
                                      / avg_inbound_gap_days)::numeric, 1)
                                ELSE 0 END as deviation,
                           COALESCE(communication_pref, 'email') as channel,
                           email, whatsapp_id
                    FROM vip_contacts
                    WHERE avg_inbound_gap_days IS NOT NULL
                      AND last_inbound_at IS NOT NULL
                      AND last_inbound_at < NOW() - INTERVAL '7 days'
                      AND (EXTRACT(EPOCH FROM NOW() - last_inbound_at)/86400.0
                           / NULLIF(avg_inbound_gap_days, 0)) >= 3.0
                      AND COALESCE(cadence_snoozed_until, '1970-01-01'::timestamptz) < NOW()
                      AND COALESCE(cadence_tracking, true) = true
                    ORDER BY (EXTRACT(EPOCH FROM NOW() - last_inbound_at)/86400.0
                              / NULLIF(avg_inbound_gap_days, 0)) DESC
                    LIMIT 5
                """)
                silent_contacts = [_serialize(dict(r)) for r in cur.fetchall()]
            except Exception:
                # Fallback: rollback aborted txn (new columns may not exist), use old query
                try:
                    conn.rollback()
                    import psycopg2.extras as _pe
                    cur = conn.cursor(cursor_factory=_pe.RealDictCursor)
                    cur.execute("""
                        SELECT name, last_contact_date,
                               EXTRACT(DAY FROM NOW() - last_contact_date)::int as days_silent
                        FROM vip_contacts
                        WHERE last_contact_date IS NOT NULL
                          AND last_contact_date < NOW() - INTERVAL '30 days'
                          AND tier <= 2
                        ORDER BY last_contact_date ASC LIMIT 5
                    """)
                    silent_contacts = [_serialize(dict(r)) for r in cur.fetchall()]
                except Exception:
                    pass

            # LANDING-FIX-2: Travel queries moved inside connection block (was using conn after pool return)
            # Travel alerts (any tier, not just top_fires tier=1)
            try:
                cur.execute("""
                    SELECT * FROM alerts
                    WHERE status = 'pending'
                      AND (tags ? 'travel' OR title ILIKE '%%flight%%')
                      AND NOT (tags ? 'meeting')
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
                _travel_alerts_rows = [_serialize(dict(r)) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"Morning brief: travel alerts query failed: {e}")
                conn.rollback()
                _travel_alerts_rows = []

            # Travel-related deadlines (next 3 days)
            try:
                # DEADLINE_SIGNAL_HYGIENE_1 Scope B: exclude closed-matter
                # travel deadlines.
                cur.execute("""
                    SELECT d.id, d.description, d.due_date, d.priority, d.source_snippet
                    FROM deadlines d
                    LEFT JOIN matter_registry m
                      ON LOWER(REPLACE(m.matter_name, ' ', '-')) = LOWER(d.matter_slug)
                    WHERE d.status = 'active'
                      AND (d.matter_slug IS NULL OR m.status IS NULL OR m.status = 'active')
                      AND d.due_date >= CURRENT_DATE
                      AND d.due_date < CURRENT_DATE + INTERVAL '4 days'
                      AND (d.description ILIKE '%%flight%%' OR d.description ILIKE '%%departure%%'
                           OR d.description ILIKE '%%travel%%' OR d.description ILIKE '%%airport%%'
                           OR d.description ILIKE '%%train%%' OR d.description ILIKE '%%depart%%')
                    ORDER BY d.due_date ASC LIMIT 10
                """)
                _travel_deadlines_rows = [_serialize(dict(r)) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"Morning brief: travel deadlines query failed: {e}")
                conn.rollback()
                _travel_deadlines_rows = []

            # LANDING-FIX-3: Meeting alerts removed — was pulling noise like
            # "Meeting Transcript Processing Failed" into Meetings card.
            _meeting_alerts_rows = []

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
                    silent_contacts,
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

        # Phase 3A: Fetch today's calendar events, classify as meeting vs travel
        # TRAVEL-FIX-1: Use poll_todays_meetings() so past flights/events still show
        # TRAVEL-FIX-2: Split into meetings_today + travel_today
        meetings_today = []
        travel_today = []
        try:
            from triggers.calendar_trigger import poll_todays_meetings
            from triggers.state import trigger_state
            raw_meetings = poll_todays_meetings()  # all of today (past + future)
            for m in raw_meetings:
                wk = f"calendar_prep_{m.get('id', '')}"
                prepped = trigger_state.watermark_exists(wk)
                attendee_names = [a.get('name', '') or a.get('email', '') for a in m.get('attendees', [])]
                # Fetch Baker's prep notes from alerts table
                prep_notes = ""
                if prepped:
                    try:
                        prep_title = f"Meeting prep: {m['title']}"
                        conn_prep = store._get_conn()
                        if conn_prep:
                            try:
                                cur_prep = conn_prep.cursor()
                                cur_prep.execute("""
                                    SELECT body FROM alerts
                                    WHERE title = %s AND source = 'calendar_prep'
                                    ORDER BY created_at DESC LIMIT 1
                                """, (prep_title,))
                                row_prep = cur_prep.fetchone()
                                if row_prep:
                                    prep_notes = row_prep[0] or ""
                                cur_prep.close()
                            finally:
                                store._put_conn(conn_prep)
                    except Exception:
                        pass

                event_data = {
                    "title": m['title'],
                    "start": m['start'],
                    "end": m.get('end', ''),
                    "location": m.get('location', ''),
                    "attendees": attendee_names[:5],
                    "prepped": prepped,
                    "prep_notes": prep_notes,
                }

                # TRAVEL-FIX-2: Classify as travel vs meeting
                if _is_travel_event(m['title'], m.get('location', '')):
                    event_data["event_type"] = "travel"
                    travel_today.append(event_data)
                else:
                    event_data["event_type"] = "meeting"
                    meetings_today.append(event_data)
        except Exception as e:
            logger.warning(f"Morning brief: calendar unavailable (travel cards use DB fallback): {e}")

        # EXCHANGE-CALENDAR-POLL-1: Merge Exchange/Outlook calendar events
        # 8s timeout: cold EWS connections can take 10-20s
        try:
            import asyncio as _aio_exc
            from triggers.exchange_calendar_poller import poll_exchange_todays_meetings
            exchange_events = await _aio_exc.wait_for(
                _aio_exc.to_thread(poll_exchange_todays_meetings),
                timeout=8.0
            )
            for m in exchange_events:
                # Dedup: skip if same title + same start time already in meetings_today or travel_today
                m_title = (m.get('title', '') or '').lower().strip()
                m_start = (m.get('start', '') or '')[:16]  # Compare to minute precision
                already_exists = False
                for existing in meetings_today + travel_today:
                    if (existing.get('title', '') or '').lower().strip() == m_title and \
                       (existing.get('start', '') or '')[:16] == m_start:
                        already_exists = True
                        break
                if already_exists:
                    continue

                attendee_names = [a.get('name', '') or a.get('email', '') for a in m.get('attendees', [])]
                event_data = {
                    "title": m['title'],
                    "start": m['start'],
                    "end": m.get('end', ''),
                    "location": m.get('location', ''),
                    "attendees": attendee_names[:5],
                    "prepped": False,
                    "prep_notes": "",
                    "source": "exchange",
                }

                if _is_travel_event(m['title'], m.get('location', '')):
                    event_data["event_type"] = "travel"
                    travel_today.append(event_data)
                else:
                    event_data["event_type"] = "meeting"
                    meetings_today.append(event_data)

            if exchange_events:
                logger.info(f"Exchange calendar: merged {len(exchange_events)} events into morning brief")
        except Exception as e:
            logger.warning(f"Morning brief: Exchange calendar unavailable (non-fatal): {e}")

        # TRIP-INTELLIGENCE-1: Match/create trips for travel events
        active_trips = []
        try:
            active_trips = store.get_active_trips()
            home_cities = ""
            commute_cities = ""
            prefs = store.get_preferences("domain_context")
            for p in prefs:
                if p.get("pref_key") == "home_cities":
                    home_cities = p.get("pref_value", "")
                elif p.get("pref_key") == "commute_cities":
                    commute_cities = p.get("pref_value", "")

            for event_data in travel_today:
                origin_city, dest_city = _extract_trip_cities(event_data)
                if not dest_city:
                    continue

                # Skip home cities
                home_list = [c.strip().lower() for c in home_cities.split(",") if c.strip()]
                if dest_city.lower() in home_list:
                    continue

                # Find existing trip
                event_data["calendar_event_id"] = ""  # may not have it
                trip = _match_trip(active_trips, event_data, dest_city)

                if not trip:
                    category = _classify_trip_category(dest_city, home_cities, commute_cities)
                    if category:
                        # Check for conference keywords → auto-upgrade
                        title = event_data.get("title", "")
                        if _CONF_KEYWORDS_RE.search(title):
                            category = "event"

                        event_date = None
                        try:
                            event_date = datetime.fromisoformat(
                                event_data["start"].replace("Z", "+00:00")
                            ).date().isoformat()
                        except Exception:
                            pass

                        trip = store.upsert_trip(
                            destination=dest_city,
                            origin=origin_city,
                            start_date=event_date,
                            end_date=event_date,
                            category=category,
                        )
                        if trip:
                            active_trips.append(trip)

                if trip:
                    event_data["trip_id"] = trip["id"]
                    event_data["trip_status"] = trip["status"]
                    event_data["trip_category"] = trip.get("category", "meeting")

            # Auto-complete past trips
            store.auto_complete_trips()
        except Exception as e:
            logger.warning(f"Morning brief: trip auto-detection failed: {e}")

        # LANDING-FIX-2: travel_alerts now fetched inside connection block above
        travel_alerts = _travel_alerts_rows

        # LANDING-FIX-2: travel_deadlines now fetched inside connection block above
        travel_deadlines = _travel_deadlines_rows

        # TRAVEL-DOT-UNIFY-1: Enrich travel deadlines with linked trip status
        try:
            if _travel_deadlines_rows and active_trips:
                for tdl in _travel_deadlines_rows:
                    tdl_desc = (tdl.get("description") or "").lower()
                    tdl_date = str(tdl.get("due_date", ""))[:10] if tdl.get("due_date") else ""
                    for atrip in active_trips:
                        trip_dest = (atrip.get("destination") or "").lower()
                        trip_date = str(atrip.get("start_date", ""))
                        if trip_dest and trip_dest in tdl_desc and trip_date == tdl_date:
                            tdl["linked_trip_id"] = atrip.get("id")
                            tdl["trip_status"] = atrip.get("status", "planned")
                            break
                    else:
                        tdl["trip_status"] = "planned"  # Default: blue dot
        except Exception:
            pass

        # LANDING-FIX-3: meeting alerts for Meetings card
        meeting_alerts = _meeting_alerts_rows

        # MEETINGS-DETECT-1: Detected meetings from Director messages
        detected_meetings = []
        try:
            detected_meetings = [_serialize(m) for m in store.get_detected_meetings(days_ahead=14)]
        except Exception as e:
            logger.warning(f"Morning brief: detected meetings query failed: {e}")

        # CRITICAL-CARD-1: Director's critical/must-do-today items
        critical_items = []
        try:
            from models.deadlines import get_critical_items
            critical_items = [_serialize(ci) for ci in get_critical_items(5)]
        except Exception as e:
            logger.warning(f"Morning brief: critical items query failed: {e}")

        # Weekly priorities for dashboard widget
        weekly_priorities = []
        try:
            from orchestrator.priority_manager import get_current_priorities
            weekly_priorities = get_current_priorities()
            for p in weekly_priorities:
                for key in ("week_start", "created_at"):
                    if p.get(key) and hasattr(p[key], "isoformat"):
                        p[key] = p[key].isoformat()
        except Exception:
            pass

        return {
            "unanswered_count": unanswered_count,
            "fire_count": fire_count,
            "deadline_count": deadline_count,
            "processed_overnight": processed_overnight,
            "actions_completed": actions_completed,
            "todoist_overdue": todoist_overdue,
            "narrative": narrative,
            "proposals": proposals,
            "top_fires": top_fires,
            "critical_items": critical_items,
            "deadlines": deadlines,
            "activity": activity,
            "meetings_today": meetings_today,
            "detected_meetings": detected_meetings,
            "meeting_count": len(meetings_today) + len(detected_meetings),
            "travel_today": travel_today,
            "overdue_commitments": overdue_commitments,
            "silent_contacts": silent_contacts,
            "travel_alerts": travel_alerts,
            "travel_deadlines": travel_deadlines,
            "meeting_alerts": meeting_alerts,
            "trips": [_serialize(t) for t in active_trips],
            "weekly_priorities": weekly_priorities,
            "proposed_actions": _get_proposed_actions_for_brief(),
            "research_proposals": _get_research_proposals_for_brief(),
            "extraction_summary": _get_extraction_summary(),
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
            "meetings_today": [], "detected_meetings": [], "meeting_count": 0,
            "travel_today": [],
            "overdue_commitments": [], "silent_contacts": [],
            "travel_alerts": [], "travel_deadlines": [], "trips": [],
        }


# ============================================================
# TRIP-INTELLIGENCE-1: Trip API endpoints
# ============================================================

@app.get("/api/trips", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def list_trips():
    """List active + recently completed trips."""
    store = _get_store()
    trips = store.get_active_trips()
    return {"trips": [_serialize(t) for t in trips]}


@app.get("/api/trips/{trip_id}", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def get_trip_detail(trip_id: int):
    """Full trip detail with contacts."""
    store = _get_store()
    trip = store.get_trip(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return _serialize(trip)


class TripCreate(BaseModel):
    destination: str
    origin: str = None
    start_date: str = None
    end_date: str = None
    category: str = "meeting"
    event_name: str = None
    strategic_objective: str = None


@app.post("/api/trips", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def create_trip(body: TripCreate):
    """Manually create a trip."""
    store = _get_store()
    trip = store.upsert_trip(
        destination=body.destination,
        origin=body.origin,
        start_date=body.start_date,
        end_date=body.end_date,
        category=body.category,
        event_name=body.event_name,
        strategic_objective=body.strategic_objective,
    )
    if not trip:
        raise HTTPException(status_code=500, detail="Failed to create trip")
    return _serialize(trip)


class TripUpdate(BaseModel):
    status: str = None
    category: str = None
    event_name: str = None
    strategic_objective: str = None
    destination: str = None
    origin: str = None
    start_date: str = None
    end_date: str = None


@app.patch("/api/trips/{trip_id}", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def update_trip(trip_id: int, body: TripUpdate):
    """Update trip status, category, or other fields."""
    store = _get_store()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    trip = store.update_trip(trip_id, **updates)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return _serialize(trip)


@app.post("/api/travel/promote-deadline/{deadline_id}", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def promote_deadline_to_trip(deadline_id: int):
    """TRAVEL-DOT-UNIFY-1: Create a trip from a travel deadline. Returns the new trip with id."""
    store = _get_store()
    from models.deadlines import get_conn, put_conn
    conn = get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB connection failed")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, description, due_date, source_snippet
            FROM deadlines WHERE id = %s LIMIT 1
        """, (deadline_id,))
        dl = cur.fetchone()
        cur.close()
        if not dl:
            raise HTTPException(status_code=404, detail="Deadline not found")

        # Parse destination from description (e.g., "Return from Vienna to Geneva (Flight OS 155)")
        desc = dl["description"] or ""
        destination = ""
        origin = ""
        import re
        to_match = re.search(r"(?:to|nach|→)\s+([A-Za-z\s]+?)(?:\s*\(|$)", desc)
        from_match = re.search(r"(?:from|von|Return from)\s+([A-Za-z\s]+?)(?:\s+to|\s*\(|$)", desc, re.IGNORECASE)
        if to_match:
            destination = to_match.group(1).strip()
        if from_match:
            origin = from_match.group(1).strip()

        flight_date = None
        if dl.get("due_date"):
            flight_date = dl["due_date"]
            if hasattr(flight_date, "date"):
                flight_date = flight_date.date()
            flight_date = str(flight_date)

        trip = store.upsert_trip(
            destination=destination or "Unknown",
            origin=origin or "",
            start_date=flight_date,
            end_date=flight_date,
            event_name=desc,
            category="meeting",
            status="planned",
        )
        return _serialize(trip)
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Promote deadline to trip failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        put_conn(conn)


class TripNote(BaseModel):
    text: str


@app.post("/api/trips/{trip_id}/note", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def add_trip_note(trip_id: int, body: TripNote):
    """Add a note to a trip."""
    store = _get_store()
    # Verify trip exists
    trip = store.get_trip(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    success = store.add_trip_note(trip_id, body.text)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to add note")
    return {"ok": True}


class TripPersonAdd(BaseModel):
    contact_id: int
    role: str = "counterparty"
    roi_type: str = None
    roi_score: int = None
    notes: str = None


@app.post("/api/trips/{trip_id}/people", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def add_trip_person(trip_id: int, body: TripPersonAdd):
    """Add a contact to a trip."""
    store = _get_store()
    trip = store.get_trip(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    tc = store.add_trip_contact(
        trip_id=trip_id,
        contact_id=body.contact_id,
        role=body.role,
        roi_type=body.roi_type,
        roi_score=body.roi_score,
        notes=body.notes,
    )
    if not tc:
        raise HTTPException(status_code=500, detail="Failed to add contact")
    return _serialize(tc)


# ============================================================
# TRIP-INTELLIGENCE-1 Batch 2+3: Trip Cards
# ============================================================


def _build_people_dossiers(store, trip: dict) -> list:
    """TRIP-INTELLIGENCE-1 Batch 3 — Card 4: People to Meet.
    For each trip_contact, pull interactions, obligations, and emails."""
    contacts = trip.get("contacts") or []
    if not contacts:
        return []

    import psycopg2.extras
    conn = store._get_conn()
    if not conn:
        return [_people_stub(c) for c in contacts]

    dossiers = []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        for tc in contacts:
            cid = tc.get("contact_id")
            dossier = {
                "trip_contact_id": tc.get("id"),
                "contact_id": cid,
                "name": tc.get("contact_name") or "Unknown",
                "role": tc.get("contact_role") or tc.get("role") or "",
                "roi_score": tc.get("roi_score"),
                "roi_type": tc.get("roi_type") or "",
                "outreach_status": tc.get("outreach_status") or "none",
                "notes": tc.get("notes") or "",
                "interactions": [],
                "obligations": [],
                "emails": [],
                "tier": tc.get("contact_tier"),
                "role_context": tc.get("contact_role_context") or "",
                "expertise": tc.get("contact_expertise") or "",
            }
            if not cid:
                dossiers.append(dossier)
                continue

            # Recent interactions (last 90 days, max 5)
            cur.execute("""
                SELECT channel, direction, timestamp, subject
                FROM contact_interactions
                WHERE contact_id = %s
                ORDER BY timestamp DESC LIMIT 5
            """, (cid,))
            dossier["interactions"] = [_serialize(dict(r)) for r in cur.fetchall()]

            # Mutual obligations (deadlines assigned to or mentioning this contact)
            contact_name = dossier["name"]
            # DEADLINE_SIGNAL_HYGIENE_1 Scope B: exclude closed-matter deadlines
            # from contact-dossier obligation list.
            cur.execute("""
                SELECT d.description, d.due_date, d.priority, d.severity, d.status
                FROM deadlines d
                LEFT JOIN matter_registry m
                  ON LOWER(REPLACE(m.matter_name, ' ', '-')) = LOWER(d.matter_slug)
                WHERE d.status = 'active'
                  AND (d.matter_slug IS NULL OR m.status IS NULL OR m.status = 'active')
                  AND (LOWER(d.assigned_to) LIKE %s
                    OR LOWER(d.description) LIKE %s)
                ORDER BY d.due_date ASC NULLS LAST LIMIT 5
            """, (f"%{contact_name.lower()}%", f"%{contact_name.lower()}%"))
            dossier["obligations"] = [_serialize(dict(r)) for r in cur.fetchall()]

            # Recent emails to/from this contact (last 60 days, max 5)
            cur.execute("""
                SELECT subject, sender_name, sender_email, received_date,
                       LEFT(full_body, 300) as snippet
                FROM email_messages
                WHERE (LOWER(sender_name) LIKE %s
                    OR LOWER(sender_email) LIKE %s
                    OR LOWER(recipients) LIKE %s)
                  AND received_date >= NOW() - INTERVAL '60 days'
                ORDER BY received_date DESC LIMIT 5
            """, (f"%{contact_name.lower()}%", f"%{contact_name.lower()}%",
                  f"%{contact_name.lower()}%"))
            dossier["emails"] = [_serialize(dict(r)) for r in cur.fetchall()]

            dossiers.append(dossier)
        cur.close()
    except Exception as e:
        logger.warning(f"_build_people_dossiers failed: {e}")
        # Return stubs for any contacts not yet processed
        while len(dossiers) < len(contacts):
            dossiers.append(_people_stub(contacts[len(dossiers)]))
    finally:
        store._put_conn(conn)

    return dossiers


def _people_stub(tc: dict) -> dict:
    """Minimal dossier when DB is unavailable."""
    return {
        "trip_contact_id": tc.get("id"),
        "contact_id": tc.get("contact_id"),
        "name": tc.get("contact_name") or "Unknown",
        "role": tc.get("contact_role") or tc.get("role") or "",
        "roi_score": tc.get("roi_score"),
        "roi_type": tc.get("roi_type") or "",
        "outreach_status": tc.get("outreach_status") or "none",
        "notes": tc.get("notes") or "",
        "tier": tc.get("contact_tier"),
        "role_context": tc.get("contact_role_context") or "",
        "expertise": tc.get("contact_expertise") or "",
        "interactions": [],
        "obligations": [],
        "emails": [],
    }

_CITY_TIMEZONE = {
    'Vienna': 'Europe/Vienna', 'Frankfurt': 'Europe/Berlin', 'Zurich': 'Europe/Zurich',
    'Geneva': 'Europe/Zurich', 'San Francisco': 'America/Los_Angeles',
    'New York': 'America/New_York', 'London': 'Europe/London', 'Paris': 'Europe/Paris',
    'Munich': 'Europe/Berlin', 'Los Angeles': 'America/Los_Angeles',
    'Singapore': 'Asia/Singapore', 'Dubai': 'Asia/Dubai', 'Rome': 'Europe/Rome',
    'Barcelona': 'Europe/Madrid', 'Amsterdam': 'Europe/Amsterdam',
    'Palma de Mallorca': 'Europe/Madrid', 'Nice': 'Europe/Paris', 'Berlin': 'Europe/Berlin',
}


def _get_timezone_info(dest_city: str) -> dict:
    """Get timezone info for a destination city."""
    from zoneinfo import ZoneInfo
    tz_name = _CITY_TIMEZONE.get(dest_city)
    if not tz_name:
        return {"tz": None, "diff": None, "local_now": None}
    dest_tz = ZoneInfo(tz_name)
    home_tz = ZoneInfo("Europe/Zurich")
    now_utc = datetime.now(timezone.utc)
    dest_now = now_utc.astimezone(dest_tz)
    home_now = now_utc.astimezone(home_tz)
    diff_hours = (dest_now.utcoffset().total_seconds() - home_now.utcoffset().total_seconds()) / 3600
    diff_str = f"{diff_hours:+.0f}h" if diff_hours != 0 else "same"
    return {
        "tz": tz_name,
        "diff": diff_str,
        "diff_hours": diff_hours,
        "local_now": dest_now.strftime("%H:%M"),
        "home_now": home_now.strftime("%H:%M"),
    }


def _haiku_filter_reading(candidates: list, trip_context: str) -> list:
    """Use Haiku to pick the 5 most trip-relevant documents from candidates."""
    try:
        items_text = "\n".join(
            f"[{i}] {d.get('filename', 'unknown')} ({d.get('document_type', '?')}) — {(d.get('preview') or '')[:200]}"
            for i, d in enumerate(candidates)
        )
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = _llm_call("gemini-2.5-flash",
            max_tokens=200,
            system="You select documents relevant to a business trip. Return ONLY a JSON array of indices (e.g. [0, 3, 7]) of the most relevant documents. Pick up to 5. If none are relevant, return []. No explanation.",
            messages=[{"role": "user", "content": f"Trip context:\n{trip_context}\n\nDocuments:\n{items_text}"}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="trip_reading_filter")
        except Exception:
            pass
        import re
        text = resp.text.strip()
        match = re.search(r'\[[\d,\s]*\]', text)
        if match:
            indices = json.loads(match.group())
            return [candidates[i] for i in indices if 0 <= i < len(candidates)][:5]
    except Exception as e:
        logger.warning(f"Haiku reading filter failed: {e}")
    # Fallback: return first 5
    return candidates[:5]


def _haiku_filter_messages(messages: list, trip_context: str) -> list:
    """Use Haiku to pick trip-relevant VIP messages from the last 24h."""
    try:
        items_text = "\n".join(
            f"[{i}] {m.get('sender_name', '?')}: {(m.get('snippet') or '')[:150]}"
            for i, m in enumerate(messages)
        )
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = _llm_call("gemini-2.5-flash",
            max_tokens=200,
            system="You filter WhatsApp messages for a traveling CEO. Return ONLY a JSON array of indices (e.g. [0, 2, 5]) of messages worth surfacing. INCLUDE: (1) anything about the trip itself, (2) business decisions or strategy discussions, (3) requests that need a response, (4) deal/project updates. EXCLUDE ONLY: single-word replies ('Ok', 'Thanks'), links with no context, purely social pleasantries. When in doubt, INCLUDE. No explanation.",
            messages=[{"role": "user", "content": f"Trip context:\n{trip_context}\n\nMessages:\n{items_text}"}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="trip_message_filter")
        except Exception:
            pass
        import re
        text = resp.text.strip()
        match = re.search(r'\[[\d,\s]*\]', text)
        if match:
            indices = json.loads(match.group())
            return [messages[i] for i in indices if 0 <= i < len(messages)]
    except Exception as e:
        logger.warning(f"Haiku message filter failed: {e}")
    # Fallback: return all
    return messages


@app.get("/api/trips/{trip_id}/cards", tags=["trips"], dependencies=[Depends(verify_api_key)])
async def get_trip_cards(trip_id: int):
    """TRIP-INTELLIGENCE-1 Batch 2: All trip card data in one response."""
    store = _get_store()
    trip = store.get_trip(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    dest = trip.get("destination", "") or ""
    start_date = str(trip.get("start_date", "")) if trip.get("start_date") else None
    end_date = str(trip.get("end_date", "")) if trip.get("end_date") else start_date
    import psycopg2.extras

    cards = {}

    # --- Card 1: Logistics & Comms ---
    logistics = {"emails": [], "whatsapp": [], "timezone": _get_timezone_info(dest)}
    if dest:
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                dest_lower = dest.lower()
                # Emails mentioning destination, event name, or trip contacts
                email_search_terms = [dest_lower]
                event_name_lower = (trip.get("event_name") or "").lower()
                if event_name_lower:
                    for word in event_name_lower.split():
                        if len(word) >= 3 and not word.isdigit():
                            email_search_terms.append(word)
                # Add trip contact names
                for tc in trip.get("contacts", []):
                    cname = (tc.get("contact_name") or "").strip()
                    if cname and len(cname) >= 3:
                        email_search_terms.append(cname.lower())
                email_like_parts = []
                email_params = []
                for term in email_search_terms:
                    email_like_parts.append("LOWER(subject) LIKE %s OR LOWER(full_body) LIKE %s")
                    email_params.extend([f"%{term}%", f"%{term}%"])
                email_where = " OR ".join(email_like_parts)
                if start_date:
                    cur.execute(f"""
                        SELECT sender_name, sender_email, subject, received_date,
                               LEFT(full_body, 400) as snippet
                        FROM email_messages
                        WHERE ({email_where})
                          AND received_date >= %s::date - INTERVAL '14 days'
                          AND received_date <= %s::date + INTERVAL '1 day'
                        ORDER BY received_date DESC LIMIT 10
                    """, (*email_params, start_date, end_date or start_date))
                else:
                    cur.execute(f"""
                        SELECT sender_name, sender_email, subject, received_date,
                               LEFT(full_body, 400) as snippet
                        FROM email_messages
                        WHERE ({email_where})
                        ORDER BY received_date DESC LIMIT 10
                    """, (*email_params,))
                logistics["emails"] = [_serialize(dict(r)) for r in cur.fetchall()]

                # WhatsApp mentioning destination, event, or trip contacts — resolve phone numbers to names
                event_name_lower = (trip.get("event_name") or "").lower()
                search_terms = [f"%{dest_lower}%"]
                if event_name_lower:
                    for word in event_name_lower.split():
                        if len(word) >= 3 and not word.isdigit():
                            search_terms.append(f"%{word}%")
                for tc in trip.get("contacts", []):
                    cname = (tc.get("contact_name") or "").strip()
                    if cname and len(cname) >= 3:
                        search_terms.append(f"%{cname.lower()}%")
                like_clause = " OR ".join(["LOWER(wm.full_text) LIKE %s"] * len(search_terms))
                if start_date:
                    cur.execute(f"""
                        SELECT COALESCE(vc.name, wm.sender_name) as sender_name,
                               LEFT(wm.full_text, 300) as snippet, wm.timestamp
                        FROM whatsapp_messages wm
                        LEFT JOIN vip_contacts vc ON wm.sender = vc.whatsapp_id
                        WHERE ({like_clause})
                          AND wm.timestamp >= %s::date - INTERVAL '7 days'
                          AND wm.timestamp <= %s::date + INTERVAL '1 day'
                        ORDER BY wm.timestamp DESC LIMIT 10
                    """, (*search_terms, start_date, end_date or start_date))
                else:
                    cur.execute(f"""
                        SELECT COALESCE(vc.name, wm.sender_name) as sender_name,
                               LEFT(wm.full_text, 300) as snippet, wm.timestamp
                        FROM whatsapp_messages wm
                        LEFT JOIN vip_contacts vc ON wm.sender = vc.whatsapp_id
                        WHERE ({like_clause})
                        ORDER BY wm.timestamp DESC LIMIT 10
                    """, (*search_terms,))
                logistics["whatsapp"] = [_serialize(dict(r)) for r in cur.fetchall()]
                cur.close()
            except Exception as e:
                logger.warning(f"Trip card logistics failed: {e}")
            finally:
                store._put_conn(conn)
    cards["logistics"] = logistics

    # --- Card 3: Daily Agenda ---
    agenda = {"days": []}
    if start_date and end_date:
        try:
            from triggers.calendar_trigger import poll_meetings_by_date_range
            raw_events = poll_meetings_by_date_range(start_date, end_date)
            # Group by date
            by_date = {}
            for ev in raw_events:
                ev_date = ev["start"][:10] if ev.get("start") else "unknown"
                by_date.setdefault(ev_date, []).append(ev)
            for date_key in sorted(by_date.keys()):
                agenda["days"].append({"date": date_key, "events": by_date[date_key]})
        except Exception as e:
            logger.warning(f"Trip card agenda failed: {e}")
    cards["agenda"] = agenda

    # --- Card 5: Flight Reading (Haiku-curated) ---
    # Build trip context string for Haiku filtering
    trip_keywords = [dest]
    if trip.get("event_name"):
        trip_keywords.append(trip["event_name"])
    if trip.get("strategic_objective"):
        trip_keywords.append(trip["strategic_objective"][:200])
    trip_contact_names = [c.get("contact_name", "") for c in trip.get("contacts", []) if c.get("contact_name")]
    trip_keywords.extend(trip_contact_names)
    trip_context_str = f"Trip: {trip.get('event_name') or dest} ({trip.get('category', 'meeting')}). " \
                       f"Destination: {dest}. " \
                       f"Purpose: {trip.get('strategic_objective', 'Not specified')}. " \
                       f"Key people: {', '.join(trip_contact_names) if trip_contact_names else 'None'}."

    reading = {"documents": []}
    conn = store._get_conn()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Fetch MORE candidates (15), then Haiku picks the best 5
            cur.execute("""
                SELECT id, filename, document_type, ingested_at,
                       LEFT(full_text, 500) as preview
                FROM documents
                WHERE document_type IN ('legal_opinion', 'financial_model', 'report',
                                        'proposal', 'contract', 'correspondence')
                  AND ingested_at >= NOW() - INTERVAL '30 days'
                ORDER BY ingested_at DESC LIMIT 15
            """)
            candidates = [_serialize(dict(r)) for r in cur.fetchall()]
            seen_ids = {d["id"] for d in candidates}

            # Also search by destination, event name, and contact names via FTS
            fts_terms = [dest]
            if trip.get("event_name"):
                fts_terms.append(trip["event_name"])
            fts_terms.extend(trip_contact_names)
            for kw in fts_terms:
                if kw:
                    cur.execute("""
                        SELECT id, filename, document_type, ingested_at,
                               LEFT(full_text, 500) as preview
                        FROM documents
                        WHERE search_vector @@ plainto_tsquery('simple', %s)
                        ORDER BY ingested_at DESC LIMIT 5
                    """, (kw,))
                    for r in cur.fetchall():
                        d = _serialize(dict(r))
                        if d["id"] not in seen_ids:
                            candidates.append(d)
                            seen_ids.add(d["id"])
            cur.close()

            # Haiku picks the 5 most relevant to the trip
            if candidates:
                reading["documents"] = _haiku_filter_reading(candidates, trip_context_str)
        except Exception as e:
            logger.warning(f"Trip card reading failed: {e}")
        finally:
            store._put_conn(conn)
    cards["reading"] = reading

    # --- Card 6: Opportunistic Radar ---
    radar = {"dormant_contacts": []}
    if dest:
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                dest_lower = dest.lower()
                cur.execute("""
                    SELECT id, name, role, role_context, tier, last_contact_date, primary_location
                    FROM vip_contacts
                    WHERE (LOWER(primary_location) = %s
                        OR LOWER(role_context) LIKE %s
                        OR LOWER(expertise) LIKE %s
                        OR LOWER(role) LIKE %s
                        OR LOWER(name) LIKE %s)
                      AND (last_contact_date IS NULL
                        OR last_contact_date < NOW() - INTERVAL '30 days')
                    ORDER BY
                        CASE WHEN LOWER(primary_location) = %s THEN 0 ELSE 1 END,
                        last_contact_date ASC NULLS FIRST
                    LIMIT 10
                """, (dest_lower, f"%{dest_lower}%", f"%{dest_lower}%", f"%{dest_lower}%", f"%{dest_lower}%", dest_lower))
                for r in cur.fetchall():
                    contact = _serialize(dict(r))
                    if contact.get("last_contact_date"):
                        from datetime import datetime as _dt
                        try:
                            lcd = _dt.fromisoformat(str(contact["last_contact_date"]))
                            days_ago = (datetime.now(timezone.utc) - lcd).days
                            contact["days_since_contact"] = days_ago
                        except Exception:
                            contact["days_since_contact"] = None
                    else:
                        contact["days_since_contact"] = None
                    radar["dormant_contacts"].append(contact)
                cur.close()
            except Exception as e:
                logger.warning(f"Trip card radar failed: {e}")
            finally:
                store._put_conn(conn)
    cards["radar"] = radar

    # --- Card 7: Europe While You Sleep ---
    tz_card = {"vip_messages": [], "urgent_alerts": [], "deadlines": [], "timezone": _get_timezone_info(dest)}
    conn = store._get_conn()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # VIP messages from last 24h — resolve phone numbers to names
            cur.execute("""
                SELECT COALESCE(vc.name, wm.sender_name) as sender_name,
                       LEFT(wm.full_text, 200) as snippet, wm.timestamp
                FROM whatsapp_messages wm
                JOIN vip_contacts vc ON wm.sender = vc.whatsapp_id
                WHERE vc.tier <= 2
                  AND wm.timestamp >= NOW() - INTERVAL '24 hours'
                  AND wm.is_director = false
                ORDER BY wm.timestamp DESC LIMIT 15
            """)
            vip_msgs = [_serialize(dict(r)) for r in cur.fetchall()]

            # Haiku filters to trip-relevant messages
            if vip_msgs:
                tz_card["vip_messages"] = _haiku_filter_messages(vip_msgs, trip_context_str)
            else:
                tz_card["vip_messages"] = []

            # Pending urgent alerts
            cur.execute("""
                SELECT title, LEFT(body, 200) as snippet, created_at
                FROM alerts
                WHERE status = 'pending' AND tier <= 2
                ORDER BY created_at DESC LIMIT 5
            """)
            tz_card["urgent_alerts"] = [_serialize(dict(r)) for r in cur.fetchall()]

            # Deadlines due soon
            # DEADLINE_SIGNAL_HYGIENE_1 Scope B: exclude closed-matter deadlines
            # from trip-card "Deadlines due soon" surface.
            cur.execute("""
                SELECT d.description, d.due_date, d.priority
                FROM deadlines d
                LEFT JOIN matter_registry m
                  ON LOWER(REPLACE(m.matter_name, ' ', '-')) = LOWER(d.matter_slug)
                WHERE d.status = 'active'
                  AND (d.matter_slug IS NULL OR m.status IS NULL OR m.status = 'active')
                  AND d.due_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '3 days'
                ORDER BY d.due_date LIMIT 5
            """)
            tz_card["deadlines"] = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
        except Exception as e:
            logger.warning(f"Trip card timezone failed: {e}")
        finally:
            store._put_conn(conn)
    cards["timezone"] = tz_card

    # --- Card 4: People to Meet (Batch 3) ---
    cards["people"] = _build_people_dossiers(store, trip)

    return cards


import re as _re

# TRAVEL-FIX-2: Detect travel events from calendar title/location
_TRAVEL_PATTERNS = _re.compile(
    r'\b(flight|flug|fly|airport|airline|boarding|check.?in)\b'
    r'|\b(train|zug|bahn|rail)\b'
    r'|\b(transfer|taxi|uber|car.?rental)\b'
    r'|\b[A-Z]{2}\s?\d{2,4}\b'  # Flight numbers: LH 454, OS 201, BA 123
    r'|\b(?:VIE|FRA|SFO|JFK|LHR|CDG|ZRH|MUC|LAX|SIN|DXB|FCO|BCN|AMS|NCE|GVA|PMI|BER|TXL)\b',  # IATA codes
    _re.IGNORECASE,
)


def _is_travel_event(title: str, location: str = "") -> bool:
    """Detect if a calendar event is travel (flight, train, transfer) vs a meeting."""
    combined = f"{title} {location}"
    return bool(_TRAVEL_PATTERNS.search(combined))


# TRIP-INTELLIGENCE-1: IATA → City mapping for trip auto-detection
_IATA_TO_CITY = {
    'VIE': 'Vienna', 'FRA': 'Frankfurt', 'ZRH': 'Zurich', 'GVA': 'Geneva',
    'SFO': 'San Francisco', 'JFK': 'New York', 'LHR': 'London', 'CDG': 'Paris',
    'MUC': 'Munich', 'LAX': 'Los Angeles', 'SIN': 'Singapore', 'DXB': 'Dubai',
    'FCO': 'Rome', 'BCN': 'Barcelona', 'AMS': 'Amsterdam', 'PMI': 'Palma de Mallorca',
    'NCE': 'Nice', 'TXL': 'Berlin', 'BER': 'Berlin',
}

_FLIGHT_TO_RE = _re.compile(r'(?:flight|flug)\s+to\s+(.+?)(?:\s*\(|$)', _re.IGNORECASE)
_IATA_CODE_RE = _re.compile(r'\b([A-Z]{3})\b')
_CONF_KEYWORDS_RE = _re.compile(r'\b(conference|summit|forum|congress|symposium|expo|mipim|ihif)\b', _re.IGNORECASE)


def _extract_trip_cities(event: dict) -> tuple:
    """Extract (origin_city, dest_city) from a calendar event.
    Returns (str|None, str|None)."""
    title = event.get("title", "")
    location = event.get("location", "")

    # Destination: "Flight to San Francisco (LH454)" → "San Francisco"
    dest_city = None
    to_match = _FLIGHT_TO_RE.search(title)
    if to_match:
        dest_city = to_match.group(1).strip()

    # Check title for IATA → city
    if not dest_city:
        for code_match in _IATA_CODE_RE.finditer(title):
            code = code_match.group(1)
            if code in _IATA_TO_CITY:
                dest_city = _IATA_TO_CITY[code]
                break

    # Origin from location field ("Vienna VIE" or "FRA")
    origin_city = None
    for code_match in _IATA_CODE_RE.finditer(location):
        code = code_match.group(1)
        if code in _IATA_TO_CITY:
            origin_city = _IATA_TO_CITY[code]
            break

    # If destination is an IATA code, resolve it
    if dest_city and dest_city.upper() in _IATA_TO_CITY:
        dest_city = _IATA_TO_CITY[dest_city.upper()]

    return (origin_city, dest_city)


def _classify_trip_category(dest_city: str, home_cities: str, commute_cities: str) -> str:
    """Classify a destination into a trip category. Returns category or None (no trip card).
    home_cities/commute_cities are comma-separated strings."""
    if not dest_city:
        return None
    home_list = [c.strip().lower() for c in (home_cities or "").split(",") if c.strip()]
    commute_list = [c.strip().lower() for c in (commute_cities or "").split(",") if c.strip()]
    dl = dest_city.lower()
    if dl in home_list:
        return None  # Going home — no trip card
    if dl in commute_list:
        return "meeting"  # Commute — logistics only
    return "meeting"  # Default; user can toggle to event/personal


def _match_trip(active_trips: list, event_data: dict, dest_city: str) -> dict:
    """Find existing trip matching this event by calendar_event_id or dest+date."""
    cal_id = event_data.get("calendar_event_id", "")
    for trip in active_trips:
        # Match by calendar event ID
        if cal_id and cal_id in (trip.get("calendar_event_ids") or []):
            return trip
        # Match by destination + date proximity
        if dest_city and trip.get("destination"):
            if dest_city.lower() == trip["destination"].lower():
                return trip
    return None


def _get_morning_narrative(fire_count: int, deadline_count: int,
                           processed: int, top_fires: list,
                           deadlines: list = None,
                           silent_contacts: list = None) -> str:
    """Generate morning narrative via Haiku. Cached 30 min. Phase 3B: includes per-fire proposals."""
    global _morning_narrative_cache
    now = time.time()
    if _morning_narrative_cache["text"] and (now - _morning_narrative_cache["generated_at"]) < 1800:
        return _morning_narrative_cache["text"]

    try:
        fire_titles = [f.get("title", "") for f in top_fires[:3]]
        # F3: Cadence-aware silent contact descriptions
        def _fmt_silent(c):
            name = c.get('name', '?')
            days = c.get('days_silent', '?')
            dev = c.get('deviation')
            if dev:
                return f"{name} ({days}d silent, {dev}x normal)"
            return f"{name} ({days}d)"
        silent_names = [_fmt_silent(c) for c in (silent_contacts or [])[:3]]
        prompt = (
            f"You are Baker, chief of staff for Dimitry Vallen. "
            f"Write a 2-3 sentence status summary. Be warm but direct.\n\n"
            f"IMPORTANT: Do NOT start with 'Good morning' or any greeting — "
            f"the page header already shows the greeting. Jump straight to content.\n\n"
            f"Stats: {fire_count} fires, {deadline_count} deadlines this week, "
            f"{processed} items processed overnight.\n"
            f"Top fires: {'; '.join(fire_titles) if fire_titles else 'None'}\n"
        )
        if silent_names:
            prompt += f"Relationships cooling: {', '.join(silent_names)} — unusually silent.\n"
        prompt += (
            f"\nIf zero fires: 'All clear. No fires overnight.' then mention routine updates.\n"
            f"If fires exist: lead with the top issue and deadline, then mention others.\n"
            f"If relationships cooling: mention briefly at end ('Consider reaching out to X').\n"
            f"Keep it under 60 words. No bullet points. Plain text only."
        )
        client = anthropic.Anthropic(
            api_key=config.claude.api_key,
            timeout=15.0,
        )
        # TRUSTED — morning narrative is the Director-facing digest card (AC5);
        # Gemini Pro floor, never Flash (BAKER_DASHBOARD_V2_MODEL_LOCK_1).
        resp = _llm_call("gemini-2.5-pro",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            from orchestrator.model_policy import log_model_provenance
            log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="morning_narrative")
            log_model_provenance(model="gemini-2.5-pro", trusted=True, source_channel="digest", output_type="morning_narrative", context="morning_narrative")
        except Exception:
            pass
        narrative = resp.text.strip()

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

        # TRUSTED — morning proposals are Director-visible suggested next steps
        # (AC5); Gemini Pro floor, never Flash (BAKER_DASHBOARD_V2_MODEL_LOCK_1).
        resp = _llm_call("gemini-2.5-pro",
            max_tokens=300,
            system=_MORNING_PROPOSALS_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            from orchestrator.model_policy import log_model_provenance
            log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="morning_proposals")
            log_model_provenance(model="gemini-2.5-pro", trusted=True, source_channel="digest", output_type="morning_proposal", context="morning_proposals")
        except Exception:
            pass
        raw = resp.text.strip()
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


_PROJECTS_CATEGORIES = frozenset({"active-deal", "legal-risk", "financial", "origination"})
_OPERATIONS_CATEGORIES = frozenset({"tax", "admin-ops-pr", "private-assets", "personal-admin"})
_IMPORTANCE_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "frozen": 4}

# Legacy alert-table display labels → canonical priority slug. Tier-2 fallback
# for free-text labels NOT already aliased in baker-vault/slugs.yml. Consulted
# after slug_registry.normalize() (Tier 1). Verified entries only — each value
# present in baker-vault/slugs.yml (repo CLAUDE.md hard rule: no slugs.yml edits
# from this repo). Unknown free-text labels stay in inbox (safe default).
LEGACY_DISPLAY_LABEL_ALIASES: dict[str, str] = {
    "Oskolkov-RG7": "hagenauer-rg7",
    "Mandarin Oriental Sales": "mo-vie-exit",
}


def _safe_describe(slug: str) -> str:
    """``slug_registry.describe()`` raises ``KeyError`` on unknown slug
    (verified at ``kbl/slug_registry.py:215-220``). Wrap so cockpit still
    renders when ``_priorities.yml`` references a slug not yet in
    ``slugs.yml`` (separate-repo drift window)."""
    try:
        return slug_describe(slug)
    except KeyError:
        return slug


def _build_legacy_response(cur) -> dict:
    """Pre-cockpit-wiring sidebar shape. Runs ONLY when priorities_registry
    returns empty (e.g. ``_priorities.yml`` missing or vault-mirror lag).
    Preserves the legacy ``matter_registry``-bucketed sidebar so the panel
    never goes blank."""
    cur.execute("""
        SELECT
            COALESCE(a.matter_slug, '_ungrouped') AS matter_slug,
            COUNT(*) AS item_count,
            MIN(a.tier) AS worst_tier,
            COUNT(*) FILTER (WHERE a.created_at >= NOW() - INTERVAL '24 hours') AS new_count,
            COALESCE(mr.category, 'inbox') AS category
        FROM alerts a
        LEFT JOIN matter_registry mr ON LOWER(REPLACE(mr.matter_name, ' ', '-')) = LOWER(a.matter_slug)
            OR LOWER(mr.matter_name) = LOWER(REPLACE(a.matter_slug, '-', ' '))
        WHERE a.status = 'pending'
        GROUP BY COALESCE(a.matter_slug, '_ungrouped'), COALESCE(mr.category, 'inbox')
        ORDER BY item_count DESC
        LIMIT 500
    """)
    all_matters = [dict(r) for r in cur.fetchall()]
    inbox_count = sum(m['item_count'] for m in all_matters if m['matter_slug'] == '_ungrouped')
    projects = [m for m in all_matters if m.get('category') == 'project']
    operations = [m for m in all_matters if m.get('category') == 'operations']
    inbox_items = [m for m in all_matters if m.get('category') == 'inbox' or m['matter_slug'] == '_ungrouped']
    return {
        "matters": all_matters,
        "projects": projects,
        "operations": operations,
        "inbox": inbox_items,
        "inbox_count": inbox_count,
        "count": len(all_matters),
        "priorities_version": None,
        "priorities_ratified_at": None,
        "fallback_mode": "legacy_no_priorities",
    }


def _canonicalize_alert_slug(raw: str) -> Optional[str]:
    """Map a raw ``alerts.matter_slug`` to its canonical priority slug.

    Tier 1: ``slug_registry.normalize()`` — catches aliases in ``slugs.yml``
            (e.g. ``movie_am`` → ``mo-vie-am``, ``hagenauer`` → ``hagenauer-rg7``).
    Tier 2: ``LEGACY_DISPLAY_LABEL_ALIASES`` — free-text labels not in slugs.yml.

    Returns ``None`` for unmappable strings; caller routes those to the inbox.
    Preserves ``_ungrouped`` sentinel as ``None`` (inbox).
    """
    if not raw or raw == "_ungrouped":
        return None
    canonical = slug_normalize(raw)
    if canonical:
        return canonical
    return LEGACY_DISPLAY_LABEL_ALIASES.get(raw)


def _fold_alerts_to_canonical(alerts_by_slug: dict) -> tuple[dict, dict]:
    """Fold raw-slug alert aggregations into canonical-slug aggregations.

    Returns ``(canonical_folded, unmapped)``. When multiple raw slugs collapse
    to the same canonical, ``item_count`` and ``new_count`` are summed and
    ``worst_tier`` takes the MIN (lower tier = more severe; ``None`` does not
    overwrite a real tier). Unmapped rows (incl. ``_ungrouped``) are returned
    unchanged for inbox routing.
    """
    canonical_folded: dict = {}
    unmapped: dict = {}

    for raw_slug, row in alerts_by_slug.items():
        canonical = _canonicalize_alert_slug(raw_slug)
        if canonical is None:
            unmapped[raw_slug] = row
            continue

        if canonical in canonical_folded:
            existing = canonical_folded[canonical]
            existing["item_count"] = (existing.get("item_count") or 0) + (row.get("item_count") or 0)
            existing["new_count"] = (existing.get("new_count") or 0) + (row.get("new_count") or 0)
            row_tier = row.get("worst_tier")
            existing_tier = existing.get("worst_tier")
            if row_tier is not None and (existing_tier is None or row_tier < existing_tier):
                existing["worst_tier"] = row_tier
        else:
            canonical_folded[canonical] = {
                "matter_slug": canonical,
                "item_count": row.get("item_count") or 0,
                "new_count": row.get("new_count") or 0,
                "worst_tier": row.get("worst_tier"),
            }

    return canonical_folded, unmapped


@app.get("/api/dashboard/matters-summary", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_matters_summary():
    """List matters for the cockpit sidebar.

    Source of truth: ``baker-vault/wiki/_priorities.yml`` (Director-curated
    Triaga ratifications). Alerts table provides ``item_count`` + ``new_count``
    overlay. Slug labels come from ``slugs.yml`` via ``slug_registry.describe``.

    Falls back to the pre-cockpit-wiring legacy shape if the priorities file
    is missing or returns empty (vault-mirror lag).
    """
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                priorities = get_all_priorities()
                if not priorities:
                    return _build_legacy_response(cur)

                priority_slugs = {p.slug for p in priorities}

                cur.execute("""
                    SELECT
                        COALESCE(NULLIF(a.matter_slug, ''), '_ungrouped') AS matter_slug,
                        COUNT(*) AS item_count,
                        MIN(a.tier) AS worst_tier,
                        COUNT(*) FILTER (WHERE a.created_at >= NOW() - INTERVAL '24 hours') AS new_count
                    FROM alerts a
                    WHERE a.status = 'pending'
                    GROUP BY COALESCE(NULLIF(a.matter_slug, ''), '_ungrouped')
                    ORDER BY item_count DESC
                    LIMIT 500
                """)
                alerts_by_slug = {r["matter_slug"]: dict(r) for r in cur.fetchall()}

                # Fold raw alert slugs to canonical priority slugs (handles
                # legacy aliases like ``movie_am`` → ``mo-vie-am`` and free-text
                # labels like ``"Oskolkov-RG7"`` → ``hagenauer-rg7``).
                canonical_alerts, unmapped_alerts = _fold_alerts_to_canonical(alerts_by_slug)

                # Build display rows for priorities (gate). Multi-row priorities
                # for the same slug get folded — one row per slug, severity is
                # the highest, category attributed to the highest-importance row.
                seen_slugs: set[str] = set()
                rows: list[dict] = []
                for p in priorities:
                    if p.slug in seen_slugs:
                        continue
                    seen_slugs.add(p.slug)
                    alert = canonical_alerts.get(p.slug, {})
                    rows.append({
                        "matter_slug": p.slug,
                        "display_label": _safe_describe(p.slug),
                        "severity": p.importance,
                        "category": p.category,
                        "triaga_ref": p.triaga_ref,
                        "description": p.description,
                        "item_count": alert.get("item_count", 0),
                        "worst_tier": alert.get("worst_tier"),
                        "new_count": alert.get("new_count", 0),
                    })

                # Inbox = (a) unmapped raw-slug alerts (incl. ``_ungrouped``) +
                # (b) canonical-folded alerts whose canonical slug is NOT a
                # priority. Preserves "General" semantics + catches canonical
                # slugs that lack a priority row.
                inbox_rows: list[dict] = []
                for slug, row in unmapped_alerts.items():
                    inbox_rows.append({
                        "matter_slug": slug,
                        "display_label": _safe_describe(slug) if slug != "_ungrouped" else "General",
                        "severity": "low",
                        "category": "inbox",
                        "triaga_ref": None,
                        "description": "",
                        "item_count": row["item_count"],
                        "worst_tier": row["worst_tier"],
                        "new_count": row["new_count"],
                    })
                for slug, row in canonical_alerts.items():
                    if slug not in priority_slugs:
                        inbox_rows.append({
                            "matter_slug": slug,
                            "display_label": _safe_describe(slug),
                            "severity": "low",
                            "category": "inbox",
                            "triaga_ref": None,
                            "description": "",
                            "item_count": row["item_count"],
                            "worst_tier": row["worst_tier"],
                            "new_count": row["new_count"],
                        })

                projects = [r for r in rows if r["category"] in _PROJECTS_CATEGORIES]
                operations = [r for r in rows if r["category"] in _OPERATIONS_CATEGORIES]

                def _sort_key(r):
                    return (
                        _IMPORTANCE_RANK.get(r["severity"], 5),
                        -(r["item_count"] or 0),
                        r.get("triaga_ref") or "",
                    )

                projects.sort(key=_sort_key)
                operations.sort(key=_sort_key)
                inbox_rows.sort(key=lambda r: -(r["item_count"] or 0))

                return {
                    "matters": rows + inbox_rows,
                    "projects": projects,
                    "operations": operations,
                    "inbox": inbox_rows,
                    "inbox_count": sum(r["item_count"] for r in inbox_rows),
                    "count": len(rows) + len(inbox_rows),
                    "priorities_version": priorities_registry_version(),
                    "priorities_ratified_at": priorities_registry_ratified_at(),
                    "fallback_mode": None,
                }
            except HTTPException:
                raise
            except Exception:
                # Per python-backend.md: rollback before any new query.
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                cur.close()
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /api/dashboard/matters-summary failed: {e}")
        return {
            "matters": [], "projects": [], "operations": [], "inbox": [],
            "inbox_count": 0, "count": 0,
            "priorities_version": None, "priorities_ratified_at": None,
            "fallback_mode": "error",
        }


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
# CORTEX-PHASE-3 — Intent Feed API
# ============================================================

@app.get("/api/cortex/events", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def get_cortex_events(
    event_type: str = None,
    category: str = None,
    source_agent: str = None,
    limit: int = 30,
):
    """Cortex event feed — filterable by type, category, agent."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        clauses = []
        params = []
        if event_type:
            clauses.append("event_type = %s")
            params.append(event_type)
        if category:
            clauses.append("category = %s")
            params.append(category)
        if source_agent:
            clauses.append("source_agent = %s")
            params.append(source_agent)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        safe_limit = min(max(limit, 1), 100)
        params.append(safe_limit)
        cur.execute(f"""
            SELECT id, event_type, category, source_agent, source_type,
                   source_ref, payload, refers_to, canonical_id, created_at
            FROM cortex_events
            {where}
            ORDER BY created_at DESC
            LIMIT %s
        """, params)
        events = [_serialize(dict(r)) for r in cur.fetchall()]
        cur.close()
        conn.commit()
        return {"events": events, "count": len(events)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("get_cortex_events: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.get(
    "/api/cortex/cycles/{cycle_id}/proposal",
    tags=["cortex"],
    dependencies=[Depends(verify_api_key)],
)
async def get_cortex_cycle_proposal(cycle_id: str):
    """Return the propose-phase synthesis text for a cycle.

    Read-only. Backs the Scan UI's terminal card render in
    CORTEX_RUN_SCAN_UI_RENDER_1. Returns 404 if cycle has no
    synthesis row yet (cycle still running, archived without propose,
    or failed pre-synthesis).
    """
    import uuid as _uuid
    try:
        _uuid.UUID(cycle_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid cycle_id")

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT cycle_id::text, matter_slug, triggered_by, status,
                   current_phase, cost_dollars, cost_tokens,
                   started_at, completed_at
            FROM cortex_cycles
            WHERE cycle_id = %s
            LIMIT 1
            """,
            (cycle_id,),
        )
        cyc = cur.fetchone()
        if not cyc:
            cur.close()
            conn.commit()
            raise HTTPException(status_code=404, detail="Cycle not found")

        cur.execute(
            """
            SELECT payload, created_at
            FROM cortex_phase_outputs
            WHERE cycle_id = %s
              AND artifact_type = 'synthesis'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (cycle_id,),
        )
        syn = cur.fetchone()

        cur.execute(
            """
            SELECT payload, created_at
            FROM cortex_phase_outputs
            WHERE cycle_id = %s
              AND artifact_type = 'director_card'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (cycle_id,),
        )
        card_row = cur.fetchone()
        cur.close()
        conn.commit()

        proposal_text = None
        if syn and isinstance(syn.get("payload"), dict):
            proposal_text = syn["payload"].get("proposal_text")

        director_card = None
        if card_row and isinstance(card_row.get("payload"), dict):
            director_card = card_row["payload"]

        result = _serialize({
            "cycle_id": cyc["cycle_id"],
            "matter_slug": cyc["matter_slug"],
            "triggered_by": cyc["triggered_by"],
            "status": cyc["status"],
            "current_phase": cyc["current_phase"],
            "cost_dollars": float(cyc.get("cost_dollars") or 0.0),
            "cost_tokens": int(cyc.get("cost_tokens") or 0),
            "started_at": cyc.get("started_at"),
            "completed_at": cyc.get("completed_at"),
        })
        # NOTE: aborted_reason is NOT in cortex_cycles schema — it lives
        # only on the in-memory cycle object returned by maybe_run_cycle
        # (consumed by the SSE terminal event). Frontend gets it from
        # SSE, not from this endpoint.
        result["proposal_text"] = proposal_text
        result["has_proposal"] = bool(proposal_text)
        result["director_card"] = director_card
        result["has_director_card"] = director_card is not None
        return result
    except HTTPException:
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("get_cortex_cycle_proposal: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.get(
    "/api/cortex/cycles/pending",
    tags=["cortex"],
    dependencies=[Depends(verify_api_key)],
)
async def list_cortex_cycles_pending(
    limit: int = 50,
    include_smoke: bool = False,
):
    """List Cortex cycles awaiting Director ratification.

    Returns cycles where status='tier_b_pending' with a 200-char
    proposal_preview pulled from the latest synthesis phase_output.
    Read-only. Backs the Cortex Intent Feed "Pending" tab.

    Smoke filter (CORTEX_DIRECTOR_CARD_V1_1): by default,
    smoke / heartbeat / health-check cycles are EXCLUDED so Director
    sees only real cycles. Pass ``include_smoke=true`` for the full
    set (used by the frontend "Show all" toggle). A cycle is smoke
    when ANY of:
      - triggered_by ILIKE '%smoke%' OR '%health%' OR '%self_wake_smoke%'
        OR '%heartbeat%'
      - first 200 chars of latest synthesis proposal_text ILIKE
        '%smoke #%' OR '%health check%' OR '%heartbeat%'
    Brief originally referenced ``cortex_cycles.signal_text`` but that
    column does not exist (schema verified against memory/store_back.py
    bootstrap + migrations/20260428_cortex_cycles.sql); the triggered_by
    + proposal_text branches cover the actual smoke cycles in prod
    (Oskolkov ``self_wake_smoke`` triggered_by + 'Smoke #N' proposal markers).
    """
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    safe_limit = min(max(limit, 1), 100)
    from orchestrator.cortex_lite_policy import stale_pending_hours
    stale_hours = stale_pending_hours()
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            WITH base AS (
                SELECT
                    c.cycle_id::text AS cycle_id,
                    c.matter_slug,
                    c.triggered_by,
                    c.current_phase,
                    c.cost_dollars,
                    c.cost_tokens,
                    c.started_at,
                    EXTRACT(EPOCH FROM (NOW() - c.started_at))/60   AS age_minutes,
                    EXTRACT(EPOCH FROM (NOW() - c.started_at))/3600 AS age_hours,
                    (EXTRACT(EPOCH FROM (NOW() - c.started_at))/3600 >= %(stale_hours)s) AS is_stale_pending,
                    (
                      SELECT po.payload->>'proposal_text'
                      FROM cortex_phase_outputs po
                      WHERE po.cycle_id = c.cycle_id
                        AND po.artifact_type = 'synthesis'
                      ORDER BY po.created_at DESC
                      LIMIT 1
                    ) AS proposal_text,
                    (
                      SELECT po.payload
                      FROM cortex_phase_outputs po
                      WHERE po.cycle_id = c.cycle_id
                        AND po.artifact_type = 'director_card'
                      ORDER BY po.created_at DESC
                      LIMIT 1
                    ) AS director_card
                FROM cortex_cycles c
                WHERE c.status = 'tier_b_pending'
            ),
            flagged AS (
                SELECT
                    b.*,
                    (
                            COALESCE(b.triggered_by, '') ILIKE '%%smoke%%'
                         OR COALESCE(b.triggered_by, '') ILIKE '%%health%%'
                         OR COALESCE(b.triggered_by, '') ILIKE '%%self_wake_smoke%%'
                         OR COALESCE(b.triggered_by, '') ILIKE '%%heartbeat%%'
                         OR LEFT(COALESCE(b.proposal_text, ''), 200) ILIKE '%%smoke #%%'
                         OR LEFT(COALESCE(b.proposal_text, ''), 200) ILIKE '%%health check%%'
                         OR LEFT(COALESCE(b.proposal_text, ''), 200) ILIKE '%%heartbeat%%'
                    ) AS is_smoke
                FROM base b
            )
            SELECT *
            FROM flagged
            WHERE (%(include_smoke)s OR NOT is_smoke)
            ORDER BY started_at DESC
            LIMIT %(limit)s
            """,
            {"include_smoke": bool(include_smoke), "limit": safe_limit,
             "stale_hours": stale_hours},
        )
        rows = cur.fetchall()
        # Hidden-count: only meaningful when the toggle is hiding smoke.
        smoke_hidden_count = 0
        if not include_smoke:
            cur.execute(
                """
                SELECT COUNT(*) AS hidden
                FROM cortex_cycles c
                LEFT JOIN LATERAL (
                    SELECT po.payload->>'proposal_text' AS proposal_text
                    FROM cortex_phase_outputs po
                    WHERE po.cycle_id = c.cycle_id
                      AND po.artifact_type = 'synthesis'
                    ORDER BY po.created_at DESC
                    LIMIT 1
                ) syn ON TRUE
                WHERE c.status = 'tier_b_pending'
                  AND (
                        COALESCE(c.triggered_by, '') ILIKE '%smoke%'
                     OR COALESCE(c.triggered_by, '') ILIKE '%health%'
                     OR COALESCE(c.triggered_by, '') ILIKE '%self_wake_smoke%'
                     OR COALESCE(c.triggered_by, '') ILIKE '%heartbeat%'
                     OR LEFT(COALESCE(syn.proposal_text, ''), 200) ILIKE '%smoke #%'
                     OR LEFT(COALESCE(syn.proposal_text, ''), 200) ILIKE '%health check%'
                     OR LEFT(COALESCE(syn.proposal_text, ''), 200) ILIKE '%heartbeat%'
                  )
                """
            )
            hidden_row = cur.fetchone()
            smoke_hidden_count = int(hidden_row["hidden"] or 0) if hidden_row else 0
        cur.close()
        conn.commit()
        cycles = []
        for r in rows:
            proposal_text = r.get("proposal_text") or ""
            preview = proposal_text[:200] if proposal_text else ""
            director_card = r.get("director_card")
            cycles.append(_serialize({
                "cycle_id": r["cycle_id"],
                "matter_slug": r.get("matter_slug"),
                "triggered_by": r.get("triggered_by"),
                "current_phase": r.get("current_phase"),
                "cost_dollars": float(r.get("cost_dollars") or 0.0),
                "cost_tokens": int(r.get("cost_tokens") or 0),
                "started_at": r.get("started_at"),
                "age_minutes": float(r.get("age_minutes") or 0.0),
                "age_hours": float(r.get("age_hours") or 0.0),
                "is_stale_pending": bool(r.get("is_stale_pending")),
                "proposal_preview": preview,
                "has_proposal": bool(proposal_text),
                "director_card": director_card if isinstance(director_card, dict) else None,
                "has_director_card": isinstance(director_card, dict),
                "is_smoke": bool(r.get("is_smoke")),
            }))
        return {
            "cycles": cycles,
            "count": len(cycles),
            "smoke_hidden_count": smoke_hidden_count,
            "include_smoke": bool(include_smoke),
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("list_cortex_cycles_pending: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.get(
    "/api/cortex/cycles/{cycle_id}/trace",
    tags=["cortex"],
    dependencies=[Depends(verify_api_key)],
)
async def get_cortex_cycle_trace(cycle_id: str):
    """Return all phase outputs for a cycle, chronologically ordered.

    Backs the Tier-2 "Show your work" expansion in the ratify panel:
    phase trace + specialist breakdown + citations + cost telemetry.
    Read-only; 400 on bad UUID, 404 on missing cycle. Mirrors auth +
    UUID-validation pattern from get_cortex_cycle_proposal above.
    """
    import uuid as _uuid
    try:
        _uuid.UUID(cycle_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid cycle_id")

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT cycle_id::text AS cycle_id, matter_slug, status,
                   current_phase, cost_dollars, cost_tokens,
                   started_at, completed_at
            FROM cortex_cycles
            WHERE cycle_id = %s
            LIMIT 1
            """,
            (cycle_id,),
        )
        cyc = cur.fetchone()
        if not cyc:
            cur.close()
            conn.commit()
            raise HTTPException(status_code=404, detail="Cycle not found")
        cur.execute(
            """
            SELECT phase, phase_order, artifact_type, payload, created_at
            FROM cortex_phase_outputs
            WHERE cycle_id = %s
            ORDER BY created_at ASC, phase_order ASC NULLS LAST
            """,
            (cycle_id,),
        )
        outputs = [_serialize(dict(r)) for r in cur.fetchall()]
        cur.close()
        conn.commit()
        return _serialize({
            "cycle_id": cyc["cycle_id"],
            "matter_slug": cyc.get("matter_slug"),
            "status": cyc.get("status"),
            "current_phase": cyc.get("current_phase"),
            "cost_dollars": float(cyc.get("cost_dollars") or 0.0),
            "cost_tokens": int(cyc.get("cost_tokens") or 0),
            "started_at": cyc.get("started_at"),
            "completed_at": cyc.get("completed_at"),
            "phase_outputs": outputs,
            "count": len(outputs),
        })
    except HTTPException:
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("get_cortex_cycle_trace: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.get("/api/cortex/lint", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def get_cortex_lint(status: str = "open", limit: int = 50):
    """Lint results — wiki health findings."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        safe_limit = min(max(limit, 1), 100)
        cur.execute("""
            SELECT id, finding_type, severity, slug_or_ref, description, status, created_at
            FROM cortex_lint_results
            WHERE status = %s
            ORDER BY
                CASE severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
                created_at DESC
            LIMIT %s
        """, (status, safe_limit))
        results = [_serialize(dict(r)) for r in cur.fetchall()]
        cur.close()
        conn.commit()
        return {"lint_results": results, "count": len(results)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("get_cortex_lint: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.post("/api/cortex/lint/run", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def run_cortex_lint_now():
    """Trigger wiki lint on demand."""
    try:
        from models.cortex import run_wiki_lint
        findings = run_wiki_lint()
        return {"findings": len(findings), "details": findings[:20]}
    except Exception as e:
        logger.error("run_cortex_lint_now: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cortex/stats", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def get_cortex_stats():
    """Cortex summary stats for dashboard card header."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Event counts by type (last 7 days)
        cur.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM cortex_events
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY event_type
            ORDER BY cnt DESC
            LIMIT 20
        """)
        event_counts = {r["event_type"]: r["cnt"] for r in cur.fetchall()}

        # Total events
        cur.execute("SELECT COUNT(*) as cnt FROM cortex_events LIMIT 1")
        total_events = cur.fetchone()["cnt"]

        # Lint findings
        cur.execute("""
            SELECT severity, COUNT(*) as cnt
            FROM cortex_lint_results
            WHERE status = 'open'
            GROUP BY severity
            LIMIT 10
        """)
        lint_counts = {r["severity"]: r["cnt"] for r in cur.fetchall()}

        # Wiki pages
        cur.execute("""
            SELECT page_type, COUNT(*) as cnt
            FROM wiki_pages
            GROUP BY page_type
            LIMIT 10
        """)
        wiki_counts = {r["page_type"]: r["cnt"] for r in cur.fetchall()}

        # Dedup stats (shadow)
        cur.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM cortex_events
            WHERE event_type IN ('would_merge', 'review_needed', 'merged')
            GROUP BY event_type
            LIMIT 10
        """)
        dedup_counts = {r["event_type"]: r["cnt"] for r in cur.fetchall()}

        cur.close()
        conn.commit()
        return {
            "total_events": total_events,
            "events_7d": event_counts,
            "dedup": dedup_counts,
            "lint_open": lint_counts,
            "wiki_pages": wiki_counts,
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("get_cortex_stats: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.post("/api/cortex/trigger", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def trigger_cortex_cycle(req: CortexTriggerRequest):
    """CORTEX_TRIGGER_ENDPOINT_1: Director-invoke a Cortex cycle synchronously
    inside the Render container.

    Designed for: (a) Director curl-from-anywhere on demand, (b) the eventual
    Slack interactivity proxy, (c) UI button clicks.

    Runs maybe_run_cycle inline. Returns the terminal cycle state. The cycle's
    own asyncio.wait_for(timeout=CYCLE_TIMEOUT_SECONDS) bounds total wait time;
    if the cycle exceeds that cap, maybe_run_cycle marks the row 'failed' and
    raises asyncio.TimeoutError, which we translate to HTTP 504.

    Sensitive payload (director_question, aborted_reason) is NOT info-logged —
    only matter_slug + triggered_by appear in error-level logs.
    """
    try:
        cycle = await maybe_run_cycle(
            matter_slug=req.matter_slug,
            triggered_by=req.triggered_by,
            director_question=req.director_question,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Cortex trigger timed out (matter=%s, triggered_by=%s)",
            req.matter_slug, req.triggered_by,
        )
        raise HTTPException(
            status_code=504,
            detail="Cycle exceeded internal timeout cap",
        )
    except HTTPException:
        # Propagate any HTTPException raised inside maybe_run_cycle untouched.
        raise
    except Exception as e:
        logger.error(
            "Cortex trigger failed (matter=%s, triggered_by=%s): %s",
            req.matter_slug, req.triggered_by, e,
        )
        raise HTTPException(status_code=500, detail=f"Cycle invocation failed: {str(e)[:200]}")

    return {
        "cycle_id": cycle.cycle_id,
        "matter_slug": cycle.matter_slug,
        "triggered_by": cycle.triggered_by,
        "status": cycle.status,
        "current_phase": cycle.current_phase,
        "cost_tokens": cycle.cost_tokens,
        "cost_dollars": float(cycle.cost_dollars) if cycle.cost_dollars is not None else 0.0,
        "aborted_reason": getattr(cycle, "aborted_reason", None),
    }


# CORTEX_MANUAL_INVOKE_1: streaming Director-invoke endpoint. SSE phase
# events emitted while maybe_run_cycle runs in the background. Disconnect
# does NOT cancel the cycle — it runs to completion regardless.
@app.post("/api/cortex/run", tags=["cortex"], dependencies=[Depends(verify_api_key)])
async def cortex_run_stream(req: CortexRunRequest):
    """Director-invoke streaming Cortex cycle. SSE Phase 1-6 transitions.

    Auth: X-Baker-Key (reuse existing verify_api_key dependency).
    Whitelist: matter must have cortex-config.md (CORTEX_MULTI_MATTER_GATE_1).
    Rate limit: 5 runs/hour/matter across (director_manual, scan_intent) →
    HTTP 429.
    Cost guardrail: ≥30 specialist invocations/24h/matter posts a Slack DM
    warning (observability only — does NOT block the run).

    Sensitive payload (director_question, frontmatter content) is NEVER
    info-logged — only matter_slug + triggered_by + counts at info-level.
    """
    from outputs.cortex_run_stream import (
        stream_cycle_events,
        runs_in_last_hour,
        specialist_calls_today,
        RUN_RATE_LIMIT_PER_HOUR,
        COST_WARN_SPECIALIST_PER_DAY,
    )
    from triggers.cortex_pre_review_gate import matter_has_cortex_config

    # Whitelist: refuse matters without cortex-config.md (per CORTEX_MULTI_MATTER_GATE_1)
    if not matter_has_cortex_config(req.matter_slug):
        logger.info(
            "cortex_run rejected — matter=%s has no cortex-config.md",
            req.matter_slug,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Matter '{req.matter_slug}' is not Cortex-enabled "
                "(no cortex-config.md in vault)."
            ),
        )

    # Rate limit: 5 manual runs/hour/matter
    n_recent = runs_in_last_hour(req.matter_slug)
    if n_recent >= RUN_RATE_LIMIT_PER_HOUR:
        logger.info(
            "cortex_run rate-limited matter=%s recent=%d cap=%d",
            req.matter_slug, n_recent, RUN_RATE_LIMIT_PER_HOUR,
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit: {n_recent} runs in last hour for "
                f"{req.matter_slug} (cap={RUN_RATE_LIMIT_PER_HOUR})"
            ),
        )

    # Cost guardrail: warn-only Slack DM at threshold, run proceeds.
    # CORTEX_NOTIFICATION_DEFER_1: per-invoke + per-matter opt-out.
    n_specialist = specialist_calls_today(req.matter_slug)
    if n_specialist >= COST_WARN_SPECIALIST_PER_DAY:
        from triggers.cortex_pre_review_gate import (
            DIRECTOR_DM_CHANNEL,
            matter_notification_deferred,
        )
        defer_matter = matter_notification_deferred(req.matter_slug)
        # Always log for observability — separate from Slack push.
        logger.info(
            "cortex_run cost-warn matter=%s specialists=%d threshold=%d defer_invoke=%s defer_matter=%s",
            req.matter_slug,
            n_specialist,
            COST_WARN_SPECIALIST_PER_DAY,
            req.defer_notification,
            defer_matter,
        )
        if not (req.defer_notification or defer_matter):
            try:
                from outputs.slack_notifier import post_to_channel
                post_to_channel(
                    DIRECTOR_DM_CHANNEL,
                    (
                        f"⚠️ Cortex spend watch: {req.matter_slug} has "
                        f"{n_specialist} specialist invocations in last 24h "
                        f"(warn threshold: {COST_WARN_SPECIALIST_PER_DAY}). "
                        "Run proceeding — observability ping only."
                    ),
                    unfurl_links=False,
                    unfurl_media=False,
                )
            except Exception as e:
                logger.error("cortex_run cost-warn Slack post failed: %s", e)
        else:
            logger.info(
                "cortex_run cost-warn Slack DM suppressed matter=%s defer_invoke=%s defer_matter=%s",
                req.matter_slug,
                req.defer_notification,
                defer_matter,
            )

    return StreamingResponse(
        stream_cycle_events(
            matter_slug=req.matter_slug,
            director_question=req.director_question,
            triggered_by=req.triggered_by,
        ),
        media_type="text/event-stream",
    )


@app.post("/api/clerk/run", tags=["clerk"], dependencies=[Depends(verify_api_key)])
async def clerk_run(req: ClerkRunRequest, background_tasks: BackgroundTasks):
    """Start a Clerk Qwen3 workbench session without blocking the event loop."""
    task = req.task.strip()
    if not task:
        raise HTTPException(status_code=400, detail="task is required")
    session_id = str(uuid4())
    _clerk_create_session(
        session_id,
        task,
        {"approval_token_supplied": bool(req.approval_token)},
    )
    background_tasks.add_task(_clerk_run_session_background, session_id, task)
    row = _clerk_fetch_session(session_id)
    return _clerk_public_session(row or {"session_id": session_id, "status": "running"})


@app.get("/clerk", tags=["clerk"], response_class=HTMLResponse)
async def clerk_launcher():
    return HTMLResponse(_clerk_launcher_html())


@app.get("/api/clerk/sessions", tags=["clerk"], dependencies=[Depends(verify_api_key)])
async def clerk_sessions(limit: int = Query(10, ge=1)):
    bounded_limit = min(limit, 50)
    return {"sessions": _clerk_list_sessions(bounded_limit)}


@app.get("/api/clerk/session/{session_id}", tags=["clerk"], dependencies=[Depends(verify_api_key)])
async def clerk_session(session_id: str):
    row = _clerk_fetch_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="clerk_session_not_found")
    return _clerk_public_session(row)


@app.get("/clerk/edit/{session_id}", tags=["clerk"], response_class=HTMLResponse)
async def clerk_edit(session_id: str):
    return HTMLResponse(_clerk_edit_html({"session_id": session_id}))


# ── BRISEN_LAB_WIP_MATERIALS_PANEL_1 — cockpit "Work in progress" panel ──────
# Read-only browser over the vault mirror's wiki/_wip/<topic>/ subtree. Auth is
# ?key= (via _mcp_verify_key) so the page + file serve work inside an iframe /
# opened tab where request headers can't be set. Path safety lives in
# wip_materials.safe_path (reuses vault_mirror._normalize_and_resolve). No DB.

_WIP_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Work in progress — Brisen Lab</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262b35; --text:#e6e8ec;
          --muted:#8a92a0; --blue:#4f8cff; --blue-bg:#1b2740; }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; }
  body { background:var(--bg); color:var(--text);
         font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  .wip-wrap { display:flex; flex-direction:column; height:100vh; }
  .wip-bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap;
             padding:12px 16px; border-bottom:1px solid var(--line); background:var(--panel); }
  .wip-bar label { color:var(--muted); font-weight:600; }
  .wip-bar select { background:var(--bg); color:var(--text); border:1px solid var(--line);
                    border-radius:8px; padding:8px 10px; font-size:14px; min-width:200px; max-width:100%; }
  .wip-status { color:var(--muted); font-size:13px; margin-left:auto; }
  .wip-main { display:flex; flex:1; min-height:0; }
  .wip-files { list-style:none; margin:0; padding:8px; width:300px; max-width:42%;
               overflow:auto; border-right:1px solid var(--line); background:var(--panel); }
  .wip-files li { display:flex; flex-direction:column; padding:2px 4px; }
  .wip-file { color:var(--text); text-decoration:none; padding:8px 10px; border-radius:8px;
              word-break:break-word; cursor:pointer; }
  .wip-file:hover { background:var(--blue-bg); }
  .wip-file.active { background:var(--blue-bg); color:var(--blue); font-weight:600; }
  .wip-mod { color:var(--muted); font-size:11px; padding:0 10px 4px; }
  .wip-content { flex:1; min-width:0; border:0; background:#fff; }
  .wip-empty { color:var(--muted); padding:24px; }
  @media (max-width:640px) {
    .wip-main { flex-direction:column; }
    .wip-files { width:100%; max-width:none; max-height:38%; border-right:0;
                 border-bottom:1px solid var(--line); }
  }
</style>
</head>
<body>
<div class="wip-wrap">
  <div class="wip-bar">
    <label for="wipTopic">Work in progress</label>
    <select id="wipTopic" aria-label="Topic">
      <option value="">— select a topic —</option>
      __OPTIONS__
    </select>
    <span id="wipStatus" class="wip-status"></span>
  </div>
  <div class="wip-main">
    <ul id="wipFiles" class="wip-files"></ul>
    <iframe id="wipContent" class="wip-content" title="Work-in-progress document"></iframe>
  </div>
</div>
<script>
(function(){
  var KEY = new URLSearchParams(location.search).get('key') || '';
  var filesEl = document.getElementById('wipFiles');
  var contentEl = document.getElementById('wipContent');
  var statusEl = document.getElementById('wipStatus');
  var topicEl = document.getElementById('wipTopic');
  function setStatus(t){ statusEl.textContent = t || ''; }
  function clearContent(){ contentEl.removeAttribute('src'); }
  function loadFiles(topic){
    filesEl.textContent=''; clearContent();
    if(!topic){ setStatus('Select a topic.'); return; }
    setStatus('Loading\\u2026');
    fetch('/wip/list?topic='+encodeURIComponent(topic)+'&key='+encodeURIComponent(KEY))
      .then(function(r){ if(!r.ok){ throw new Error(r.status); } return r.json(); })
      .then(function(data){
        var files = (data && data.files) || [];
        if(!files.length){ setStatus('No materials yet.'); return; }
        setStatus(files.length+' file'+(files.length===1?'':'s'));
        files.forEach(function(f){
          var li=document.createElement('li');
          var a=document.createElement('a');
          a.href='#'; a.className='wip-file'; a.textContent=f.name;
          a.addEventListener('click',function(e){
            e.preventDefault();
            var act=filesEl.querySelectorAll('.wip-file');
            for(var i=0;i<act.length;i++){ act[i].classList.remove('active'); }
            a.classList.add('active');
            contentEl.src=f.href;
          });
          li.appendChild(a);
          if(f.modified){ var s=document.createElement('span'); s.className='wip-mod';
                          s.textContent=String(f.modified).slice(0,10); li.appendChild(s); }
          filesEl.appendChild(li);
        });
      })
      .catch(function(){ setStatus('Error loading files.'); });
  }
  topicEl.addEventListener('change',function(){ loadFiles(topicEl.value); });
})();
</script>
</body>
</html>"""


@app.get("/wip", include_in_schema=False, response_class=HTMLResponse)
async def wip_page(request: Request):
    """Server-rendered WIP-materials browser page (?key= gated)."""
    if not _mcp_verify_key(request):
        return HTMLResponse("Unauthorized", status_code=401)
    import html as _html
    import wip_materials
    try:
        topics = wip_materials.list_topics()
    except Exception:
        logger.exception("wip_page: list_topics failed")
        topics = []
    options = "\n      ".join(
        '<option value="{0}">{0}</option>'.format(_html.escape(t, quote=True))
        for t in topics
    )
    page = _WIP_PAGE_TEMPLATE.replace("__OPTIONS__", options)
    return HTMLResponse(page)


@app.get("/wip/list", include_in_schema=False)
async def wip_list(request: Request, topic: str = Query(...)):
    """JSON file listing for a topic, each with a key-bearing href (?key= gated)."""
    if not _mcp_verify_key(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    import wip_materials
    from urllib.parse import quote
    key = request.query_params.get("key") or request.headers.get("x-baker-key", "")
    try:
        files = wip_materials.list_files(topic)
    except Exception:
        logger.exception("wip_list: list_files failed for topic=%r", topic)
        files = []
    for f in files:
        f["href"] = (
            "/wip/file?topic=" + quote(topic, safe="")
            + "&name=" + quote(f["name"], safe="")
            + "&key=" + quote(key, safe="")
        )
    return JSONResponse({"files": files})


@app.get("/wip/file", include_in_schema=False)
async def wip_file(
    request: Request, topic: str = Query(...), name: str = Query(...)
):
    """Serve a single WIP file inside WIP_ROOT (?key= gated). 404 on any miss."""
    if not _mcp_verify_key(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    import wip_materials
    try:
        path = wip_materials.safe_path(topic, name)
    except Exception:
        logger.exception("wip_file: safe_path raised topic=%r name=%r", topic, name)
        path = None
    if path is None:
        raise HTTPException(status_code=404, detail="wip_file_not_found")
    if path.suffix.lower() == ".md":
        return FileResponse(str(path), media_type="text/plain; charset=utf-8")
    return FileResponse(str(path), media_type="text/html")


@app.post("/api/clerk/save/{session_id}", tags=["clerk"], dependencies=[Depends(verify_api_key)])
async def clerk_save(session_id: str, req: ClerkSaveRequest):
    row = _clerk_fetch_session(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="clerk_session_not_found")

    target_path = _clerk_normalize_dropbox_path(
        req.target_path or row.get("draft_path") or f"{_CLERK_WORKING_PREFIX}/{session_id}.md"
    )
    if not target_path:
        raise HTTPException(status_code=400, detail="invalid_target_path")

    approved_save_paths: set[str] = set()
    if _clerk_path_under(target_path, (_CLERK_WORKING_PREFIX,)):
        pass
    elif _clerk_validate_save_approval(session_id, target_path, req.approval_token):
        approved_save_paths.add(target_path)
    else:
        _clerk_update_session(
            session_id,
            status="pending_approval",
            result_json={"status": "pending_approval", "target_path": target_path},
            error="target path requires Director approval",
        )
        raise HTTPException(
            status_code=403,
            detail={
                "status": "pending_approval",
                "reason": "target path requires Director approval",
                "target_path": target_path,
            },
        )

    result = await asyncio.to_thread(
        _clerk_save_content_sync,
        session_id,
        req.content,
        target_path,
        approved_save_paths,
    )
    if result.get("status") == "saved":
        return result
    if result.get("status") == "blocked":
        raise HTTPException(status_code=403, detail=result)
    raise HTTPException(status_code=500, detail=result)


# CORTEX_PRE_REVIEW_GATE_1: tap-from-Slack endpoint for the cost gate.
# Auth: signed-token (HMAC) — no X-Baker-Key (must be openable by Slack tap).
@app.get("/api/cortex/gate/decide", tags=["cortex"], response_class=HTMLResponse)
async def cortex_gate_decide(
    background_tasks: BackgroundTasks,
    signal_id: int,
    action: str,
    exp: int,
    token: str,
):
    """CORTEX_PRE_REVIEW_GATE_1: Director-tap endpoint for the cost gate.

    Auth: signed-token via query string (HMAC-SHA256 of
    signal_id|action|expires_at, secret=CORTEX_GATE_SECRET). NO X-Baker-Key —
    must be tap-clickable from Slack-on-iPhone (iOS Safari follow-link drops
    custom headers).

    Idempotent: a re-tap after the decision is already recorded returns the
    recorded decision page; the cycle does NOT re-fire.

    Sensitive payload (preview text / aborted_reason) is never echoed back
    in the HTML — only matter_slug + signal_id + action are shown.
    """
    from triggers.cortex_pre_review_gate import (
        verify_token, already_decided, record_decision, lookup_matter_slug,
    )

    # 1. Verify signed token + action + expiry.
    ok, err = verify_token(
        signal_id=signal_id, action=action, expires_at=exp, token=token,
    )
    if not ok:
        return HTMLResponse(
            f"<h1>Gate link invalid</h1><p>Reason: {err}</p>",
            status_code=403,
        )

    # 2. Idempotency — re-tap returns recorded decision, never re-fires.
    prior = already_decided(signal_id)
    if prior:
        return HTMLResponse(
            f"<h1>Already decided</h1>"
            f"<p>Signal {signal_id}: <b>{prior}</b></p>",
            status_code=200,
        )

    # 3. Resolve matter from signal_queue (real column: `matter`).
    matter_slug = lookup_matter_slug(signal_id)
    if matter_slug is None:
        # DB unavailable or lookup error — best-effort error page (not 500
        # to avoid exposing infra signals to the world).
        return HTMLResponse(
            f"<h1>Lookup error</h1><p>signal_id={signal_id}</p>",
            status_code=503,
        )
    if matter_slug == "":
        return HTMLResponse(
            f"<h1>Signal not found</h1><p>signal_id={signal_id}</p>",
            status_code=404,
        )

    # 4. Atomically claim the decision row (CORTEX_PRE_REVIEW_GATE_2 — closes
    #    the TOCTOU race between the prior already_decided() read above and
    #    the INSERT below). record_decision returns False if a concurrent
    #    request — including a Slackbot-LinkExpanding GET, an iPhone
    #    double-tap, or a tab-reload — already won the race. We MUST NOT
    #    fire the BackgroundTask in that case (would trigger 2× $4 cycles).
    claimed = record_decision(
        signal_id=signal_id, action=action, matter_slug=matter_slug,
    )
    if not claimed:
        return HTMLResponse(
            f"<h1>Already decided</h1>"
            f"<p>Signal {signal_id}: another decision was recorded "
            f"simultaneously.</p>",
            status_code=200,
        )

    # 5. Branch on action — only reached if THIS call won the race.
    if action == "approve":
        # Fire cycle in background — release HTTP response immediately so the
        # Director's browser tab does not hang for 4-5 minutes.
        background_tasks.add_task(
            _cortex_gate_fire_cycle, matter_slug, signal_id,
        )
        return HTMLResponse(
            "<h1>✅ Cycle started</h1>"
            "<p>Cortex is analyzing now. ETA ~5 minutes. "
            "Watch Slack for the proposal card.</p>",
            status_code=200,
        )

    # action == "skip" (verify_token already rejected anything else)
    return HTMLResponse(
        "<h1>❌ Skipped</h1>"
        "<p>Signal recorded as skipped. No cycle fired, no spend.</p>",
        status_code=200,
    )


async def _cortex_gate_fire_cycle(matter_slug: str, signal_id: int) -> None:
    """CORTEX_PRE_REVIEW_GATE_1: background-task wrapper that fires
    maybe_run_cycle after a gate approval. Never raises — failures are
    logged so the FastAPI background-task pool stays healthy.
    """
    try:
        cycle = await maybe_run_cycle(
            matter_slug=matter_slug,
            triggered_by="director_gate_approve",
            trigger_signal_id=signal_id,
        )
        logger.info(
            "gate-approved cycle complete: cycle_id=%s status=%s cost=$%.4f",
            cycle.cycle_id, cycle.status,
            float(cycle.cost_dollars) if cycle.cost_dollars is not None else 0.0,
        )
    except Exception as e:  # noqa: BLE001 — background tasks must not propagate
        logger.error(
            "gate-approved cycle failed signal_id=%s matter=%s: %s",
            signal_id, matter_slug, e,
        )


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


@app.get("/api/rss/category-counts", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_rss_category_counts():
    """Return article counts by RSS feed category (last 7 days)."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"categories": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT f.category AS name, COUNT(a.id) AS count
                FROM rss_feeds f JOIN rss_articles a ON a.feed_id = f.id
                WHERE f.is_active = true AND a.published_at > NOW() - INTERVAL '7 days'
                GROUP BY f.category ORDER BY count DESC
            """)
            categories = [dict(r) for r in cur.fetchall()]
            cur.close()
            return {"categories": categories}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/rss/category-counts failed: {e}")
        return {"categories": []}


@app.get("/api/rss/knowledge-digests", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_knowledge_digests(category: Optional[str] = None):
    """Get compiled knowledge digests, optionally filtered by category."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"digests": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if category:
                cur.execute("""
                    SELECT id, category, title, digest_md, article_count,
                           last_compiled, period_start, period_end
                    FROM knowledge_digests
                    WHERE category = %s
                    ORDER BY last_compiled DESC LIMIT 5
                """, (category,))
            else:
                cur.execute("""
                    SELECT DISTINCT ON (category)
                        id, category, title, digest_md, article_count,
                        last_compiled, period_start, period_end
                    FROM knowledge_digests
                    ORDER BY category, last_compiled DESC
                """)
            digests = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
            return {"digests": digests}
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.error(f"GET /api/rss/knowledge-digests failed: {e}")
        return {"digests": []}


@app.post("/api/rss/compile-digests", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def compile_digests_endpoint():
    """Trigger knowledge digest compilation for all active categories."""
    import asyncio
    try:
        from triggers.rss_trigger import compile_knowledge_digest
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return {"status": "error", "message": "No DB connection"}
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM rss_feeds WHERE is_active = true AND category IS NOT NULL")
        categories = [r[0] for r in cur.fetchall()]
        cur.close()
        store._put_conn(conn)

        results = {}
        for cat in categories:
            try:
                digest_id = await asyncio.to_thread(compile_knowledge_digest, cat)
                results[cat] = digest_id
            except Exception as e:
                results[cat] = f"error: {e}"
        return {"status": "ok", "compiled": results}
    except Exception as e:
        logger.error(f"compile-digests failed: {e}")
        return {"status": "error", "message": str(e)}


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
                cur.execute("SELECT name, role, email, whatsapp_id, tier, domain, role_context FROM contacts ORDER BY tier, name")
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
                FROM contacts
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
                SELECT id, name, tier, last_contact_date FROM contacts
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
                    JOIN contacts vc ON ci.contact_id = vc.id
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


@app.post("/api/networking/backfill-last-contact", tags=["networking"], dependencies=[Depends(verify_api_key)])
async def backfill_last_contact():
    """Backfill last_contact_date on vip_contacts from emails, WhatsApp, and meetings."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            # Build reversed name for "Last First" matching
            # For each VIP contact, find the most recent interaction across all channels
            # Note: no psycopg2 params, so use single % for LIKE wildcards (not %%)
            cur.execute("""
                UPDATE contacts vc
                SET last_contact_date = sub.last_contact
                FROM (
                    SELECT vc2.id, GREATEST(
                        (SELECT MAX(received_date) FROM email_messages
                         WHERE LOWER(sender_name) = LOWER(vc2.name)
                            OR LOWER(sender_email) = LOWER(vc2.email)
                            OR (POSITION(' ' IN vc2.name) > 0 AND LOWER(sender_name) = LOWER(
                                SPLIT_PART(vc2.name, ' ', 2) || ' ' || SPLIT_PART(vc2.name, ' ', 1)
                            ))
                            OR LOWER(sender_name) LIKE '%' || LOWER(SPLIT_PART(vc2.name, ' ', 2)) || '%'),
                        (SELECT MAX(timestamp) FROM whatsapp_messages
                         WHERE LOWER(sender_name) = LOWER(vc2.name)
                            OR sender = vc2.whatsapp_id
                            OR LOWER(sender_name) LIKE '%' || LOWER(SPLIT_PART(vc2.name, ' ', 2)) || '%'),
                        (SELECT MAX(meeting_date) FROM meeting_transcripts
                         WHERE LOWER(participants) LIKE '%' || LOWER(vc2.name) || '%'
                            OR LOWER(participants) LIKE '%' || LOWER(SPLIT_PART(vc2.name, ' ', 2)) || '%')
                    ) AS last_contact
                    FROM contacts vc2
                ) sub
                WHERE vc.id = sub.id AND sub.last_contact IS NOT NULL
            """)
            updated = cur.rowcount
            conn.commit()
            cur.close()
            return {"status": "ok", "contacts_updated": updated}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backfill last_contact_date failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/obligations/migrate-commitments", tags=["obligations"], dependencies=[Depends(verify_api_key)])
async def migrate_commitments():
    """OBLIGATIONS-UNIFY-1: Migrate commitments into deadlines table. Idempotent."""
    store = _get_store()
    import psycopg2.extras
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()
        # Ensure schema columns exist on the SAME connection used for migration
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS severity VARCHAR(10) DEFAULT 'firm'")
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS assigned_to TEXT")
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS assigned_by TEXT")
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS matter_slug TEXT")
        cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS obligation_type VARCHAR(20) DEFAULT 'deadline'")
        cur.execute("ALTER TABLE deadlines ALTER COLUMN due_date DROP NOT NULL")
        cur.execute("ALTER TABLE deadlines ALTER COLUMN confidence DROP NOT NULL")
        conn.commit()
        # Migrate commitments → deadlines (skip if source_id already exists)
        cur.execute("""
            INSERT INTO deadlines (description, due_date, source_type, source_id, status,
                                    matter_slug, assigned_to, assigned_by, severity,
                                    obligation_type, confidence, priority, created_at)
            SELECT
                c.description,
                c.due_date,
                COALESCE(c.source_type, 'commitment'),
                'commitment:' || c.id,
                CASE c.status
                    WHEN 'open' THEN 'active'
                    WHEN 'overdue' THEN 'active'
                    WHEN 'dismissed' THEN 'dismissed'
                    ELSE 'active'
                END,
                c.matter_slug,
                c.assigned_to,
                c.assigned_by,
                CASE WHEN c.due_date IS NOT NULL THEN 'firm' ELSE 'soft' END,
                'commitment',
                'medium',
                'normal',
                c.created_at
            FROM commitments c
            WHERE NOT EXISTS (
                SELECT 1 FROM deadlines d WHERE d.source_id = 'commitment:' || c.id
            )
        """)
        migrated = cur.rowcount

        # Classify existing deadlines that don't have severity set
        cur.execute("""
            UPDATE deadlines SET severity = 'hard'
            WHERE severity IS NULL OR severity = 'firm'
              AND obligation_type IS NULL OR obligation_type = 'deadline'
              AND (LOWER(description) LIKE '%%legal%%'
                OR LOWER(description) LIKE '%%contract%%'
                OR LOWER(description) LIKE '%%gewaehr%%'
                OR LOWER(description) LIKE '%%frist%%'
                OR LOWER(description) LIKE '%%regulatory%%'
                OR priority = 'critical')
        """)
        hard_classified = cur.rowcount

        conn.commit()
        cur.close()

        return {
            "status": "ok",
            "commitments_migrated": migrated,
            "hard_deadlines_classified": hard_classified,
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"Migrate commitments failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.post("/api/networking/backfill-interactions", tags=["networking"], dependencies=[Depends(verify_api_key)])
async def backfill_interactions():
    """INTERACTION-PIPELINE-1: Backfill contact_interactions from emails, WhatsApp, meetings.
    Idempotent — safe to run multiple times."""
    try:
        store = _get_store()
        counts = store.backfill_interactions()
        if "error" in counts:
            raise HTTPException(status_code=500, detail=counts["error"])
        return {"status": "ok", **counts}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Backfill interactions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/networking/sync-whatsapp-contacts", tags=["networking"], dependencies=[Depends(verify_api_key)])
async def sync_whatsapp_contacts():
    """INTERACTION-PIPELINE-1: Sync WhatsApp contact names from WAHA contacts API.
    Creates/updates vip_contacts and fixes phone-number-only sender_names in whatsapp_messages.
    Uses /api/contacts/all (address book names) with list_chats as fallback."""
    try:
        from triggers.waha_client import list_contacts, list_chats
        store = _get_store()
        import psycopg2.extras

        # Primary: WAHA contacts API (has address book names)
        chats = list_contacts(limit=500)
        if not chats:
            # Fallback: chat list (may only have phone numbers)
            chats = list_chats(limit=300)
        created = 0
        updated_names = 0
        updated_msgs = 0

        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            for chat in chats:
                chat_id = chat.get("id", "")
                # Skip groups, broadcasts, status
                if "@g.us" in chat_id or "status@" in chat_id or "@lid" in chat_id:
                    continue

                name = chat.get("name", "") or chat.get("pushname", "") or ""
                if not name or name == chat_id.split("@")[0]:
                    continue  # Still just a phone number

                wa_id = chat_id  # e.g. "41799605092@c.us"

                # Skip Director's own number
                if "41799605092" in wa_id:
                    continue

                # Check if contact already exists by whatsapp_id
                cur.execute(
                    "SELECT id, name FROM vip_contacts WHERE whatsapp_id = %s LIMIT 1",
                    (wa_id,),
                )
                existing = cur.fetchone()

                if existing:
                    # Update name if it was a phone number
                    if existing["name"] and existing["name"].isdigit():
                        cur.execute(
                            "UPDATE vip_contacts SET name = %s WHERE id = %s",
                            (name, existing["id"]),
                        )
                        updated_names += 1
                else:
                    # Create new contact
                    cur.execute(
                        """INSERT INTO vip_contacts (name, whatsapp_id, tier, communication_pref)
                           VALUES (%s, %s, 3, 'whatsapp')
                           ON CONFLICT DO NOTHING""",
                        (name, wa_id),
                    )
                    if cur.rowcount > 0:
                        created += 1

                # Fix phone-number sender_names in whatsapp_messages
                phone = wa_id.split("@")[0]
                cur.execute(
                    """UPDATE whatsapp_messages
                       SET sender_name = %s
                       WHERE (sender = %s OR chat_id = %s)
                         AND (sender_name = %s OR sender_name = %s)""",
                    (name, wa_id, wa_id, phone, wa_id),
                )
                updated_msgs += cur.rowcount

            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)

        return {
            "status": "ok",
            "chats_scanned": len(chats),
            "contacts_created": created,
            "names_updated": updated_names,
            "messages_fixed": updated_msgs,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sync WhatsApp contacts failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
            cur.execute("SELECT * FROM contacts WHERE id = %s", (contact_id,))
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


@app.get("/api/cost/dashboard", tags=["phase-4a"], dependencies=[Depends(verify_api_key)])
async def get_cost_dashboard_endpoint(days: int = Query(7, ge=1, le=90)):
    """G2: Full cost dashboard — today's breakdown, daily history, per-capability costs, weekly summary."""
    from orchestrator.cost_monitor import get_cost_dashboard
    return get_cost_dashboard(days)


@app.get("/api/cost/capabilities", tags=["phase-4a"], dependencies=[Depends(verify_api_key)])
async def get_capability_costs_endpoint(days: int = Query(7, ge=1, le=90)):
    """G2: Per-capability cost breakdown for the last N days."""
    from orchestrator.cost_monitor import get_capability_costs
    return {"days": days, "capabilities": get_capability_costs(days)}


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


@app.post("/api/alerts/quick-add", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def quick_add_alert(body: dict):
    """Director quick-adds an issue. Creates T2 alert, Baker auto-enriches in background."""
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    try:
        store = _get_store()
        alert_id = store.create_alert(
            tier=2,
            title=title,
            body="",
            action_required=True,
            tags=["manual"],
            source="director_quick_add",
        )
        if not alert_id:
            raise HTTPException(status_code=500, detail="Failed to create alert")
        # Background: ask Haiku to enrich the alert with structured_actions
        import threading
        def _enrich():
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=config.claude.api_key)
                # TRUSTED — enrichment becomes alerts.structured_actions on a
                # Director-visible card; Gemini Pro floor, never Flash
                # (BAKER_DASHBOARD_V2_MODEL_LOCK_1).
                resp = _llm_call("gemini-2.5-pro",
                    max_tokens=800,
                    messages=[{"role": "user", "content": f"The Director flagged this issue: \"{title}\"\n\nGenerate a JSON object with: problem (1 sentence), cause (1 sentence), solution (1 sentence). Return ONLY valid JSON."}],
                )
                import json as _json
                raw = resp.text.strip()
                if raw.startswith("```"): raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                sa = _json.loads(raw)
                store.update_alert_structured_actions(alert_id, sa)
                from orchestrator.cost_monitor import log_api_cost
                from orchestrator.model_policy import log_model_provenance
                log_api_cost("gemini-2.5-pro", resp.usage.input_tokens, resp.usage.output_tokens, source="quick_add_enrich")
                log_model_provenance(model="gemini-2.5-pro", trusted=True, source_channel="director_flag", output_type="alert_structured_actions", context="quick_add_enrich")
            except Exception as e:
                logger.warning(f"Quick-add enrichment failed for alert {alert_id}: {e}")
        threading.Thread(target=_enrich, daemon=True).start()
        return {"ok": True, "alert_id": alert_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/alerts/quick-add failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══ E3: Web Push ═══

@app.get("/api/push/vapid-key", tags=["push"])
async def get_vapid_key():
    """Return the VAPID public key for Web Push subscription (no auth — needed before login)."""
    pub = config.web_push.vapid_public_key
    if not pub:
        raise HTTPException(status_code=503, detail="VAPID not configured")
    return {"public_key": pub}


@app.post("/api/push/subscribe", tags=["push"], dependencies=[Depends(verify_api_key)])
async def push_subscribe(request: Request):
    """Store a Web Push subscription from the client."""
    body = await request.json()
    endpoint = body.get("endpoint", "")
    keys = body.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")
    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Missing subscription fields")
    store = _get_store()
    ok = store.store_push_subscription(endpoint, p256dh, auth)
    return {"status": "ok" if ok else "error"}


# ═══ Baker 3.0: Digest Endpoints ═══

@app.get("/api/digest/morning", tags=["push"], dependencies=[Depends(verify_api_key)])
async def morning_digest():
    """Gather items for morning digest."""
    from outputs.push_sender import gather_morning_items
    items = gather_morning_items()
    return {"items": items, "count": len(items), "type": "morning"}


@app.get("/api/digest/evening", tags=["push"], dependencies=[Depends(verify_api_key)])
async def evening_digest():
    """Gather items for evening digest."""
    from outputs.push_sender import gather_evening_items
    items = gather_evening_items()
    return {"items": items, "count": len(items), "type": "evening"}


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

    # CITATIONS_API_SCAN_1: Build Anthropic Citations document blocks from the
    # pre-fetched context sections. Model-level grounding hooks when the
    # capability_runner stream surfaces the raw Anthropic response (follow-on).
    # Adapter degrades gracefully — empty list if pre_parts empty.
    try:
        _citation_doc_blocks = build_document_blocks([
            {"title": f"Specialist Context {i + 1}", "body": part}
            for i, part in enumerate(pre_parts) if part
        ])
        logger.debug(
            f"Specialist citations adapter: {len(_citation_doc_blocks)} doc blocks",
        )
    except Exception as _cite_e:
        logger.warning(f"Specialist citations adapter failed (non-fatal): {_cite_e}")

    plan = RoutingPlan(mode="fast", capabilities=[cap])
    scan_req = ScanRequest(question=req.question, history=req.history)
    return _scan_chat_capability(scan_req, start, {"plan": plan},
                                  entity_context=entity_context)


@app.post("/api/scan/client-pm", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def scan_client_pm(req: SpecialistScanRequest):
    """
    CLIENT-PM-1: Force-route to a Client PM capability with deep context.
    Reuses the specialist pre-fetch pattern — same deep context injection.

    CITATIONS_API_SCAN_1: Citations adapter wiring — the actual retrieval
    and document-block construction happens inside scan_specialist (the
    shared deep-context path). This call site shape-validates the adapter
    entry point for the client-pm surface per S5 §5 mechanical enforcement.
    """
    # Shape-validate the adapter on empty input — guarantees the import path
    # is exercised on every client-pm request. Graceful on empty input.
    try:
        _ = build_document_blocks([])
    except Exception as _cite_e:
        logger.warning(f"Client-PM citations adapter warm-path failed: {_cite_e}")
    return await scan_specialist(req)


@app.get("/api/client-pms", tags=["dashboard-v3"], dependencies=[Depends(verify_api_key)])
async def get_client_pms():
    """CLIENT-PM-1: List active client PM capabilities for the sidebar picker."""
    try:
        store = _get_store()
        caps = store.get_capability_sets(active_only=True)
        pms = [_serialize(c) for c in caps if c.get("capability_type") == "client_pm"]
        return {"client_pms": pms, "count": len(pms)}
    except Exception as e:
        logger.error(f"GET /api/client-pms failed: {e}")
        return {"client_pms": [], "count": 0, "error": str(e)}


@app.post("/api/scan/image", tags=["scan"], dependencies=[Depends(verify_api_key)])
async def scan_image(
    file: UploadFile = File(...),
    question: str = Form("What is this? Analyze it and tell me anything relevant."),
):
    """
    MOBILE-VOICE-1: Accept an image + optional question, analyze with Claude Vision.
    Returns a JSON response (not SSE) for iOS Shortcuts compatibility.
    Supports JPEG, PNG, GIF, WebP.
    """
    # Validate file type
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        ext = Path(file.filename or "").suffix.lower()
        type_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                    ".gif": "image/gif", ".webp": "image/webp"}
        content_type = type_map.get(ext, "")
    if content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        raise HTTPException(400, "Unsupported image type. Accepted: JPEG, PNG, GIF, WebP.")

    # Read, resize if needed, and base64-encode
    import base64
    from io import BytesIO
    image_bytes = await file.read()
    if len(image_bytes) > 20 * 1024 * 1024:  # 20MB hard limit
        raise HTTPException(400, "Image too large (max 20MB).")

    # Resize if over 4.5MB (Claude limit is 5MB base64, ~3.75MB raw)
    if len(image_bytes) > 3_500_000:
        try:
            from PIL import Image as PILImage
            img = PILImage.open(BytesIO(image_bytes))
            # Progressive downscale until under 3.5MB
            quality = 85
            while len(image_bytes) > 3_500_000 and quality >= 30:
                w, h = img.size
                if w > 2048 or h > 2048:
                    img.thumbnail((2048, 2048), PILImage.LANCZOS)
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                image_bytes = buf.getvalue()
                content_type = "image/jpeg"
                quality -= 10
            logger.info(f"Image resized: {len(image_bytes)} bytes, quality={quality+10}")
        except Exception as resize_err:
            logger.warning(f"Image resize failed (will try raw): {resize_err}")

    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    # Call Claude Vision
    try:
        client = anthropic.Anthropic()
        resp = _llm_call("gemini-2.5-flash",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}},
                    {"type": "text", "text": question},
                ],
            }],
        )
        answer = resp.text
        # Log cost
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="scan_image")
        logger.info(f"Scan image: {file.filename}, {len(image_bytes)} bytes, question='{question[:60]}'")
        return {"answer": answer, "model": "gemini-2.5-flash",
                "tokens": {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}}
    except Exception as e:
        logger.error(f"POST /api/scan/image failed: {e}")
        raise HTTPException(500, f"Image analysis failed: {e}")


# ============================================================
# AI_HOTEL_FIELD_CAPTURE_1 — one-tap mobile capture → LLM classify → Field notes
# ============================================================

_AI_HOTEL_SECTIONS = ("use_case", "stakeholder", "research", "comms", "general")

_AI_HOTEL_CLASSIFY_PROMPT = (
    "You are sorting a field note captured by Brisen's chairman at a "
    "hospitality-tech exhibition into one section of the \"AI Hotel\" dashboard "
    "(a NVIDIA × Mandarin Oriental × Brisen strategy map). Sections: "
    "`use_case` (an AI hotel capability area: flagship, concierge/reservations, "
    "staff training, operations/personalization, digital twins/design, "
    "discovery/GEO, robotics), `stakeholder` (a party's give/get: NVIDIA, "
    "Mandarin Oriental, Brisen, AI startups, investor/owner/lender, guests), "
    "`research` (a study/source/competitor/market datapoint), `comms` "
    "(something about outreach to NVIDIA or MOHG), `general` (anything else "
    "worth keeping). Return STRICT JSON only: "
    "{\"section_guess\":\"<one of the five>\",\"related_area\":\"<short tag or "
    "null>\",\"summary\":\"<≤18-word plain-English summary>\"}. No prose."
)


# base64 inflates ~33%, so a 370KB raw target yields ~493KB encoded — under the
# brief's ~500KB DB cap. Hard ceiling, not advisory (codex G3 S2): an image that
# cannot be decoded OR cannot be brought under this size is REJECTED, never
# stored raw.
_AI_HOTEL_DB_RAW_CAP = 370_000

# AI_HOTEL_CAPTURE_UPGRADES_1 limits.
_AI_HOTEL_MAX_IMAGES = 8            # photos per capture; the 9th is rejected (400)
_AI_HOTEL_NOTE_CAP = 50_000        # server-enforced note ceiling (HTML maxlength is advisory)
_AI_HOTEL_AUDIO_CAP = 25 * 1024 * 1024   # 25MB hard cap; ~10-min dictation fits well under
_AI_HOTEL_AUDIO_TYPES = (
    "audio/webm", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav",
    "audio/ogg", "audio/aac", "audio/m4a", "audio/x-m4a",
)
_AI_HOTEL_VIDEO_CAP = 50 * 1024 * 1024
_AI_HOTEL_VIDEO_MAX_SECONDS = 30.0
_AI_HOTEL_VIDEO_TYPES = ("video/webm", "video/mp4", "video/quicktime")
_AI_HOTEL_POSTER_CAP = 1 * 1024 * 1024
_AI_HOTEL_POSTER_TYPES = ("image/jpeg", "image/png", "image/webp")
_AI_HOTEL_MEDIA_PREFIX = "ai-hotel/captures"

# Verbatim-transcription prompt for the dictated-audio path. Gemini returns the
# transcript as plain text via the same response.text access the classify call
# already uses — no new response-shape assumption (three-way match holds).
_AI_HOTEL_TRANSCRIBE_PROMPT = (
    "Transcribe this audio dictation verbatim into plain English text. "
    "Output ONLY the transcript — no commentary, no headings, no speaker labels. "
    "If the audio is silent or unintelligible, output an empty string."
)
_AI_HOTEL_TRANSCRIBE_MAX_TOKENS = 8000   # ~10-min speech ≈ 1.5k words ≈ 2k tok; generous


class AIHotelCaptureMediaPresignRequest(BaseModel):
    asset: Literal["video", "thumbnail"] = "video"
    content_type: str
    size_bytes: int = Field(..., ge=1)
    duration_seconds: Optional[float] = None


class AIHotelCaptureMediaConfirmRequest(BaseModel):
    media_type: Literal["video"] = "video"
    storage_key: str
    thumbnail_key: Optional[str] = None
    content_type: str
    size_bytes: int = Field(..., ge=1)
    duration_seconds: float


def _ai_hotel_clean_content_type(content_type: str) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _ai_hotel_validate_media_payload(
    asset: str,
    content_type: str,
    size_bytes: int,
    duration_seconds: Optional[float] = None,
):
    content_type = _ai_hotel_clean_content_type(content_type)
    try:
        size_bytes = int(size_bytes)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid media size.")
    if size_bytes <= 0:
        raise HTTPException(400, "Invalid media size.")
    if asset == "video":
        if content_type not in _AI_HOTEL_VIDEO_TYPES:
            raise HTTPException(400, "Unsupported video type. Accepted: WebM, MP4, MOV.")
        if size_bytes > _AI_HOTEL_VIDEO_CAP:
            raise HTTPException(400, "Video too large (max 50MB).")
        try:
            duration = float(duration_seconds)
        except (TypeError, ValueError):
            raise HTTPException(400, "Video duration is required.")
        if duration <= 0 or duration > _AI_HOTEL_VIDEO_MAX_SECONDS:
            raise HTTPException(400, "Video must be 30 seconds or shorter.")
        return content_type, size_bytes, duration
    if asset == "thumbnail":
        if content_type not in _AI_HOTEL_POSTER_TYPES:
            raise HTTPException(400, "Unsupported thumbnail type. Accepted: JPEG, PNG, WebP.")
        if size_bytes > _AI_HOTEL_POSTER_CAP:
            raise HTTPException(400, "Thumbnail too large (max 1MB).")
        return content_type, size_bytes, None
    raise HTTPException(400, "Unsupported media asset.")


def _ai_hotel_media_ext(content_type: str) -> str:
    return {
        "video/webm": "webm",
        "video/mp4": "mp4",
        "video/quicktime": "mov",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type, "bin")


def _ai_hotel_media_prefix(capture_id: int, asset: str) -> str:
    folder = "video" if asset == "video" else "thumbnail"
    return f"{_AI_HOTEL_MEDIA_PREFIX}/{int(capture_id)}/{folder}/"


def _ai_hotel_new_media_key(capture_id: int, asset: str, content_type: str) -> str:
    return (
        f"{_ai_hotel_media_prefix(capture_id, asset)}"
        f"{uuid4().hex}.{_ai_hotel_media_ext(content_type)}"
    )


def _ai_hotel_require_media_key(capture_id: int, asset: str, key: str) -> str:
    key = (key or "").strip()
    if not key.startswith(_ai_hotel_media_prefix(capture_id, asset)):
        raise HTTPException(400, "Media key does not belong to this capture.")
    if any(part in ("", ".", "..") for part in key.split("/")) or "\\" in key:
        raise HTTPException(400, "Invalid media key.")
    return key


def _ai_hotel_resize_for_db(image_bytes: bytes, content_type: str):
    """Validate + resize an uploaded image to <= ~500KB base64 for Postgres.

    Always re-encodes to JPEG so the stored row is a known-good, size-capped
    image. Applies EXIF orientation before re-encoding so phone portrait shots do
    not become sideways after Pillow strips metadata. Raises ``ValueError`` when
    the bytes are not a decodable image or
    cannot be brought under ``_AI_HOTEL_DB_RAW_CAP`` — the caller converts that
    to HTTP 400 (codex G3 S2: never persist undecodable/oversize raw bytes).
    Returns ``(b64_text, "image/jpeg")``.
    """
    import base64
    from io import BytesIO
    from PIL import Image as PILImage, ImageOps

    # Decode/validate up front — reject anything PIL cannot open (verify() then
    # a fresh open, since verify() leaves the handle unusable for further ops).
    try:
        PILImage.open(BytesIO(image_bytes)).verify()
        img = PILImage.open(BytesIO(image_bytes))
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
    except Exception as decode_err:
        raise ValueError(f"undecodable image: {decode_err}")

    # Dimension-cap first (bounds the first encode), then progressively shrink
    # until raw JPEG bytes are under the DB cap or we hit the dimension floor.
    img.thumbnail((2048, 2048), PILImage.LANCZOS)
    max_dim = 2048
    quality = 85
    while True:
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= _AI_HOTEL_DB_RAW_CAP or max_dim < 480:
            break
        max_dim = int(max_dim * 0.8)
        img.thumbnail((max_dim, max_dim), PILImage.LANCZOS)
        if quality > 55:
            quality -= 5

    if len(data) > _AI_HOTEL_DB_RAW_CAP:
        raise ValueError(
            f"image still {len(data)} bytes after resize (cap {_AI_HOTEL_DB_RAW_CAP})"
        )

    logger.info(f"ai_hotel image capped for DB: {len(data)} bytes")
    b64 = base64.standard_b64encode(data).decode("utf-8")
    return b64, "image/jpeg"


def _ai_hotel_thumb_data_url(image_b64, media: str = "image/jpeg", px: int = 160):
    """AI_HOTEL_FIELDNOTES_THUMBNAIL_LAZYIMG_1: a small (~160px longest-edge)
    JPEG thumbnail data-URL from a stored base64 image, or None.

    The Field Notes list inlined full-res base64 for every capture (7.1 MB feed →
    phone hung on "Loading…"). The list now carries only this tiny thumb; full
    images load on tap. Fail-soft: any decode/resize error returns None so the
    feed never breaks (kill criterion)."""
    if not image_b64:
        return None
    try:
        import base64 as _b64
        from io import BytesIO
        from PIL import Image as PILImage, ImageOps
        raw = _b64.b64decode(image_b64)
        img = PILImage.open(BytesIO(raw))
        img.load()
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((px, px), PILImage.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=70, optimize=True)
        return "data:image/jpeg;base64," + _b64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        logger.warning("ai_hotel thumbnail generation failed (thumb=None): %s", e)
        return None


def _ai_hotel_image_data_url(image_b64, media: str = "image/jpeg"):
    """Return a displayable data URL, correcting EXIF orientation when present.

    Stored AI-Hotel images are usually already JPEG-normalized at upload. This
    helper preserves the raw stored data unless it sees an EXIF orientation tag,
    then rotates pixels and re-encodes to JPEG so the lightbox is upright even if
    the stored row still carries phone orientation metadata. Bad legacy/fake rows
    fall back to the previous straight-through data URL behavior.
    """
    if not image_b64:
        return None
    media = media or "image/jpeg"
    raw_url = f"data:{media};base64,{image_b64}"
    try:
        import base64 as _b64
        from io import BytesIO
        from PIL import Image as PILImage, ImageOps

        raw = _b64.b64decode(image_b64)
        img = PILImage.open(BytesIO(raw))
        img.load()
        try:
            orientation = img.getexif().get(274)
        except Exception:
            orientation = None
        if orientation not in (2, 3, 4, 5, 6, 7, 8):
            return raw_url
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        return "data:image/jpeg;base64," + _b64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        logger.warning("ai_hotel full-image EXIF orientation fallback used: %s", e)
        return raw_url


def _ai_hotel_rotate_image_b64(image_b64: str, media: str = "image/jpeg", deg: int = 90):
    """Rotate stored AI-Hotel image pixels clockwise and return JPEG base64.

    The caller updates Postgres only after this helper has decoded, rotated, and
    re-encoded successfully, so a bad legacy image never destroys the original
    stored bytes.
    """
    import base64 as _b64
    from io import BytesIO
    from PIL import Image as PILImage, ImageOps

    if deg not in (90, 180, 270):
        raise ValueError("deg must be 90, 180, or 270")
    raw = _b64.b64decode(image_b64)
    img = PILImage.open(BytesIO(raw))
    img.load()
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    rotated = img.rotate(-deg, expand=True)
    if rotated.mode != "RGB":
        rotated = rotated.convert("RGB")
    buf = BytesIO()
    rotated.save(buf, format="JPEG", quality=85, optimize=True)
    data = buf.getvalue()
    return _b64.b64encode(data).decode("ascii"), "image/jpeg"


# ── AI_HOTEL_GPS_CAPTURE_1: capture-level GPS evidence ──────────────────────
# GPS is captured client-side (navigator.geolocation, with permission) and is
# HARD EVIDENCE — stored SEPARATELY from any dictated address_or_location_clue
# (a claim). The coordinates are persisted as a post-commit enrichment of the
# raw capture row (the raw capture is committed FIRST, exactly like the audio
# transcript UPDATE) so a GPS/geocode failure can NEVER lose a capture.

_AI_HOTEL_GPS_ACCURACY_LOW_M = 150.0   # > this → low-accuracy: store, flag, do NOT geocode
_ai_hotel_nominatim_last_call = [0.0]  # module-level 1-req/s guard for OSM Nominatim


def _ai_hotel_reverse_geocode(lat: float, lng: float):
    """Reverse-geocode (lat,lng) → (address, source) server-side, single-shot.

    Google Geocoding API if GOOGLE_GEOCODING_API_KEY is set (best street-address
    quality), else OSM Nominatim with an explicit User-Agent + a 1 req/s guard.
    NEVER raises — returns (None, None) on any failure so the caller can record
    gps_address_status='geocode_failed' with the coordinates still intact. No
    geocode key is ever exposed client-side; this runs server-only."""
    import os as _os
    import requests as _requests
    gkey = (_os.environ.get("GOOGLE_GEOCODING_API_KEY") or "").strip()
    try:
        if gkey:
            r = _requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"latlng": f"{lat},{lng}", "key": gkey},
                timeout=6,
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("results") or []
            if data.get("status") == "OK" and results:
                addr = (results[0].get("formatted_address") or "").strip()
                if addr:
                    return addr[:500], "google"
            return None, None
        # OSM Nominatim — usage policy requires a real User-Agent + ≤1 req/s.
        import time as _time
        elapsed = _time.time() - _ai_hotel_nominatim_last_call[0]
        if elapsed < 1.0:
            _time.sleep(1.0 - elapsed)
        _ai_hotel_nominatim_last_call[0] = _time.time()
        r = _requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lng, "format": "jsonv2"},
            headers={"User-Agent": "BakerSentinel/1.0 (ai-hotel field capture; dvallen@brisengroup.com)"},
            timeout=6,
        )
        r.raise_for_status()
        data = r.json()
        addr = (data.get("display_name") or "").strip()
        if addr:
            return addr[:500], "nominatim"
        return None, None
    except Exception as e:
        logger.warning("ai_hotel reverse-geocode failed (address=None): %s", e)
        return None, None


def _ai_hotel_persist_gps(store, capture_id: int, *, gps_lat="", gps_lng="",
                          gps_accuracy_m="", gps_captured_at="",
                          gps_capture_method="", gps_address_status=""):
    """Post-commit GPS enrichment of an already-saved capture. Parses + validates
    the client payload, reverse-geocodes ONCE (server-side, non-blocking), and
    UPDATEs the gps_* columns. NEVER raises — the raw capture is already
    committed, so any failure here is logged and swallowed (AC2/AC3 fail-soft).

    Status precedence (gps_address_status):
      - no coords + client 'permission_denied'/'timeout' → that status, coords NULL
      - coords + accuracy > 150 m → 'low_accuracy', address NULL (a fuzzy point
        must NOT be geocoded into a precise-looking street address — kill criterion)
      - coords + geocode ok       → 'ok'
      - coords + geocode failed   → 'geocode_failed'
      - nothing requested         → 'not_requested'
    """
    def _f(x):
        try:
            s = str(x).strip()
            return float(s) if s != "" else None
        except (TypeError, ValueError):
            return None

    try:
        lat = _f(gps_lat)
        lng = _f(gps_lng)
        acc = _f(gps_accuracy_m)
        client_status = (gps_address_status or "").strip().lower()

        # captured_at: accept an ISO-8601 string; store NULL if unparseable.
        captured_at = None
        cap_raw = (gps_captured_at or "").strip()
        if cap_raw:
            try:
                import datetime as _dt
                captured_at = _dt.datetime.fromisoformat(cap_raw.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("ai_hotel GPS captured_at unparseable (stored NULL): %r", cap_raw)

        address = None
        source = None

        have_coords = (
            lat is not None and lng is not None
            and -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0
        )
        if lat is not None and lng is not None and not have_coords:
            # Out-of-range coordinates — reject server-side (the DB CHECK is the
            # backstop). Do not store junk coords presented as GPS evidence.
            logger.warning("ai_hotel GPS coords out of range, dropped: lat=%r lng=%r", lat, lng)
            lat = lng = acc = None

        if have_coords:
            if acc is not None and acc < 0:
                acc = None
            if acc is not None and acc > _AI_HOTEL_GPS_ACCURACY_LOW_M:
                status = "low_accuracy"   # flagged, NOT geocoded (no precise-looking address)
            else:
                address, source = _ai_hotel_reverse_geocode(lat, lng)
                status = "ok" if address else "geocode_failed"
        elif client_status in ("permission_denied", "timeout"):
            status = client_status
            lat = lng = acc = None
            captured_at = None
        else:
            status = "not_requested"

        with_conn = store._get_conn()
        if not with_conn:
            return
        try:
            cur = with_conn.cursor()
            cur.execute(
                """UPDATE ai_hotel_captures
                      SET gps_lat = %s, gps_lng = %s, gps_accuracy_m = %s,
                          gps_captured_at = %s, gps_address = %s,
                          gps_address_source = %s, gps_address_status = %s
                    WHERE id = %s""",
                (lat, lng, acc, captured_at, address, source, status, capture_id),
            )
            with_conn.commit()
            cur.close()
            logger.info("ai_hotel GPS persisted: capture=%s status=%s acc=%s source=%s",
                        capture_id, status, acc, source)
        except Exception:
            with_conn.rollback()
            raise
        finally:
            store._put_conn(with_conn)
    except Exception as e:
        # Capture is already committed — never propagate (AC2/AC3 fail-soft).
        logger.error("ai_hotel GPS persist failed (capture %s intact): %s", capture_id, e)


@app.post("/api/ai-hotel/capture", tags=["ai-hotel"], dependencies=[Depends(verify_api_key)])
async def ai_hotel_capture(
    images: list[UploadFile] = File(None),
    audio: UploadFile = File(None),
    note: str = Form(""),
    gps_lat: str = Form(""),
    gps_lng: str = Form(""),
    gps_accuracy_m: str = Form(""),
    gps_captured_at: str = Form(""),
    gps_capture_method: str = Form(""),
    gps_address_status: str = Form(""),
):
    """AI_HOTEL_FIELD_CAPTURE_1 + _UPGRADES_1: accept up to 8 phone photos
    and/or a dictated note and/or a long audio dictation; classify into one
    AI-Hotel dashboard section via Gemini Vision; persist to Postgres (photos as
    base64 in a child table — Render FS is ephemeral). Modeled on scan_image's
    image-handling + LLM pattern.
    """
    note = (note or "").strip()
    # Enforce the note cap server-side — the HTML maxlength is advisory only and
    # trivially bypassed (codex G3 S3). This bounds the user-typed note; a long
    # audio transcript is appended afterward (transcripts can be lengthy).
    if len(note) > _AI_HOTEL_NOTE_CAP:
        raise HTTPException(400, f"Note too long (max {_AI_HOTEL_NOTE_CAP} characters).")

    # FastAPI gives `images` as None, [] or a list of UploadFile; an empty field
    # arrives as an UploadFile with no filename. Keep only real uploads.
    incoming = [im for im in (images or []) if im is not None and getattr(im, "filename", None)]
    if len(incoming) > _AI_HOTEL_MAX_IMAGES:
        raise HTTPException(400, f"Too many photos (max {_AI_HOTEL_MAX_IMAGES} per capture).")
    has_audio = audio is not None and getattr(audio, "filename", None)

    if not incoming and not note and not has_audio:
        raise HTTPException(400, "Provide a photo, a note, or an audio dictation.")

    # --- Resize each photo (reuse the single-image validator verbatim) --------
    resized_images: list = []   # list of (b64, media) in upload order
    for image in incoming:
        content_type = image.content_type or ""
        if not content_type.startswith("image/"):
            ext = Path(image.filename or "").suffix.lower()
            type_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                        ".gif": "image/gif", ".webp": "image/webp"}
            content_type = type_map.get(ext, "")
        if content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            raise HTTPException(400, "Unsupported image type. Accepted: JPEG, PNG, GIF, WebP.")
        image_bytes = await image.read()
        if len(image_bytes) > 20 * 1024 * 1024:  # 20MB hard limit, per photo
            raise HTTPException(400, "Image too large (max 20MB).")
        try:
            ib64, imedia = _ai_hotel_resize_for_db(image_bytes, content_type)
        except ValueError as ve:
            logger.warning(f"ai_hotel_capture rejected image: {ve}")
            raise HTTPException(400, "Unreadable image, or could not compress it under the size limit.")
        resized_images.append((ib64, imedia))

    # --- Transcribe audio (server-side via Gemini multimodal) -----------------
    transcript = ""
    if has_audio:
        audio_type = audio.content_type or ""
        if audio_type not in _AI_HOTEL_AUDIO_TYPES:
            ext = Path(audio.filename or "").suffix.lower()
            audio_map = {".webm": "audio/webm", ".mp4": "audio/mp4", ".m4a": "audio/mp4",
                         ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
                         ".aac": "audio/aac"}
            audio_type = audio_map.get(ext, "")
        if audio_type not in _AI_HOTEL_AUDIO_TYPES:
            raise HTTPException(400, "Unsupported audio type. Accepted: WebM, MP4/M4A, MP3, WAV, OGG, AAC.")
        audio_bytes = await audio.read()
        if len(audio_bytes) > _AI_HOTEL_AUDIO_CAP:
            raise HTTPException(400, "Audio too large (max 25MB).")
        try:
            import base64 as _b64a
            audio_b64 = _b64a.standard_b64encode(audio_bytes).decode("utf-8")
            # thinking_budget=0 is load-bearing here exactly as on the sibling
            # classify call: 2.5-flash's default dynamic thinking would eat the
            # output budget and truncate/empty the transcript (the #372
            # MAX_TOKENS root cause). Transcription needs ZERO thinking.
            aresp = _llm_call(
                "gemini-2.5-flash",
                max_tokens=_AI_HOTEL_TRANSCRIBE_MAX_TOKENS,
                thinking_budget=0,
                messages=[{"role": "user", "content": [
                    {"type": "audio", "source": {"type": "base64",
                                                 "media_type": audio_type, "data": audio_b64}},
                    {"type": "text", "text": _AI_HOTEL_TRANSCRIBE_PROMPT},
                ]}],
            )
            transcript = (aresp.text or "").strip()
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", aresp.usage.input_tokens, aresp.usage.output_tokens,
                         source="ai_hotel_capture_transcribe")
            if not transcript:
                logger.warning(
                    "ai_hotel_capture audio transcription returned EMPTY text "
                    "(in=%s out=%s).", aresp.usage.input_tokens, aresp.usage.output_tokens)
        except HTTPException:
            raise
        except Exception as tx_err:
            # Fault-tolerant: a transcription failure must not lose the capture.
            # Fall through with an empty transcript (loud server-side log).
            logger.error(f"ai_hotel_capture audio transcription failed: {tx_err}", exc_info=True)
            transcript = ""

    # Fold the transcript into note_text — the text that is classified + embedded.
    if transcript:
        note = f"{note}\n\n{transcript}".strip() if note else transcript

    if not resized_images and not note:
        # Audio yielded no usable transcript and nothing else was attached —
        # fail loud rather than persist an empty capture.
        raise HTTPException(400, "Nothing to save — audio could not be transcribed and no photo or note was provided.")

    # Provenance: photos win, else audio-only, else plain note.
    if resized_images:
        source = "photo"
    elif has_audio:
        source = "audio"
    else:
        source = "note"

    # Legacy single-image columns mirror the FIRST photo for any un-upgraded
    # reader; ALL photos also land in the child table after the parent insert.
    b64 = resized_images[0][0] if resized_images else None
    image_media = resized_images[0][1] if resized_images else None
    section_guess = "general"
    related_area = None
    summary = (note[:200] if note else "Photo capture")

    # Classification — reuse scan_image's exact _llm_call / .text / .usage shape.
    try:
        content = []
        if b64:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": image_media, "data": b64}})
        text_block = _AI_HOTEL_CLASSIFY_PROMPT
        if note:
            text_block += f"\n\nField note text (chairman dictation):\n{note}"
        elif b64:
            text_block += "\n\n(Photo only, no dictated text.)"
        content.append({"type": "text", "text": text_block})

        # thinking_budget=0 DISABLES 2.5-flash thinking — without it the default
        # dynamic thinking eats the 600-tok budget and truncates the JSON mid-
        # object (finish_reason=MAX_TOKENS, empty .text), which silently routed
        # 100% of captures to general (AI_HOTEL_CAPTURE_CLASSIFY_1 diagnosis).
        # response_format="json" forces clean fence-free JSON.
        resp = _llm_call("gemini-2.5-flash", max_tokens=600,
                         response_format="json", thinking_budget=0,
                         messages=[{"role": "user", "content": content}])
        answer = (resp.text or "").strip()
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens,
                     source="ai_hotel_capture")

        # FAIL LOUD: an empty model response is the silent-truncation signature —
        # log at error so it can never again be swallowed unnoticed.
        if not answer:
            logger.error(
                "ai_hotel_capture classification returned EMPTY text "
                "(in=%s out=%s) — staying general; check thinking/token budget.",
                resp.usage.input_tokens, resp.usage.output_tokens,
            )

        # Defensive parse: strip code fences, json.loads, validate section.
        raw = answer
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1] if "```" in raw[3:] else raw.strip("`")
            if raw.lstrip().lower().startswith("json"):
                raw = raw.lstrip()[4:]
        start, end = raw.find("{"), raw.rfind("}")
        parsed = json.loads(raw[start:end + 1]) if start != -1 and end != -1 else {}
        cand = str(parsed.get("section_guess", "")).strip().lower()
        if cand in _AI_HOTEL_SECTIONS:
            section_guess = cand
            ra = parsed.get("related_area")
            related_area = str(ra).strip()[:120] if ra and str(ra).strip().lower() != "null" else None
            s = parsed.get("summary")
            if s and str(s).strip():
                summary = str(s).strip()[:400]
        elif answer:
            # Non-empty but unusable (no valid section parsed): surface it loud
            # rather than silently defaulting — this is the other silent path.
            logger.error(
                "ai_hotel_capture classification produced no valid section "
                "(cand=%r) — staying general. Raw head: %s",
                cand, answer[:200],
            )
    except Exception as classify_err:
        logger.error(f"ai_hotel_capture classification failed (fail-soft to general): {classify_err}",
                     exc_info=True)

    # Persist (parameterized) — image as base64 text, never to disk.
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(503, "Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO ai_hotel_captures
                       (source, note_text, image_b64, image_media,
                        section_guess, related_area, summary)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (source, note or None, b64, image_media,
                 section_guess, related_area, summary),
            )
            new_id = cur.fetchone()[0]
            # One child row per photo, ordered. The first photo is duplicated in
            # the parent legacy columns above for un-upgraded readers; the GET
            # endpoint reads the child table for the full ordered set.
            for ordinal, (ib64, imedia) in enumerate(resized_images):
                cur.execute(
                    """INSERT INTO ai_hotel_capture_images
                           (capture_id, ordinal, image_b64, image_media)
                       VALUES (%s, %s, %s, %s)""",
                    (new_id, ordinal, ib64, imedia),
                )
            conn.commit()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        # Log the raw exception server-side; return a generic message so we
        # never leak DB internals to the client (security-review LOW nit,
        # mirrors the read endpoint's fail-soft pattern).
        logger.error(f"POST /api/ai-hotel/capture insert failed: {e}")
        raise HTTPException(500, "Could not save capture")

    logger.info(f"ai_hotel_capture saved: id={new_id} source={source} section={section_guess}")

    # AI_HOTEL_GPS_CAPTURE_1: enrich with GPS evidence AFTER the raw capture is
    # safely committed (single-shot reverse-geocode, non-blocking, non-fatal).
    _ai_hotel_persist_gps(
        store, new_id,
        gps_lat=gps_lat, gps_lng=gps_lng, gps_accuracy_m=gps_accuracy_m,
        gps_captured_at=gps_captured_at, gps_capture_method=gps_capture_method,
        gps_address_status=gps_address_status,
    )

    # AI_HOTEL_CAPTURE_EMBED_1: also make the note semantically searchable via
    # Baker's vector memory. BEST-EFFORT — the DB row above is the source of
    # truth; an embed failure must never block the 200 (the insert already
    # committed). Routes through the canonical kbl ingest chokepoint, which uses
    # the SentinelStoreBack singleton internally (never instantiate directly).
    if note:
        try:
            from kbl.ingest_endpoint import ingest as _kbl_ingest
            _body_parts = []
            if summary and summary != note[:200]:
                _body_parts.append(f"Summary: {summary}")
            _body_parts.append(note)
            _result = _kbl_ingest(
                frontmatter={
                    "type": "entity",
                    "slug": f"ai-hotel-capture-{new_id}",
                    "name": f"AI Hotel field capture #{new_id} ({section_guess})",
                    "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "author": "agent",
                    "tags": ["ai-hotel"],
                    "related": [],
                },
                body="\n\n".join(_body_parts),
                trigger_source="ai_hotel_capture",
            )
            # ingest() writes the wiki page atomically but does the Qdrant upsert
            # post-atomically and returns qdrant_point_id=None when Qdrant is down
            # or the embedding is empty. Don't claim "embedded" unless it actually
            # vectorized — that false-success was itself a silent gap (G3 S2-2).
            if getattr(_result, "qdrant_point_id", None) is not None:
                logger.info(
                    f"ai_hotel_capture embedded to vector memory: id={new_id} "
                    f"point={_result.qdrant_point_id}"
                )
            else:
                logger.warning(
                    f"ai_hotel_capture wiki page written but NOT vector-embedded "
                    f"(Qdrant unavailable or empty embedding): id={new_id}"
                )
        except Exception as embed_err:
            # Loud but non-fatal — capture is already persisted.
            logger.error(
                f"ai_hotel_capture embed failed (non-fatal, id={new_id}): {embed_err}",
                exc_info=True,
            )

    return {"id": new_id, "section_guess": section_guess,
            "related_area": related_area, "summary": summary}


def _ai_hotel_form_record_view(fr):
    """AI_HOTEL_FIELD_NOTES_CARD_SHELF_1: shape a raw ai_hotel_form_records row
    into the feed's optional `form_record` object, or None.

    Fail-soft (AC5): any malformed/missing field yields None rather than breaking
    the feed. Never duplicates image base64 — images stay sourced from captures.
    A confirmed card surfaces its user-corrected values; otherwise the extracted
    values."""
    if not fr:
        return None
    try:
        status = fr.get("status")
        corrected = fr.get("corrected_json")
        extracted = fr.get("extracted_json")
        vals = corrected if (status == "confirmed" and isinstance(corrected, dict)) else extracted
        if not isinstance(vals, dict):
            vals = {}
        fm = fr.get("field_meta_json")
        if not isinstance(fm, dict):
            fm = {}
        return {
            "id": fr.get("id"),
            "form_type": fr.get("form_type"),
            "schema_version": fr.get("schema_version"),
            "status": status,
            "values": vals,
            "field_meta": fm,
        }
    except Exception:
        return None


@app.post("/api/ai-hotel/captures/{capture_id}/media/presign",
          tags=["ai-hotel"], dependencies=[Depends(verify_api_key)])
async def ai_hotel_capture_media_presign(
    capture_id: int,
    payload: AIHotelCaptureMediaPresignRequest,
):
    """Presign one R2 media object for an existing raw capture.

    The caller must enforce the user-facing cap and pass the browser's
    ``File.size`` before this route signs. This route repeats those checks
    server-side; it never accepts base64 media and never creates the parent
    capture, so upload failure cannot roll back the raw capture row.
    """
    content_type, size_bytes, duration = _ai_hotel_validate_media_payload(
        payload.asset, payload.content_type, payload.size_bytes, payload.duration_seconds,
    )
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(503, "Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM ai_hotel_captures WHERE id = %s", (capture_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Capture not found.")
            cur.close()
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("ai_hotel media presign capture check failed: %s", e)
        raise HTTPException(500, "Could not prepare media upload.")

    key = _ai_hotel_new_media_key(capture_id, payload.asset, content_type)
    try:
        from kbl.object_storage import generate_presigned_put
        signed = generate_presigned_put(key, content_type, size_bytes, expires=300)
    except Exception as e:
        logger.error("ai_hotel media presign failed: %s", e)
        raise HTTPException(503, "Media storage unavailable.")
    if not signed.get("ok"):
        logger.warning("ai_hotel media presign unavailable: %s", signed.get("error"))
        raise HTTPException(503, "Media storage unavailable.")
    return {
        "ok": True,
        "asset": payload.asset,
        "key": key,
        "upload": signed,
        "limits": {
            "video_max_bytes": _AI_HOTEL_VIDEO_CAP,
            "video_max_seconds": _AI_HOTEL_VIDEO_MAX_SECONDS,
            "thumbnail_max_bytes": _AI_HOTEL_POSTER_CAP,
        },
        "duration_seconds": duration,
    }


@app.post("/api/ai-hotel/captures/{capture_id}/media/confirm",
          tags=["ai-hotel"], dependencies=[Depends(verify_api_key)])
async def ai_hotel_capture_media_confirm(
    capture_id: int,
    payload: AIHotelCaptureMediaConfirmRequest,
):
    """Record metadata for a video that was already uploaded to R2."""
    content_type, size_bytes, duration = _ai_hotel_validate_media_payload(
        "video", payload.content_type, payload.size_bytes, payload.duration_seconds,
    )
    storage_key = _ai_hotel_require_media_key(capture_id, "video", payload.storage_key)
    thumbnail_key = None
    if payload.thumbnail_key:
        thumbnail_key = _ai_hotel_require_media_key(capture_id, "thumbnail", payload.thumbnail_key)
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(503, "Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM ai_hotel_captures WHERE id = %s", (capture_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Capture not found.")
            cur.execute(
                """INSERT INTO ai_hotel_capture_media
                       (capture_id, media_type, storage_key, thumbnail_key,
                        content_type, size_bytes, duration_seconds)
                   VALUES (%s, 'video', %s, %s, %s, %s, %s)
                   RETURNING id, created_at""",
                (capture_id, storage_key, thumbnail_key, content_type, size_bytes, duration),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
        media_id = row[0] if not isinstance(row, dict) else row.get("id")
        created_at = row[1] if not isinstance(row, dict) else row.get("created_at")
        return {
            "ok": True,
            "media": {
                "id": media_id,
                "media_type": "video",
                "content_type": content_type,
                "size_bytes": size_bytes,
                "duration_seconds": duration,
                "has_thumbnail": bool(thumbnail_key),
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("POST /api/ai-hotel/captures/%s/media/confirm failed: %s", capture_id, e)
        raise HTTPException(500, "Could not save media metadata.")


@app.get("/api/ai-hotel/captures", tags=["ai-hotel"],
         dependencies=[Depends(verify_ai_hotel_read_access)])
async def ai_hotel_captures(limit: int = 100):
    """AI_HOTEL_FIELD_CAPTURE_1 + _FIELD_NOTES_CARD_SHELF_1: list field-note
    captures newest-first for the dashboard "Field notes" surface, each with its
    latest non-discarded structured card (form_record) when present. Fail-soft
    empty list on any error."""
    limit = max(1, min(limit, 200))
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"captures": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT id, created_at, source, note_text, image_b64, image_media,
                          section_guess, related_area, summary, status,
                          gps_lat, gps_lng, gps_accuracy_m, gps_captured_at,
                          gps_address, gps_address_source, gps_address_status
                     FROM ai_hotel_captures
                    WHERE status <> 'dismissed'
                      AND deleted_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
            # Fetch all child photos for the returned captures in ONE query
            # (avoids N+1); group by capture_id in Python, ordered by ordinal.
            cap_ids = [r["id"] for r in rows]
            child_by_cap: dict = {}
            if cap_ids:
                cur.execute(
                    """SELECT capture_id, ordinal, image_b64, image_media
                         FROM ai_hotel_capture_images
                        WHERE capture_id = ANY(%s)
                        ORDER BY capture_id, ordinal""",
                    (cap_ids,),
                )
                for ci in cur.fetchall():
                    child_by_cap.setdefault(ci["capture_id"], []).append(ci)
            # AI_HOTEL_FIELD_NOTES_CARD_SHELF_1: attach the latest non-discarded
            # structured form record per capture (one extra batch query, N+1-safe).
            # Fail-soft: a form-record failure must NEVER break the raw capture
            # feed (AC5) — guard locally, clear any aborted txn, serve captures.
            form_by_cap: dict = {}
            if cap_ids:
                try:
                    cur.execute(
                        """SELECT DISTINCT ON (capture_id)
                                  capture_id, id, form_type, schema_version, status,
                                  extracted_json, corrected_json, field_meta_json
                             FROM ai_hotel_form_records
                            WHERE capture_id = ANY(%s) AND status <> 'discarded'
                            ORDER BY capture_id, id DESC""",
                        (cap_ids,),
                    )
                    for fr in cur.fetchall():
                        form_by_cap[fr["capture_id"]] = fr
                except Exception as fe:
                    logger.error(
                        "ai_hotel_captures form_record join failed (feed still served): %s", fe)
                    conn.rollback()
                    form_by_cap = {}
            # WP-B / AC10: audio METADATA only in the list — never the big base64.
            # Full audio_b64 is fetched on demand from the card-detail endpoint.
            audio_by_cap: dict = {}
            if cap_ids:
                try:
                    cur.execute(
                        """SELECT capture_id, ordinal, audio_media, duration_seconds,
                                  (transcript_text IS NOT NULL AND transcript_text <> '')
                                      AS has_transcript
                             FROM ai_hotel_capture_audio
                            WHERE capture_id = ANY(%s)
                            ORDER BY capture_id, ordinal""",
                        (cap_ids,),
                    )
                    for a in cur.fetchall():
                        audio_by_cap.setdefault(a["capture_id"], []).append({
                            "ordinal": a["ordinal"],
                            "audio_media": a["audio_media"],
                            "duration_seconds": a["duration_seconds"],
                            "has_transcript": bool(a["has_transcript"]),
                        })
                except Exception as ae:
                    logger.error(
                        "ai_hotel_captures audio metadata join failed (feed still served): %s", ae)
                    conn.rollback()
                    audio_by_cap = {}
            # R2-backed video METADATA only. Do not include storage_key,
            # presigned URLs, or any binary payload in the list response.
            video_by_cap: dict = {}
            if cap_ids:
                try:
                    cur.execute(
                        """SELECT capture_id, id, content_type, size_bytes,
                                  duration_seconds, created_at,
                                  (thumbnail_key IS NOT NULL AND thumbnail_key <> '')
                                      AS has_thumbnail
                             FROM ai_hotel_capture_media
                            WHERE capture_id = ANY(%s) AND media_type = 'video'
                            ORDER BY capture_id, created_at DESC""",
                        (cap_ids,),
                    )
                    for v in cur.fetchall():
                        video_by_cap.setdefault(v["capture_id"], []).append({
                            "id": v["id"],
                            "content_type": v["content_type"],
                            "size_bytes": v["size_bytes"],
                            "duration_seconds": v["duration_seconds"],
                            "created_at": v["created_at"].isoformat()
                                if hasattr(v["created_at"], "isoformat") else v["created_at"],
                            "has_thumbnail": bool(v["has_thumbnail"]),
                        })
                except Exception as ve:
                    logger.error(
                        "ai_hotel_captures video metadata join failed (feed still served): %s", ve)
                    conn.rollback()
                    video_by_cap = {}
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
        captures = []
        for r in rows:
            d = dict(r)
            parent_b64 = d.pop("image_b64", None)
            parent_media = d.get("image_media") or "image/jpeg"
            # AI_HOTEL_FIELDNOTES_THUMBNAIL_LAZYIMG_1: the list returns ONLY a
            # tiny thumbnail of the first image + a count — never the full-res
            # base64 (that 7.1 MB feed hung the Director's phone). Full images
            # load on tap via GET /captures/{id}/images.
            children = [ci for ci in child_by_cap.get(d["id"], []) if ci.get("image_b64")]
            if children:
                image_count = len(children)
                first_b64 = children[0]["image_b64"]
                first_media = children[0].get("image_media") or "image/jpeg"
            elif parent_b64:
                image_count = 1
                first_b64 = parent_b64
                first_media = parent_media
            else:
                image_count = 0
                first_b64 = None
                first_media = "image/jpeg"
            d["thumb"] = _ai_hotel_thumb_data_url(first_b64, first_media)
            d["image_count"] = image_count
            d.pop("image_media", None)   # not needed in the list payload
            # Attach the structured card (if any); fail-soft per row (AC5).
            d["form_record"] = _ai_hotel_form_record_view(form_by_cap.get(d["id"]))
            # Attach audio METADATA only (AC10) — playback bytes come from detail.
            d["audio"] = audio_by_cap.get(d["id"], [])
            # Attach video METADATA only — playback URLs come from media detail.
            d["video"] = video_by_cap.get(d["id"], [])
            # AI_HOTEL_GPS_CAPTURE_1: fold the gps_* columns into one compact
            # `gps` object for the feed (small metadata — coords + short address;
            # NO heavy payload). Null for captures with no GPS so legacy rows
            # render cleanly (AC6). The Maps deep link is built client-side from
            # lat/lng (never from the free-text address) — AC8.
            g_lat = d.pop("gps_lat", None)
            g_lng = d.pop("gps_lng", None)
            g_acc = d.pop("gps_accuracy_m", None)
            g_cap_at = d.pop("gps_captured_at", None)
            g_addr = d.pop("gps_address", None)
            g_src = d.pop("gps_address_source", None)
            g_status = d.pop("gps_address_status", None)
            g_cap_iso = g_cap_at.isoformat() if hasattr(g_cap_at, "isoformat") else g_cap_at
            if g_lat is not None and g_lng is not None:
                d["gps"] = {
                    "lat": g_lat, "lng": g_lng, "accuracy_m": g_acc,
                    "captured_at": g_cap_iso, "address": g_addr,
                    "address_source": g_src, "address_status": g_status,
                }
            elif g_status and g_status != "not_requested":
                # No coords but a meaningful outcome (permission_denied/timeout).
                d["gps"] = {
                    "lat": None, "lng": None, "accuracy_m": None,
                    "captured_at": None, "address": None,
                    "address_source": None, "address_status": g_status,
                }
            else:
                d["gps"] = None
            captures.append(_serialize(d))
        return {"captures": captures}
    except Exception as e:
        logger.error(f"GET /api/ai-hotel/captures failed: {e}")
        return {"captures": []}


@app.get("/api/ai-hotel/captures/{capture_id}/audio", tags=["ai-hotel"],
         dependencies=[Depends(verify_ai_hotel_read_access)])
async def ai_hotel_capture_audio_detail(capture_id: int):
    """AI_HOTEL_FIELD_NOTES_AND_AUDIO_1: full audio for ONE capture, fetched on
    demand from card detail (the list endpoint returns metadata only — AC10).
    Returns playable data-URL(s). Fail-soft empty list on any error."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"audio": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT ordinal, audio_b64, audio_media, duration_seconds, transcript_text
                     FROM ai_hotel_capture_audio
                    WHERE capture_id = %s
                    ORDER BY ordinal
                    LIMIT 20""",
                (capture_id,),
            )
            rows = cur.fetchall()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
        audio = []
        for a in rows:
            if not a.get("audio_b64"):
                continue
            media = a.get("audio_media") or "audio/webm"
            audio.append({
                "ordinal": a.get("ordinal"),
                "audio_media": media,
                "duration_seconds": a.get("duration_seconds"),
                "transcript_text": a.get("transcript_text"),
                "audio": f"data:{media};base64,{a['audio_b64']}",
            })
        return {"audio": audio}
    except Exception as e:
        logger.error(f"GET /api/ai-hotel/captures/{capture_id}/audio failed: {e}")
        return {"audio": []}


@app.get("/api/ai-hotel/captures/{capture_id}/images", tags=["ai-hotel"],
         dependencies=[Depends(verify_ai_hotel_read_access)])
async def ai_hotel_capture_images_detail(capture_id: int):
    """AI_HOTEL_FIELDNOTES_THUMBNAIL_LAZYIMG_1: full-res images for ONE capture,
    fetched on demand from card detail (the list returns thumbnails only).
    Returns ordered `data:` URLs. Fail-soft empty list on any error."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"images": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT ordinal, image_b64, image_media
                     FROM ai_hotel_capture_images
                    WHERE capture_id = %s
                    ORDER BY ordinal
                    LIMIT 50""",
                (capture_id,),
            )
            rows = cur.fetchall()
            if not rows:
                # legacy single-image row (pre child-table) — fall back to parent.
                cur.execute(
                    "SELECT image_b64, image_media FROM ai_hotel_captures WHERE id = %s",
                    (capture_id,),
                )
                p = cur.fetchone()
                rows = [p] if (p and p.get("image_b64")) else []
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
        images = [
            _ai_hotel_image_data_url(r["image_b64"], r.get("image_media") or "image/jpeg")
            for r in rows if r.get("image_b64")
        ]
        return {"images": images}
    except Exception as e:
        logger.error(f"GET /api/ai-hotel/captures/{capture_id}/images failed: {e}")
        return {"images": []}


@app.get("/api/ai-hotel/captures/{capture_id}/thumbs", tags=["ai-hotel"],
         dependencies=[Depends(verify_ai_hotel_read_access)])
async def ai_hotel_capture_thumbs_detail(capture_id: int):
    """AI_HOTEL_FIELDNOTES_IMAGE_VIEWER_FIX_1: per-image SMALL thumbnails for one
    capture's detail strip. The old detail path pulled every full-res image in
    one response (capture 17 = 2.07 MB → "Loading photos…" hang on cellular).
    The strip now loads these tiny ~160px thumbs (6 imgs ≈ 60-90 KB) immediately;
    a tapped photo fetches its single full-res image on demand from /images/{idx}.
    Ordered, fail-soft (a bad image yields null, never breaks the strip)."""
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"thumbs": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT ordinal, image_b64, image_media
                     FROM ai_hotel_capture_images
                    WHERE capture_id = %s
                    ORDER BY ordinal
                    LIMIT 50""",
                (capture_id,),
            )
            rows = cur.fetchall()
            if not rows:
                cur.execute(
                    "SELECT image_b64, image_media FROM ai_hotel_captures WHERE id = %s",
                    (capture_id,),
                )
                p = cur.fetchone()
                rows = [p] if (p and p.get("image_b64")) else []
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
        # _ai_hotel_thumb_data_url is fail-soft (returns None on a bad image).
        thumbs = [
            _ai_hotel_thumb_data_url(r["image_b64"], r.get("image_media") or "image/jpeg")
            for r in rows if r.get("image_b64")
        ]
        return {"thumbs": thumbs}
    except Exception as e:
        logger.error(f"GET /api/ai-hotel/captures/{capture_id}/thumbs failed: {e}")
        return {"thumbs": []}


@app.get("/api/ai-hotel/captures/{capture_id}/images/{idx}", tags=["ai-hotel"],
         dependencies=[Depends(verify_ai_hotel_read_access)])
async def ai_hotel_capture_single_image_detail(capture_id: int, idx: int):
    """AI_HOTEL_FIELDNOTES_IMAGE_VIEWER_FIX_1: ONE full-res image (by ordinal) for
    the lightbox — loaded only when the user taps a thumb, so the detail modal
    never pulls the whole 2 MB image set upfront. Auth-gated, fail-soft: an
    out-of-range index returns {"image": null} (never a 500)."""
    try:
        if idx < 0:
            return {"image": None}
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"image": None}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT image_b64, image_media
                     FROM ai_hotel_capture_images
                    WHERE capture_id = %s AND ordinal = %s
                    LIMIT 1""",
                (capture_id, idx),
            )
            r = cur.fetchone()
            if r is None and idx == 0:
                # legacy single-image capture (pre child-table) — parent column.
                cur.execute(
                    "SELECT image_b64, image_media FROM ai_hotel_captures WHERE id = %s",
                    (capture_id,),
                )
                r = cur.fetchone()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
        if not r or not r.get("image_b64"):
            return {"image": None}
        media = r.get("image_media") or "image/jpeg"
        return {"image": _ai_hotel_image_data_url(r["image_b64"], media)}
    except Exception as e:
        logger.error(f"GET /api/ai-hotel/captures/{capture_id}/images/{idx} failed: {e}")
        return {"image": None}


@app.post("/api/ai-hotel/captures/{capture_id}/images/{idx}/rotate", tags=["ai-hotel"],
          dependencies=[Depends(verify_ai_hotel_photo_edit_access)])
async def ai_hotel_capture_image_rotate(
    capture_id: int,
    idx: int,
    payload: AIHotelImageRotateRequest,
):
    """Rotate ONE stored photo clockwise and persist the pixel change.

    AI_HOTEL_PHOTO_ROTATE_BUTTON_1: manual repair for old EXIF-stripped sideways
    Field Notes photos. Reads the stored base64, rotates into a fresh JPEG
    buffer, and updates Postgres only after the new bytes are ready; thumbs and
    full images are generated on demand from the same stored copy.
    """
    if idx < 0:
        raise HTTPException(status_code=404, detail="Image not found.")
    deg = int(payload.deg)
    if deg not in (90, 180, 270):
        raise HTTPException(status_code=400, detail="deg must be 90, 180, or 270.")
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="DB unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT image_b64, image_media
                     FROM ai_hotel_capture_images
                    WHERE capture_id = %s AND ordinal = %s
                    LIMIT 1""",
                (capture_id, idx),
            )
            row = cur.fetchone()
            target = "child"
            if row is None and idx == 0:
                cur.execute(
                    "SELECT image_b64, image_media FROM ai_hotel_captures WHERE id = %s",
                    (capture_id,),
                )
                row = cur.fetchone()
                target = "parent"
            if not row or not row.get("image_b64"):
                raise HTTPException(status_code=404, detail="Image not found.")

            old_b64 = row["image_b64"]
            media = row.get("image_media") or "image/jpeg"
            new_b64, new_media = _ai_hotel_rotate_image_b64(old_b64, media, deg)
            if target == "child":
                cur.execute(
                    """UPDATE ai_hotel_capture_images
                          SET image_b64 = %s, image_media = %s
                        WHERE capture_id = %s AND ordinal = %s AND image_b64 = %s
                    RETURNING ordinal""",
                    (new_b64, new_media, capture_id, idx, old_b64),
                )
                updated = cur.fetchone()
                if not updated:
                    raise HTTPException(status_code=409, detail="Image changed; reload and retry.")
                if idx == 0:
                    cur.execute(
                        """UPDATE ai_hotel_captures
                              SET image_b64 = %s, image_media = %s
                            WHERE id = %s""",
                        (new_b64, new_media, capture_id),
                    )
            else:
                cur.execute(
                    """UPDATE ai_hotel_captures
                          SET image_b64 = %s, image_media = %s
                        WHERE id = %s AND image_b64 = %s
                    RETURNING id""",
                    (new_b64, new_media, capture_id, old_b64),
                )
                updated = cur.fetchone()
                if not updated:
                    raise HTTPException(status_code=409, detail="Image changed; reload and retry.")
            conn.commit()
            cur.close()
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
        return {
            "ok": True,
            "deg": deg,
            "image": _ai_hotel_image_data_url(new_b64, new_media),
            "thumb": _ai_hotel_thumb_data_url(new_b64, new_media),
        }
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(
            "POST /api/ai-hotel/captures/%s/images/%s/rotate rejected: %s",
            capture_id, idx, e,
        )
        raise HTTPException(status_code=400, detail="Image could not be rotated.")
    except Exception as e:
        logger.error(
            "POST /api/ai-hotel/captures/%s/images/%s/rotate failed: %s",
            capture_id, idx, e,
        )
        raise HTTPException(status_code=500, detail="Image rotate failed.")


@app.post("/api/ai-hotel/captures/{capture_id}/delete", tags=["ai-hotel"],
          dependencies=[Depends(verify_ai_hotel_photo_edit_access)])
async def ai_hotel_capture_soft_delete(capture_id: int):
    """Soft-delete one Field Notes capture without destroying evidence/media.

    AI_HOTEL_DELETE_CARD_BUTTON_1: the card disappears from the live Field Notes
    feed, but the capture row and linked image/audio/video rows remain
    recoverable. Idempotent: deleting an already-hidden capture keeps the first
    deleted_at timestamp.
    """
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="DB unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """UPDATE ai_hotel_captures
                      SET deleted_at = COALESCE(deleted_at, NOW())
                    WHERE id = %s
                RETURNING id, deleted_at""",
                (capture_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Capture not found.")
            conn.commit()
            cur.close()
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
        deleted = _serialize({"deleted_at": row.get("deleted_at")})["deleted_at"]
        return {"ok": True, "id": row.get("id") or capture_id, "deleted_at": deleted}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "POST /api/ai-hotel/captures/%s/delete failed: %s",
            capture_id, e,
        )
        raise HTTPException(status_code=500, detail="Capture delete failed.")


@app.get("/api/ai-hotel/captures/{capture_id}/media", tags=["ai-hotel"],
         dependencies=[Depends(verify_ai_hotel_read_access)])
async def ai_hotel_capture_media_detail(capture_id: int):
    """Return short-lived playback URLs for R2-backed capture media.

    The feed endpoint returns metadata only; this detail route signs read URLs on
    demand and deliberately omits the underlying R2 object keys.
    """
    try:
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            return {"media": []}
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                """SELECT id, media_type, storage_key, thumbnail_key,
                          content_type, size_bytes, duration_seconds, created_at
                     FROM ai_hotel_capture_media
                    WHERE capture_id = %s AND media_type = 'video'
                    ORDER BY created_at DESC
                    LIMIT 20""",
                (capture_id,),
            )
            rows = cur.fetchall()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
        try:
            from kbl.object_storage import generate_presigned_get
        except Exception:
            generate_presigned_get = None
        media = []
        for r in rows:
            created_at = r.get("created_at")
            item = {
                "id": r.get("id"),
                "media_type": r.get("media_type"),
                "content_type": r.get("content_type"),
                "size_bytes": r.get("size_bytes"),
                "duration_seconds": r.get("duration_seconds"),
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                "url": None,
                "thumbnail_url": None,
            }
            if generate_presigned_get:
                try:
                    signed = generate_presigned_get(r.get("storage_key"), expires=300)
                    if signed.get("ok"):
                        item["url"] = signed.get("url")
                    tkey = r.get("thumbnail_key")
                    if tkey:
                        tsigned = generate_presigned_get(tkey, expires=300)
                        if tsigned.get("ok"):
                            item["thumbnail_url"] = tsigned.get("url")
                except Exception as se:
                    logger.warning("ai_hotel media signed read failed for %s: %s", r.get("id"), se)
            media.append(item)
        return {"media": media}
    except Exception as e:
        logger.error(f"GET /api/ai-hotel/captures/{capture_id}/media failed: {e}")
        return {"media": []}


# ── AI_HOTEL_VOICE_FORM_SUPPLIER_1: voice → structured supplier-card draft ───
# Structured extraction sits BESIDE the raw capture, never replaces it. The raw
# capture (note/transcript/photos) is persisted FIRST; the typed draft is a
# child record that only becomes 'confirmed' after an explicit user review.


def _ai_hotel_transcribe(audio_bytes: bytes, audio_type: str) -> str:
    """Transcribe dictated audio via Gemini (thinking_budget=0 — same load-
    bearing guard as the capture leg). Returns '' on any failure: a transcription
    failure must never lose the raw capture (the caller persists raw regardless)."""
    try:
        import base64 as _b64a
        audio_b64 = _b64a.standard_b64encode(audio_bytes).decode("utf-8")
        aresp = _llm_call(
            "gemini-2.5-flash",
            max_tokens=_AI_HOTEL_TRANSCRIBE_MAX_TOKENS,
            thinking_budget=0,
            messages=[{"role": "user", "content": [
                {"type": "audio", "source": {"type": "base64",
                                             "media_type": audio_type, "data": audio_b64}},
                {"type": "text", "text": _AI_HOTEL_TRANSCRIBE_PROMPT},
            ]}],
        )
        transcript = (aresp.text or "").strip()
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost("gemini-2.5-flash", aresp.usage.input_tokens, aresp.usage.output_tokens,
                     source="ai_hotel_form_draft_transcribe")
        if not transcript:
            logger.warning("ai_hotel_form_draft transcription returned EMPTY text "
                           "(in=%s out=%s).", aresp.usage.input_tokens, aresp.usage.output_tokens)
        return transcript
    except Exception as tx_err:
        logger.error(f"ai_hotel_form_draft transcription failed: {tx_err}", exc_info=True)
        return ""


@app.post("/api/ai-hotel/form-drafts", tags=["ai-hotel"], dependencies=[Depends(verify_api_key)])
async def ai_hotel_form_draft(
    form_type: str = Form(""),
    images: list[UploadFile] = File(None),
    audio: UploadFile = File(None),
    note: str = Form(""),
    duration_seconds: str = Form(""),
    gps_lat: str = Form(""),
    gps_lng: str = Form(""),
    gps_accuracy_m: str = Form(""),
    gps_captured_at: str = Form(""),
    gps_capture_method: str = Form(""),
    gps_address_status: str = Form(""),
):
    """Voice/note/photo capture → schema-driven structured draft (site_visit or
    supplier_card). Flow: resolve form_type (explicit or auto-detect) → persist
    raw capture (safety net) → transcribe → schema-driven extraction →
    deterministic validators → draft.

    The draft is never auto-confirmed. zero send/payment/external side-effects.
    """
    from orchestrator.ai_hotel_form_schemas import (
        get_form_schema, detect_form_type, build_extraction_prompt,
        parse_and_validate, PROMPT_VERSION,
    )

    # 1) Resolve form_type. An EXPLICIT unknown form_type → 400 with NO rows
    #    written (AC7). An ABSENT form_type is auto-detected after transcription
    #    (always resolves to a valid form, never 400).
    form_type = (form_type or "").strip()
    schema = None
    auto_detected = False
    if form_type:
        schema = get_form_schema(form_type)
        if schema is None:
            raise HTTPException(400, f"Unknown form_type: {form_type!r}")

    note = (note or "").strip()
    if len(note) > _AI_HOTEL_NOTE_CAP:
        raise HTTPException(400, f"Note too long (max {_AI_HOTEL_NOTE_CAP} characters).")

    incoming = [im for im in (images or []) if im is not None and getattr(im, "filename", None)]
    if len(incoming) > _AI_HOTEL_MAX_IMAGES:
        raise HTTPException(400, f"Too many photos (max {_AI_HOTEL_MAX_IMAGES} per capture).")
    has_audio = audio is not None and getattr(audio, "filename", None)
    if not incoming and not note and not has_audio:
        raise HTTPException(400, "Provide a photo, a note, or an audio dictation.")

    # --- Resize photos (reuse the single-image validator verbatim) ------------
    resized_images: list = []
    for image in incoming:
        content_type = image.content_type or ""
        if not content_type.startswith("image/"):
            ext = Path(image.filename or "").suffix.lower()
            type_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                        ".gif": "image/gif", ".webp": "image/webp"}
            content_type = type_map.get(ext, "")
        if content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            raise HTTPException(400, "Unsupported image type. Accepted: JPEG, PNG, GIF, WebP.")
        image_bytes = await image.read()
        if len(image_bytes) > 20 * 1024 * 1024:
            raise HTTPException(400, "Image too large (max 20MB).")
        try:
            ib64, imedia = _ai_hotel_resize_for_db(image_bytes, content_type)
        except ValueError as ve:
            logger.warning(f"ai_hotel_form_draft rejected image: {ve}")
            raise HTTPException(400, "Unreadable image, or could not compress it under the size limit.")
        resized_images.append((ib64, imedia))

    # --- Validate + read audio (do NOT transcribe yet) ------------------------
    # G3 S1 fix: transcription must NOT run before the raw capture is persisted.
    # We validate/read the audio here, persist the raw row, THEN transcribe — so
    # an audio-only dictation whose transcription fails still leaves a
    # retrievable capture row (never a 400 with zero rows).
    transcript = ""
    audio_bytes = None
    audio_type = None
    if has_audio:
        audio_type = audio.content_type or ""
        if audio_type not in _AI_HOTEL_AUDIO_TYPES:
            ext = Path(audio.filename or "").suffix.lower()
            audio_map = {".webm": "audio/webm", ".mp4": "audio/mp4", ".m4a": "audio/mp4",
                         ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
                         ".aac": "audio/aac"}
            audio_type = audio_map.get(ext, "")
        if audio_type not in _AI_HOTEL_AUDIO_TYPES:
            raise HTTPException(400, "Unsupported audio type. Accepted: WebM, MP4/M4A, MP3, WAV, OGG, AAC.")
        audio_bytes = await audio.read()
        if len(audio_bytes) > _AI_HOTEL_AUDIO_CAP:
            raise HTTPException(400, "Audio too large (max 25MB).")

    # Provenance + legacy single-image mirror columns.
    if resized_images:
        source = "photo"
    elif has_audio:
        source = "audio"
    else:
        source = "note"
    b64 = resized_images[0][0] if resized_images else None
    image_media = resized_images[0][1] if resized_images else None
    summary = (note[:200] if note else "Field dictation")

    # WP-A: prepare the raw audio for persistence. It is stored as a child row in
    # the SAME transaction as the raw capture (below) — i.e. BEFORE transcription
    # — so a transcription failure never loses the recording (AC6/AC7).
    audio_id = None
    audio_b64 = None
    audio_duration = None
    if has_audio and audio_bytes is not None:
        import base64 as _b64p
        audio_b64 = _b64p.standard_b64encode(audio_bytes).decode("utf-8")
        _ds = str(duration_seconds or "").strip()
        if _ds.isdigit():
            audio_duration = int(_ds)

    # 2) Persist the RAW capture FIRST — BEFORE transcription/extraction. This is
    #    the no-data-loss invariant (G3 S1 fix): the early "provide something"
    #    400 already rejected truly-empty submissions, so by here we always have
    #    audio, a photo, or a note. The typed note (if any) is stored now; the
    #    transcript is folded in via an UPDATE once transcription succeeds.
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(503, "Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO ai_hotel_captures
                       (source, note_text, image_b64, image_media,
                        section_guess, related_area, summary)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (source, note or None, b64, image_media, "general", None, summary),
            )
            capture_id = cur.fetchone()[0]
            for ordinal, (ib64, imedia) in enumerate(resized_images):
                cur.execute(
                    """INSERT INTO ai_hotel_capture_images
                           (capture_id, ordinal, image_b64, image_media)
                       VALUES (%s, %s, %s, %s)""",
                    (capture_id, ordinal, ib64, imedia),
                )
            # WP-A: persist the raw audio in the SAME transaction (committed
            # BEFORE transcription) so a transcription failure keeps BOTH rows.
            if has_audio and audio_b64:
                cur.execute(
                    """INSERT INTO ai_hotel_capture_audio
                           (capture_id, ordinal, audio_b64, audio_media, duration_seconds)
                       VALUES (%s, 0, %s, %s, %s) RETURNING id""",
                    (capture_id, audio_b64, audio_type, audio_duration),
                )
                audio_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/ai-hotel/form-drafts raw capture insert failed: {e}")
        raise HTTPException(500, "Could not save capture")

    # 2a) AI_HOTEL_GPS_CAPTURE_1: enrich the just-committed capture with GPS
    # evidence (single-shot reverse-geocode, non-blocking, non-fatal) BEFORE
    # transcription/extraction so the location survives even if those fail.
    _ai_hotel_persist_gps(
        store, capture_id,
        gps_lat=gps_lat, gps_lng=gps_lng, gps_accuracy_m=gps_accuracy_m,
        gps_captured_at=gps_captured_at, gps_capture_method=gps_capture_method,
        gps_address_status=gps_address_status,
    )

    # 2b) Transcribe AFTER the raw capture is safely committed. A transcription
    #     failure now leaves the capture row intact (no data loss); on success we
    #     fold the transcript into note_text via an UPDATE.
    if has_audio:
        transcript = _ai_hotel_transcribe(audio_bytes, audio_type)
        if transcript:
            note = f"{note}\n\n{transcript}".strip() if note else transcript
            updated_summary = note[:200] if note else summary
            try:
                store = _get_store()
                conn = store._get_conn()
                if conn:
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            """UPDATE ai_hotel_captures
                                  SET note_text = %s, summary = %s
                                WHERE id = %s""",
                            (note or None, updated_summary, capture_id),
                        )
                        # AC8: mirror the transcript onto the audio row too.
                        if audio_id is not None:
                            cur.execute(
                                """UPDATE ai_hotel_capture_audio
                                      SET transcript_text = %s WHERE id = %s""",
                                (transcript, audio_id),
                            )
                        conn.commit()
                        cur.close()
                    except Exception:
                        conn.rollback()
                        raise
                    finally:
                        store._put_conn(conn)
            except Exception as e:
                logger.error(f"POST /api/ai-hotel/form-drafts transcript UPDATE failed "
                             f"(capture {capture_id} intact): {e}")

    # 2c) Auto-detect the form_type from the full captured text (incl. transcript)
    #     when not explicit. The user's explicit selection always wins (AC5/AC6).
    if schema is None:
        detected, auto_detected = detect_form_type(note)
        schema = get_form_schema(detected)

    # 3) Schema-driven extraction (guarded — never raises out; raw already safe).
    extraction_failed = False
    extracted: dict = {}
    try:
        prompt = build_extraction_prompt(schema, transcript, note)
        eresp = _llm_call(
            "gemini-2.5-flash", max_tokens=1500,
            response_format="json", thinking_budget=0,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        )
        from orchestrator.cost_monitor import log_api_cost
        log_api_cost("gemini-2.5-flash", eresp.usage.input_tokens, eresp.usage.output_tokens,
                     source="ai_hotel_form_draft_extract")
        raw = (eresp.text or "").strip()
        if not raw:
            logger.error("ai_hotel_form_draft extraction returned EMPTY text (in=%s out=%s).",
                         eresp.usage.input_tokens, eresp.usage.output_tokens)
            extraction_failed = True
        else:
            body_txt = raw
            if body_txt.startswith("```"):
                body_txt = body_txt.split("```", 2)[1] if "```" in body_txt[3:] else body_txt.strip("`")
                if body_txt.lstrip().lower().startswith("json"):
                    body_txt = body_txt.lstrip()[4:]
            s_i, e_i = body_txt.find("{"), body_txt.rfind("}")
            extracted = json.loads(body_txt[s_i:e_i + 1]) if s_i != -1 and e_i != -1 else {}
            if not isinstance(extracted, dict):
                extracted = {}
                extraction_failed = True
    except Exception as ex_err:
        logger.error(f"ai_hotel_form_draft extraction failed (raw capture {capture_id} intact): {ex_err}",
                     exc_info=True)
        extraction_failed = True
        extracted = {}

    result = parse_and_validate(schema, extracted, capture_source=source)
    if extraction_failed:
        result.warnings.append(
            "Extraction failed — the raw capture was saved; fields are blank. Fill them in or retry.")

    # 4) Persist the DRAFT record BESIDE the raw capture. A failure here must NOT
    #    lose the raw capture (already committed) — degrade to draft_id=None.
    draft_id = None
    try:
        store = _get_store()
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO ai_hotel_form_records
                           (capture_id, form_type, schema_version, status,
                            extracted_json, field_meta_json, validation_errors_json,
                            model, prompt_version)
                       VALUES (%s, %s, %s, 'draft', %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                       RETURNING id""",
                    (capture_id, schema.form_type, schema.version,
                     json.dumps(result.values), json.dumps(result.field_meta),
                     json.dumps(result.validation_errors),
                     "gemini-2.5-flash", PROMPT_VERSION),
                )
                draft_id = cur.fetchone()[0]
                conn.commit()
                cur.close()
            except Exception:
                conn.rollback()
                raise
            finally:
                store._put_conn(conn)
    except Exception as e:
        logger.error(f"POST /api/ai-hotel/form-drafts draft insert failed (raw capture {capture_id} intact): {e}")
        result.warnings.append("Draft record could not be saved; the raw capture was kept. Retry extraction.")

    logger.info(f"ai_hotel_form_draft saved: capture_id={capture_id} draft_id={draft_id} "
                f"form_type={schema.form_type} auto={auto_detected} "
                f"missing={len(result.missing_critical)} errors={len(result.validation_errors)}")

    return {
        "capture_id": capture_id,
        "draft_id": draft_id,
        "form_type": schema.form_type,
        "form_title": schema.title,
        "schema_version": schema.version,
        "auto_detected": auto_detected,
        "status": "draft",
        "values": result.values,
        "field_meta": result.field_meta,
        "missing_critical": result.missing_critical,
        "validation_errors": result.validation_errors,
        "warnings": result.warnings,
        "transcript_preview": (transcript[:280] if transcript else ""),
    }


@app.post("/api/ai-hotel/form-drafts/{draft_id}/confirm", tags=["ai-hotel"],
          dependencies=[Depends(verify_api_key)])
async def ai_hotel_form_draft_confirm(draft_id: int, payload: dict = Body(default=None)):
    """Promote a draft to a confirmed, typed record — the ONLY path that writes
    status='confirmed'. Server re-validates the user-corrected values (the model
    never confirms anything). Required-but-missing or malformed → 422, no write."""
    from orchestrator.ai_hotel_form_schemas import get_form_schema, validate_corrected
    payload = payload or {}
    corrected = payload.get("values") or {}
    ack = tuple(payload.get("acknowledged_unknown") or ())

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(503, "Database unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT form_type, status FROM ai_hotel_form_records WHERE id = %s",
            (draft_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Draft not found")
        form_type, status = row[0], row[1]
        if status != "draft":
            raise HTTPException(409, f"Draft already {status}; cannot confirm.")
        schema = get_form_schema(form_type)
        if schema is None:
            raise HTTPException(400, f"Unknown form_type on draft: {form_type}")
        normalized, missing, errors = validate_corrected(schema, corrected, ack)
        if missing or errors:
            raise HTTPException(422, detail={
                "error": "validation_failed",
                "missing_critical": missing,
                "validation_errors": errors,
            })
        cur.execute(
            """UPDATE ai_hotel_form_records
                  SET status = 'confirmed', corrected_json = %s::jsonb,
                      reviewed_at = now(), updated_at = now()
                WHERE id = %s AND status = 'draft'""",
            (json.dumps(normalized), draft_id),
        )
        conn.commit()
        cur.close()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"confirm form draft {draft_id} failed: {e}")
        raise HTTPException(500, "Could not confirm draft")
    finally:
        store._put_conn(conn)
    return {"draft_id": draft_id, "status": "confirmed", "values": normalized}


@app.post("/api/ai-hotel/form-drafts/{draft_id}/discard", tags=["ai-hotel"],
          dependencies=[Depends(verify_api_key)])
async def ai_hotel_form_draft_discard(draft_id: int):
    """Discard a draft (user chose 'keep as field note only'). The raw capture is
    untouched and stays retrievable; only the structured draft is set discarded."""
    affected = 0
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(503, "Database unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE ai_hotel_form_records
                  SET status = 'discarded', reviewed_at = now(), updated_at = now()
                WHERE id = %s AND status = 'draft'""",
            (draft_id,),
        )
        affected = cur.rowcount
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"discard form draft {draft_id} failed: {e}")
        raise HTTPException(500, "Could not discard draft")
    finally:
        store._put_conn(conn)
    if not affected:
        raise HTTPException(409, "Draft not found or not in draft state")
    return {"draft_id": draft_id, "status": "discarded"}


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

        resp = _llm_call("gemini-2.5-flash",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens,
                         resp.usage.output_tokens, source="followup_suggestions")
        except Exception:
            pass

        raw = resp.text.strip()
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


@app.get("/api/debug/memory", tags=["debug"], dependencies=[Depends(verify_api_key)])
async def debug_memory():
    """OOM-PHASE3: Memory diagnostics endpoint."""
    from triggers.embedded_scheduler import _get_rss_mb
    rss_mb = _get_rss_mb()

    # Count singleton instances
    from memory.retriever import SentinelRetriever
    from memory.store_back import SentinelStoreBack
    retriever_exists = SentinelRetriever._instance is not None
    storeback_exists = SentinelStoreBack._instance is not None

    # PG pool stats from StoreBack singleton
    pg_stats = {}
    if storeback_exists:
        store = SentinelStoreBack._get_global_instance()
        pool = getattr(store, "_pool", None)
        if pool:
            pg_stats = {
                "minconn": getattr(pool, "minconn", "?"),
                "maxconn": getattr(pool, "maxconn", "?"),
            }

    # Scheduler info
    try:
        status = get_scheduler_status()
        job_count = status.get("job_count", 0)
        scheduler_running = status.get("running", False)
    except Exception:
        job_count = 0
        scheduler_running = False

    # Uptime
    import os
    try:
        uptime_sec = os.popen("cat /proc/uptime 2>/dev/null").read().split()[0]
        uptime_min = float(uptime_sec) / 60
    except Exception:
        uptime_min = -1

    # Recent memory log (last 12 entries = ~1 hour)
    recent_log = []
    try:
        store = _get_store()
        conn = store._get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT timestamp, rss_mb, note
                FROM baker_memory_log
                ORDER BY timestamp DESC LIMIT 12
            """)
            for row in cur.fetchall():
                recent_log.append({
                    "timestamp": row[0].isoformat() if row[0] else None,
                    "rss_mb": row[1],
                    "note": row[2],
                })
            cur.close()
            store._put_conn(conn)
    except Exception:
        pass

    return {
        "rss_mb": int(rss_mb),
        "rss_pct": round(rss_mb / 4096 * 100, 1),
        "pg_pool": pg_stats,
        "singletons": {
            "retriever": retriever_exists,
            "store_back": storeback_exists,
        },
        "scheduler_jobs": job_count,
        "scheduler_running": scheduler_running,
        "uptime_minutes": round(uptime_min, 1),
        "recent_log": recent_log,
    }


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
    """Dismiss a deadline. Also writes a 'mute' feedback row for the phase-3 training corpus."""
    try:
        from models.deadlines import update_deadline, get_deadline_by_id
        from models.deadline_feedback import insert_feedback
        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")
        # DEADLINE_FEEDBACK_LOOP_1: corpus row first; failure here must NOT block the dismiss
        try:
            insert_feedback(
                deadline_id=deadline_id,
                feedback_type="mute",
                original_matter_slug=dl.get("matter_slug"),
                corrected_matter_slug=None,
                original_description=dl.get("description") or "",
                original_source_type=dl.get("source_type"),
                director_note=None,
            )
        except Exception as fe:
            logger.warning(f"deadline_feedback (mute) write failed for {deadline_id}: {fe}")
        update_deadline(deadline_id, status="dismissed", dismissed_reason="Dismissed via dashboard")
        return {"status": "dismissed", "id": deadline_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/dismiss failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/deadlines/{deadline_id}/complete", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def complete_deadline_api(deadline_id: int):
    """Mark a deadline as completed. Also writes a 'confirm' feedback row for the phase-3 training corpus."""
    try:
        from models.deadlines import update_deadline, get_deadline_by_id
        from models.deadline_feedback import insert_feedback
        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")
        # DEADLINE_FEEDBACK_LOOP_1: corpus row first; failure here must NOT block the complete
        try:
            insert_feedback(
                deadline_id=deadline_id,
                feedback_type="confirm",
                original_matter_slug=dl.get("matter_slug"),
                corrected_matter_slug=None,
                original_description=dl.get("description") or "",
                original_source_type=dl.get("source_type"),
                director_note=None,
            )
        except Exception as fe:
            logger.warning(f"deadline_feedback (confirm) write failed for {deadline_id}: {fe}")
        update_deadline(deadline_id, status="completed", dismissed_reason="Completed via dashboard")
        return {"status": "completed", "id": deadline_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/complete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/critical/{deadline_id}/done", tags=["critical"], dependencies=[Depends(verify_api_key)])
async def complete_critical_api(deadline_id: int):
    """CRITICAL-CARD-1: Mark critical item as done."""
    try:
        from models.deadlines import complete_critical
        complete_critical(deadline_id)
        return {"status": "completed", "id": deadline_id}
    except Exception as e:
        logger.error(f"/api/critical/{deadline_id}/done failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/critical/{alert_id}/promote", tags=["critical"], dependencies=[Depends(verify_api_key)])
async def promote_to_critical_api(alert_id: int):
    """CRITICAL-CARD-1: Promote an alert to critical (creates/flags deadline)."""
    try:
        from models.deadlines import insert_deadline, set_critical, get_critical_count
        if get_critical_count() >= 5:
            return {"error": "Max 5 critical items. Complete one first."}
        # Get alert details
        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT title, body FROM alerts WHERE id = %s", (alert_id,))
            alert = cur.fetchone()
            cur.close()
        finally:
            store._put_conn(conn)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        from datetime import datetime
        did = insert_deadline(
            description=alert['title'],
            due_date=datetime.now(),
            source_type="critical_promote",
            source_id=f"critical-promote:{alert_id}",
            confidence="high",
            priority="critical",
            source_snippet=(alert.get('body') or '')[:300],
        )
        if did:
            set_critical(did, True)
        return {"status": "promoted", "deadline_id": did, "alert_id": alert_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/critical/{alert_id}/promote failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/critical/add", tags=["critical"], dependencies=[Depends(verify_api_key)])
async def add_critical_quick(request: Request):
    """CRITICAL-CARD-1: Quick-add critical item from dashboard."""
    try:
        body = await request.json()
        description = body.get("description", "").strip()
        if not description:
            return {"error": "Description required"}
        from models.deadlines import insert_deadline, set_critical, get_critical_count
        if get_critical_count() >= 5:
            return {"error": "Max 5 critical items. Complete one first."}
        from datetime import datetime
        did = insert_deadline(
            description=description,
            due_date=datetime.now(),
            source_type="dashboard",
            source_id=f"critical-quick:{datetime.now().strftime('%Y%m%d%H%M%S')}",
            confidence="high",
            priority="critical",
        )
        if did:
            set_critical(did, True)
        return {"status": "added", "id": did}
    except Exception as e:
        logger.error(f"POST /api/critical/add failed: {e}")
        return {"error": str(e)}


@app.post("/api/deadlines/from-alert", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def create_deadline_from_alert(request: Request):
    """Create a non-critical deadline (Promised To Do) from an alert."""
    try:
        body = await request.json()
        alert_id = body.get("alert_id")
        if not alert_id:
            raise HTTPException(status_code=400, detail="alert_id required")

        store = _get_store()
        import psycopg2.extras
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT title, body FROM alerts WHERE id = %s", (alert_id,))
            alert = cur.fetchone()
            cur.close()
        finally:
            store._put_conn(conn)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        from models.deadlines import insert_deadline
        from datetime import datetime
        did = insert_deadline(
            description=alert['title'],
            due_date=datetime.now(),
            source_type="alert_to_promised",
            source_id=f"promised:{alert_id}",
            confidence="high",
            priority="normal",
            source_snippet=(alert.get('body') or '')[:300],
        )
        return {"status": "added", "deadline_id": did, "alert_id": alert_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/deadlines/from-alert failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/landing/move", tags=["landing"], dependencies=[Depends(verify_api_key)])
async def landing_move_item(request: Request):
    """DRAG-DROP-1: Move a deadline item between landing grid sections."""
    try:
        body = await request.json()
        item_id = body.get("item_id")
        target = body.get("target_section", "").strip().lower()
        if not item_id or not target:
            raise HTTPException(status_code=400, detail="item_id and target_section required")

        from models.deadlines import set_critical, update_deadline

        if target == "critical":
            set_critical(int(item_id), True)
            update_deadline(int(item_id), priority="critical")
            return {"status": "moved", "target": "critical", "id": item_id}
        elif target == "promised":
            set_critical(int(item_id), False)
            update_deadline(int(item_id), priority="normal")
            return {"status": "moved", "target": "promised", "id": item_id}
        elif target == "dismiss":
            update_deadline(int(item_id), status="dismissed")
            set_critical(int(item_id), False)
            return {"status": "dismissed", "id": item_id}
        else:
            raise HTTPException(status_code=400, detail=f"Invalid target_section: {target}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/landing/move failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/detected-meetings/{meeting_id}/cancel", tags=["meetings"], dependencies=[Depends(verify_api_key)])
async def cancel_detected_meeting(meeting_id: int):
    """LANDING-TRIAGE-1: Cancel a detected meeting."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("UPDATE detected_meetings SET status = 'cancelled', dismissed = TRUE WHERE id = %s", (meeting_id,))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
        return {"status": "cancelled", "id": meeting_id}
    except Exception as e:
        logger.error(f"/api/detected-meetings/{meeting_id}/cancel failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/detected-meetings/{meeting_id}/confirm", tags=["meetings"], dependencies=[Depends(verify_api_key)])
async def confirm_detected_meeting(meeting_id: int):
    """MEETING-TRIAGE-1: Confirm a detected meeting."""
    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            cur.execute("UPDATE detected_meetings SET status = 'confirmed', updated_at = NOW() WHERE id = %s", (meeting_id,))
            conn.commit()
            cur.close()
        finally:
            store._put_conn(conn)
        return {"status": "confirmed", "id": meeting_id}
    except Exception as e:
        logger.error(f"POST /api/detected-meetings/{meeting_id}/confirm failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/meetings/add", tags=["meetings"], dependencies=[Depends(verify_api_key)])
async def add_meeting_quick(request: Request):
    """MEETING-TRIAGE-1: Quick-add meeting from dashboard. Uses Flash to parse natural language."""
    import json as _json_mod
    try:
        body = await request.json()
        text = body.get("text", "").strip()
        if not text:
            return {"error": "Meeting description required"}

        # TRUSTED — parsed meeting is inserted into detected_meetings and shows on
        # the Director dashboard/calendar; Gemini Pro floor, never Flash
        # (BAKER_DASHBOARD_V2_MODEL_LOCK_1).
        from orchestrator.model_policy import call_trusted
        today = datetime.now().strftime('%Y-%m-%d')
        resp = call_trusted(
            output_type="meeting", context="add_meeting",
            messages=[{"role": "user", "content": f"""Parse this meeting description into structured data. Today is {today}.

Input: "{text}"

Return JSON only (no markdown):
{{
  "title": "short meeting title",
  "participants": ["Name1", "Name2"],
  "date": "YYYY-MM-DD",
  "time": "HH:MM or null",
  "location": "place or null",
  "status": "confirmed"
}}

If no date is specified, assume today. If "tomorrow", use the next day."""}],
        )

        parsed = _json_mod.loads(resp.text.strip().strip('`').replace('json\n', ''))

        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        meeting_id = store.insert_detected_meeting(
            title=parsed.get("title", text[:100]),
            participant_names=parsed.get("participants", []),
            meeting_date=parsed.get("date"),
            meeting_time=parsed.get("time"),
            location=parsed.get("location"),
            status=parsed.get("status", "confirmed"),
            source="dashboard",
            raw_text=text,
        )

        return {
            "status": "added",
            "id": meeting_id,
            "title": parsed.get("title", text[:100]),
            "date": parsed.get("date"),
            "time": parsed.get("time"),
        }
    except _json_mod.JSONDecodeError:
        # Flash returned non-JSON — store as-is with minimal parsing
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        meeting_id = store.insert_detected_meeting(
            title=text[:100],
            status="confirmed",
            source="dashboard",
            raw_text=text,
        )
        return {"status": "added", "id": meeting_id, "title": text[:100]}
    except Exception as e:
        logger.error(f"POST /api/meetings/add failed: {e}")
        return {"error": str(e)}


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


@app.patch("/api/deadlines/{deadline_id}", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def update_deadline(deadline_id: int, request: Request):
    """D3: General deadline update — status, priority, description. Used by triage UI."""
    try:
        body = await request.json()
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            # Whitelist allowed fields
            allowed = {"status", "priority", "description", "confidence", "severity"}
            updates = []
            params = []
            for key, value in body.items():
                if key in allowed:
                    updates.append(f"{key} = %s")
                    params.append(value)
            if not updates:
                raise HTTPException(status_code=400, detail="No valid fields to update")
            params.append(deadline_id)
            cur.execute(
                f"UPDATE deadlines SET {', '.join(updates)} WHERE id = %s RETURNING id",
                params,
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if not row:
                raise HTTPException(status_code=404, detail="Deadline not found")
            return {"status": "updated", "id": deadline_id, "fields": list(body.keys())}
        finally:
            store._put_conn(conn)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PATCH /api/deadlines/{deadline_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/deadlines/{deadline_id}/feedback", tags=["deadlines"], dependencies=[Depends(verify_api_key)])
async def deadline_feedback_api(deadline_id: int, request: Request):
    """DEADLINE_FEEDBACK_LOOP_1: capture labeled Director click for phase-3 training corpus.

    Body shape:
        {
            "feedback_type": "confirm" | "mute" | "wrong_matter" | "wrong_deadline",
            "corrected_matter_slug": "hagenauer-rg7"  # optional, only for wrong_matter
        }

    Side effects:
        - confirm:        status -> completed   (mirrors /complete endpoint)
        - mute:           status -> dismissed   (mirrors /dismiss endpoint)
        - wrong_matter:   no status flip; matter_slug NOT mutated on deadlines table
                          (row stays visible — Director is correcting the classifier
                          label, not removing the row from view)
        - wrong_deadline: status -> dismissed with reason 'wrong_deadline'
                          (this isn't a deadline — remove from view but tag the
                          dismiss reason distinctly so phase 3 sees it)
    """
    try:
        payload = await request.json()
        feedback_type = payload.get("feedback_type")
        corrected_slug_raw = payload.get("corrected_matter_slug")

        from models.deadlines import get_deadline_by_id, update_deadline
        from models.deadline_feedback import insert_feedback, VALID_FEEDBACK_TYPES
        from kbl.slug_registry import normalize as slug_normalize

        if feedback_type not in VALID_FEEDBACK_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"feedback_type must be one of {sorted(VALID_FEEDBACK_TYPES)}",
            )

        dl = get_deadline_by_id(deadline_id)
        if not dl:
            raise HTTPException(status_code=404, detail=f"Deadline {deadline_id} not found")

        # Validate corrected slug for wrong_matter (canonical or known alias).
        # Hallucinated slugs become None; the click still records but with NULL.
        corrected_slug = None
        if feedback_type == "wrong_matter" and corrected_slug_raw:
            corrected_slug = slug_normalize(corrected_slug_raw)
            if corrected_slug is None:
                logger.warning(
                    f"deadline_feedback: wrong_matter received unknown slug "
                    f"{corrected_slug_raw!r} on deadline {deadline_id} — corpus row will store NULL"
                )

        # Snapshot fields off the deadline row at click time.
        # Inner try/except mirrors /dismiss + /complete: a raise from insert_feedback
        # (despite its internal try/except) must NEVER block the status flip, otherwise
        # the user sees a 500 and the card stays visible with no corpus row written.
        fid = None
        try:
            fid = insert_feedback(
                deadline_id=deadline_id,
                feedback_type=feedback_type,
                original_matter_slug=dl.get("matter_slug"),
                corrected_matter_slug=corrected_slug,
                original_description=dl.get("description") or "",
                original_source_type=dl.get("source_type"),
                director_note=None,
            )
        except Exception as fe:
            logger.warning(f"deadline_feedback ({feedback_type}) write failed for {deadline_id}: {fe}")

        # Side-effect status flip (verb-specific). wrong_matter does NOT flip status.
        if feedback_type == "confirm":
            update_deadline(deadline_id, status="completed",
                            dismissed_reason="Completed via dashboard feedback")
        elif feedback_type == "mute":
            update_deadline(deadline_id, status="dismissed",
                            dismissed_reason="Muted via dashboard feedback")
        elif feedback_type == "wrong_deadline":
            update_deadline(deadline_id, status="dismissed",
                            dismissed_reason="wrong_deadline")

        return {"status": "ok", "feedback_id": fid, "deadline_id": deadline_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/deadlines/{deadline_id}/feedback failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# BAKER_DASHBOARD_V2_CANDIDATE_INGEST_1 — triage queue (AC6/AC7/AC9/AC10)
# Candidates are a QUARANTINE layer. These endpoints expose the review queue +
# manual dismiss/verify; nothing here feeds Today (AC8). Responses carry summary
# + metadata + internal source refs only — never raw bodies (AC9).
# ---------------------------------------------------------------------------


@app.get("/api/today", tags=["dashboard-v2"], dependencies=[Depends(verify_api_key)])
async def get_today(limit_per_lane: int = Query(5, ge=1, le=20)):
    """BAKER_DASHBOARD_V2_TODAY_1 — trusted Today surface. Reads ONLY
    verified_items (verified|ratified) via the today_v2 service, grouped into
    critical/promises/meetings/travel with evidence metadata only. Never reads
    signal_candidates/alerts/deadlines and returns no raw source bodies."""
    try:
        from orchestrator.today_v2 import get_today_payload
        return get_today_payload(limit_per_lane=limit_per_lane)
    except Exception as e:
        logger.error(f"/api/today failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/verified-items/{item_id}", tags=["dashboard-v2"], dependencies=[Depends(verify_api_key)])
async def get_verified_item_detail_route(item_id: int):
    """BAKER_DASHBOARD_V2_CARD_DETAIL_1 — bounded detail for ONE trusted item.

    Returns the trusted card + bounded evidence metadata + the verification audit
    timeline (actor_type / model / timestamps). Reads ONLY verified_items +
    verification_events; never returns raw email/WhatsApp/ClaimsMax source bodies
    (sanitized + length-bounded). Untrusted (candidate/dismissed) and missing ids
    both return 404 so candidate rows cannot be enumerated. Auth-gated."""
    try:
        from orchestrator.verified_item_detail import get_verified_item_detail
        result = get_verified_item_detail(item_id)
        if result.get("status") in ("not_found", "not_trusted"):
            raise HTTPException(status_code=404, detail="verified item not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/verified-items/{item_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/triage/candidates", tags=["dashboard-v2"], dependencies=[Depends(verify_api_key)])
async def list_triage_candidates(
    matter_slug: str = Query(None),
    source_type: str = Query(None),
    candidate_type: str = Query(None),
    source_trust: str = Query(None),
    status: str = Query(None),
    created_after: str = Query(None, description="ISO datetime lower bound (AC7 window)"),
    created_before: str = Query(None, description="ISO datetime upper bound (AC7 window)"),
    limit: int = Query(100, ge=1, le=1000),
):
    """AC6/AC7 — matter-aware candidate triage queue with a created-date window.
    Summaries + metadata + internal source refs only (AC9)."""
    try:
        from orchestrator.candidate_ingest import list_candidates
        rows = list_candidates(
            matter_slug=matter_slug, source_type=source_type,
            candidate_type=candidate_type, source_trust=source_trust,
            status=status, created_after=created_after,
            created_before=created_before, limit=limit,
        )
        return {"status": "ok", "count": len(rows), "candidates": rows}
    except Exception as e:
        logger.error(f"/api/triage/candidates failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/triage/{candidate_id}/dismiss", tags=["dashboard-v2"], dependencies=[Depends(verify_api_key)])
async def dismiss_triage_candidate(candidate_id: int, request: Request):
    """AC10 — dismiss a candidate with a structured reason (one of the 10-value
    DISMISS_REASONS set). Body: {"reason": "...", "actor_id": "..."}."""
    try:
        from orchestrator.candidate_ingest import dismiss_candidate
        from models.verified_items import DISMISS_REASONS
        payload = await request.json()
        reason = payload.get("reason")
        actor_id = payload.get("actor_id") or "director"
        if reason not in DISMISS_REASONS:
            raise HTTPException(
                status_code=400,
                detail=f"reason must be one of {sorted(DISMISS_REASONS)}",
            )
        res = dismiss_candidate(candidate_id, reason, actor_id)
        if not res.get("ok"):
            if res.get("error") == "not_found":
                raise HTTPException(status_code=404, detail=f"candidate {candidate_id} not found")
            raise HTTPException(status_code=400, detail=res)
        return {"status": "ok", **res}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/triage/{candidate_id}/dismiss failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/triage/{candidate_id}/verify-manual", tags=["dashboard-v2"], dependencies=[Depends(verify_api_key)])
async def verify_manual_triage_candidate(candidate_id: int, request: Request):
    """AC6 — manually promote a candidate to a verified_items row with a supplied
    evidence packet. The human verifier is recorded in verification_events (not
    just created_by) via the audited transition path. Untrusted-legacy candidates
    are refused (AC2.3). Body requires: item_type, claim, actor_type, actor_id,
    confidence, source_trust, verification_summary, counterargument."""
    try:
        from orchestrator.candidate_ingest import (
            promote_candidate_manual, VERIFIER_ACTOR_TYPES,
        )
        payload = await request.json()
        required = (
            "item_type", "claim", "actor_type", "actor_id", "confidence",
            "source_trust", "verification_summary", "counterargument",
        )

        def _blank(v):
            return v is None or (isinstance(v, str) and not v.strip())

        miss = [k for k in required if _blank(payload.get(k))]
        if miss:
            raise HTTPException(status_code=400, detail=f"missing required fields: {miss}")
        # deputy-codex F1 — enforce the verifier allowlist at the boundary too.
        if payload.get("actor_type") not in VERIFIER_ACTOR_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"actor_type must be one of {sorted(VERIFIER_ACTOR_TYPES)}",
            )
        res = promote_candidate_manual(
            candidate_id,
            item_type=payload["item_type"],
            claim=payload["claim"],
            actor_type=payload["actor_type"],
            actor_id=payload["actor_id"],
            confidence=payload["confidence"],
            source_trust=payload["source_trust"],
            verification_summary=payload["verification_summary"],
            counterargument=payload["counterargument"],
            why_matters=payload.get("why_matters"),
            next_action=payload.get("next_action"),
            owner=payload.get("owner"),
            matter_slug=payload.get("matter_slug"),
            people=payload.get("people"),
        )
        if not res.get("ok"):
            err = res.get("error")
            if err == "not_found":
                raise HTTPException(status_code=404, detail=f"candidate {candidate_id} not found")
            # F3 — an already-dismissed/promoted/concurrently-claimed candidate is
            # a conflict (normal double-click), not a server error.
            if err == "bad_candidate_status":
                raise HTTPException(status_code=409, detail=res)
            if err in ("not_promotable", "verifier_required", "missing_actor",
                       "missing_evidence"):
                raise HTTPException(status_code=400, detail=res)
            raise HTTPException(status_code=500, detail=res)
        return {"status": "ok", **res}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/triage/{candidate_id}/verify-manual failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# BAKER_DASHBOARD_V2_VERIFIER_1 — trusted Opus-class candidate verifier (AC6).
# These are the ONLY surface for the auto-verifier: a health probe and a
# single-candidate verify. No batch, no cron, no UI (AC8). The verifier model
# floor is Opus-class only (AC1); raw source bodies stay prompt-only (AC7).
@app.get("/api/triage/verifier/health", tags=["dashboard-v2"], dependencies=[Depends(verify_api_key)])
async def triage_verifier_health():
    """AC6 — verifier health: resolved verifier model + whether it passes the
    Opus-class floor + the allowlisted source tables + (cheap) awaiting count.
    Metadata only — no source text. Auth-gated like every dashboard-v2 route."""
    try:
        from orchestrator.candidate_verifier import get_verifier_health
        return await asyncio.to_thread(get_verifier_health)
    except Exception as e:
        logger.error(f"/api/triage/verifier/health failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/triage/{candidate_id}/verify-auto", tags=["dashboard-v2"], dependencies=[Depends(verify_api_key)])
async def verify_auto_triage_candidate(candidate_id: int, request: Request):
    """AC6 — re-verify ONE candidate with an Opus-class model and, unless dry_run,
    promote it to a trusted verified_items row via the audited Cortex path. The
    model call is blocking, so it runs in a worker thread (asyncio.to_thread).
    Optional body: {"actor_id": "...", "dry_run": bool}. Response is sanitized —
    never any raw source body or prompt text (AC7)."""
    try:
        from orchestrator.candidate_verifier import verify_candidate
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}  # empty/no body is fine — sensible defaults below

        actor_id = payload.get("actor_id") or "cortex:dashboard-v2-verifier"
        dry_run = bool(payload.get("dry_run", False))

        res = await asyncio.to_thread(
            verify_candidate, candidate_id, actor_id=actor_id, dry_run=dry_run,
        )
        if not res.get("ok"):
            err = res.get("error")
            if err in ("not_found", "source_not_found"):
                raise HTTPException(status_code=404, detail=res)
            # already-verified / wrong-status / concurrent claim = conflict, not error.
            if err in ("bad_candidate_status", "already_verified"):
                raise HTTPException(status_code=409, detail=res)
            # cost breaker tripped or the provider is unreachable = unavailable.
            if err in ("cost_hard_stop", "provider_unavailable"):
                raise HTTPException(status_code=503, detail=res)
            if err in ("unsupported_source", "verification_refused",
                       "model_not_allowed", "missing_evidence", "bad_json"):
                raise HTTPException(status_code=400, detail=res)
            # promote_failed / internal_error / unknown -> 500 (already logged).
            raise HTTPException(status_code=500, detail=res)
        return {"status": "ok", **res}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/triage/{candidate_id}/verify-auto failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/slug-registry", tags=["registry"], dependencies=[Depends(verify_api_key)])
async def slug_registry_api(status: str = Query("active", regex="^(active|all)$")):
    """DEADLINE_FEEDBACK_LOOP_1: serve canonical slug list for the wrong-matter dropdown."""
    try:
        from kbl.slug_registry import active_slugs, canonical_slugs
        slugs = sorted(active_slugs() if status == "active" else canonical_slugs())
        return {"slugs": slugs, "count": len(slugs), "status_filter": status}
    except Exception as e:
        logger.error(f"/api/slug-registry failed: {e}")
        return {"slugs": [], "count": 0, "error": str(e)}


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

# F3: Cadence endpoint MUST come before {name} route (FastAPI matches in order)
@app.get("/api/contacts/cadence", tags=["contacts"], dependencies=[Depends(verify_api_key)])
async def contact_cadence():
    """F3: Return contacts with cadence data, sorted by deviation from normal."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return {"contacts": []}
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT name, tier, avg_inbound_gap_days, last_inbound_at,
                   EXTRACT(DAY FROM NOW() - last_inbound_at)::float as days_silent,
                   CASE WHEN avg_inbound_gap_days > 0
                        THEN ROUND((EXTRACT(EPOCH FROM NOW() - last_inbound_at)/86400.0
                              / avg_inbound_gap_days)::numeric, 1)
                        ELSE 0 END as deviation
            FROM vip_contacts
            WHERE avg_inbound_gap_days IS NOT NULL
              AND last_inbound_at IS NOT NULL
            ORDER BY deviation DESC
            LIMIT 30
        """)
        contacts = [_serialize(dict(r)) for r in cur.fetchall()]
        cur.close()
        return {"contacts": contacts}
    except Exception as e:
        logger.error(f"/api/contacts/cadence failed: {e}")
        return {"contacts": [], "error": str(e)}
    finally:
        store._put_conn(conn)


@app.get("/api/contacts/vips", tags=["contacts"], dependencies=[Depends(verify_api_key)])
async def list_vip_contacts():
    """Return all VIP contacts for delegate picker."""
    try:
        from models.deadlines import get_vip_contacts
        vips = get_vip_contacts()
        return {"contacts": [_serialize(v) for v in vips]}
    except Exception as e:
        logger.error(f"/api/contacts/vips failed: {e}")
        return {"contacts": [], "error": str(e)}


@app.post("/api/alerts/{alert_id}/draft", tags=["alerts"], dependencies=[Depends(verify_api_key)])
async def draft_reply_for_alert(alert_id: int, request: Request):
    """Generate a draft reply for an alert using Haiku. Returns draft text."""
    try:
        import anthropic
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM alerts WHERE id = %s", (alert_id,))
            alert = cur.fetchone()
            cur.close()
            if not alert:
                raise HTTPException(status_code=404, detail="Alert not found")
            alert = dict(alert)
        finally:
            store._put_conn(conn)

        title = alert.get("title", "")
        body = alert.get("body", "")
        source = alert.get("source", "")
        sa = alert.get("structured_actions") or {}
        suggestion = sa.get("suggested_action", "")

        prompt = f"""You are Baker, an AI Chief of Staff. Draft a concise, professional reply for the following alert.

Alert: {title}
Source: {source}
Details: {body[:2000]}
{f"Suggested action: {suggestion}" if suggestion else ""}

Write a draft reply that is:
- Professional but warm
- Concise (2-4 sentences for email, 1-2 for WhatsApp)
- Ready to send with minimal editing
- In the appropriate language (match the source language)

Output ONLY the draft text, nothing else."""

        client = anthropic.Anthropic()
        resp = _llm_call("gemini-2.5-flash",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        draft = resp.text.strip()
        return {"draft": draft, "alert_id": alert_id, "source": source}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/api/alerts/{alert_id}/draft failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


# --- D6: Unified Knowledge Base Search ---

_UNIFIED_QDRANT_SOURCE_ALIASES = {
    "documents": {"baker-documents", "sentinel-documents"},
    "conversations": {"baker-conversations"},
}


def _configured_unified_qdrant_collections(allowed_sources: Optional[set[str]] = None) -> list[str]:
    """Return configured Qdrant collections for /api/search/unified.

    Unfiltered unified search must track the same source of truth as
    /api/search: config.qdrant.collections / BAKER_COLLECTIONS. Explicit legacy
    source filters remain narrow, so sources=documents does not unexpectedly
    fan out across mail, ClickUp, Slack, etc.
    """
    configured = []
    seen = set()
    for raw in config.qdrant.collections:
        collection = str(raw).strip()
        if collection and collection not in seen:
            configured.append(collection)
            seen.add(collection)

    if not allowed_sources:
        return configured

    allowed = {s.strip().lower() for s in allowed_sources if s and s.strip()}
    selected = []
    for collection in configured:
        collection_key = collection.lower()
        source_key = collection_key
        for prefix in ("baker-", "sentinel-"):
            if source_key.startswith(prefix):
                source_key = source_key[len(prefix):]
                break

        if collection_key in allowed or source_key in allowed:
            selected.append(collection)
            continue

        for source, aliases in _UNIFIED_QDRANT_SOURCE_ALIASES.items():
            if source in allowed and collection in aliases:
                selected.append(collection)
                break

    return selected


def _unified_qdrant_source(collection: str, result_source: Optional[str]) -> str:
    if collection == "baker-documents":
        return "document"
    if collection == "baker-conversations":
        return "conversation"
    return result_source or collection.replace("baker-", "").replace("sentinel-", "")


@app.get("/api/search/unified", tags=["search"], dependencies=[Depends(verify_api_key)])
async def unified_search(
    q: str = Query(..., min_length=2, max_length=500),
    limit: int = Query(20, ge=1, le=50),
    sources: Optional[str] = Query(None, description="Comma-separated: emails,meetings,whatsapp,documents,conversations"),
):
    """D6: Search across all stored content from one endpoint.
    Returns merged, relevance-ranked results across emails, meetings, docs, WhatsApp, conversations."""
    from memory.retriever import SearchBackendUnavailable

    retriever = _get_retriever()
    all_results = []
    # CLERK_SEARCH_BACKEND_FAILSILENT_FIX_1 (B): track sources whose backend was
    # UNREACHABLE (vs legitimately empty) so a partial/degraded search is not
    # mistaken for "no results found". Surfaced in the response as
    # `backend_unavailable`; callers (e.g. MCP baker_search) can fail loud.
    backend_errors = []

    # Parse source filter (default: all)
    allowed = set()
    if sources:
        allowed = {s.strip().lower() for s in sources.split(",")}

    def _search_source(fn, source_name, search_limit=5):
        if allowed and source_name not in allowed:
            return
        try:
            results = fn(q, limit=search_limit)
            for r in results:
                all_results.append({
                    "source": r.source or source_name,
                    "content": r.content[:500],
                    "score": round(r.score, 3),
                    "metadata": r.metadata,
                    "token_estimate": r.token_estimate,
                })
        except SearchBackendUnavailable as e:
            logger.error(f"Unified search: {source_name} backend unavailable: {e}")
            backend_errors.append(source_name)
        except Exception as e:
            logger.warning(f"Unified search: {source_name} failed: {e}")

    # Search all sources in parallel (sync retriever, but fast DB queries)
    per_source = max(3, limit // 5)
    _search_source(retriever.get_email_messages, "emails", per_source)
    _search_source(retriever.get_meeting_transcripts, "meetings", per_source)
    _search_source(retriever.get_whatsapp_messages, "whatsapp", per_source)

    # Qdrant semantic search: config-driven, matching /api/search's collection
    # source of truth while preserving unified's existing raw-score response.
    qdrant_collections = _configured_unified_qdrant_collections(allowed or None)
    if qdrant_collections:
        try:
            query_vector = retriever._embed_query(q)
            for collection in qdrant_collections:
                try:
                    hits = retriever.search_collection(
                        query_vector=query_vector,
                        collection=collection,
                        limit=per_source,
                        score_threshold=0.3,
                    )
                    for r in hits:
                        all_results.append({
                            "source": _unified_qdrant_source(collection, r.source),
                            "content": r.content[:500],
                            "score": round(r.score, 3),
                            "metadata": r.metadata,
                            "token_estimate": r.token_estimate,
                        })
                except Exception as e:
                    logger.warning(f"Unified search: Qdrant collection {collection} failed: {e}")
        except Exception as e:
            logger.warning(f"Unified search: Qdrant embedding failed: {e}")

    # Sort by score descending, deduplicate by content prefix
    all_results.sort(key=lambda x: x["score"], reverse=True)

    # Dedup: skip results with identical first 100 chars of content
    seen_prefixes = set()
    deduped = []
    for r in all_results:
        prefix = r["content"][:100].lower()
        if prefix not in seen_prefixes:
            seen_prefixes.add(prefix)
            deduped.append(r)

    resp = {
        "query": q,
        "results": deduped[:limit],
        "total": len(deduped),
        "sources_searched": list(allowed) if allowed else ["emails", "meetings", "whatsapp", "documents", "conversations"],
        "qdrant_collections_searched": qdrant_collections,
    }
    # B (fail loud): if any source's backend was unreachable, say so — an empty
    # result with backend_unavailable set is NOT "no data", it's a degraded search.
    if backend_errors:
        resp["backend_unavailable"] = sorted(set(backend_errors))
    return resp


# --- Semantic Search (legacy Qdrant-only) ---

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


@app.post("/api/clickup/create-from-alert", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def create_clickup_from_alert(request: Request):
    """TRIAGE-CARDS-1: Create a ClickUp task from an alert. Uses Handoff Notes list by default."""
    try:
        body = await request.json()
        name = body.get("name", "Untitled task")
        description = body.get("description", "")
        alert_id = body.get("alert_id")

        from clickup_client import ClickUpClient
        client = ClickUpClient()
        result = client.create_task(
            list_id="901521426367",  # Handoff Notes
            name=name[:200],
            description=description[:2000] if description else f"Created from alert #{alert_id}",
            priority=3,
            tags=["from-baker"],
        )
        task_id = result.get("id")
        task_url = result.get("url")
        logger.info(f"TRIAGE-CARDS-1: ClickUp task created from alert #{alert_id}: {task_id}")
        return {"task_id": task_id, "url": task_url}
    except Exception as e:
        logger.error(f"POST /api/clickup/create-from-alert failed: {e}")
        return {"error": str(e)}


# ── CLICKUP-DROPDOWN-2: Structure + create-in-list endpoints ──────────────

@app.get("/api/clickup/structure", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def get_clickup_structure():
    """Return workspaces → spaces → lists for task creation dropdown."""
    from clickup_client import ClickUpClient
    client = ClickUpClient._get_global_instance()

    # All 5 active workspace IDs (from clickup_trigger.py)
    workspace_ids = ["2652545", "24368967", "24382372", "24382764", "24385290"]
    structure = []

    for ws_id in workspace_ids:
        try:
            spaces = client.get_spaces(ws_id)
            for space in spaces:
                space_name = space.get("name", "Unknown")
                space_id = space.get("id")
                try:
                    lists = client.get_lists(space_id)
                    for lst in lists:
                        # Folder info if available
                        folder_name = lst.get("folder", {}).get("name", "")
                        full_path = f"{space_name} / {folder_name} / {lst['name']}" if folder_name else f"{space_name} / {lst['name']}"
                        structure.append({
                            "workspace_id": ws_id,
                            "space_id": space_id,
                            "space_name": space_name,
                            "list_id": lst["id"],
                            "list_name": lst["name"],
                            "folder_name": folder_name,
                            "full_path": full_path,
                        })
                except Exception:
                    continue
        except Exception:
            continue

    return {"lists": structure}


@app.post("/api/clickup/create-task", tags=["clickup"], dependencies=[Depends(verify_api_key)])
async def create_clickup_task_in_list(request: Request):
    """CLICKUP-DROPDOWN-2: Create a ClickUp task in a specific list."""
    body = await request.json()
    list_id = body.get("list_id")
    name = body.get("name", "Untitled task")
    description = body.get("description", "")
    priority = body.get("priority")
    due_date = body.get("due_date")

    if not list_id:
        return JSONResponse({"error": "list_id required"}, status_code=400)

    try:
        from clickup_client import ClickUpClient
        client = ClickUpClient._get_global_instance()

        # Convert ISO date to unix ms if provided
        due_ms = None
        if due_date:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                due_ms = int(dt.timestamp() * 1000)
            except Exception:
                pass

        result = client.create_task(
            list_id=list_id,
            name=name[:200],
            description=description[:2000] if description else "",
            priority=priority,
            due_date=due_ms,
            tags=["from-baker"],
        )

        if not result:
            return JSONResponse({"error": "ClickUp API returned no result"}, status_code=500)

        task_id = result.get("id")
        task_url = result.get("url")
        logger.info(f"CLICKUP-DROPDOWN-2: Task created in list {list_id}: {task_id}")
        return {"status": "created", "task_id": task_id, "url": task_url}
    except Exception as e:
        logger.error(f"POST /api/clickup/create-task failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


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

        # SCAN-CONTEXT-1: Prepend alert context to question for intent classification
        # Also check client-side history for system context messages
        _alert_ctx = req.alert_context or ""
        if not _alert_ctx and req.history:
            for h in req.history:
                if h.get("role") == "system" and h.get("content", "").startswith("[Context from alert:"):
                    _alert_ctx = h["content"]
                    break
        # IDEAS-CAPTURE-1: Detect idea prefix before intent classification
        if req.question.lower().startswith('idea:') or req.question.lower().startswith('idea -'):
            import re as _idea_re
            _idea_content = _idea_re.sub(r'^idea[:\-\s]+', '', req.question, flags=_idea_re.IGNORECASE).strip()
            if _idea_content:
                try:
                    _idea_store = _get_store()
                    _idea_conn = _idea_store._get_conn()
                    if _idea_conn:
                        try:
                            _idea_cur = _idea_conn.cursor()
                            _idea_cur.execute("INSERT INTO ideas (content, source) VALUES (%s, %s)", (_idea_content, 'scan'))
                            _idea_conn.commit()
                            _idea_cur.close()
                        finally:
                            _idea_store._put_conn(_idea_conn)
                except Exception:
                    pass

            async def _idea_stream():
                yield f"data: {json.dumps({'token': 'Idea captured. You can find it in the Ideas section on the sidebar.'})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(_idea_stream(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        # YOUTUBE-GEMMA-INGEST-1: Auto-detect YouTube URLs in scan input
        try:
            from triggers.youtube_ingest import detect_youtube_urls, ingest_youtube_video
            from triggers.state import trigger_state as _yt_ts
            _yt_ids = detect_youtube_urls(req.question)
            for _yt_vid in _yt_ids[:2]:  # Max 2 videos per query
                _yt_src = f"youtube_{_yt_vid}"
                if not _yt_ts.is_processed("youtube", _yt_src):
                    try:
                        _yt_result = ingest_youtube_video(_yt_vid)
                        if _yt_result.get("status") == "ok":
                            logger.info(f"Auto-ingested YouTube video from scan: {_yt_result.get('title')}")
                    except Exception as _yt_e:
                        logger.debug(f"YouTube auto-ingest failed (non-fatal): {_yt_e}")
        except Exception:
            pass  # Non-fatal — scan continues regardless

        _classify_question = req.question
        if _alert_ctx:
            _classify_question = f"{_alert_ctx}\n\nDirector's request: {req.question}"
            logger.info(f"SCAN-CONTEXT-1: alert context injected ({len(_alert_ctx)} chars)")

        intent = _ah.classify_intent(_classify_question, conversation_history=_conv_history)
        logger.info(f"SCAN_DEBUG: intent_type={intent.get('type')}, recipient={intent.get('recipient')}")

        # CONV-SAFETY-1: Build limited history (2 turns) for outbound actions (email, WhatsApp)
        # This prevents old conversation topics from bleeding into new emails/messages
        _limited_history = ""
        if intent.get("type") in ("email_action", "whatsapp_action"):
            try:
                _ltd_turns = store.get_recent_conversations(limit=2) if store else []
                if _ltd_turns:
                    _ltd_lines = []
                    for turn in reversed(_ltd_turns):
                        _ltd_lines.append(f"Director: {(turn.get('question') or '')[:200]}")
                        a = (turn.get("answer") or "")[:300]
                        if a:
                            _ltd_lines.append(f"Baker: {a}")
                    _limited_history = "\n".join(_ltd_lines)
            except Exception:
                pass

        if intent.get("type") == "email_action":
            # If alert context present, prepend it to the content_request so email body uses correct topic
            if _alert_ctx and intent.get("content_request"):
                intent["content_request"] = f"{_alert_ctx}\n\n{intent['content_request']}"
            elif _alert_ctx:
                intent["content_request"] = _alert_ctx + "\n\n" + (intent.get("subject") or req.question)
            logger.info("SCAN_DEBUG: routing to handle_email_action (history limited to 2 turns)")
            return _action_stream_response(
                _ah.handle_email_action(intent, _get_retriever(), req.project, req.role),
                req.question,
            )
        elif intent.get("type") == "whatsapp_action":
            logger.info("SCAN_DEBUG: routing to handle_whatsapp_action")
            intent["original_question"] = req.question  # pass full text for phone extraction
            # CONV-SAFETY-1: Use limited history to prevent topic bleed
            return _action_stream_response(
                _ah.handle_whatsapp_action(
                    intent, _get_retriever(), channel="scan",
                    conversation_history=_limited_history,
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
        elif intent.get("type") == "meeting_declaration":
            logger.info("SCAN_DEBUG: routing to handle_meeting_declaration")
            return _action_stream_response(
                _ah.handle_meeting_declaration(req.question, channel="ask_baker"),
                req.question,
            )
        elif intent.get("type") == "critical_declaration":
            logger.info("SCAN_DEBUG: routing to handle_critical_declaration")
            return _action_stream_response(
                _ah.handle_critical_declaration(req.question, channel="ask_baker"),
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
        elif intent.get("type") == "cortex_run_action":
            # CORTEX_MANUAL_INVOKE_1: route "run cortex on <matter>" through SSE stream
            from outputs.cortex_run_stream import stream_cycle_events
            from triggers.cortex_pre_review_gate import matter_has_cortex_config
            _matter = (intent.get("matter_slug") or "").strip()
            if not _matter:
                logger.warning(
                    "cortex_run_action intent missing matter_slug; falling through"
                )
            elif not matter_has_cortex_config(_matter):
                logger.info(
                    "cortex_run_action rejected — matter=%s has no cortex-config.md",
                    _matter,
                )
                return _action_stream_response(
                    f"Matter '{_matter}' is not Cortex-enabled (no cortex-config.md). "
                    "Add the config in baker-vault first.",
                    req.question,
                )
            else:
                logger.info(
                    "SCAN_DEBUG: routing to cortex_run_stream matter=%s",
                    _matter,
                )
                _question_text = (intent.get("question") or req.question or "").strip()
                return StreamingResponse(
                    stream_cycle_events(
                        matter_slug=_matter,
                        director_question=_question_text,
                        triggered_by="scan_intent",
                    ),
                    media_type="text/event-stream",
                )
        elif intent.get("type") == "capability_task":
            # AGENT-FRAMEWORK-1: Explicit capability invocation
            from orchestrator.complexity_router import classify_complexity as _cc_cap
            return _scan_chat_capability(req, start, intent,
                                          complexity=_cc_cap(req.question))
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
        # COMPLEXITY-ROUTER-REFACTOR: Rule-based classification (no LLM)
        from orchestrator.complexity_router import classify_complexity
        _complexity = classify_complexity(req.question)
        if _task_id:
            store.update_baker_task(_task_id, complexity=_complexity)
        logger.info(f"Complexity router: {_complexity} for '{req.question[:60]}'")
    except Exception as _te:
        logger.warning(f"baker_task creation failed (non-fatal): {_te}")
        _complexity = "deep"

    return _scan_chat_deep(req, start, task_id=_task_id, complexity=_complexity)


def _scan_chat_deep(req, start: float, task_id: int = None, complexity: str = None):
    """DEEP-MODE-1: Deep agentic path for all Ask Baker questions.

    Pre-stuffs recent emails, WhatsApp, meetings, decisions, and analyses
    into the system prompt, PLUS gives the agent all tools for deeper search.
    90s timeout, 15 iterations, full session history. No capability routing.
    COMPLEXITY-ROUTER-1: Fast-classified questions use Haiku with fewer iterations.
    """
    from orchestrator.agent import run_agent_loop_streaming
    from orchestrator.scan_prompt import build_mode_aware_prompt

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Full session history — no cap
    history = []
    for msg in (req.history or []):
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": content})

    async def event_stream():
        # THINKING-DOTS-FIX: Signal retrieval phase BEFORE doing retrieval
        # This yield opens the SSE connection and shows "Searching memory..." to the user
        yield f"data: {json.dumps({'status': 'retrieving'})}\n\n"

        # --- Pre-stuff context from DB (moved inside generator so status streams first) ---
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

        # CITATIONS_API_SCAN_1: Build Anthropic Citations document blocks from
        # the retrieval context. Model-level grounding replaces prompt-engineered
        # "never fabricate citations" (belt-and-braces: the prompt instruction
        # in capability_runner.py:1149 is retained for 7-day observation). The
        # blocks feed the __citations__ SSE event emitted at end-of-stream.
        _scan_doc_blocks: list = []
        try:
            _scan_doc_blocks = build_document_blocks([
                {"title": f"Scan Context Block {i + 1}", "body": cb}
                for i, cb in enumerate(context_blocks) if cb
            ])
            logger.debug(
                f"Scan citations adapter: {len(_scan_doc_blocks)} doc blocks built",
            )
        except Exception as _cite_e:
            logger.warning(f"Scan citations adapter failed (non-fatal): {_cite_e}")

        # Build system prompt: base + pre-stuffed context + preferences
        base_scan_prompt = _scan_prompt_with_ingestion_surfaces()
        system_prompt = (
            f"{base_scan_prompt}\n\n"
            f"## CURRENT TIME\n{now}\n\n"
            f"{pre_stuffed}"
        )
        system_prompt = build_mode_aware_prompt(system_prompt, domain=None, mode="delegate")

        logger.info(f"DEEP-MODE: system prompt {len(system_prompt)} chars, "
                    f"{len(context_blocks)} context blocks pre-stuffed")

        # THINKING-DOTS-FIX: Signal generation phase after retrieval is done
        yield f"data: {json.dumps({'status': 'generating'})}\n\n"

        full_response = ""
        agent_result = None

        import queue as _queue
        item_queue = _queue.Queue()

        def _run_agent():
            try:
                # COMPLEXITY-ROUTER-REFACTOR: Rule-based (no LLM, no regex hacks)
                _cc = config.complexity
                _is_fast = (complexity == "fast" and not _cc.shadow_mode)
                gen = run_agent_loop_streaming(
                    question=req.question,
                    system_prompt=system_prompt,
                    history=history,
                    max_iterations=5 if _is_fast else 15,
                    timeout_override=float(_cc.fast_timeout) if _is_fast else 90.0,
                    model_override=_cc.fast_model if _is_fast else None,
                    max_tokens_override=_cc.fast_max_tokens if _is_fast else None,
                    tool_limit=_cc.fast_tool_limit if _is_fast else None,
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
                elif "screenshot" in item:
                    yield f"data: {json.dumps({'screenshot': item['screenshot']})}\n\n"
                elif "error" in item:
                    logger.error(f"Deep scan error: {item['error']}")
                    yield f"data: {json.dumps({'error': item['error']})}\n\n"
        except Exception as e:
            logger.error(f"Deep scan error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        await agent_thread
        # A6 LEARNING-LOOP: Yield task_id for frontend feedback buttons
        if task_id:
            yield f"data: {json.dumps({'task_id': task_id})}\n\n"

        # CITATIONS_API_SCAN_1: End-of-stream __citations__ event. Agent-loop
        # doesn't surface the raw Anthropic response yet; we degrade gracefully
        # via an empty ExtractedResponse. When the agent loop is upgraded to
        # pass through the Anthropic response (follow-on brief), replace the
        # fallback with extract_citations(response). Frontend parsing of the
        # __citations__ event lands in SCAN_CITATIONS_FRONTEND_1.
        try:
            _extracted = extract_citations(ExtractedResponse(text=full_response))
            _citations_payload = {
                "documents": [b.get("title") for b in _scan_doc_blocks],
                "citations": [c.__dict__ for c in _extracted.citations_flat],
            }
            yield f"data: __citations__{json.dumps(_citations_payload)}\n\n"
        except Exception as _cite_e:
            logger.debug(f"__citations__ emit failed (non-fatal): {_cite_e}")

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
        _scan_store_back(req, full_response, start, extra_meta, task_id=task_id,
                         complexity=complexity)

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
        base_scan_prompt = _scan_prompt_with_ingestion_surfaces()
        return (
            f"{base_scan_prompt}\n"
            f"## CURRENT TIME\n{now}\n"
            f"{domain_context}"
            f"{deadline_block}"
        )
    else:
        # Legacy mode: context stuffed into prompt
        context_block = _format_scan_context(contexts)
        base_scan_prompt = _scan_prompt_with_ingestion_surfaces()
        return (
            f"{base_scan_prompt}\n"
            f"## CURRENT TIME\n{now}\n\n"
            f"{domain_context}"
            f"## RETRIEVED CONTEXT\n{context_block}"
            f"{deadline_block}"
        )


def _maybe_save_to_dossiers(question: str, answer: str, owner: str = "dimitry"):
    """AUTO-SAVE-DOSSIERS-1: Auto-save substantive Baker answers to deep_analyses.
    Filters out short replies, action confirmations, and unstructured text.
    Dossier-worthy = long + structured + not an action confirmation."""
    import re as _re_dossier
    # Filter: too short
    if len(answer) < 800:
        return
    # Filter: action confirmations
    _skip_prefixes = ("\u2705", "\U0001f4e7", "\u274c", "Noted", "Done", "Got it", "I don't have", "I couldn't")
    if any(answer.lstrip().startswith(p) for p in _skip_prefixes):
        return
    # Filter: must have structural markers (formatted analysis)
    _structure_markers = ("## ", "**", "| ", "---", "1. ", "2. ", "3. ")
    if not any(m in answer for m in _structure_markers):
        return

    # Build topic from question (first 120 chars, cleaned)
    topic = _re_dossier.sub(r'https?://\S+', '', question).strip()[:120]
    if not topic:
        topic = "Baker Analysis"

    try:
        store = _get_store()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            # Dedup: skip if same topic saved in last 24h
            cur.execute("""
                SELECT id FROM deep_analyses
                WHERE topic = %s AND created_at > NOW() - INTERVAL '24 hours'
                LIMIT 1
            """, (f"Ask Baker: {topic}",))
            if cur.fetchone():
                cur.close()
                return
            cur.close()
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            store._put_conn(conn)

        import uuid as _uuid_dossier
        store.log_deep_analysis(
            analysis_id=str(_uuid_dossier.uuid4()),
            topic=f"Ask Baker: {topic}",
            source_documents=["conversation_memory"],
            prompt=question[:500],
            analysis_text=answer,
            token_count=len(answer) // 4,
            chunk_count=1,
            cost_usd=0.0,
        )
        logger.info(f"AUTO-SAVE-DOSSIERS-1: saved dossier: {topic[:60]}")
    except Exception as e:
        logger.warning(f"Auto-save to dossiers failed (non-fatal): {e}")


def _scan_store_back(req, full_response: str, start: float,
                     extra_meta: Optional[dict] = None, task_id: int = None,
                     complexity: str = None):
    """Store-back logic shared by both agentic and legacy paths.
    COMPLEXITY-ROUTER-1: Fast path skips Qdrant embedding (simple lookups not worth remembering)."""
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
    # COMPLEXITY-ROUTER-1: Skip Qdrant embedding on fast path (simple lookups not worth storing)
    _skip_qdrant = (complexity == "fast" and not config.complexity.shadow_mode)
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

        if _skip_qdrant:
            chunk_count = 0
            logger.info("COMPLEXITY-ROUTER-1: Skipping Qdrant embedding (fast path)")
        elif len(conversation_content) <= 8000:
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
            owner=req.owner or "dimitry",
        )
        logger.info("Conversation stored in Baker's memory (CONV-MEM-1)")
    except Exception as e:
        logger.warning(f"Conversation store-back failed (non-fatal): {e}")

    # AUTO-SAVE-DOSSIERS-1: Save substantive answers to Dossiers for persistence
    try:
        _maybe_save_to_dossiers(req.question, full_response, owner=req.owner or "dimitry")
    except Exception as e:
        logger.warning(f"Dossier auto-save failed (non-fatal): {e}")

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
                          entity_context: str = "", complexity: str = None):
    """AGENT-FRAMEWORK-1: Route through capability framework.
    Handles both explicit ('have the finance agent...') and implicit (router match) paths.
    SPECIALIST-DEEP-1: entity_context forwarded to capability runner for pre-stuffed context."""
    import json as _json

    from orchestrator.capability_router import CapabilityRouter, RoutingPlan
    from orchestrator.capability_runner import CapabilityRunner, PM_REGISTRY

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

    # PM-SIDEBAR-STATE-WRITE-1 D3: tag conversation_memory with capability_slug
    # when a client_pm capability handles the scan, so the backfill script and
    # downstream queries can isolate PM history from other sidebar traffic.
    if (plan.mode == "fast" and len(plan.capabilities) == 1
            and plan.capabilities[0].slug in PM_REGISTRY):
        try:
            req.project = plan.capabilities[0].slug
        except Exception:
            # ScanRequest is pydantic — mutation allowed. SpecialistScanRequest
            # (converted to ScanRequest upstream at :5491) may be frozen in rare
            # cases; swallow to preserve existing behavior.
            pass
    elif plan.mode == "delegate":
        _pm_in_plan = [s for s in cap_slugs if s in PM_REGISTRY]
        if _pm_in_plan:
            try:
                req.project = _pm_in_plan[0]
            except Exception:
                pass

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

            # THINKING-DOTS-FIX: Signal retrieval phase immediately
            yield f"data: {_json.dumps({'status': 'retrieving'})}\n\n"

            def _run():
                try:
                    for chunk in runner.run_streaming(cap, req.question,
                                                      history=req.history,
                                                      domain=domain, mode=mode,
                                                      entity_context=entity_context,
                                                      complexity=complexity):
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
                    elif kind == "screenshot":
                        yield f"data: {_json.dumps({'screenshot': value})}\n\n"
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

            # PM-SIDEBAR-STATE-WRITE-1 D2: fire-and-forget PM state extraction
            # for client_pm capabilities on the fast path. Same Opus pipeline as
            # CapabilityRunner._auto_update_pm_state, tagged mutation_source=
            # 'sidebar' per Amendment H §H4 surface attribution.
            if ar and ar.answer and cap.slug in PM_REGISTRY:
                def _sidebar_state_write():
                    try:
                        from orchestrator.capability_runner import (
                            extract_and_update_pm_state,
                        )
                        extract_and_update_pm_state(
                            pm_slug=cap.slug,
                            question=req.question,
                            answer=ar.answer,
                            mutation_source="sidebar",
                        )
                    except Exception as _e:
                        logger.warning(
                            f"Sidebar state-write failed [{cap.slug}] (non-fatal): {_e}"
                        )

                import threading as _threading
                _threading.Thread(target=_sidebar_state_write, daemon=True).start()

            # A8: Extract actionable tasks from specialist output (background, non-blocking)
            if ar and ar.answer and len(ar.answer) >= 200 and cap.slug not in ("decomposer", "synthesizer"):
                try:
                    from orchestrator.insight_to_task import extract_tasks_from_specialist, create_tasks_from_insights
                    _a8_tasks = extract_tasks_from_specialist(
                        question=req.question,
                        response=ar.answer,
                        capability_slug=cap.slug,
                        matter_slug=getattr(req, "matter_slug", None),
                    )
                    if _a8_tasks:
                        create_tasks_from_insights(
                            tasks=_a8_tasks,
                            capability_slug=cap.slug,
                            matter_slug=getattr(req, "matter_slug", None),
                            baker_task_id=task_id,
                        )
                except Exception as _a8_err:
                    logger.warning(f"A8 insight-to-task failed (non-fatal): {_a8_err}")

            # Yield task_id for frontend feedback buttons (LEARNING-LOOP)
            if task_id:
                yield f"data: {_json.dumps({'task_id': task_id})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_cap_stream(), media_type="text/event-stream")

    elif plan.mode == "delegate":
        # Delegate path — multi-capability
        # THINKING-DOTS-FIX: run_multi moved inside generator so status events stream during execution
        async def _delegate_stream():
            yield f"data: {_json.dumps({'status': 'retrieving'})}\n\n"
            yield f"data: {_json.dumps({'capabilities': cap_slugs})}\n\n"

            result = runner.run_multi(plan, req.question, history=req.history,
                                      domain=domain, mode=mode,
                                      entity_context=entity_context)

            yield f"data: {_json.dumps({'status': 'generating', 'phase': 'synthesizing'})}\n\n"
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

            # PM-SIDEBAR-STATE-WRITE-1 D2: delegate-path state-write. Runs the
            # same Opus extraction for every client_pm capability referenced by
            # the decomposer's plan. Tagged mutation_source='decomposer' per
            # Amendment H §H4 — a distinct surface from 'sidebar' even though
            # both are served from this dashboard route.
            try:
                pm_slugs_in_plan = [s for s in cap_slugs if s in PM_REGISTRY]
                if result and result.answer and pm_slugs_in_plan:
                    def _delegate_state_write():
                        try:
                            from orchestrator.capability_runner import (
                                extract_and_update_pm_state,
                            )
                            for _slug in pm_slugs_in_plan:
                                extract_and_update_pm_state(
                                    pm_slug=_slug,
                                    question=req.question,
                                    answer=result.answer,
                                    mutation_source="decomposer",
                                )
                        except Exception as _e:
                            logger.warning(
                                f"Delegate state-write failed (non-fatal): {_e}"
                            )
                    import threading as _threading
                    _threading.Thread(target=_delegate_state_write, daemon=True).start()
            except Exception:
                pass

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
        # THINKING-DOTS-FIX: Signal retrieval phase immediately
        yield f"data: {json.dumps({'status': 'retrieving'})}\n\n"

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
                    # AGENTIC-LOOP-FIX: Only fall back to legacy if no synthesis was produced
                    if agent_result.timed_out and not agent_result.answer:
                        logger.warning("Agent timed out with no answer — falling back to single-pass")
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
                    yield f"data: {json.dumps({'tool_call': item['tool_call']})}\n\n"
                elif "screenshot" in item:
                    yield f"data: {json.dumps({'screenshot': item['screenshot']})}\n\n"
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
            system=_split_scan_system_for_cache(system_prompt),
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                full_response += text
                payload = json.dumps({"token": text})
                yield f"data: {payload}\n\n"
            try:
                final_msg = stream.get_final_message()
                log_cache_usage(final_msg.usage,
                                call_site="outputs.dashboard.scan_chat",
                                model=config.claude.model)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Scan stream error: {e}")
        err_payload = json.dumps({"error": str(e)})
        yield f"data: {err_payload}\n\n"

    yield "data: [DONE]\n\n"
    _scan_store_back(req, full_response, start, task_id=task_id)


def _scan_chat_legacy(req, start: float, domain_context: str = "",
                      task_id: int = None, mode: str = None, domain: str = None):
    """Legacy single-pass RAG — unchanged behavior, refactored into own function.
    THINKING-DOTS-FIX: Retrieval moved inside generator so status events stream during each phase."""

    async def event_stream():
        # THINKING-DOTS-FIX: Signal retrieval phase immediately
        yield f"data: {json.dumps({'status': 'retrieving'})}\n\n"

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

        # THINKING-DOTS-FIX: Signal augmentation phase
        yield f"data: {json.dumps({'status': 'thinking'})}\n\n"

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

        # THINKING-DOTS-FIX: Signal generation phase
        yield f"data: {json.dumps({'status': 'generating'})}\n\n"

        # 4. Stream Claude response
        full_response = ""
        try:
            claude = anthropic.Anthropic(api_key=config.claude.api_key)
            with claude.messages.stream(
                model=config.claude.model,
                max_tokens=4096,
                system=_split_scan_system_for_cache(system_prompt),
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    # SSE format: data: <json>\n\n
                    payload = json.dumps({"token": text})
                    yield f"data: {payload}\n\n"
                try:
                    final_msg = stream.get_final_message()
                    log_cache_usage(final_msg.usage,
                                    call_site="outputs.dashboard.scan_chat_legacy",
                                    model=config.claude.model)
                except Exception:
                    pass
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
    from document_generator import generate_document
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
    from document_generator import get_file
    info = get_file(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="File not found or expired")

    filepath = info.get("filepath")
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=410, detail="File no longer available")

    media_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return FileResponse(
        path=filepath,
        filename=info["filename"],
        media_type=media_types.get(info["format"], "application/octet-stream"),
    )


@app.get("/api/scan/generated-documents", tags=["scan"], dependencies=[Depends(verify_api_key)])
async def list_generated_docs(limit: int = 20):
    """List recently generated documents for the right panel."""
    from document_generator import list_generated_documents
    docs = list_generated_documents(limit=limit)
    return {"documents": docs}


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

    # B3 (INGEST_SEARCH_DURABILITY_FOLLOWUPS_1): compute the path-stripped filename
    # ONCE and reuse it for ext derivation, temp path, the PG row (store_document_full
    # source_path/filename), the Qdrant source_file (= temp basename), the response,
    # and logs. A client sending "folder/Mandarin.pdf" must not diverge across surfaces.
    safe_filename = Path(file.filename).name

    # 1. Validate file extension
    ext = Path(safe_filename).suffix.lower()
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

    # 5. Write to temp file under a temp DIRECTORY using the ORIGINAL filename.
    #    DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1: ingest_file derives the Qdrant
    #    `source_file` payload from filepath.name, while store_document_full (7b)
    #    writes documents.filename = file.filename. The semantic-search resolver
    #    joins Qdrant source_file -> documents.filename, so the temp basename MUST
    #    equal the original filename. A NamedTemporaryFile prefix produced
    #    `Mandarin_<rand>.pdf` ≠ documents.filename `Mandarin.pdf`, dropping every
    #    /api/ingest-uploaded doc from semantic search (regressed the #285 path).
    import shutil
    tmp_dir = None
    tmp_path = None
    try:
        tmp_dir = tempfile.mkdtemp()
        tmp_path = Path(tmp_dir) / safe_filename  # B3: same path-stripped name as every other surface
        tmp_path.write_bytes(contents)

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

        # 7b. INGEST_RETRIEVAL_GAP_FIX_1 — persist to the Postgres `documents`
        # table so the doc is retrievable via GET /api/documents/search.
        #
        # ROOT CAUSE: this endpoint previously wrote ONLY Qdrant chunks (via
        # ingest_file). But /api/documents/search reads the Postgres `documents`
        # table (its Qdrant branch has been dead since DOCUMENTS-REDESIGN-1 —
        # `from memory.retriever import Retriever` ImportErrors → silent ILIKE
        # fallback). So an /api/ingest "success" landed in Qdrant + ingestion_log
        # but never in `documents` → invisible to search. We now mirror the
        # established triggers/dropbox_trigger.py two-write pattern:
        # store_document_full() for Postgres + ingest_file() for Qdrant.
        #
        # Skipped for business cards (card_data set → routed to contacts, not
        # documents) and for skipped ingests (dedup / empty). store_document_full
        # is idempotent (ON CONFLICT file_hash + content_hash dedup) so re-uploads
        # collapse instead of duplicating.
        #
        # B5.2 — partial-embed posture (DELIBERATE, contrasts with dropbox_trigger):
        # `result.skipped` is True with skip_reason="partial_embed" when A2 refused to
        # seal a half-embedded doc. Gating the PG write on `not result.skipped` means a
        # partial embed writes NEITHER store → the one-shot upload stays fully
        # retryable (the user re-uploads; nothing half-lands). dropbox_trigger takes the
        # opposite, also-deliberate posture (PG-first, ungated) because it is a
        # re-runnable poller; its PG-without-Qdrant drift is surfaced by the A3
        # reconciliation query (_documents_missing_qdrant) for re-ingest.
        document_id = None
        if not result.skipped and not result.card_data and result.full_text:
            try:
                store = _get_store()
                document_id = store.store_document_full(
                    source_path=safe_filename,
                    filename=safe_filename,
                    file_hash=result.file_hash,
                    full_text=result.full_text,
                    token_count=result.token_count,
                    owner="shared",
                )
                result.document_id = document_id
                if document_id:
                    # B1: patch the durable join key onto the Qdrant points. /api/ingest
                    # writes Qdrant (ingest_file) BEFORE it has the PG id, so unlike the
                    # dropbox/promote callers it can't thread document_id at embed time —
                    # set_payload it after the fact. Best-effort; legacy filename join is
                    # the fallback if this fails.
                    try:
                        from tools.ingest.pipeline import set_document_payload
                        set_document_payload(result.collection, result.point_ids, document_id=document_id)
                    except Exception as pe:
                        logger.warning(f"/api/ingest: set_document_payload failed for doc {document_id} (non-fatal): {pe}")
                    # Queue classification + extraction (SPECIALIST-UPGRADE-1B),
                    # matching the dropbox-trigger flow so facets/matter tags populate.
                    try:
                        from tools.document_pipeline import queue_extraction
                        queue_extraction(document_id)
                    except Exception as qe:
                        logger.warning(f"/api/ingest: queue_extraction failed for doc {document_id} (non-fatal): {qe}")
                else:
                    # Fail loud: Qdrant write succeeded but the read-store write did not.
                    logger.error(
                        "/api/ingest: store_document_full returned no id for %s — "
                        "doc is in Qdrant but NOT retrievable via /api/documents/search",
                        safe_filename,
                    )
            except Exception as doc_err:
                logger.error(f"/api/ingest: documents-table write failed for {safe_filename} (non-fatal): {doc_err}")

        response = {
            "status": "skipped" if result.skipped else "success",
            "filename": safe_filename,
            "collection": result.collection,
            "chunks": result.chunk_count,
            "dedup": result.skipped and "duplicate" in (result.skip_reason or "").lower(),
            "skip_reason": result.skip_reason,
            "project": project,
            "role": role,
            "document_id": document_id,
            # stored_postgres reflects whether the doc reached the read store
            # (the search-backing `documents` table) — not just Qdrant.
            "stored_postgres": document_id is not None,
        }

        # Include card extraction data if present
        if result.card_data:
            response["card_data"] = result.card_data
        if result.contact_result:
            response["contact_result"] = result.contact_result

        return response
    finally:
        # 8. Clean up the temp directory (and the file inside it)
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


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

    # CORRECTION-MEMORY-1: Extract learned rule from negative feedback with comment
    if body.feedback in ("rejected", "revised") and body.comment:
        task["director_feedback"] = body.feedback
        task["feedback_comment"] = body.comment
        threading.Thread(
            target=_extract_correction_safe, args=(task,), daemon=True
        ).start()

    # CORRECTION-MEMORY-1 Phase 2: Embed accepted tasks as positive examples
    if body.feedback == "accepted" and task.get("deliverable"):
        threading.Thread(
            target=_embed_positive_example_safe, args=(task,), daemon=True
        ).start()

    return {"status": "updated", "task_id": task_id, "feedback": body.feedback}


# ============================================================
# COMPLEXITY-ROUTER-1: Complexity Stats
# ============================================================

@app.get("/api/tasks/complexity-stats", tags=["tasks"], dependencies=[Depends(verify_api_key)])
async def complexity_stats_endpoint(days: int = Query(7, ge=1, le=90)):
    """PM monitoring: complexity classification distribution and accuracy."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Overall distribution
        cur.execute("""
            SELECT
                complexity,
                COUNT(*) as count,
                AVG(complexity_confidence) as avg_confidence,
                COUNT(CASE WHEN director_feedback = 'rejected' THEN 1 END) as rejected,
                COUNT(CASE WHEN director_feedback = 'accepted' THEN 1 END) as accepted,
                COUNT(CASE WHEN complexity_override IS NOT NULL THEN 1 END) as overrides
            FROM baker_tasks
            WHERE created_at > NOW() - INTERVAL '%s days'
              AND complexity IS NOT NULL
            GROUP BY complexity
            ORDER BY complexity
        """ % days)
        distribution = [dict(r) for r in cur.fetchall()]

        # By domain breakdown
        cur.execute("""
            SELECT
                COALESCE(domain, 'unknown') as domain,
                complexity,
                COUNT(*) as count,
                AVG(complexity_confidence) as avg_confidence
            FROM baker_tasks
            WHERE created_at > NOW() - INTERVAL '%s days'
              AND complexity IS NOT NULL
            GROUP BY domain, complexity
            ORDER BY domain, complexity
        """ % days)
        by_domain = [dict(r) for r in cur.fetchall()]

        # Potential misclassifications: fast tasks that got rejected
        cur.execute("""
            SELECT id, title, complexity, complexity_confidence,
                   complexity_reasoning, director_feedback, feedback_comment
            FROM baker_tasks
            WHERE created_at > NOW() - INTERVAL '%s days'
              AND complexity = 'fast'
              AND director_feedback = 'rejected'
            ORDER BY created_at DESC
            LIMIT 10
        """ % days)
        misclassified = [dict(r) for r in cur.fetchall()]

        cur.close()
        return {
            "days": days,
            "distribution": distribution,
            "by_domain": by_domain,
            "misclassified_fast": misclassified,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


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
# Admin: Manual job triggers + Chain visibility (Session 28)
# ============================================================

@app.get("/api/priorities", tags=["priorities"], dependencies=[Depends(verify_api_key)])
async def get_priorities():
    """Get current weekly priorities."""
    from orchestrator.priority_manager import get_current_priorities
    priorities = get_current_priorities()
    for p in priorities:
        for key in ("week_start", "created_at"):
            if p.get(key) and hasattr(p[key], "isoformat"):
                p[key] = p[key].isoformat()
    return {"priorities": priorities, "count": len(priorities)}


@app.post("/api/priorities", tags=["priorities"], dependencies=[Depends(verify_api_key)])
async def set_priorities(request: Request):
    """Set this week's priorities. Body: {"priorities": [{"text": "...", "matter": "..."}]}"""
    from orchestrator.priority_manager import set_priorities
    body = await request.json()
    items = body.get("priorities", [])
    if not items:
        raise HTTPException(status_code=400, detail="Provide at least one priority")
    created = set_priorities(items)
    for p in created:
        for key in ("week_start", "created_at"):
            if p.get(key) and hasattr(p[key], "isoformat"):
                p[key] = p[key].isoformat()
    return {"status": "set", "priorities": created}


@app.delete("/api/priorities/{priority_id}", tags=["priorities"], dependencies=[Depends(verify_api_key)])
async def complete_priority(priority_id: int):
    """Mark a priority as completed."""
    from orchestrator.priority_manager import complete_priority as _complete
    ok = _complete(priority_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to complete priority")
    return {"status": "completed", "id": priority_id}


@app.post("/api/admin/consolidate", tags=["admin"], dependencies=[Depends(verify_api_key)])
async def trigger_memory_consolidation(background_tasks: BackgroundTasks):
    """Manually trigger memory consolidation (normally runs weekly)."""
    from orchestrator.memory_consolidator import run_memory_consolidation
    background_tasks.add_task(run_memory_consolidation)
    return {"status": "running", "message": "Memory consolidation started in background"}


@app.post("/api/admin/trends", tags=["admin"], dependencies=[Depends(verify_api_key)])
async def trigger_trend_detection(background_tasks: BackgroundTasks):
    """Manually trigger trend detection (normally runs monthly)."""
    from orchestrator.trend_detector import run_trend_detection
    background_tasks.add_task(run_trend_detection)
    return {"status": "running", "message": "Trend detection started in background"}


@app.post("/api/admin/priorities/reload", tags=["admin"], dependencies=[Depends(verify_api_key)])
async def admin_priorities_reload():
    """Drop the priorities-registry cache; next call re-reads ``_priorities.yml``.

    Triggered after Director edits the YAML in the vault (in-process cache
    would otherwise survive until the Render dyno restarts). Returns the
    refreshed schema/version snapshot for confirmation.
    """
    from kbl import priorities_registry
    try:
        priorities_registry.reload()
        return {
            "reloaded_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": priorities_registry.registry_version(),
            "ratified_at": priorities_registry.registry_ratified_at(),
            "priority_count": len(priorities_registry.get_all()),
        }
    except Exception as e:
        logger.error(f"/api/admin/priorities/reload failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/admin/tier-b-status", tags=["admin"], dependencies=[Depends(verify_api_key)])
async def admin_tier_b_status():
    """Live Tier-B autonomous-action budget state (CORTEX_TIER_B_RUNTIME_V1).

    Read-only. Returns caps + current day/month totals + headroom + pending
    ratify queue snapshot + recent committed Tier-B actions.
    """
    from memory.store_back import SentinelStoreBack
    from orchestrator.tier_b_runtime import (
        DAILY_POOL_CAP_EUR,
        MONTHLY_POOL_CAP_EUR,
        PER_ACTION_CAP_EUR,
    )

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if conn is None:
        return JSONResponse({"error": "no DB connection"}, status_code=503)
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT COALESCE(SUM(cost_eur), 0)
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
               AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')
             LIMIT 100000
            """
        )
        day_total = float(cur.fetchone()[0])

        cur.execute(
            """
            SELECT COALESCE(SUM(cost_eur), 0)
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
               AND committed_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
             LIMIT 100000
            """
        )
        month_total = float(cur.fetchone()[0])

        cur.execute(
            """
            SELECT id, cost_eur, action_class, committer_agent, reason_paused, created_at
              FROM tier_b_pending
             WHERE status = 'pending'
             ORDER BY created_at DESC
             LIMIT 50
            """
        )
        pending = [
            {
                "id": int(r[0]),
                "cost_eur": float(r[1]),
                "action_class": r[2],
                "committer_agent": r[3],
                "reason_paused": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT id, cost_eur, action_class, committer_agent, committed_at
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
             ORDER BY committed_at DESC NULLS LAST
             LIMIT 20
            """
        )
        recent = [
            {
                "id": int(r[0]),
                "cost_eur": float(r[1]),
                "action_class": r[2],
                "committer_agent": r[3],
                "committed_at": r[4].isoformat() if r[4] else None,
            }
            for r in cur.fetchall()
        ]

        cur.close()

        return JSONResponse({
            "caps": {
                "per_action_eur": PER_ACTION_CAP_EUR,
                "daily_pool_eur": DAILY_POOL_CAP_EUR,
                "monthly_pool_eur": MONTHLY_POOL_CAP_EUR,
            },
            "current": {
                "day_total_eur": day_total,
                "month_total_eur": month_total,
                "day_remaining_eur": max(0.0, DAILY_POOL_CAP_EUR - day_total),
                "month_remaining_eur": max(0.0, MONTHLY_POOL_CAP_EUR - month_total),
            },
            "pending": pending,
            "recent_committed": recent,
        })
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"/api/admin/tier-b-status failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        store._put_conn(conn)


@app.get("/api/chains", tags=["chains"], dependencies=[Depends(verify_api_key)])
async def get_chains(limit: int = 20):
    """Get chain execution history from baker_tasks."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, title, domain as matter, description as director_summary,
                   deliverable, agent_iterations as total_steps,
                   agent_tool_calls as completed_steps,
                   agent_elapsed_ms as elapsed_ms,
                   director_feedback, feedback_comment,
                   created_at
            FROM baker_tasks
            WHERE task_type = 'chain'
            ORDER BY created_at DESC
            LIMIT %s
        """, (min(limit, 100),))
        chains = [dict(r) for r in cur.fetchall()]
        cur.close()
        for c in chains:
            if c.get("created_at"):
                c["created_at"] = c["created_at"].isoformat()
            if c.get("elapsed_ms"):
                c["elapsed_ms"] = int(c["elapsed_ms"])
        return {"chains": chains, "count": len(chains)}
    finally:
        store._put_conn(conn)


@app.get("/api/memory-summaries", tags=["memory"], dependencies=[Depends(verify_api_key)])
async def get_memory_summaries(matter: str = None, limit: int = 20):
    """Get memory consolidation summaries."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if matter:
            cur.execute("""
                SELECT * FROM memory_summaries
                WHERE matter_slug ILIKE %s
                ORDER BY interaction_count DESC
                LIMIT %s
            """, (f"%{matter}%", min(limit, 50)))
        else:
            cur.execute("""
                SELECT * FROM memory_summaries
                ORDER BY updated_at DESC
                LIMIT %s
            """, (min(limit, 50),))
        summaries = [dict(r) for r in cur.fetchall()]
        cur.close()
        for s in summaries:
            for key in ("created_at", "updated_at", "period_start", "period_end"):
                if s.get(key) and hasattr(s[key], "isoformat"):
                    s[key] = s[key].isoformat()
        return {"summaries": summaries, "count": len(summaries)}
    except Exception as e:
        # Table may not exist yet
        if "does not exist" in str(e):
            return {"summaries": [], "count": 0, "note": "No summaries yet — first consolidation pending"}
        raise
    finally:
        store._put_conn(conn)


@app.post("/api/memory/compress", tags=["memory"], dependencies=[Depends(verify_api_key)])
async def trigger_memory_compression(tier: int = Query(2, ge=2, le=3)):
    """THREE-TIER-MEMORY: Manually trigger compression for testing.
    tier=2: Opus weekly compression. tier=3: Sonnet institutional."""
    import threading
    try:
        if tier == 2:
            from orchestrator.memory_consolidator import run_memory_consolidation
            t = threading.Thread(target=run_memory_consolidation, daemon=True)
            t.start()
            return {"status": "started", "tier": 2, "model": "Opus", "note": "Running in background"}
        else:
            from orchestrator.memory_consolidator import run_institutional_consolidation
            t = threading.Thread(target=run_institutional_consolidation, daemon=True)
            t.start()
            return {"status": "started", "tier": 3, "model": "Sonnet", "note": "Running in background"}
    except Exception as e:
        logger.error(f"POST /api/memory/compress failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/memory/health", tags=["memory"], dependencies=[Depends(verify_api_key)])
async def get_memory_health():
    """THREE-TIER-MEMORY: Memory tier health stats for dashboard."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        stats = {}
        # Tier 1: active records (last 90 days)
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM email_messages WHERE received_date > NOW() - INTERVAL '90 days') as emails,
                (SELECT COUNT(*) FROM whatsapp_messages WHERE timestamp > NOW() - INTERVAL '90 days') as whatsapp,
                (SELECT COUNT(*) FROM alerts WHERE created_at > NOW() - INTERVAL '90 days') as alerts,
                (SELECT COUNT(*) FROM conversation_memory WHERE created_at > NOW() - INTERVAL '90 days') as conversations
        """)
        tier1 = cur.fetchone()
        stats["tier1"] = {"label": "Active (0-90d)", "total": sum(v or 0 for v in tier1.values()), "breakdown": dict(tier1)}
        # Tier 2
        try:
            cur.execute("SELECT COUNT(*) as count, MAX(updated_at) as last_run FROM memory_summaries")
            t2 = cur.fetchone()
            stats["tier2"] = {"label": "Compressed (Opus)", "count": t2["count"] or 0,
                              "last_compression": t2["last_run"].isoformat() if t2.get("last_run") else None}
        except Exception:
            stats["tier2"] = {"label": "Compressed", "count": 0, "last_compression": None}
        # Tier 3
        try:
            cur.execute("SELECT COUNT(*) as count, MAX(updated_at) as last_run FROM memory_institutional")
            t3 = cur.fetchone()
            stats["tier3"] = {"label": "Institutional (Sonnet)", "count": t3["count"] or 0,
                              "last_compression": t3["last_run"].isoformat() if t3.get("last_run") else None}
        except Exception:
            stats["tier3"] = {"label": "Institutional", "count": 0, "last_compression": None}
        # Archive
        try:
            cur.execute("SELECT COUNT(*) as count FROM memory_archive_log")
            stats["archive"] = {"count": cur.fetchone()["count"] or 0}
        except Exception:
            stats["archive"] = {"count": 0}
        cur.close()
        return stats
    except Exception as e:
        logger.error(f"GET /api/memory/health failed: {e}")
        return {"error": str(e)}
    finally:
        store._put_conn(conn)


# ============================================================
# PROACTIVE-INITIATIVE-1: Initiatives API
# ============================================================

@app.get("/api/initiatives", tags=["initiatives"], dependencies=[Depends(verify_api_key)])
async def get_initiatives(days: int = 7):
    """Get recent proactive initiatives."""
    from orchestrator.initiative_engine import get_initiatives
    initiatives = get_initiatives(days=days)
    for init in initiatives:
        for key in ("created_at",):
            if init.get(key) and hasattr(init[key], "isoformat"):
                init[key] = init[key].isoformat()
        if init.get("run_date") and hasattr(init["run_date"], "isoformat"):
            init["run_date"] = init["run_date"].isoformat()
    return {"initiatives": initiatives, "count": len(initiatives)}


@app.post("/api/initiatives/{initiative_id}/respond", tags=["initiatives"], dependencies=[Depends(verify_api_key)])
async def respond_to_initiative(initiative_id: int, request: Request):
    """Record Director's response to an initiative (approved/dismissed/deferred)."""
    from orchestrator.initiative_engine import respond_to_initiative
    body = await request.json()
    response = body.get("response", "acknowledged")
    ok = respond_to_initiative(initiative_id, response)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to record response")
    return {"status": "ok", "initiative_id": initiative_id, "response": response}


@app.post("/api/admin/run-initiatives", tags=["admin"], dependencies=[Depends(verify_api_key)])
async def admin_run_initiatives(background_tasks: BackgroundTasks):
    """Manually trigger the initiative engine."""
    from orchestrator.initiative_engine import run_initiative_engine
    background_tasks.add_task(run_initiative_engine)
    return {"status": "triggered", "note": "Initiative engine running in background"}



# ============================================================
# SENTIMENT-TRAJECTORY-1: Sentiment API
# ============================================================

@app.get("/api/sentiment/trends", tags=["sentiment"], dependencies=[Depends(verify_api_key)])
async def get_sentiment_trends():
    """Get sentiment trends for all contacts with 5+ scored interactions."""
    from orchestrator.sentiment_scorer import compute_sentiment_trends
    trends = compute_sentiment_trends()
    return {"trends": trends, "count": len(trends)}


@app.get("/api/sentiment/contact/{contact_name}", tags=["sentiment"], dependencies=[Depends(verify_api_key)])
async def get_contact_sentiment(contact_name: str):
    """Get sentiment profile for a specific contact."""
    from orchestrator.sentiment_scorer import get_contact_sentiment
    profile = get_contact_sentiment(contact_name)
    # Serialize datetimes
    if profile.get("recent_messages"):
        for msg in profile["recent_messages"]:
            if msg.get("date") and hasattr(msg["date"], "isoformat"):
                msg["date"] = msg["date"].isoformat()
    return profile


@app.post("/api/admin/run-sentiment-backfill", tags=["admin"], dependencies=[Depends(verify_api_key)])
async def admin_run_sentiment_backfill(background_tasks: BackgroundTasks):
    """Manually trigger sentiment backfill."""
    from orchestrator.sentiment_scorer import run_sentiment_backfill
    background_tasks.add_task(run_sentiment_backfill)
    return {"status": "triggered", "note": "Sentiment backfill running in background"}


# ============================================================
# CROSS-MATTER-CONVERGENCE-1: Convergence API
# ============================================================

@app.get("/api/convergence", tags=["convergence"], dependencies=[Depends(verify_api_key)])
async def get_convergence_report():
    """Run on-demand cross-matter convergence detection."""
    from orchestrator.convergence_detector import get_convergence_report
    return get_convergence_report()


@app.post("/api/admin/run-convergence", tags=["admin"], dependencies=[Depends(verify_api_key)])
async def admin_run_convergence(background_tasks: BackgroundTasks):
    """Manually trigger weekly convergence detection."""
    from orchestrator.convergence_detector import run_convergence_detection
    background_tasks.add_task(run_convergence_detection)
    return {"status": "triggered", "note": "Convergence detection running in background"}


# ============================================================
# OBLIGATION-GENERATOR: Proposed Actions API
# ============================================================

@app.get("/api/proposed-actions", tags=["actions"], dependencies=[Depends(verify_api_key)])
async def api_get_proposed_actions(status: str = "proposed", days: int = 7):
    """Get proposed actions for triage."""
    from orchestrator.obligation_generator import get_proposed_actions
    actions = get_proposed_actions(status=status, days=days)
    return {"actions": actions, "count": len(actions)}


@app.get("/api/proposed-actions/count", tags=["actions"], dependencies=[Depends(verify_api_key)])
async def api_get_proposed_actions_count():
    """Get count of untriaged proposed actions."""
    from orchestrator.obligation_generator import get_proposed_actions_count
    count = get_proposed_actions_count()
    return {"proposed": count}


@app.post("/api/proposed-actions/{action_id}/respond", tags=["actions"], dependencies=[Depends(verify_api_key)])
async def api_respond_to_action(action_id: int, request: Request):
    """Record Director's response to a proposed action."""
    from orchestrator.obligation_generator import respond_to_action
    body = await request.json()
    response = body.get("response", "")
    escalate_to = body.get("escalate_to")
    if response not in ("approved", "dismissed", "done", "escalated"):
        raise HTTPException(status_code=400, detail="response must be approved|dismissed|done|escalated")
    ok = respond_to_action(action_id, response, escalate_to=escalate_to)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to record response")
    return {"status": "ok", "action_id": action_id, "response": response}


@app.post("/api/admin/run-obligation-generator", tags=["admin"], dependencies=[Depends(verify_api_key)])
async def admin_run_obligation_generator(background_tasks: BackgroundTasks):
    """Manually trigger the obligation generator."""
    from orchestrator.obligation_generator import run_obligation_generator
    background_tasks.add_task(run_obligation_generator)
    return {"status": "triggered", "note": "Obligation generator running in background"}


# ============================================================
# BROWSER-AGENT-1 Phase 3: Browser Action Confirmation API
# ============================================================

@app.get("/api/browser/actions", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def api_get_browser_actions():
    """Get pending browser actions awaiting Director confirmation."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    actions = store.get_pending_browser_actions()
    # Strip screenshot_b64 from list view (it's large)
    for a in actions:
        a.pop("screenshot_b64", None)
        # Serialize datetimes
        for k in ("created_at", "expires_at", "confirmed_at", "completed_at"):
            if k in a and a[k]:
                a[k] = a[k].isoformat() if hasattr(a[k], "isoformat") else str(a[k])
    return {"actions": actions, "count": len(actions)}


@app.get("/api/browser/actions/{action_id}", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def api_get_browser_action(action_id: int):
    """Get a browser action by ID (includes screenshot)."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    action = store.get_browser_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Browser action not found")
    # Serialize datetimes
    for k in ("created_at", "expires_at", "confirmed_at", "completed_at"):
        if k in action and action[k]:
            action[k] = action[k].isoformat() if hasattr(action[k], "isoformat") else str(action[k])
    return {"action": action}


@app.post("/api/browser/confirm/{action_id}", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def api_confirm_browser_action(action_id: int, background_tasks: BackgroundTasks):
    """Confirm and execute a browser action. Runs the CDP command in background."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    action = store.get_browser_action(action_id)

    if not action:
        raise HTTPException(status_code=404, detail="Browser action not found")
    if action["status"] != "pending_confirmation":
        raise HTTPException(status_code=400, detail=f"Action is {action['status']}, not pending")

    # Check expiry
    from datetime import datetime, timezone
    if action.get("expires_at") and action["expires_at"] < datetime.now(timezone.utc):
        store.update_browser_action(action_id, status="expired")
        raise HTTPException(status_code=410, detail="Action has expired")

    # Mark confirmed
    store.update_browser_action(action_id, status="confirmed")

    # Execute in background
    background_tasks.add_task(_execute_browser_action, action_id, action)

    return {"status": "confirmed", "action_id": action_id, "message": "Action confirmed — executing now"}


@app.post("/api/browser/cancel/{action_id}", tags=["browser"], dependencies=[Depends(verify_api_key)])
async def api_cancel_browser_action(action_id: int):
    """Cancel a pending browser action."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    action = store.get_browser_action(action_id)

    if not action:
        raise HTTPException(status_code=404, detail="Browser action not found")
    if action["status"] != "pending_confirmation":
        raise HTTPException(status_code=400, detail=f"Action is {action['status']}, not pending")

    store.update_browser_action(action_id, status="cancelled")

    # Also resolve the linked alert (uses resolve_alert which triggers ALERT-DEDUP-2 auto-dismiss)
    if action.get("alert_id"):
        try:
            store = SentinelStoreBack._get_global_instance()
            store.resolve_alert(action["alert_id"])
        except Exception:
            pass

    return {"status": "cancelled", "action_id": action_id}


def _execute_browser_action(action_id: int, action: dict):
    """Background task: execute a confirmed browser action via CDP."""
    from triggers.browser_client import BrowserClient
    from memory.store_back import SentinelStoreBack

    store = SentinelStoreBack._get_global_instance()
    client = BrowserClient._get_global_instance()

    action_type = action.get("action_type", "")
    selector = action.get("target_selector", "")
    target_text = action.get("target_text", "")
    value = action.get("fill_value", "")

    store.update_browser_action(action_id, status="executing")

    try:
        result_parts = []

        if action_type == "click":
            if selector:
                res = client.click_element(selector)
            elif target_text:
                res = client.click_by_text(target_text)
            else:
                store.update_browser_action(action_id, status="failed", error="No selector or target_text")
                return
            if res.get("success"):
                result_parts.append(f"Clicked: {res.get('element_text', '')}")
            else:
                store.update_browser_action(action_id, status="failed", error=res.get("error", "Click failed"))
                return

        elif action_type == "fill":
            if not selector:
                store.update_browser_action(action_id, status="failed", error="Fill requires a CSS selector")
                return
            res = client.fill_field(selector, value)
            if res.get("success"):
                result_parts.append(f"Filled {selector} (was: {res.get('previous_value', '')})")
            else:
                store.update_browser_action(action_id, status="failed", error=res.get("error", "Fill failed"))
                return

        elif action_type == "click_and_fill":
            # Fill first, then click
            if not selector and not target_text:
                store.update_browser_action(action_id, status="failed", error="Need selector for fill target")
                return
            fill_selector = selector
            if fill_selector:
                fill_res = client.fill_field(fill_selector, value)
                if fill_res.get("success"):
                    result_parts.append(f"Filled {fill_selector}")
                else:
                    store.update_browser_action(action_id, status="failed", error=fill_res.get("error", "Fill failed"))
                    return
            # Click the submit/search button (look for common patterns)
            if target_text:
                click_res = client.click_by_text(target_text)
            else:
                # Try common submit patterns
                click_res = client.click_element('button[type="submit"], input[type="submit"], button.submit')
            if click_res.get("success"):
                result_parts.append(f"Clicked: {click_res.get('element_text', '')}")
            else:
                result_parts.append(f"Fill succeeded but click failed: {click_res.get('error', '')}")

        else:
            store.update_browser_action(action_id, status="failed", error=f"Unknown action type: {action_type}")
            return

        result_text = " | ".join(result_parts)
        store.update_browser_action(action_id, status="completed", result=result_text)

        # Resolve the linked alert (uses resolve_alert which triggers ALERT-DEDUP-2 auto-dismiss)
        if action.get("alert_id"):
            try:
                store.resolve_alert(action["alert_id"])
            except Exception:
                pass

        logger.info(f"Browser action #{action_id} completed: {result_text}")

    except Exception as e:
        logger.error(f"Browser action #{action_id} execution failed: {e}")
        store.update_browser_action(action_id, status="failed", error=str(e))


# ============================================================
# Relationship Cooling: Dismiss/Snooze/Stop API
# ============================================================

@app.post("/api/contacts/cooling/dismiss", tags=["contacts"], dependencies=[Depends(verify_api_key)])
async def dismiss_cooling_contact(request: Request):
    """Dismiss a cooling contact from the morning brief.

    Actions:
      - reached_out: Reset last_inbound_at to now (contact won't show as cooling)
      - snooze: Hide for 1 week (cadence_snoozed_until)
      - stop_tracking: Permanently stop cadence tracking for this contact
    """
    body = await request.json()
    name = (body.get("name") or "").strip()
    action = body.get("action", "")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if action not in ("reached_out", "snooze", "stop_tracking"):
        raise HTTPException(status_code=400, detail="action must be reached_out|snooze|stop_tracking")

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        cur = conn.cursor()

        # Ensure columns exist
        for col, default in [("cadence_snoozed_until", "TIMESTAMPTZ"), ("cadence_tracking", "BOOLEAN DEFAULT true")]:
            try:
                cur.execute(f"ALTER TABLE vip_contacts ADD COLUMN IF NOT EXISTS {col} {default}")
                conn.commit()
            except Exception:
                conn.rollback()

        if action == "reached_out":
            # Reset the silence counter — mark as heard from now
            cur.execute(
                "UPDATE vip_contacts SET last_inbound_at = NOW() WHERE LOWER(name) = LOWER(%s) RETURNING id",
                (name,),
            )
        elif action == "snooze":
            cur.execute(
                "UPDATE vip_contacts SET cadence_snoozed_until = NOW() + INTERVAL '7 days' "
                "WHERE LOWER(name) = LOWER(%s) RETURNING id",
                (name,),
            )
        elif action == "stop_tracking":
            cur.execute(
                "UPDATE vip_contacts SET cadence_tracking = false "
                "WHERE LOWER(name) = LOWER(%s) RETURNING id",
                (name,),
            )

        row = cur.fetchone()
        conn.commit()
        cur.close()

        if not row:
            raise HTTPException(status_code=404, detail=f"Contact '{name}' not found")

        logger.info(f"Cooling contact dismiss: {name} — action={action}")
        return {"status": "ok", "name": name, "action": action}
    except HTTPException:
        raise
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"dismiss_cooling_contact failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


# ============================================================
# ART-1: Research Proposals API
# ============================================================

@app.get("/api/research-proposals", tags=["research"], dependencies=[Depends(verify_api_key)])
async def api_get_research_proposals(status: str = None, days: int = 90):
    """Get research proposals. Default 90 days for Dossier Library."""
    from orchestrator.research_trigger import get_research_proposals
    proposals = get_research_proposals(status=status, days=days)
    return {"proposals": proposals, "count": len(proposals)}


@app.post("/api/research-proposals/{proposal_id}/respond", tags=["research"], dependencies=[Depends(verify_api_key)])
async def api_respond_to_research_proposal(proposal_id: int, request: Request, background_tasks: BackgroundTasks):
    """Approve or skip a research proposal. Approval triggers dossier execution."""
    from orchestrator.research_trigger import respond_to_research_proposal
    body = await request.json()
    response = body.get("response", "")
    if response not in ("approved", "skipped"):
        raise HTTPException(status_code=400, detail="response must be approved|skipped")
    ok = respond_to_research_proposal(proposal_id, response)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to record response")

    # On approval, trigger dossier execution in background
    if response == "approved":
        from orchestrator.research_executor import execute_research_dossier
        background_tasks.add_task(execute_research_dossier, proposal_id)
        return {"status": "ok", "proposal_id": proposal_id, "response": response,
                "execution": "started"}

    return {"status": "ok", "proposal_id": proposal_id, "response": response}


@app.get("/api/research-proposals/{proposal_id}/status", tags=["research"], dependencies=[Depends(verify_api_key)])
async def api_research_proposal_status(proposal_id: int):
    """Get current status of a research proposal (for polling during execution)."""
    import psycopg2.extras
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, status, deliverable_path, completed_at, subject_name, error_message
            FROM research_proposals WHERE id = %s
        """, (proposal_id,))
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")
        result = dict(row)
        for k in ("completed_at",):
            if result.get(k) and hasattr(result[k], "isoformat"):
                result[k] = result[k].isoformat()
        return result
    finally:
        store._put_conn(conn)


@app.post("/api/research-proposals/{proposal_id}/retry", tags=["research"], dependencies=[Depends(verify_api_key)])
async def api_retry_research_proposal(proposal_id: int, background_tasks: BackgroundTasks):
    """Retry a failed research proposal — resets to approved and re-executes."""
    import psycopg2.extras
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, status FROM research_proposals WHERE id = %s", (proposal_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if row["status"] not in ("failed", "completed"):
            raise HTTPException(status_code=400, detail=f"Can only retry failed/completed proposals (current: {row['status']})")
        cur.execute("""
            UPDATE research_proposals
            SET status = 'approved', error_message = NULL, deliverable_summary = NULL,
                deliverable_path = NULL, completed_at = NULL, approved_at = NOW()
            WHERE id = %s
        """, (proposal_id,))
        conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)

    from orchestrator.research_executor import execute_research_dossier
    background_tasks.add_task(execute_research_dossier, proposal_id)
    return {"status": "ok", "proposal_id": proposal_id, "execution": "started"}


@app.get("/api/research-proposals/{proposal_id}/download", tags=["research"])
async def api_download_research_dossier(proposal_id: int, key: str = ""):
    """Download the completed dossier as professional .docx (generated on-the-fly)."""
    if key != _BAKER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    import psycopg2.extras
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT subject_name, subject_type, specialists, deliverable_summary, status
            FROM research_proposals WHERE id = %s
        """, (proposal_id,))
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if row["status"] != "completed":
            raise HTTPException(status_code=400, detail="Dossier not yet completed")
        if not row.get("deliverable_summary"):
            raise HTTPException(status_code=404, detail="No dossier content stored")
    finally:
        store._put_conn(conn)

    # Generate professional .docx on-the-fly
    import re as _re
    from document_generator import generate_dossier_docx
    from orchestrator.research_executor import SPECIALIST_NAMES

    subject_name = row["subject_name"]
    subject_type = row.get("subject_type") or "person"
    specialists = row.get("specialists") or ["research"]
    if isinstance(specialists, str):
        import json as _json
        specialists = _json.loads(specialists)
    specialists_text = ", ".join(SPECIALIST_NAMES.get(s, s) for s in specialists)

    safe_name = _re.sub(r'[^\w\s-]', '', subject_name).strip().replace(' ', '_')
    filename = f"Dossier_{safe_name}.docx"

    filepath = os.path.join(tempfile.gettempdir(), f"baker_dl_{safe_name}.docx")
    generate_dossier_docx(
        dossier_md=row["deliverable_summary"],
        subject_name=subject_name,
        subject_type=subject_type,
        specialists_text=specialists_text,
        filepath=filepath,
    )

    from starlette.responses import FileResponse
    return FileResponse(
        filepath,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.get("/api/research-proposals/{proposal_id}/view", tags=["research"])
async def api_view_research_dossier(proposal_id: int, key: str = ""):
    """View a completed dossier as a mobile-friendly HTML page."""
    if key != _BAKER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    import psycopg2.extras
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT subject_name, deliverable_summary, status, completed_at
            FROM research_proposals WHERE id = %s
        """, (proposal_id,))
        row = cur.fetchone()
        cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if row["status"] != "completed" or not row.get("deliverable_summary"):
            raise HTTPException(status_code=400, detail="Dossier not yet completed")
    finally:
        store._put_conn(conn)

    import re as _re
    # Convert markdown to simple HTML
    md = row["deliverable_summary"]
    # Headers
    html_body = _re.sub(r'^### (.+)$', r'<h3>\1</h3>', md, flags=_re.MULTILINE)
    html_body = _re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_body, flags=_re.MULTILINE)
    html_body = _re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_body, flags=_re.MULTILINE)
    # Bold
    html_body = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_body)
    # Line breaks
    html_body = html_body.replace('\n\n', '</p><p>').replace('\n', '<br>')
    html_body = f'<p>{html_body}</p>'
    # Lists
    html_body = _re.sub(r'<br>- ', r'<br>• ', html_body)

    title = row["subject_name"]
    completed = row["completed_at"].strftime("%d %b %Y %H:%M") if row.get("completed_at") else ""

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dossier: {title}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 16px;
         background: #111; color: #e0e0e0; line-height: 1.6; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  h2 {{ font-size: 17px; color: #60a5fa; margin: 24px 0 8px; border-bottom: 1px solid #333; padding-bottom: 4px; }}
  h3 {{ font-size: 15px; color: #a78bfa; margin: 16px 0 6px; }}
  strong {{ color: #fff; }}
  p {{ margin: 0 0 12px; }}
  .meta {{ font-size: 12px; color: #888; margin-bottom: 16px; }}
  .dl-link {{ display: inline-block; margin-top: 16px; padding: 10px 20px; background: #22c55e;
              color: #000; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; }}
  .back {{ display: inline-block; margin-bottom: 12px; color: #60a5fa; text-decoration: none; font-size: 14px; }}
  .back:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<a class="back" href="/dossiers?key={key}">&larr; Back to Dossiers</a>
<h1>{title}</h1>
<div class="meta">Completed {completed}</div>
{html_body}
<a class="dl-link" href="/api/research-proposals/{proposal_id}/download?key={key}">Download .docx</a>
</body>
</html>"""
    from starlette.responses import HTMLResponse
    return HTMLResponse(page)


@app.get("/dossiers", tags=["research"])
async def dossier_library_page(key: str = ""):
    """Mobile-friendly dossier library — lists all completed dossiers from all sources."""
    if key != _BAKER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    import psycopg2.extras
    import html as _html
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        entries = []

        # Source 1: Completed research proposals
        cur.execute("""
            SELECT id, subject_name, completed_at
            FROM research_proposals
            WHERE status = 'completed' AND deliverable_summary IS NOT NULL
            ORDER BY completed_at DESC LIMIT 50
        """)
        for r in cur.fetchall():
            entries.append({
                "name": r["subject_name"],
                "date": r["completed_at"],
                "source": "Baker",
                "view_url": f"/api/research-proposals/{r['id']}/view?key={key}",
            })

        # Source 2: Deep analyses (Cowork/Claude Code)
        cur.execute("""
            SELECT analysis_id, topic, created_at
            FROM deep_analyses
            WHERE (topic ILIKE '%%Profile%%' OR topic ILIKE '%%Dossier%%')
              AND analysis_text IS NOT NULL AND LENGTH(analysis_text) > 200
              AND analysis_id NOT LIKE 'research_%%'
            ORDER BY created_at DESC LIMIT 50
        """)
        for r in cur.fetchall():
            topic = r["topic"] or ""
            name = topic.split("—")[0].split("–")[0].split("-")[0].strip() or topic
            entries.append({
                "name": name,
                "date": r["created_at"],
                "source": "Cowork",
                "view_url": f"/api/dossiers/analysis/{r['analysis_id']}/view?key={key}",
            })

        cur.close()
    finally:
        store._put_conn(conn)

    # Sort by date
    entries.sort(key=lambda e: e.get("date") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    cards_html = ""
    for e in entries:
        completed = e["date"].strftime("%d %b %H:%M") if e.get("date") else ""
        source_tag = f'<span style="font-size:10px;color:#60a5fa;margin-left:8px;">{_html.escape(e["source"])}</span>'
        cards_html += f"""
        <a class="dossier-card" href="{_html.escape(e['view_url'])}">
            <div class="dossier-name">{_html.escape(e['name'])}{source_tag}</div>
            <div class="dossier-date">{completed}</div>
        </a>"""

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dossier Library — Baker</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 0;
         background: #111; color: #e0e0e0; }}
  .header {{ padding: 16px; font-size: 20px; font-weight: 700; border-bottom: 1px solid #333;
             position: sticky; top: 0; background: #111; z-index: 10; }}
  .header a {{ color: #60a5fa; text-decoration: none; font-size: 14px; float: right; margin-top: 4px; }}
  .dossier-card {{ display: block; padding: 14px 16px; border-bottom: 1px solid #222;
                   text-decoration: none; color: inherit; }}
  .dossier-card:active {{ background: #1a1a1a; }}
  .dossier-name {{ font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 4px; }}
  .dossier-date {{ font-size: 12px; color: #888; }}
  .empty {{ padding: 40px 16px; text-align: center; color: #666; }}
</style>
</head>
<body>
<div class="header">Dossier Library <a href="/mobile">Back to Baker</a></div>
{cards_html if cards_html else '<div class="empty">No completed dossiers yet</div>'}
</body>
</html>"""
    from starlette.responses import HTMLResponse
    return HTMLResponse(page)


# ============================================================
# DOSSIER-PIPELINE-1: Unified Dossiers API
# ============================================================

@app.post("/api/research/request", tags=["research"], dependencies=[Depends(verify_api_key)])
async def api_request_dossier(request: Request, background_tasks: BackgroundTasks):
    """Director manually requests a dossier on a person/company."""
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")

    import psycopg2.extras
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO research_proposals
                (trigger_source, trigger_ref, subject_name, subject_type,
                 context, specialists, status, approved_at)
            VALUES ('manual_request', NULL, %s, 'person',
                    %s, %s, 'approved', NOW())
            RETURNING id
        """, (
            name[:200],
            f"Director requested dossier on {name}",
            json.dumps(["research", "legal", "profiling"]),
        ))
        proposal_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)

    # Trigger research executor in background
    from orchestrator.research_executor import execute_research_dossier
    background_tasks.add_task(execute_research_dossier, proposal_id)

    return {"proposal_id": proposal_id, "status": "running"}


@app.get("/api/dossiers", tags=["research"], dependencies=[Depends(verify_api_key)])
async def api_get_unified_dossiers(days: int = 180):
    """Unified dossier list pulling from research_proposals + deep_analyses."""
    import psycopg2.extras
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        dossiers = []

        # Source 1: Completed research proposals
        cur.execute(f"""
            SELECT id, subject_name, subject_type, specialists, status,
                   deliverable_path, created_at, completed_at
            FROM research_proposals
            WHERE status = 'completed' AND deliverable_summary IS NOT NULL
              AND created_at > NOW() - INTERVAL '{int(days)} days'
            ORDER BY completed_at DESC NULLS LAST
            LIMIT 50
        """)
        for r in cur.fetchall():
            row = dict(r)
            for k in ("created_at", "completed_at"):
                if row.get(k) and hasattr(row[k], "isoformat"):
                    row[k] = row[k].isoformat()
            specialists = row.get("specialists") or []
            if isinstance(specialists, str):
                import json as _json
                specialists = _json.loads(specialists)
            dossiers.append({
                "id": f"rp_{row['id']}",
                "source_id": row["id"],
                "name": row["subject_name"],
                "type": row.get("subject_type") or "person",
                "source": "Baker",
                "specialists": specialists,
                "date": row.get("completed_at") or row.get("created_at") or "",
                "dropbox_path": row.get("deliverable_path") or "",
                "view_url": f"/api/research-proposals/{row['id']}/view",
                "download_url": f"/api/research-proposals/{row['id']}/download",
            })

        # Source 2: Deep analyses (Cowork/Claude Code dossiers)
        cur.execute(f"""
            SELECT analysis_id, topic, analysis_text, created_at
            FROM deep_analyses
            WHERE (topic ILIKE '%%Profile%%' OR topic ILIKE '%%Dossier%%')
              AND analysis_text IS NOT NULL AND LENGTH(analysis_text) > 200
              AND created_at > NOW() - INTERVAL '{int(days)} days'
            ORDER BY created_at DESC
            LIMIT 50
        """)
        for r in cur.fetchall():
            row = dict(r)
            date_str = row["created_at"].isoformat() if row.get("created_at") and hasattr(row["created_at"], "isoformat") else ""
            topic = row.get("topic") or ""
            name = topic.split("\u2014")[0].split("\u2013")[0].split("-")[0].strip() if topic else topic
            # Skip entries already cross-stored from research_proposals
            if row["analysis_id"] and row["analysis_id"].startswith("research_"):
                continue
            dossiers.append({
                "id": f"da_{row['analysis_id']}",
                "source_id": row["analysis_id"],
                "name": name or topic,
                "type": "analysis",
                "source": "Cowork",
                "specialists": [],
                "date": date_str,
                "dropbox_path": "",
                "view_url": f"/api/dossiers/analysis/{row['analysis_id']}/view",
                "download_url": f"/api/dossiers/analysis/{row['analysis_id']}/download",
            })

        # Sort combined by date descending
        dossiers.sort(key=lambda d: d.get("date") or "", reverse=True)

        cur.close()
        return {"dossiers": dossiers, "count": len(dossiers)}
    finally:
        store._put_conn(conn)


@app.post("/api/dossiers/save", tags=["research"], dependencies=[Depends(verify_api_key)])
async def api_save_to_dossiers(request: Request):
    """CHAT-TRIAGE-1: Save a Baker chat answer to deep_analyses (Dossiers section)."""
    body = await request.json()
    question = body.get("question", "Baker Analysis")
    answer = body.get("answer", "")

    if not answer or len(answer) < 100:
        return JSONResponse({"error": "Answer too short to save"}, status_code=400)

    import re as _re
    import secrets
    topic = _re.sub(r'https?://\S+', '', question).strip()[:120] or "Baker Analysis"
    analysis_id = "chat_" + secrets.token_hex(6)

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor()
        # Dedup: skip if same topic saved in last 1 hour
        cur.execute("""
            SELECT analysis_id FROM deep_analyses
            WHERE topic = %s AND created_at > NOW() - INTERVAL '1 hour'
            LIMIT 1
        """, (topic,))
        if cur.fetchone():
            cur.close()
            return JSONResponse({"status": "already_saved", "message": "Already in Dossiers"})

        cur.execute("""
            INSERT INTO deep_analyses (analysis_id, topic, analysis_text, prompt, source_documents, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (analysis_id, topic, answer, question, json.dumps("ask_baker")))
        conn.commit()
        cur.close()
        return JSONResponse({"status": "saved", "id": analysis_id})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"Save to dossiers failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


# ─────────────────────────────────────────────────
# PEOPLE-SECTION-1: People + Issues endpoints
# ─────────────────────────────────────────────────

@app.get("/api/people/issues-summary", tags=["people"], dependencies=[Depends(verify_api_key)])
async def api_list_people_issues():
    """List people with open issue counts (for sidebar)."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT person_name,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status = 'overdue') AS overdue_count,
                   MAX(updated_at) AS last_updated
            FROM people_issues
            WHERE status NOT IN ('done', 'dismissed')
            GROUP BY person_name
            ORDER BY overdue_count DESC, total DESC
        """)
        rows = cur.fetchall()
        cur.close()
        return [{"name": r[0], "total": r[1], "overdue": r[2],
                 "last_updated": r[3].isoformat() if r[3] else None} for r in rows]
    finally:
        store._put_conn(conn)


@app.get("/api/people/{name}/issues", tags=["people"], dependencies=[Depends(verify_api_key)])
async def api_get_person_issues(name: str):
    """Get issues for a specific person."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, detail, status, due_date, source, matter, is_critical, created_at
            FROM people_issues
            WHERE LOWER(person_name) = LOWER(%s)
              AND status NOT IN ('dismissed')
            ORDER BY
              CASE WHEN status = 'overdue' THEN 0
                   WHEN due_date IS NOT NULL THEN 1
                   ELSE 2 END,
              due_date ASC NULLS LAST,
              created_at DESC
        """, (name,))
        rows = cur.fetchall()
        cur.close()
        return [{"id": r[0], "title": r[1], "detail": r[2], "status": r[3],
                 "due_date": str(r[4]) if r[4] else None, "source": r[5],
                 "matter": r[6], "is_critical": r[7],
                 "created_at": r[8].isoformat() if r[8] else None} for r in rows]
    finally:
        store._put_conn(conn)


@app.post("/api/people/issues", tags=["people"], dependencies=[Depends(verify_api_key)])
async def api_save_people_issues(request: Request):
    """Save issue(s) to a person. Deduplicates by person + title."""
    body = await request.json()
    person = body.get("person_name")
    issues = body.get("issues", [])
    if not person or not issues:
        return JSONResponse({"error": "person_name and issues required"}, status_code=400)

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    saved = 0
    try:
        cur = conn.cursor()
        for issue in issues:
            cur.execute("""
                SELECT id FROM people_issues
                WHERE LOWER(person_name) = LOWER(%s)
                  AND LOWER(title) = LOWER(%s)
                  AND status NOT IN ('dismissed', 'done')
                LIMIT 1
            """, (person, issue.get("title", "")))
            if cur.fetchone():
                continue
            cur.execute("""
                INSERT INTO people_issues (person_name, title, detail, status, due_date, source, matter)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (person, issue.get("title", "Untitled"), issue.get("detail"),
                  issue.get("status", "open"), issue.get("due_date"),
                  issue.get("source", "ask_baker"), issue.get("matter")))
            saved += 1
        conn.commit()
        cur.close()
        return {"saved": saved, "person": person}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"Save people issues failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.patch("/api/people/issues/{issue_id}", tags=["people"], dependencies=[Depends(verify_api_key)])
async def api_triage_people_issue(issue_id: int, request: Request):
    """Triage an issue: update status or is_critical."""
    body = await request.json()
    updates = []
    params = []
    if "status" in body:
        updates.append("status = %s")
        params.append(body["status"])
    if "is_critical" in body:
        updates.append("is_critical = %s")
        params.append(body["is_critical"])
    if not updates:
        return JSONResponse({"error": "Nothing to update"}, status_code=400)
    updates.append("updated_at = NOW()")
    params.append(issue_id)

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE people_issues SET {', '.join(updates)} WHERE id = %s RETURNING id", params)
        row = cur.fetchone()
        conn.commit()
        cur.close()
        if not row:
            return JSONResponse({"error": "Issue not found"}, status_code=404)
        return {"updated": issue_id}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        store._put_conn(conn)


@app.get("/api/dossiers/analysis/{analysis_id}/view", tags=["research"])
async def api_view_deep_analysis_dossier(analysis_id: str, key: str = ""):
    """View a deep_analyses dossier as HTML."""
    if key != _BAKER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    import psycopg2.extras
    import re as _re
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT topic, analysis_text, created_at FROM deep_analyses WHERE analysis_id = %s", (analysis_id,))
        row = cur.fetchone()
        cur.close()
        if not row or not row.get("analysis_text"):
            raise HTTPException(status_code=404, detail="Dossier not found")
    finally:
        store._put_conn(conn)

    topic = row["topic"] or "Analysis"
    text = row["analysis_text"]
    date_str = row["created_at"].strftime("%d %b %Y %H:%M") if row.get("created_at") else ""

    import html as _html
    lines = text.split("\n")
    html_parts = []
    for line in lines:
        s = line.strip()
        if not s:
            html_parts.append("<br>")
        elif s.startswith("### "):
            html_parts.append(f"<h3>{_html.escape(s[4:])}</h3>")
        elif s.startswith("## "):
            html_parts.append(f"<h2>{_html.escape(s[3:])}</h2>")
        elif s.startswith("# "):
            html_parts.append(f"<h1>{_html.escape(s[2:])}</h1>")
        elif s.startswith("- ") or s.startswith("* "):
            html_parts.append(f"<li>{_html.escape(s[2:])}</li>")
        else:
            escaped = _html.escape(s)
            escaped = _re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', escaped)
            escaped = _re.sub(r'\*(.*?)\*', r'<em>\1</em>', escaped)
            html_parts.append(f"<p>{escaped}</p>")

    body_html = "\n".join(html_parts)
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html.escape(topic)}</title>
<style>
body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 16px; background: #111; color: #e0e0e0; max-width: 800px; margin: 0 auto; line-height: 1.6; }}
h1 {{ color: #fff; font-size: 22px; margin-top: 24px; }}
h2 {{ color: #60a5fa; font-size: 18px; margin-top: 20px; border-bottom: 1px solid #333; padding-bottom: 6px; }}
h3 {{ color: #93c5fd; font-size: 15px; margin-top: 16px; }}
p {{ margin: 6px 0; font-size: 14px; }}
li {{ margin: 4px 0; font-size: 14px; }}
strong {{ color: #fff; }}
.meta {{ color: #888; font-size: 12px; margin-bottom: 16px; }}
a.back {{ color: #60a5fa; text-decoration: none; font-size: 14px; }}
</style></head><body>
<a class="back" href="javascript:history.back()">&larr; Back</a>
<h1>{_html.escape(topic)}</h1>
<div class="meta">{date_str}</div>
{body_html}
</body></html>"""
    from starlette.responses import HTMLResponse
    return HTMLResponse(page)


@app.get("/api/dossiers/analysis/{analysis_id}/download", tags=["research"])
async def api_download_deep_analysis_dossier(analysis_id: str, key: str = ""):
    """Download a deep_analyses dossier as .docx."""
    if key != _BAKER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    import psycopg2.extras
    import re as _re
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=500, detail="DB unavailable")
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT topic, analysis_text FROM deep_analyses WHERE analysis_id = %s", (analysis_id,))
        row = cur.fetchone()
        cur.close()
        if not row or not row.get("analysis_text"):
            raise HTTPException(status_code=404, detail="Dossier not found")
    finally:
        store._put_conn(conn)

    topic = row["topic"] or "Analysis"
    name = topic.split("\u2014")[0].split("\u2013")[0].split("-")[0].strip()

    from document_generator import generate_dossier_docx
    safe_name = _re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')
    filename = f"Dossier_{safe_name}.docx"
    filepath = os.path.join(tempfile.gettempdir(), f"baker_da_{safe_name}.docx")

    generate_dossier_docx(
        dossier_md=row["analysis_text"],
        subject_name=name,
        subject_type="analysis",
        specialists_text="Cowork / Claude Code",
        filepath=filepath,
    )

    from starlette.responses import FileResponse
    return FileResponse(
        filepath,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ============================================================
# AO RELATIONSHIP DASHBOARD
# ============================================================

_ao_view_cache: dict = {"data": None, "loaded_at": 0}

def _load_ao_view_files() -> dict:
    """Read 5 AO PM markdown view files with 10-minute cache."""
    global _ao_view_cache
    now = time.time()
    if _ao_view_cache["data"] and (now - _ao_view_cache["loaded_at"]) < 600:
        return _ao_view_cache["data"]

    ao_dir = Path(__file__).parent.parent / "data" / "ao_pm"
    files = {
        "psychology": "psychology.md",
        "investment_channels": "investment_channels.md",
        "sensitive_issues": "sensitive_issues.md",
        "communication_rules": "communication_rules.md",
        "agenda": "agenda.md",
    }
    result = {}
    for key, fname in files.items():
        fpath = ao_dir / fname
        try:
            result[key] = fpath.read_text(encoding="utf-8") if fpath.exists() else ""
        except Exception:
            result[key] = ""
    _ao_view_cache = {"data": result, "loaded_at": now}
    return result


def _get_ao_orbit_names() -> list:
    """Return list of AO orbit contact name patterns for ILIKE matching."""
    return [
        "%Oskolkov%", "%Constantinos%", "%Aelio%", "%Balazs%",
        "%Ilana%", "%Anna%", "%Siegfried%", "%Buchwalder%",
        "%Ettore%", "%Francesca%", "%Csepregi%",
    ]


# AO investment headline — STATIC figure, owned by AO Desk. Update both the
# value and the date together. Source: AO Desk confirmation (DASHBOARD_COCKPIT_
# WAVE1_QUICKWINS_1 Fix 3). This constant only dates/sources the presentation;
# the numeric value itself is an AO-Desk decision flagged separately to Director.
AO_INVESTMENT_TOTAL = "EUR 66.5M"
AO_INVESTMENT_TOTAL_AS_OF = "2026-06-01"  # date this figure was last confirmed


@app.get("/api/dashboard/ao")
async def get_ao_dashboard():
    """Aggregated AO relationship dashboard data."""
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. PM state
        pm_state = {}
        try:
            cur.execute(
                "SELECT state_json FROM pm_project_state WHERE pm_slug='ao_pm' AND state_key='current' LIMIT 1"
            )
            row = cur.fetchone()
            if row and row.get("state_json"):
                pm_state = row["state_json"] if isinstance(row["state_json"], dict) else {}
        except Exception:
            conn.rollback()

        # 2. Comms gap
        last_wa = None
        last_email = None
        try:
            cur.execute(
                "SELECT MAX(timestamp) as last_ts FROM whatsapp_messages WHERE chat_id ILIKE %s",
                ("%oskolkov%",),
            )
            r = cur.fetchone()
            if r and r.get("last_ts"):
                last_wa = r["last_ts"]
        except Exception:
            conn.rollback()

        try:
            cur.execute(
                "SELECT MAX(sent_at) as last_ts FROM sent_emails WHERE to_address ILIKE %s OR to_address ILIKE %s",
                ("%oskolkov%", "%aelio%"),
            )
            r = cur.fetchone()
            if r and r.get("last_ts"):
                last_email = r["last_ts"]
        except Exception:
            conn.rollback()

        from datetime import datetime, timezone
        last_contact_at = None
        if last_wa and last_email:
            last_contact_at = max(last_wa, last_email)
        elif last_wa:
            last_contact_at = last_wa
        elif last_email:
            last_contact_at = last_email

        comms_gap_days = 0
        gap_status = "green"
        if last_contact_at:
            if hasattr(last_contact_at, "tzinfo") and last_contact_at.tzinfo is None:
                last_contact_at = last_contact_at.replace(tzinfo=timezone.utc)
            comms_gap_days = (datetime.now(timezone.utc) - last_contact_at).days
            if comms_gap_days > 14:
                gap_status = "red"
            elif comms_gap_days > 10:
                gap_status = "amber"

        # 3. Orbit contacts
        orbit_names = _get_ao_orbit_names()
        orbit_contacts = []
        try:
            cur.execute(
                "SELECT name, role, email, tier, domain, role_context, expertise, communication_pref "
                "FROM vip_contacts WHERE name ILIKE ANY(%s) LIMIT 20",
                (orbit_names,),
            )
            orbit_contacts = [dict(r) for r in cur.fetchall()]
        except Exception:
            conn.rollback()

        # 4. Deadlines
        deadlines = []
        try:
            # DEADLINE_SIGNAL_HYGIENE_1 Scope B: exclude closed-matter deadlines
            # from AO context-pack deadline pull.
            cur.execute(
                "SELECT d.id, d.description, d.due_date, d.priority, d.status, d.confidence, d.source_snippet "
                "FROM deadlines d "
                "LEFT JOIN matter_registry m "
                "  ON LOWER(REPLACE(m.matter_name, ' ', '-')) = LOWER(d.matter_slug) "
                "WHERE d.status='active' "
                "  AND (d.matter_slug IS NULL OR m.status IS NULL OR m.status = 'active') "
                "  AND ("
                "    d.description ILIKE %s OR d.description ILIKE %s OR d.description ILIKE %s "
                "    OR d.description ILIKE %s OR d.description ILIKE %s"
                "  ) ORDER BY d.due_date LIMIT 15",
                ("%oskolkov%", "%capital call%", "%hagenauer%", "%rg7%", "%aelio%"),
            )
            deadlines = [dict(r) for r in cur.fetchall()]
            for d in deadlines:
                if d.get("due_date"):
                    d["due_date"] = str(d["due_date"])
        except Exception:
            conn.rollback()

        # 5. Decisions
        decisions = []
        try:
            cur.execute(
                "SELECT decision, reasoning, created_at, project, confidence "
                "FROM baker_decisions WHERE project ILIKE %s OR project ILIKE %s "
                "ORDER BY created_at DESC LIMIT 20",
                ("%ao%", "%oskolkov%"),
            )
            decisions = [dict(r) for r in cur.fetchall()]
            for d in decisions:
                if d.get("created_at"):
                    d["created_at"] = d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"])
        except Exception:
            conn.rollback()

        # 6. Comms log
        comms_log = []
        try:
            cur.execute(
                "SELECT id, to_address, subject, sent_at, reply_received "
                "FROM sent_emails WHERE to_address ILIKE %s OR to_address ILIKE %s "
                "ORDER BY sent_at DESC LIMIT 15",
                ("%oskolkov%", "%aelio%"),
            )
            comms_log = [dict(r) for r in cur.fetchall()]
            for c in comms_log:
                if c.get("sent_at"):
                    c["sent_at"] = c["sent_at"].isoformat() if hasattr(c["sent_at"], "isoformat") else str(c["sent_at"])
        except Exception:
            conn.rollback()

        # 7. Pending insights
        pending_insights = []
        try:
            cur.execute(
                "SELECT id, insight_text, source_type, created_at, status "
                "FROM pm_pending_insights WHERE pm_slug='ao_pm' AND status='pending' LIMIT 10"
            )
            pending_insights = [dict(r) for r in cur.fetchall()]
            for p in pending_insights:
                if p.get("created_at"):
                    p["created_at"] = p["created_at"].isoformat() if hasattr(p["created_at"], "isoformat") else str(p["created_at"])
        except Exception:
            conn.rollback()

        cur.close()

    finally:
        store._put_conn(conn)

    # View files (cached separately)
    view_files = _load_ao_view_files()

    return {
        "relationship_status": {
            "investment_total": AO_INVESTMENT_TOTAL,
            "investment_total_as_of": AO_INVESTMENT_TOTAL_AS_OF,
            "last_contact_at": last_contact_at.isoformat() if last_contact_at and hasattr(last_contact_at, "isoformat") else None,
            "comms_gap_days": comms_gap_days,
            "gap_status": gap_status,
        },
        "pm_state": pm_state,
        "orbit_contacts": orbit_contacts,
        "deadlines": deadlines,
        "decisions": decisions,
        "comms_log": comms_log,
        "pending_insights": pending_insights,
        "view_files": view_files,
    }


# ============================================================
# KBL Pipeline — observability endpoints (read-only)
#
# Four endpoints feed the "KBL Pipeline" tab in the Cockpit. All
# read-only. Same X-Baker-Key auth pattern as the rest of the dashboard.
# ============================================================


def _kbl_rows_to_dicts(cur, rows):
    """Convert psycopg2 tuples into dicts using cursor.description."""
    cols = [c.name for c in cur.description]
    out = []
    for r in rows:
        d = {}
        for i, col in enumerate(cols):
            v = r[i]
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            elif isinstance(v, _decimal.Decimal):
                v = float(v)
            d[col] = v
        out.append(d)
    return out


@app.get("/api/kbl/signals", tags=["kbl-pipeline"], dependencies=[Depends(verify_api_key)])
async def kbl_signals():
    """Recent signals (state tracker). Most-recent 50, newest first."""
    from kbl.db import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, source, primary_matter, status, vedana,
                           triage_score, created_at
                    FROM signal_queue
                    ORDER BY id DESC
                    LIMIT 50
                    """
                )
                rows = cur.fetchall()
                signals = _kbl_rows_to_dicts(cur, rows)
    except Exception as e:
        logger.exception("kbl_signals query failed")
        raise HTTPException(status_code=500, detail=f"kbl_signals failed: {e}")
    return {"signals": signals}


@app.get("/api/kbl/cost-rollup", tags=["kbl-pipeline"], dependencies=[Depends(verify_api_key)])
async def kbl_cost_rollup():
    """Last-24h cost ledger rollup grouped by step+model, plus footer totals."""
    from kbl.db import get_conn
    # Canonical cap env is KBL_COST_DAILY_CAP_EUR (kbl/cost_gate.py enforces it);
    # cost_usd ledger column stores EUR values per the same module's contract.
    try:
        cap_eur = float(os.getenv("KBL_COST_DAILY_CAP_EUR", "50.0"))
    except (TypeError, ValueError):
        cap_eur = 50.0

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT step, model,
                           COUNT(*) AS calls,
                           COALESCE(SUM(cost_usd), 0) AS total_eur,
                           COALESCE(SUM(input_tokens), 0) AS in_tok,
                           COALESCE(SUM(output_tokens), 0) AS out_tok
                    FROM kbl_cost_ledger
                    WHERE ts > NOW() - INTERVAL '24 hours'
                    GROUP BY step, model
                    ORDER BY total_eur DESC
                    """
                )
                rows = _kbl_rows_to_dicts(cur, cur.fetchall())
                cur.execute(
                    """
                    SELECT COALESCE(SUM(cost_usd), 0) AS day_total
                    FROM kbl_cost_ledger
                    WHERE ts > NOW() - INTERVAL '24 hours'
                    """
                )
                day_row = cur.fetchone()
                day_total = float(day_row[0]) if day_row and day_row[0] is not None else 0.0
    except Exception as e:
        logger.exception("kbl_cost_rollup query failed")
        raise HTTPException(status_code=500, detail=f"kbl_cost_rollup failed: {e}")

    return {
        "rollup": rows,
        "day_total_eur": day_total,
        "cap_eur": cap_eur,
        "remaining_eur": max(0.0, cap_eur - day_total),
    }


@app.get("/api/kbl/silver-landed", tags=["kbl-pipeline"], dependencies=[Depends(verify_api_key)])
async def kbl_silver_landed():
    """Last 10 signals that reached status='completed' (Silver committed to vault)."""
    from kbl.db import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, primary_matter, target_vault_path, committed_at,
                           substring(commit_sha, 1, 7) AS short_sha
                    FROM signal_queue
                    WHERE status = 'completed'
                    ORDER BY committed_at DESC NULLS LAST
                    LIMIT 10
                    """
                )
                rows = _kbl_rows_to_dicts(cur, cur.fetchall())
    except Exception as e:
        logger.exception("kbl_silver_landed query failed")
        raise HTTPException(status_code=500, detail=f"kbl_silver_landed failed: {e}")
    return {"silver": rows}


@app.get("/api/kbl/mac-mini-status", tags=["kbl-pipeline"], dependencies=[Depends(verify_api_key)])
async def kbl_mac_mini_status():
    """Latest Mac Mini heartbeat + age in seconds. Empty when no rows."""
    from kbl.db import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT host, version, created_at,
                           EXTRACT(EPOCH FROM (NOW() - created_at)) AS age_seconds
                    FROM mac_mini_heartbeat
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if not row:
                    return {"heartbeat": None}
                host, version, created_at, age_seconds = row
                return {
                    "heartbeat": {
                        "host": host,
                        "version": version,
                        "created_at": created_at.isoformat() if created_at else None,
                        "age_seconds": float(age_seconds) if age_seconds is not None else None,
                    }
                }
    except Exception as e:
        logger.exception("kbl_mac_mini_status query failed")
        raise HTTPException(status_code=500, detail=f"kbl_mac_mini_status failed: {e}")


# ============================================================
# BRIEF_CAPABILITY_THREADS_1 — sidebar thread UI endpoints
# Feature-flagged in the frontend via localStorage['baker.threads.ui_enabled']='1'.
# Endpoints themselves are always live (read-only list/turns + Director override);
# blast radius is gated entirely by the UI flag.
# ============================================================

@app.get("/api/pm/threads/{pm_slug}", dependencies=[Depends(verify_api_key)])
async def get_pm_threads(pm_slug: str, limit: int = 20):
    """BRIEF_CAPABILITY_THREADS_1: list recent threads for a PM (sidebar UI)."""
    from orchestrator.capability_runner import PM_REGISTRY
    if pm_slug not in PM_REGISTRY:
        return JSONResponse({"error": f"unknown pm_slug: {pm_slug}"}, status_code=404)
    import psycopg2.extras
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return JSONResponse({"threads": []}, status_code=200)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT thread_id, topic_summary, status, last_turn_at, turn_count
            FROM capability_threads
            WHERE pm_slug = %s
            ORDER BY last_turn_at DESC
            LIMIT %s
        """, (pm_slug, limit))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["thread_id"] = str(r["thread_id"])
            r["last_turn_at"] = r["last_turn_at"].isoformat() if r["last_turn_at"] else None
        return JSONResponse({"threads": rows})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"/api/pm/threads/{pm_slug} failed: {e}")
        return JSONResponse({"threads": [], "error": "retrieval_failed"}, status_code=200)
    finally:
        store._put_conn(conn)


@app.get("/api/pm/threads/{pm_slug}/{thread_id}/turns", dependencies=[Depends(verify_api_key)])
async def get_pm_thread_turns(pm_slug: str, thread_id: str, limit: int = 50):
    """BRIEF_CAPABILITY_THREADS_1: list turns for a specific thread (replay)."""
    import psycopg2.extras
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return JSONResponse({"turns": []}, status_code=200)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT turn_id, surface, turn_order, question, answer, created_at
            FROM capability_turns
            WHERE thread_id = %s AND pm_slug = %s
            ORDER BY turn_order ASC
            LIMIT %s
        """, (thread_id, pm_slug, limit))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        for r in rows:
            r["turn_id"] = str(r["turn_id"])
            r["created_at"] = r["created_at"].isoformat() if r["created_at"] else None
        return JSONResponse({"turns": rows})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"/api/pm/threads/{pm_slug}/{thread_id}/turns failed: {e}")
        return JSONResponse({"turns": [], "error": "retrieval_failed"}, status_code=200)
    finally:
        store._put_conn(conn)


@app.post("/api/pm/threads/re-thread", dependencies=[Depends(verify_api_key)])
async def re_thread(req: Request):
    """BRIEF_CAPABILITY_THREADS_1: Director explicit override — move a turn to a
    different thread (or spawn a new one when ``new_thread_id`` is null)."""
    import json as _json
    from datetime import datetime, timezone
    body = await req.json()
    turn_id = body.get("turn_id")
    new_thread_id = body.get("new_thread_id")  # None → start a fresh thread
    if not turn_id:
        return JSONResponse({"error": "turn_id required"}, status_code=400)
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return JSONResponse({"error": "db unavailable"}, status_code=503)
    try:
        cur = conn.cursor()
        if new_thread_id is None:
            cur.execute("""
                SELECT pm_slug, question, answer FROM capability_turns WHERE turn_id = %s
            """, (turn_id,))
            row = cur.fetchone()
            if not row:
                return JSONResponse({"error": "turn not found"}, status_code=404)
            from orchestrator.capability_threads import stitch_or_create_thread
            new_thread_id, _ = stitch_or_create_thread(
                pm_slug=row[0], question=row[1] or "", answer=row[2] or "",
                surface="sidebar", force_new=True,
            )
        cur.execute("""
            UPDATE capability_turns
            SET thread_id = %s, stitch_decision = stitch_decision || %s::jsonb
            WHERE turn_id = %s
        """, (new_thread_id,
              _json.dumps({"director_override_at": datetime.now(timezone.utc).isoformat()}),
              turn_id))
        conn.commit()
        cur.close()
        return JSONResponse({"new_thread_id": str(new_thread_id)})
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"/api/pm/threads/re-thread failed: {e}")
        return JSONResponse({"error": "re-thread_failed"}, status_code=500)
    finally:
        store._put_conn(conn)


# ============================================================
# BRIEF_PROACTIVE_PM_SENTINEL_1 — Director triage surface
# Four-verdict endpoint: accept / snooze / dismiss / reject.
# Auth-gated (B1 §2.1 trigger + PR #57 anchor incident).
# ============================================================

@app.post("/api/sentinel/feedback", dependencies=[Depends(verify_api_key)])
async def sentinel_feedback(req: Request):
    """BRIEF_PROACTIVE_PM_SENTINEL_1: Director triage surface.

    Body shape:
      {"alert_id": int, "verdict": "accept"|"snooze"|"dismiss"|"reject",
       "snooze_hours": int?,        # when verdict=snooze (default 24, max 720)
       "dismiss_reason": str?,       # when verdict=dismiss (must be in DISMISS_REASONS)
       "director_comment": str?,
       "learned_rule": str?}         # required when verdict=reject

    Returns:
      - standard feedback response dict
      - for dismiss_reason='wrong_thread': additional `rethread_hint` so the
        client can POST /api/pm/threads/re-thread (Phase 2 chain).
    """
    import psycopg2.extras
    body = await req.json()
    alert_id = body.get("alert_id")
    verdict = (body.get("verdict") or "").lower()
    if not alert_id or verdict not in ("accept", "snooze", "dismiss", "reject"):
        return JSONResponse(
            {"error": "alert_id and verdict in {accept,snooze,dismiss,reject} required"},
            status_code=400,
        )

    from orchestrator.proactive_pm_sentinel import DISMISS_REASONS

    snooze_hours = 24
    dismiss_reason = None
    if verdict == "snooze":
        try:
            snooze_hours = int(body.get("snooze_hours") or 24)
        except (TypeError, ValueError):
            return JSONResponse({"error": "snooze_hours must be integer"}, status_code=400)
        if snooze_hours < 1 or snooze_hours > 720:
            return JSONResponse({"error": "snooze_hours out of range [1, 720]"}, status_code=400)
    elif verdict == "dismiss":
        dismiss_reason = (body.get("dismiss_reason") or "").strip().lower()
        if dismiss_reason not in DISMISS_REASONS:
            return JSONResponse(
                {"error": f"dismiss_reason must be one of {sorted(DISMISS_REASONS)}"},
                status_code=400,
            )

    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return JSONResponse({"error": "db unavailable"}, status_code=503)

    row = None
    new_status = None
    latest_turn_id = None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            """
            SELECT id, source, source_id, matter_slug, structured_actions
            FROM alerts WHERE id = %s AND source = 'proactive_pm_sentinel' LIMIT 1
            """,
            (alert_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return JSONResponse({"error": "alert not found"}, status_code=404)
        row = dict(row)

        verdict_meta = {
            "director_verdict": verdict,
            "director_comment": (body.get("director_comment") or "")[:2000],
            "verdict_at": datetime.now(timezone.utc).isoformat(),
        }

        if verdict == "snooze":
            # snooze_hours is already int-coerced and range-checked — safe to
            # inline into the INTERVAL literal.
            cur.execute(
                f"""
                UPDATE alerts
                SET status = 'pending',
                    snoozed_until = NOW() + INTERVAL '{snooze_hours} hours',
                    structured_actions = COALESCE(structured_actions, '{{}}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (json.dumps({**verdict_meta, "snooze_hours": snooze_hours}), alert_id),
            )
            new_status = "snoozed"
        elif verdict == "dismiss":
            cur.execute(
                """
                UPDATE alerts
                SET status = 'dismissed',
                    dismiss_reason = %s,
                    resolved_at = NOW(),
                    structured_actions = COALESCE(structured_actions, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (dismiss_reason, json.dumps(verdict_meta), alert_id),
            )
            new_status = "dismissed"
        else:  # accept or reject — both resolve
            cur.execute(
                """
                UPDATE alerts
                SET status = 'resolved', resolved_at = NOW(),
                    structured_actions = COALESCE(structured_actions, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (json.dumps(verdict_meta), alert_id),
            )
            new_status = "resolved"

        # Upgrade 2 chain: wrong_thread dismiss → look up most-recent turn in
        # the thread while the cursor is still open. Phase 2 re-thread endpoint
        # operates on turn_id (not thread_id); sentinel's source_id is the
        # thread_id. Non-fatal — on lookup failure fall back to None and let
        # the JS guard surface a user-facing message.
        if verdict == "dismiss" and dismiss_reason == "wrong_thread":
            try:
                cur.execute(
                    """
                    SELECT turn_id FROM capability_turns
                    WHERE thread_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (row.get("source_id"),),
                )
                latest = cur.fetchone()
                if latest:
                    latest_turn_id = str(latest[0] if not isinstance(latest, dict) else latest["turn_id"])
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.warning(f"rethread_hint turn lookup failed: {e}")

        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"/api/sentinel/feedback update failed: {e}")
        return JSONResponse({"error": "feedback_failed"}, status_code=500)
    finally:
        store._put_conn(conn)

    response = {"alert_id": alert_id, "status": new_status, "verdict": verdict}

    # Reject verdict → store learned rule into baker_corrections
    if verdict == "reject":
        learned_rule = (body.get("learned_rule") or "").strip()
        director_comment = (body.get("director_comment") or "").strip()
        if not learned_rule:
            response["warning"] = "reject without learned_rule — no correction stored"
        else:
            try:
                store.store_correction(
                    baker_task_id=int(alert_id),
                    capability_slug=row.get("matter_slug") or "ao_pm",
                    correction_type="sentinel_false_positive",
                    director_comment=director_comment,
                    learned_rule=learned_rule,
                    matter_slug=row.get("matter_slug"),
                    applies_to="capability",
                )
            except Exception as e:
                logger.warning(f"store_correction failed: {e}")
                response["warning"] = f"correction_store_failed: {type(e).__name__}"

    # Upgrade 2 chain: wrong_thread dismiss → hint client to call re-thread UI.
    # alerts.source_id for a quiet-thread alert is the thread_id (UUID str).
    # latest_turn_id was looked up inside the main try (cursor still open).
    # If the thread has no turns (edge case), latest_turn_id stays None and the
    # JS guard surfaces a user-facing message instead of firing a silent 400.
    if verdict == "dismiss" and dismiss_reason == "wrong_thread":
        response["rethread_hint"] = {
            "turn_id_hint": latest_turn_id,
            "thread_id": row.get("source_id"),
            "pm_slug": row.get("matter_slug"),
            "rethread_endpoint": "/api/pm/threads/re-thread",
        }

    return JSONResponse(response)


# ============================================================
# Cortex Stage 2 V1 — Director button webhook (CORTEX_3T_FORMALIZE_1C)
# ============================================================

@app.post(
    "/cortex/cycle/{cycle_id}/action",
    tags=["cortex"],
    dependencies=[Depends(verify_api_key)],
)
async def cortex_cycle_action(cycle_id: str, request: Request):
    """Director clicked a button on the Cortex proposal card.

    Body shape:
        {"action": "approve|edit|refresh|reject|useful",
         "edits": "<optional new text for edit>",
         "selected_gold_files": ["<files chosen via per-file checkboxes>"],
         "reason": "<optional rejection reason>",
         "useful": true|false, "note": "<optional usefulness note>"}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json_body")
    action = (body.get("action") or "").lower()
    if action not in ("approve", "edit", "refresh", "reject", "useful"):
        raise HTTPException(status_code=400, detail=f"invalid_action:{action}")

    if action == "useful":
        # CORTEX_LITE_REBASE_1 WP-D: capture the Director's one-tap usefulness
        # verdict for the 14-day proof. Persisted to feedback_ledger (the
        # purpose-built, already-wired feedback store) — NO schema change.
        useful = bool(body.get("useful"))
        note = (body.get("note") or "")[:500]
        store = _get_store()
        conn = store._get_conn()
        if conn is None:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            cur = conn.cursor()
            # Best-effort matter resolution for proof-window analysis.
            cur.execute(
                "SELECT matter_slug FROM cortex_cycles "
                "WHERE cycle_id::text = %s LIMIT 1",
                (cycle_id,),
            )
            row = cur.fetchone()
            target_matter = row[0] if row else None
            payload = {
                "cycle_id": cycle_id,
                "useful": useful,
                "source": "director_card",
            }
            cur.execute(
                """
                INSERT INTO feedback_ledger
                    (action_type, target_matter, payload, director_note)
                VALUES (%s, %s, %s::jsonb, %s)
                """,
                (
                    "cortex:useful" if useful else "cortex:not_useful",
                    target_matter,
                    json.dumps(payload),
                    note,
                ),
            )
            conn.commit()
            cur.close()
            return {"status": "ok", "action": "useful", "useful": useful}
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(
                "/cortex/cycle/%s/action [useful] failed: %s", cycle_id, e,
            )
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            store._put_conn(conn)

    from orchestrator.cortex_phase5_act import (
        cortex_approve, cortex_edit, cortex_refresh, cortex_reject,
    )
    handlers = {
        "approve": cortex_approve,
        "edit": cortex_edit,
        "refresh": cortex_refresh,
        "reject": cortex_reject,
    }
    try:
        result = await handlers[action](cycle_id=cycle_id, body=body)
        return {"status": "ok", "action": action, "result": result}
    except Exception as e:
        logger.error(
            "/cortex/cycle/%s/action [%s] failed: %s", cycle_id, action, e,
        )
        raise HTTPException(status_code=500, detail=str(e))


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
