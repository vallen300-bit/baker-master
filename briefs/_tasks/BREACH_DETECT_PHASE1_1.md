# BRIEF: BREACH_DETECT_PHASE1_1 — Breach detection + containment (read-audit · tripwire · freeze switch · Slack alarm)

## Context
Director asked: "If there is a data breach, would we notice? Is there a kill switch?" Grounded audit (2026-06-27, this session) answered **no** on both. Today: a single shared `X-Baker-Key` (`outputs/dashboard.py:162,188`) guards ~237 endpoints; `baker_actions` logs **writes only** — there is **no read-access log**, no anomaly detection, no rate limit, and no global "stop all access" switch. Remediation today = rotate the env var + Render redeploy (~1–2 min during which the leaked key still works).

This brief implements **Phase 1** of the design **validated by codex-arch (bus #4497)**: a single FastAPI middleware chokepoint that (1) logs every request's metadata, (2) trips an anomaly alarm to a Slack channel that **bypasses the Director email/WhatsApp blocks**, and (3) provides a DB-backed global freeze switch that returns 503 to all protected routes **without a redeploy**. Phases 2–4 (scoped/rotatable keys, rate-limit middleware, encryption-at-rest review) are separate briefs.

Design source: bus #4497 (codex-arch). Premise audit: bus #4495 (deputy-codex). Director request 2026-06-27.

## Estimated time: ~5–7h
## Complexity: Medium (security-sensitive; runs on the hot path for every request)
## Recommended effort tier: medium (Director sets manually)
## Prerequisites: none new. Reuses `SLACK_BOT_TOKEN`, PostgreSQL (Neon), existing DB pool.

---

## Fix/Feature 1: Central security middleware — read-audit + freeze gate + tripwire

### Problem
No surface records who **reads** data, and no switch can stop a leaking key fast. A stolen key exfiltrates emails / WhatsApp / legal docs / financials silently and undetectably.

### Current State (verified)
- `app = FastAPI(...)` at `outputs/dashboard.py:487`; CORS added at `:546`.
- **Exactly one** HTTP middleware today: `scheduler_watchdog_middleware` at `:620` (`@app.middleware("http")`, throttled to once/60s, `return await call_next(request)`). Starlette runs the **most-recently-added middleware outermost** — so a security middleware **defined AFTER** line 620 wraps outermost and runs first. That is what we want (freeze + audit must be outermost).
- Auth: `verify_api_key(x_baker_key: Header)` at `:188`; query-param variant `_mcp_verify_key(request)` at `:1982`; key constant `_BAKER_API_KEY` at `:162`.
- Reusable client-IP helper: `_ai_hotel_client_ip_details(request)` at `:204` (handles `CF-Connecting-IP`/`True-Client-IP`).
- Slack-alarm template to mirror: `cost_monitor._send_hard_stop_alert` (`orchestrator/cost_monitor.py:639`) + `_send_tiered_alarm` (`:611`) + once-per-window DB claim `_claim_tier_alert` (`:594`). These post to `#cockpit` via `SLACK_BOT_TOKEN` — **Slack, not email/WA**, so they are already outside the `BAKER_BLOCK_EMAIL/WA_TO_DIRECTOR` blocks.
- Table-bootstrap pattern to mirror: `cost_monitor` `CREATE TABLE IF NOT EXISTS api_cost_log` + idempotent `ALTER ... ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` + `conn.commit()` + `conn.rollback()` in except (`orchestrator/cost_monitor.py:96-142`). Lesson #50 — also add a matching migration file (bootstrap-vs-migration drift trap).
- DB conn pattern: `store = SentinelStoreBack._get_global_instance(); conn = store._get_conn(); ... store._put_conn(conn)`; `conn.rollback()` in every except (verified in `get_daily_cost`, `cost_monitor.py:298`).
- No existing `security_access_log`, `security_freeze`, `BAKER_SECURITY_FREEZE`, or `security_alarm` symbol — clean, no shadow (grep confirmed).

### Engineering Craft Gates
- **Diagnose:** N/A — net-new feature, no bug to reproduce. (The acceptance test simulating a leaked-key bulk read **is** the pass/fail loop that proves detection works.)
- **Prototype:** N/A — standard middleware + two tables + Slack reuse; no UI/state uncertainty. Tripwire thresholds are config (start conservative), not a design unknown.
- **TDD/verification:** APPLIES. Public seam = middleware behavior + freeze gate + admin freeze routes. Write these vertical tests **FIRST**, then implement:
  1. `BAKER_SECURITY_FREEZE=1` (or DB `global_freeze=true`) → protected route returns **503**; `/health` + `/api/security/*` still **200**.
  2. A successful request writes **exactly one** `security_access_log` row with **no body/secret columns** (assert the row has only metadata fields).
  3. An auth-failure (401) is logged and increments the per-key auth-fail counter feeding the tripwire.
  4. Simulated bulk read (N sensitive requests in the window) → **one** Slack alarm (rate-limited, not N alarms).

### Implementation

**Step 0 — anti-shadow pre-check.**
```bash
grep -n "security_access_log\|security_freeze\|/api/security\|BAKER_SECURITY_FREEZE" outputs/dashboard.py
```
Confirm none exist before adding.

**Step 1 — New module `security/access_guard.py`** (keeps `dashboard.py` lean). Core contract:

```python
# security/access_guard.py
import os, time, hmac, hashlib, logging
from datetime import datetime, timezone
logger = logging.getLogger(__name__)

# Routes exempt from the FREEZE gate (must stay reachable while frozen).
FREEZE_EXEMPT_PREFIXES = ("/health", "/healthz", "/api/security")

def _hash(s: str) -> str:
    return hashlib.sha256((s or "").encode()).hexdigest()[:16]

def ensure_security_schema(conn) -> None:
    """CREATE TABLE IF NOT EXISTS for the two security tables. Mirror of the
    migration in migrations/20260628_security_access_log.sql (Lesson #50)."""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS security_access_log (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT NOW(),
                request_id TEXT,
                key_fp TEXT,            -- sha256 prefix of presented key, NEVER the key
                actor_label TEXT,       -- 'master' | 'ai-hotel-session' | 'anonymous'
                method TEXT,
                path_template TEXT,     -- route template, not raw sensitive URL values
                route_group TEXT,
                status_code INTEGER,
                latency_ms INTEGER,
                response_bytes INTEGER,
                client_ip_hash TEXT,
                user_agent_hash TEXT,
                origin TEXT,
                anomaly_flags TEXT      -- comma-joined flags, empty if none
            )
        """)
        cur.execute("""CREATE TABLE IF NOT EXISTS security_freeze (
                id INTEGER PRIMARY KEY DEFAULT 1,
                global_freeze BOOLEAN NOT NULL DEFAULT FALSE,
                reason TEXT, set_by TEXT, set_at TIMESTAMPTZ,
                CONSTRAINT security_freeze_singleton CHECK (id = 1)
            )""")
        cur.execute("INSERT INTO security_freeze (id, global_freeze) VALUES (1, FALSE) ON CONFLICT (id) DO NOTHING")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sal_ts ON security_access_log (ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sal_key_ts ON security_access_log (key_fp, ts)")
        conn.commit(); cur.close()
        logger.info("security tables verified")
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"ensure_security_schema failed: {e}")
```

`is_frozen()` — **fail-CLOSED** when a freeze is intended, with an env backstop for Neon outages:
```python
_FREEZE_CACHE = {"v": None, "ts": 0.0}

def is_frozen() -> tuple[bool, str]:
    # Env backstop wins immediately (boot-time emergency lock; survives DB outage).
    if os.getenv("BAKER_SECURITY_FREEZE", "").strip() in ("1", "true", "True"):
        return True, "env BAKER_SECURITY_FREEZE"
    now = time.time()
    if _FREEZE_CACHE["v"] is not None and now - _FREEZE_CACHE["ts"] < 3:  # 3s cache
        return _FREEZE_CACHE["v"]
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return False, ""   # DB down: env backstop above is the only freeze path
    try:
        cur = conn.cursor()
        cur.execute("SELECT global_freeze, COALESCE(reason,'') FROM security_freeze WHERE id=1 LIMIT 1")
        row = cur.fetchone(); cur.close()
        res = (bool(row[0]), row[1]) if row else (False, "")
        _FREEZE_CACHE.update(v=res, ts=now)
        return res
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        logger.warning(f"is_frozen check failed: {e}")
        return False, ""
    finally:
        store._put_conn(conn)
```

`record_access(...)` — single cheap bounded INSERT, **metadata only**, fault-tolerant (audit failure must NEVER break the request → fail-OPEN but log loud).
`security_alarm_send(text)` — copy `cost_monitor._send_hard_stop_alert` body; post to channel from `os.getenv("BAKER_SECURITY_SLACK_CHANNEL", "#cockpit")`; rate-limit via a once-per-window DB claim mirroring `_claim_tier_alert`; **fail-loud** log if `SLACK_BOT_TOKEN` missing. (This is Slack, so it is already outside `BAKER_BLOCK_EMAIL/WA_TO_DIRECTOR` — verify with a test that asserts both block-flags `true` yet the alarm still fires.)
`evaluate_tripwire(...)` — cheap synchronous flags only (per-key request count in window, new IP/UA for key, off-hours burst, repeated 401s, large `response_bytes`). Heavy aggregation runs on a **60s throttle** like the watchdog, not per-request.

**Step 2 — Wire the middleware in `outputs/dashboard.py`, defined AFTER `scheduler_watchdog_middleware` (so it is outermost):**
```python
@app.middleware("http")
async def security_guard_middleware(request, call_next):
    from security import access_guard as guard
    path = request.url.path
    # 1) FREEZE GATE — runs before any handler work. Fail-closed via env backstop.
    try:
        frozen, reason = guard.is_frozen()
    except Exception:
        frozen, reason = False, ""   # DB-path errors never hard-block; env backstop covers intent
    if frozen and not path.startswith(guard.FREEZE_EXEMPT_PREFIXES):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "service_frozen", "reason": reason}, status_code=503)
    # 2) Run the request, timed.
    t0 = time.time()
    response = await call_next(request)
    # 3) AUDIT + TRIPWIRE — must never break the response (fail-open, log loud).
    try:
        guard.record_and_evaluate(request, response, latency_ms=int((time.time()-t0)*1000))
    except Exception as e:
        logger.warning(f"security audit failed (non-fatal): {e}")
    return response
```
`JSONResponse` is already imported (used widely in `dashboard.py`). Verify with `grep -n "JSONResponse" outputs/dashboard.py`.

**Step 3 — Call `ensure_security_schema(conn)` once at startup**, alongside the existing schema bootstraps (find the startup block that calls the other `ensure_*`/`CREATE TABLE` bootstraps and add it there, using a fresh `_get_conn()`/`_put_conn()`).

**Step 4 — Three admin routes (header-gated by `Depends(verify_api_key)`), so freeze works WITHOUT redeploy:**
- `POST /api/security/freeze` — body `{reason}` → set `global_freeze=true, set_by, set_at`; clears `_FREEZE_CACHE`; fires `security_alarm_send("FREEZE engaged")`.
- `POST /api/security/unfreeze` — set false; clears cache; alarm "FREEZE lifted".
- `GET /api/security/status` — current freeze state + last 20 anomaly rows (`... ORDER BY ts DESC LIMIT 20`).
These paths are in `FREEZE_EXEMPT_PREFIXES` so you can unfreeze while frozen.

**Step 5 — Migration `migrations/20260628_security_access_log.sql`** — byte-equivalent DDL to `ensure_security_schema` (Lesson #50). Do NOT edit `applied_migrations.lock` unless prod has been hand-applied (CLAUDE.md rule).

### Key Constraints
- **Metadata only.** NEVER store request/response bodies, query values, secrets, key material, or email/WA text. Store `key_fp` (sha256 prefix), `client_ip_hash`, `user_agent_hash` — never raw.
- **Freeze fails CLOSED via env backstop; audit fails OPEN.** A logging error must not 500 the API. A freeze DB-read error must not silently unblock — that is why `BAKER_SECURITY_FREEZE=1` env is the boot-time backstop.
- **Hot path: keep it cheap.** Freeze cache ≤3s; one indexed INSERT per request; heavy aggregation throttled to 60s. No per-request full-table scans.
- **Do not change** `verify_api_key` / `_mcp_verify_key` / CORS / `scheduler_watchdog_middleware`.
- Every SQL has a `LIMIT`; every except has `conn.rollback()`.

### Verification
- Tests in `tests/test_security_access_guard.py` (the 4 TDD cases above) pass.
- Live probe (post-deploy, origin-gated): hit `/api/security/freeze` → confirm a protected GET returns 503, `/health` returns 200, then `/api/security/unfreeze` restores 200 — **no redeploy**.
- Simulated leaked-key bulk read (script: 100 sensitive GETs with the key in <1 min) → exactly one Slack alarm; `security_access_log` shows 100 rows, 0 with any body column.
- Emit `POST_DEPLOY_AC_VERDICT v1` on the bus.

---

## Files Modified
- `security/access_guard.py` — NEW (schema, freeze, record/evaluate, alarm).
- `outputs/dashboard.py` — add `security_guard_middleware` (after `:620`), startup `ensure_security_schema` call, 3 `/api/security/*` routes.
- `migrations/20260628_security_access_log.sql` — NEW (mirror DDL).
- `tests/test_security_access_guard.py` — NEW (4 vertical tests).

## Do NOT Touch
- `outputs/dashboard.py:188 verify_api_key`, `:1982 _mcp_verify_key`, `:546 CORS`, `:620 scheduler_watchdog_middleware` — auth + existing middleware stay unchanged.
- `orchestrator/cost_monitor.py` — reuse its Slack pattern by copying, do not edit it.
- `applied_migrations.lock` — do not edit (CLAUDE.md migration rule).

## Quality Checkpoints
1. `/security-review` skill MANDATORY before merge (Lesson #52) — focus: freeze-bypass, route-exemption correctness, no PII/secret in `security_access_log`, SQL parameterization.
2. Confirm middleware ordering: security middleware is outermost (freeze runs before handler).
3. Confirm both `BAKER_BLOCK_EMAIL_TO_DIRECTOR` and `BAKER_BLOCK_WA_TO_DIRECTOR` can be `true` while the Slack alarm still fires.
4. Confirm Render restart survival: tables auto-create at startup; freeze state persists in DB; `BAKER_SECURITY_FREEZE` env backstop works at boot.
5. Latency check: middleware adds <5ms p50 (one indexed INSERT).
6. Exercise the actual flow before "done" (Lesson #8) — not compile-clean.

## Verification SQL
```sql
-- reads logged with zero body/secret columns (schema has none by design)
SELECT count(*) AS rows_24h, count(*) FILTER (WHERE anomaly_flags <> '') AS flagged
FROM security_access_log WHERE ts >= NOW() - INTERVAL '24 hours';

-- freeze state
SELECT global_freeze, reason, set_by, set_at FROM security_freeze WHERE id = 1 LIMIT 1;

-- top talkers by key in last hour (the exfil signal)
SELECT key_fp, count(*) AS calls, SUM(response_bytes) AS bytes
FROM security_access_log WHERE ts >= NOW() - INTERVAL '1 hour'
GROUP BY key_fp ORDER BY calls DESC LIMIT 10;
```

## Dispatch
- `dispatched_by:` lead → ship-report routes to lead.
- Suggested worker: any free B-code (verified b1–b4 idle on merged branches). Gate chain: G2 (worker self-review) → G3 (codex independent) → G4 `/security-review` (lead) → merge. Phase 1 ships behind no flag (middleware is additive; freeze defaults false) — rollback = revert the commit.
