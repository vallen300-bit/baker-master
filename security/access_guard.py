"""security/access_guard.py — BREACH_DETECT_PHASE1_1.

Central security chokepoint for the Baker API (one FastAPI middleware):
  * read-audit log (metadata ONLY) for every request → ``security_access_log``,
  * anomaly tripwire → Slack alarm that BYPASSES the Director email/WA blocks
    (it's Slack, deliberately outside BAKER_BLOCK_EMAIL/WA_TO_DIRECTOR),
  * DB-backed global freeze switch (instant 503, no redeploy) + a boot-time
    ``BAKER_SECURITY_FREEZE`` env backstop,
  * daily retention prune (addendum #4518) so the audit table stays flat.

Design rules (brief Key Constraints):
  * Metadata only — NEVER bodies / secrets / key material / query values. The
    presented key, client IP and user-agent are stored as short sha256 prefixes.
  * Freeze fails CLOSED via the env backstop; AUDIT fails OPEN — a logging error
    must never 500 a request.
  * Hot path stays cheap: ≤3s freeze cache, ONE indexed INSERT per request,
    heavy aggregation/prune throttled or moved to the daily scheduler.

The middleware logic lives here (not inline in dashboard.py) so it is unit
testable on a minimal app without importing the 11.7k-line dashboard module;
dashboard.py keeps only a thin ``@app.middleware("http")`` wrapper, defined
AFTER ``scheduler_watchdog_middleware`` so it registers OUTERMOST.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# ── configuration (env-overridable; conservative defaults) ──────────────────
# Routes that must stay reachable while the service is frozen (so you can
# unfreeze + health-check during a lockdown).
FREEZE_EXEMPT_PREFIXES = ("/health", "/healthz", "/api/security")
FREEZE_CACHE_TTL_S = 3.0

WINDOW_SECONDS = int(os.getenv("BAKER_SEC_WINDOW_SECONDS", "60"))
BULK_READ_THRESHOLD = int(os.getenv("BAKER_SEC_BULK_READ_THRESHOLD", "100"))
AUTH_FAIL_THRESHOLD = int(os.getenv("BAKER_SEC_AUTH_FAIL_THRESHOLD", "10"))
LARGE_RESPONSE_BYTES = int(os.getenv("BAKER_SEC_LARGE_RESPONSE_BYTES", str(10 * 1024 * 1024)))
ALARM_WINDOW_SECONDS = int(os.getenv("BAKER_SEC_ALARM_WINDOW_SECONDS", "300"))
SLACK_CHANNEL = os.getenv("BAKER_SECURITY_SLACK_CHANNEL", "#cockpit")

PRUNE_BATCH_SIZE = int(os.getenv("BAKER_SECURITY_LOG_PRUNE_BATCH", "5000"))

# Canonical, metadata-ONLY column order for security_access_log inserts.
# (``id`` + ``ts`` are server-defaulted.) There is, by design, no column that
# could hold a body, secret, key, or raw URL value — the test suite asserts it.
ACCESS_LOG_COLUMNS = (
    "request_id",
    "key_fp",
    "actor_label",
    "method",
    "path_template",
    "route_group",
    "status_code",
    "latency_ms",
    "response_bytes",
    "client_ip_hash",
    "user_agent_hash",
    "origin",
    "anomaly_flags",
)

# ── in-memory tripwire state (bounded; per-process is fine for an alarm) ─────
_STATE_MAX = 4096
_lock = threading.Lock()
_key_request_times: dict[str, list[float]] = {}
_auth_fail_times: dict[str, list[float]] = {}
_seen_ip_for_key: dict[str, set[str]] = {}
_alarm_last: dict[str, float] = {}
_FREEZE_CACHE: dict[str, object] = {"v": None, "ts": 0.0}


# ── small helpers ───────────────────────────────────────────────────────────
def _hash(s: str) -> str:
    """sha256 prefix — used for key fingerprint, IP and UA. NEVER the raw value."""
    return hashlib.sha256((s or "").encode("utf-8", "replace")).hexdigest()[:16]


def _get_store_conn():
    """Borrow a pooled connection from the global SentinelStoreBack singleton.

    Returns None on any failure so callers degrade cleanly (audit fail-open;
    freeze falls back to the env backstop)."""
    try:
        from memory.store_back import SentinelStoreBack

        store = SentinelStoreBack._get_global_instance()
        return store._get_conn()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("access_guard: could not acquire DB connection: %s", e)
        return None


def _put_store_conn(conn) -> None:
    if conn is None:
        return
    try:
        from memory.store_back import SentinelStoreBack

        SentinelStoreBack._get_global_instance()._put_conn(conn)
    except Exception:  # pragma: no cover - defensive
        pass


def reset_state() -> None:
    """Test helper: clear all in-memory tripwire state + the freeze cache."""
    with _lock:
        _key_request_times.clear()
        _auth_fail_times.clear()
        _seen_ip_for_key.clear()
        _alarm_last.clear()
    clear_freeze_cache()


# ── schema bootstrap (mirror of migrations/20260628_security_access_log.sql) ─
def ensure_security_schema(conn) -> None:
    """CREATE TABLE IF NOT EXISTS for the two security tables. Byte-equivalent
    to the migration (Lesson #50 — bootstrap-vs-migration drift trap)."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS security_access_log (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT NOW(),
                request_id TEXT,
                key_fp TEXT,
                actor_label TEXT,
                method TEXT,
                path_template TEXT,
                route_group TEXT,
                status_code INTEGER,
                latency_ms INTEGER,
                response_bytes INTEGER,
                client_ip_hash TEXT,
                user_agent_hash TEXT,
                origin TEXT,
                anomaly_flags TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS security_freeze (
                id INTEGER PRIMARY KEY DEFAULT 1,
                global_freeze BOOLEAN NOT NULL DEFAULT FALSE,
                reason TEXT,
                set_by TEXT,
                set_at TIMESTAMPTZ,
                CONSTRAINT security_freeze_singleton CHECK (id = 1)
            )
            """
        )
        cur.execute(
            "INSERT INTO security_freeze (id, global_freeze) VALUES (1, FALSE) "
            "ON CONFLICT (id) DO NOTHING"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sal_ts ON security_access_log (ts)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sal_key_ts ON security_access_log (key_fp, ts)"
        )
        conn.commit()
        cur.close()
        logger.info("security tables verified")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("ensure_security_schema failed: %s", e)


# ── freeze switch (fail-CLOSED via env backstop) ────────────────────────────
def clear_freeze_cache() -> None:
    _FREEZE_CACHE["v"] = None
    _FREEZE_CACHE["ts"] = 0.0


def is_frozen() -> tuple[bool, str]:
    """Return (frozen, reason). The env backstop wins immediately so an
    operator can lock the service at boot even with the DB down."""
    if os.getenv("BAKER_SECURITY_FREEZE", "").strip() in ("1", "true", "True"):
        return True, "env BAKER_SECURITY_FREEZE"

    now = time.time()
    cached = _FREEZE_CACHE["v"]
    if cached is not None and now - float(_FREEZE_CACHE["ts"]) < FREEZE_CACHE_TTL_S:
        return cached  # type: ignore[return-value]

    conn = _get_store_conn()
    if conn is None:
        # DB unreachable: do NOT silently unblock — the env backstop above is the
        # only freeze path in that state (fail-closed-by-design).
        return False, ""
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT global_freeze, COALESCE(reason,'') FROM security_freeze WHERE id=1 LIMIT 1"
        )
        row = cur.fetchone()
        cur.close()
        res = (bool(row[0]), row[1]) if row else (False, "")
        _FREEZE_CACHE["v"] = res
        _FREEZE_CACHE["ts"] = now
        return res
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("is_frozen check failed: %s", e)
        return False, ""
    finally:
        _put_store_conn(conn)


def set_freeze(frozen: bool, reason: str = "", set_by: str = "") -> tuple[bool, str]:
    """Persist the global freeze flag (no redeploy) + clear the cache. Raises on
    DB failure so the admin route can surface it (a freeze you can't confirm is
    worse than a loud error)."""
    conn = _get_store_conn()
    if conn is None:
        raise RuntimeError("freeze switch unavailable: no DB connection")
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO security_freeze (id, global_freeze, reason, set_by, set_at)
            VALUES (1, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                global_freeze = EXCLUDED.global_freeze,
                reason = EXCLUDED.reason,
                set_by = EXCLUDED.set_by,
                set_at = EXCLUDED.set_at
            """,
            (bool(frozen), (reason or "")[:500], (set_by or "")[:120]),
        )
        conn.commit()
        cur.close()
        clear_freeze_cache()
        return bool(frozen), (reason or "")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("set_freeze failed: %s", e)
        raise
    finally:
        _put_store_conn(conn)


def get_freeze_status() -> dict:
    """Current freeze state for GET /api/security/status."""
    env_frozen = os.getenv("BAKER_SECURITY_FREEZE", "").strip() in ("1", "true", "True")
    conn = _get_store_conn()
    if conn is None:
        return {
            "global_freeze": env_frozen,
            "reason": "env BAKER_SECURITY_FREEZE" if env_frozen else "",
            "set_by": None,
            "set_at": None,
            "source": "env-only (db unavailable)",
        }
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT global_freeze, COALESCE(reason,''), COALESCE(set_by,''), set_at "
            "FROM security_freeze WHERE id=1 LIMIT 1"
        )
        row = cur.fetchone()
        cur.close()
        db_frozen = bool(row[0]) if row else False
        return {
            "global_freeze": db_frozen or env_frozen,
            "reason": (row[1] if row else "") or ("env BAKER_SECURITY_FREEZE" if env_frozen else ""),
            "set_by": (row[2] if row else None) or None,
            "set_at": (row[3].isoformat() if row and row[3] else None),
            "env_backstop": env_frozen,
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("get_freeze_status failed: %s", e)
        return {"global_freeze": env_frozen, "reason": "", "error": str(e)}
    finally:
        _put_store_conn(conn)


def recent_anomalies(limit: int = 20) -> list[dict]:
    """Last N flagged rows for GET /api/security/status."""
    conn = _get_store_conn()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ts, key_fp, actor_label, method, path_template, status_code,
                   response_bytes, anomaly_flags
            FROM security_access_log
            WHERE anomaly_flags <> ''
            ORDER BY ts DESC
            LIMIT %s
            """,
            (max(1, min(int(limit), 200)),),
        )
        rows = cur.fetchall()
        cur.close()
        out = []
        for r in rows:
            out.append(
                {
                    "ts": r[0].isoformat() if r[0] else None,
                    "key_fp": r[1],
                    "actor_label": r[2],
                    "method": r[3],
                    "path_template": r[4],
                    "status_code": r[5],
                    "response_bytes": r[6],
                    "anomaly_flags": r[7],
                }
            )
        return out
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("recent_anomalies failed: %s", e)
        return []
    finally:
        _put_store_conn(conn)


# ── request metadata extraction (no raw sensitive values) ───────────────────
def _header(request, name: str) -> str:
    try:
        v = request.headers.get(name)
        return str(v).strip()[:200] if v else ""
    except Exception:
        return ""


def _client_ip(request) -> str:
    """Mirror dashboard._ai_hotel_client_ip_details: prefer Cloudflare's
    CF-Connecting-IP (Render's edge), never trust X-Forwarded-For."""
    for h in ("cf-connecting-ip", "true-client-ip"):
        v = _header(request, h)
        if v:
            return v[:80]
    try:
        if request.client and request.client.host:
            return str(request.client.host)[:80]
    except Exception:
        pass
    return "unknown"


def _path_template(request) -> str:
    """Prefer the matched route template (e.g. /api/email/{id}) so raw, possibly
    sensitive URL values never land in the log. Fall back to a generalized,
    value-stripped path for unmatched routes (404s)."""
    try:
        route = request.scope.get("route")
        tmpl = getattr(route, "path", None) if route is not None else None
        if tmpl:
            return str(tmpl)[:200]
    except Exception:
        pass
    try:
        path = request.url.path
    except Exception:
        return "unknown"
    parts = [p for p in path.split("/") if p][:2]
    return "/" + "/".join(parts) if parts else "/"


def _route_group(path_template: str) -> str:
    parts = [p for p in path_template.split("/") if p]
    return parts[0] if parts else "root"


def _actor_label(key_fp: str, has_session: bool) -> str:
    master = os.getenv("BAKER_API_KEY", "")
    if master and key_fp == _hash(master):
        return "master"
    if has_session:
        return "ai-hotel-session"
    if key_fp and key_fp != _hash(""):
        return "keyed"
    return "anonymous"


def build_access_meta(request, response, latency_ms: int) -> dict:
    """Build the metadata-only audit row. Hashes the presented key, client IP and
    user-agent; never stores the raw values, bodies, or query values."""
    presented = _header(request, "x-baker-key")
    if not presented:
        try:
            presented = str(request.query_params.get("key") or "")
        except Exception:
            presented = ""
    key_fp = _hash(presented)

    try:
        has_session = bool(request.cookies.get("aih_session"))
    except Exception:
        has_session = False

    path_template = _path_template(request)
    try:
        status_code = int(getattr(response, "status_code", 0) or 0)
    except Exception:
        status_code = 0
    try:
        resp_bytes = int(response.headers.get("content-length") or 0)
    except Exception:
        resp_bytes = 0

    request_id = _header(request, "x-request-id") or _hash(f"{time.time()}:{path_template}")

    return {
        "request_id": request_id[:64],
        "key_fp": key_fp,
        "actor_label": _actor_label(key_fp, has_session),
        "method": (getattr(request, "method", "") or "")[:10],
        "path_template": path_template,
        "route_group": _route_group(path_template),
        "status_code": status_code,
        "latency_ms": int(latency_ms),
        "response_bytes": resp_bytes,
        "client_ip_hash": _hash(_client_ip(request)),
        "user_agent_hash": _hash(_header(request, "user-agent")),
        "origin": _header(request, "origin")[:200],
        "anomaly_flags": "",
    }


# ── audit write (metadata-only, fail-OPEN) ──────────────────────────────────
def record_access(meta: dict) -> None:
    conn = _get_store_conn()
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cols = ", ".join(ACCESS_LOG_COLUMNS)
        placeholders = ", ".join(["%s"] * len(ACCESS_LOG_COLUMNS))
        cur.execute(
            f"INSERT INTO security_access_log ({cols}) VALUES ({placeholders})",
            tuple(meta.get(c) for c in ACCESS_LOG_COLUMNS),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("security_access_log insert failed (non-fatal): %s", e)
    finally:
        _put_store_conn(conn)


# ── tripwire (cheap synchronous flags) ──────────────────────────────────────
def _trim(times: list[float], now: float, window: float) -> list[float]:
    return [t for t in times if now - t < window]


def _prune_state_locked() -> None:
    for d in (_key_request_times, _auth_fail_times, _seen_ip_for_key):
        if len(d) > _STATE_MAX:
            for k in list(d.keys())[: len(d) - _STATE_MAX]:
                d.pop(k, None)
    if len(_alarm_last) > _STATE_MAX:
        for k in list(_alarm_last.keys())[: len(_alarm_last) - _STATE_MAX]:
            _alarm_last.pop(k, None)


def get_auth_fail_count(key_fp: str) -> int:
    now = time.time()
    with _lock:
        return len(_trim(_auth_fail_times.get(key_fp, []), now, WINDOW_SECONDS))


def evaluate_tripwire(meta: dict) -> list[str]:
    """Cheap, synchronous per-request anomaly flags. Updates the bounded
    in-memory windows. Returns the list of flags (empty == clean)."""
    flags: list[str] = []
    now = time.time()
    key_fp = meta.get("key_fp") or ""
    ip_hash = meta.get("client_ip_hash") or ""
    status = meta.get("status_code") or 0
    anon = _hash("")

    with _lock:
        # 1) request rate per key (exfil/bulk-read signal)
        rt = _trim(_key_request_times.get(key_fp, []), now, WINDOW_SECONDS)
        rt.append(now)
        _key_request_times[key_fp] = rt
        if len(rt) >= BULK_READ_THRESHOLD:
            flags.append("bulk_read")

        # 2) repeated auth failures per key (stolen/guessed key signal)
        if status == 401:
            ft = _trim(_auth_fail_times.get(key_fp, []), now, WINDOW_SECONDS)
            ft.append(now)
            _auth_fail_times[key_fp] = ft
            if len(ft) >= AUTH_FAIL_THRESHOLD:
                flags.append("repeated_auth_fail")

        # 3) new client IP for an established (non-anonymous) key
        if key_fp and key_fp != anon and ip_hash:
            seen = _seen_ip_for_key.setdefault(key_fp, set())
            if ip_hash not in seen:
                if seen:  # not the first IP ever seen for this key
                    flags.append("new_ip_for_key")
                seen.add(ip_hash)
                if len(seen) > 64:
                    seen.pop()

        _prune_state_locked()

    # 4) large response body (potential bulk exfil in a single call)
    if (meta.get("response_bytes") or 0) >= LARGE_RESPONSE_BYTES:
        flags.append("large_response")

    return flags


def _should_fire_alarm(dedupe_key: str) -> bool:
    """Rate-limit alarms to one per ALARM_WINDOW_SECONDS per dedupe key."""
    now = time.time()
    with _lock:
        last = float(_alarm_last.get(dedupe_key, 0.0))
        if now - last < ALARM_WINDOW_SECONDS:
            return False
        _alarm_last[dedupe_key] = now
        return True


def _format_alarm(meta: dict, flags: list[str]) -> str:
    return (
        "🚨 *Baker Security Tripwire*\n"
        f"Flags: *{', '.join(flags)}*\n"
        f"actor: {meta.get('actor_label')} | key_fp: {meta.get('key_fp')}\n"
        f"req: {meta.get('method')} {meta.get('path_template')} "
        f"| status: {meta.get('status_code')} | bytes: {meta.get('response_bytes')}\n"
        f"client_ip_hash: {meta.get('client_ip_hash')}\n"
        "Freeze now: POST /api/security/freeze  (or set BAKER_SECURITY_FREEZE=1 + restart)"
    )


def record_and_evaluate(request, response, latency_ms: int) -> dict:
    """Build the metadata row, evaluate the tripwire, persist, and fire ONE
    rate-limited alarm if anything tripped. Must never raise to the caller
    (the middleware also guards, belt-and-suspenders)."""
    meta = build_access_meta(request, response, latency_ms)
    try:
        flags = evaluate_tripwire(meta)
    except Exception as e:
        logger.warning("tripwire evaluation failed (non-fatal): %s", e)
        flags = []
    if flags:
        meta["anomaly_flags"] = ",".join(flags)
    record_access(meta)
    if flags:
        primary = flags[0]
        dedupe = f"{meta.get('key_fp', '')}:{primary}"
        if _should_fire_alarm(dedupe):
            try:
                security_alarm_send(_format_alarm(meta, flags), dedupe_key=dedupe)
            except Exception as e:
                logger.error("security alarm dispatch failed: %s", e)
    return meta


# ── Slack alarm (bypasses Director email/WA blocks — it is Slack) ────────────
def security_alarm_send(text: str, dedupe_key: str = "") -> bool:
    """Post a security alarm to Slack #cockpit. This deliberately bypasses
    BAKER_BLOCK_EMAIL/WA_TO_DIRECTOR (those gate email/WhatsApp, not Slack).
    Fail-LOUD if the token is missing — a breach alarm that can't deliver must
    be screamed into the logs, not silently dropped."""
    try:
        import requests

        token = os.getenv("SLACK_BOT_TOKEN")
        if not token:
            logger.error(
                "SECURITY ALARM but no SLACK_BOT_TOKEN — cannot deliver: %s", text
            )
            return False
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": SLACK_CHANNEL, "text": text},
            timeout=5,
        )
        ok = getattr(resp, "status_code", 0) == 200
        if ok:
            logger.warning("security alarm sent to Slack %s", SLACK_CHANNEL)
        else:
            logger.error(
                "security alarm Slack post failed: status=%s",
                getattr(resp, "status_code", "?"),
            )
        return ok
    except Exception as e:
        logger.error("security alarm send raised: %s", e)
        return False


# ── retention prune (addendum #4518) — daily, bounded, batched ──────────────
def retention_days() -> int:
    try:
        return max(1, int(os.getenv("BAKER_SECURITY_LOG_RETENTION_DAYS", "90")))
    except (TypeError, ValueError):
        return 90


def prune_access_log(retention_days_override: int | None = None, batch_size: int | None = None) -> int:
    """Bounded, batched DELETE of security_access_log rows older than the
    retention window. Runs off the daily scheduler (NOT per-request). Returns
    the total rows deleted. Fault-tolerant — logs and returns on any error."""
    days = retention_days_override if retention_days_override is not None else retention_days()
    batch = int(batch_size) if batch_size else PRUNE_BATCH_SIZE
    conn = _get_store_conn()
    if conn is None:
        return 0
    total = 0
    try:
        while True:
            cur = conn.cursor()
            cur.execute(
                """
                DELETE FROM security_access_log
                WHERE id IN (
                    SELECT id FROM security_access_log
                    WHERE ts < NOW() - make_interval(days => %s)
                    ORDER BY id
                    LIMIT %s
                )
                """,
                (days, batch),
            )
            deleted = cur.rowcount or 0
            conn.commit()
            cur.close()
            total += deleted
            if deleted < batch:
                break
        if total:
            logger.info(
                "security_access_log prune: deleted %s rows (retention=%sd)", total, days
            )
        return total
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("security_access_log prune failed: %s", e)
        return total
    finally:
        _put_store_conn(conn)


# ── the middleware (registered by a thin wrapper in dashboard.py) ────────────
async def security_guard_middleware(request, call_next):
    """Outermost middleware: freeze gate first, then run + audit the request.

    Freeze fails CLOSED (env backstop); audit fails OPEN (never 500 a request).
    """
    try:
        path = request.url.path
    except Exception:
        path = ""

    # 1) FREEZE GATE — before any handler work.
    try:
        frozen, reason = is_frozen()
    except Exception:
        # A DB-path error here must not hard-block; the env backstop covers intent.
        frozen, reason = False, ""
    if frozen and not path.startswith(FREEZE_EXEMPT_PREFIXES):
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": "service_frozen", "reason": reason}, status_code=503)

    # 2) run the request, timed.
    t0 = time.time()
    response = await call_next(request)

    # 3) AUDIT + TRIPWIRE — must never break the response.
    try:
        record_and_evaluate(request, response, latency_ms=int((time.time() - t0) * 1000))
    except Exception as e:
        logger.warning("security audit failed (non-fatal): %s", e)
    return response
