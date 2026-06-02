# BRIEF: BRISEN_LAB_DB_CONN_HARDEN_1 (v2) — Stop the bus daemon hanging on stale Neon connections

> **v2 recut** after Codex G0 verdict **PASS-WITH-CHANGES** (2026-06-01). Folds all 6 Codex changes: direct-endpoint w/ connection-budget check, `options` only on direct, verify `tcp_user_timeout` in prod, keep checkout `SELECT 1`, prove autosuspend, add PoolError→503 handling, robust host parse + tests. Direction (root cause + fix) was confirmed by Codex; this version is the dispatch-ready cut.

## Context
2026-06-01 incident: every DB-backed endpoint on `brisen-lab.onrender.com` hung ~30–35s and returned nothing — authenticated reads (`/event/{id}/full`, `/msg/{terminal}`), ACK (`POST /msg/{id}/ack`), AND the unauthenticated card feed (`/api/v2/terminals`). Dashboard cards never lit; Architect + Codex wasted ~10 min, got through only via direct-Postgres. A Render restart of `srv-d7q7kvlckfvc739l2e8g` cleared it instantly (reads 35s→<2s), confirming the DB **connection layer**, not auth and not Neon itself.

**Root cause (verified):** `~/bm-b1-brisen-lab/db.py:37` builds `ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)` with **no `connect_timeout`, no keepalives, no `statement_timeout`, no `tcp_user_timeout`, no liveness check**. `DATABASE_URL` points at Neon's **POOLED** endpoint (`ep-summer-sun-aih7ha4h-pooler...neon.tech`). Neon autosuspends compute after idle; the pooled upstream drops; the daemon's pooled connection goes half-open (`conn.closed` stays 0). The next query blocks on the dead socket with no timeout until the client gives up (~30s). Restart = fresh pool = works until the next idle. Same class as baker-master `SCHEDULER_LIVENESS_REVIVE_1`.

### Surface contract: N/A — pure backend (`db.py` connection layer). No user-clickable surface changes. (Card behaviour improves as a side-effect; no markup/route edits.)

## Target repo: brisen-lab (`vallen300-bit/brisen-lab`); checkout `~/bm-b1-brisen-lab`
## Estimated time: ~2.5h
## Complexity: Medium (was Low — connection-budget pre-flight + PoolError path added)
## Prerequisites: Fix 0 connection-budget check MUST pass before flipping to direct.

---

## Fix 0 (PREREQUISITE — Codex required): Neon connection-budget check before switching to DIRECT
The pooled endpoint allows thousands of client conns via PgBouncer; the **direct** endpoint consumes **real** Postgres connections counted against `max_connections`. Confirm headroom BEFORE Fix 1.

- Known consumers on the shared Neon (worst-case pool maxconns): brisen-lab **10** (this) + baker-master `store_back` **5** + `deadlines` **3** + `contact_writer` **2** ≈ **20** worst-case, plus the dashboard's own pool.
- Run on the DIRECT endpoint: `SHOW max_connections;` and `SELECT count(*) FROM pg_stat_activity;`.
- **Gate:** combined steady-state + headroom must stay comfortably under `max_connections`. If margin is thin, keep `maxconn=10` (do NOT raise) and note it in the ship report. If `max_connections` is unexpectedly low (small Neon compute), STOP and escalate to AH1 before flipping.

---

## Fix 1: Point the pool at Neon's DIRECT endpoint + bound every connection

### Implementation
1. Robust host rewrite (Codex: do NOT use naive `dsn.replace("-pooler.", ".")`). Parse and replace only the hostname segment, preserving userinfo/port/query:
```python
import os
import urllib.parse as _u

def _dsn() -> str:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL not set; cannot initialize Brisen Lab DB pool")
    parts = _u.urlsplit(raw)
    host = parts.hostname or ""
    if "-pooler." in host:
        direct_host = host.replace("-pooler.", ".", 1)
        userinfo = ""
        if parts.username:
            userinfo = _u.quote(parts.username, safe="")
            if parts.password:
                userinfo += ":" + _u.quote(parts.password, safe="")
            userinfo += "@"
        netloc = f"{userinfo}{direct_host}" + (f":{parts.port}" if parts.port else "")
        parts = parts._replace(netloc=netloc)
    return _u.urlunsplit(parts)
```
2. Connection kwargs — `options=` is valid ONLY on the direct endpoint (Codex: Neon's PgBouncer restricts startup parameters and is not user-configurable):
```python
_CONN_KW = dict(
    connect_timeout=5,                      # cap the handshake
    keepalives=1, keepalives_idle=30,
    keepalives_interval=10, keepalives_count=3,
    tcp_user_timeout=15000,                 # ms: abort a dead-socket query fast (~15s), not 30s+
    options="-c statement_timeout=15000",   # DIRECT-only; pooled would reject the startup param
)
```
3. Build the pool with these:
```python
_pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=_dsn(), **_CONN_KW)
```

### Key Constraints
- Keep `maxconn=10` unless Fix 0 explicitly clears a higher number.
- If `_dsn()` finds no `-pooler` (already direct), it must return the URL unchanged.

---

## Fix 2: Recycle a dead connection on checkout (bounded probe)

### Implementation
```python
@contextmanager
def get_conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        if conn.closed:
            raise psycopg2.OperationalError("pooled connection already closed")
        with conn.cursor() as cur:        # liveness probe — bounded by tcp_user_timeout/keepalives
            cur.execute("SELECT 1")
            cur.fetchone()
    except psycopg2.Error:
        try:
            pool.putconn(conn, close=True)  # discard the dead one
        except Exception:
            pass
        conn = pool.getconn()               # fresh connect, bounded by connect_timeout
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
```
- Codex confirmed the per-checkout `SELECT 1` round-trip is acceptable for a P1 fleet-reliability fix. (Future optimization, NOT now: age-gate the probe if cross-region latency becomes visible.)

---

## Fix 3 (Codex required): handle pool exhaustion — fast 503, never a hang
`ThreadedConnectionPool.getconn()` raises `PoolError("connection pool exhausted")` at `maxconn`; `asyncio.to_thread`'s default executor can exceed 10 workers under burst. Today that PoolError is unhandled.

### Implementation
1. In `db.py`, define a typed exception and catch PoolError on BOTH `getconn()` calls in `get_conn()`:
```python
from psycopg2.pool import PoolError

class BusPoolExhausted(Exception):
    """Pool at maxconn — surface as 503, never block."""

# inside get_conn(), wrap each pool.getconn():
try:
    conn = pool.getconn()
except PoolError as e:
    raise BusPoolExhausted(str(e))
```
2. In `bus.py` (or `app.py` where `app` is defined), register a handler so it returns 503, not 500/hang:
```python
@app.exception_handler(BusPoolExhausted)
async def _pool_exhausted_handler(request, exc):
    return JSONResponse(status_code=503, content={"detail": "bus_busy_retry"})
```
3. (Defensive complement, optional but recommended) bound the default thread executor to the pool size at startup so the read path cannot outrun `maxconn`:
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
# at startup:
asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=10))
```

---

## Tests (Codex required) — add under `~/bm-b1-brisen-lab/tests/`
1. **direct-host conversion:** `_dsn()` turns `postgresql://u:p@ep-x-pooler.c-4.us-east-1.aws.neon.tech:5432/neondb?sslmode=require` into the `ep-x.c-4...` host, preserving user/pass/port/query; and leaves an already-direct host unchanged.
2. **connection kwargs:** monkeypatch `ThreadedConnectionPool` to capture kwargs; assert `connect_timeout`, `keepalives*`, `tcp_user_timeout`, and `options` containing `statement_timeout` are passed.
3. **dead-connection recycle:** a checked-out conn whose probe raises `psycopg2.OperationalError` (or `conn.closed`) → `get_conn()` calls `putconn(conn, close=True)` and returns a fresh conn.
4. **pool exhaustion:** `pool.getconn()` raising `PoolError` → `BusPoolExhausted` → handler returns 503 (not a hang/500).

## Files Modified
- `~/bm-b1-brisen-lab/db.py` — `_dsn()`, `_CONN_KW`, pool build, `get_conn()` recycle + PoolError.
- `~/bm-b1-brisen-lab/bus.py` (or `app.py`) — `BusPoolExhausted` exception handler; optional executor bound at startup.
- `~/bm-b1-brisen-lab/tests/` — the 4 tests above.

## Do NOT Touch
- `bus.py` request handlers' logic — they already correctly use `asyncio.to_thread`.
- `maxconn`/`minconn` values (unless Fix 0 clears a change).
- The secret-scrubber block in `db.py`.

## Quality Checkpoints + Verification
1. `python3 -c "import py_compile; py_compile.compile('db.py', doraise=True)"` clean; `pytest` green.
2. **Dead-socket fast-fail proof (Codex):** force a dead socket (kill the server-side connection, or trigger a Neon suspend) → the next query fails/recovers in **~15s max** (tcp_user_timeout), NOT 30s+. This is the acceptance test that proves the prod fix.
3. **Idle-recovery proof:** after idle ≥ Neon autosuspend window, `/api/v2/terminals` and `/event/{id}/full` respond **<2s**.
4. **Autosuspend confirmation (Codex):** check Neon console for scale-to-zero/suspend events around the 2026-06-01 stall windows — confirm the trigger.
5. **Budget re-check:** post-switch `SELECT count(*) FROM pg_stat_activity` stays well under `max_connections`.
6. PoolError path returns 503 under simulated burst, not a hang.

## Gate plan
- **G0** — Codex Architect: **PASS-WITH-CHANGES** received 2026-06-01; all 6 changes folded into this v2. (Re-confirm optional; changes are unambiguous.)
- **G1** — AH1 fold/static review.
- **G3** — AH2 deputy gate.
- **Post-deploy AC (mandatory)** — Checkpoints 2 + 3: the bug only manifests after idle/dead-socket, so a green deploy is NOT proof. Run post-deploy-ac-bus-gate.
- **G2 `/security-review`** — not required (connection-layer only, no auth/secret surface change); Codex concurred.
