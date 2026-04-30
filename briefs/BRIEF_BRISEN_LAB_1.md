# BRIEF: BRISEN_LAB_1 — Brisen Lab observe-only dashboard for the 6 Claude Code terminals

## Context

Director wants Hermes-Workspace-style visibility into what each Claude Code terminal (Lead, Deputy, B1–B4) is doing. Today there is no central view — Director has to tab through 6 Terminal.app windows manually. Brisen Lab is a **separate Render service** at `brisen-lab.onrender.com` that gives:

- 6 cards (hub-and-spoke layout: Lead + Deputy on top, B1–B4 below)
- Live structured event stream per terminal (tool calls, messages, prompts) via SSE
- Activity timeline across all 6
- Status (idle / working / waiting), current task (from mailbox file), last commit, open PR

Source for "what each terminal is doing" = Claude Code session JSONL files (`~/.claude/projects/<encoded-path>/<session-uuid>.jsonl`), which Claude Code already writes live and which capture every user prompt, assistant response, and tool call with timestamps. **No tmux, no terminal stdout capture.**

This brief covers v1 (observe-only). v2 (Conductor mode — spawn b1-b4 from UI) is parked.

All 13 Q&A decisions ratified by Director 2026-04-30 — see this brief's "Locked decisions" section.

## Estimated time: ~14-18h (1-2 weeks of b5 wall clock)
## Complexity: Medium-High (4 components; v1.0 includes architect-flagged hardening — connection pool, secret scrubber, unmapped-event buffer, daily retention, SSE keepalive)
## Prerequisites
- New GitHub repo `vallen300-bit/brisen-lab` (must be created before Part 1).
- New Render Web Service (Starter $7/mo) pointing at the new repo, auto-deploy from `main`.
- Reuse existing Neon Postgres (baker-master's `DATABASE_URL`) — new `forge_*` tables in same database.
- Reactivate `~/bm-b5` (currently dormant) as the build worktree for this brief.

## Locked decisions (all ratified by Director 2026-04-30)

| # | Topic | Locked decision |
|---|---|---|
| Architecture | Path | Path C — observe-only v1; Conductor (spawn) mode parked for v2. |
| 1 | Access | Public URL + `X-Forge-Key` header. No auth wall. |
| 2 | Scope v1 | Status board + activity timeline + **live structured event stream via SSE** (richer than tmux scrollback). |
| 3 | Database | Reuse Neon (`DATABASE_URL`), new `forge_*` schema. |
| 4 | MacBook agent | launchd LaunchAgent. Tails JSONL files + polls git/mailbox. Claude Code `SessionStart` hook for terminal-alias registration. |
| 5 | Repo | New standalone `vallen300-bit/brisen-lab`. |
| 6 | Render plan | Starter ($7/mo). |
| 7 | Frontend | Vanilla HTML/JS, no build step. xterm.js NOT used in v1 — events render as structured cards via safe DOM construction (no innerHTML). |
| 8 | Terminal ID | Terminal alias (`lead`, `deputy`, `b1`–`b4`) registered at SessionStart via `$FORGE_TERMINAL` env var. Card label = alias; event key = Claude Code session UUID. |
| 9 | Aliases | Lead, Deputy, B1, B2, B3, B4. |
| 10 | Name + URL | Brisen Lab — `brisen-lab.onrender.com`. |
| 11 | Build owner | b5 (reactivated, isolated from baker-master B-pool). |
| 12 | Layout | Hub-and-spoke: Lead + Deputy top (large), B1–B4 below (workers), timeline right sidebar, click card → expand event panel. |
| 13 | Alerts | Passive only. No outbound notifications. |

---

## DB schema verified

These tables do not exist yet — Part 1 creates them. No conflict with baker-master's existing schema (which uses no `forge_*` prefix; verified via `\dt forge_*` returning empty).

Existing `DATABASE_URL` Postgres is the baker-master Neon instance. Brisen Lab adds three new tables in the same DB.

---

## Part 1: Render service skeleton (FastAPI + Postgres schema)

### Problem
We need a public Render endpoint that:
- Accepts events from the MacBook daemon (`POST /api/event`, `POST /api/snapshot`, `POST /api/register`).
- Streams live events to browser (`GET /sse/stream`).
- Serves the UI (`GET /`, `GET /static/*`).
- Returns initial state for first paint (`GET /api/state`).

### Current State
Nothing exists. New repo, new service.

### Implementation

**Repo layout** (in `vallen300-bit/brisen-lab`):
```
brisen-lab/
├── app.py                  # FastAPI app — single file, ~250 lines
├── db.py                   # Postgres connection helper + schema bootstrap
├── requirements.txt
├── start.sh                # Render entrypoint
├── render.yaml             # Render service spec
├── static/
│   ├── index.html
│   ├── app.js
│   └── styles.css
└── README.md
```

**`requirements.txt`:**
```
fastapi==0.115.0
uvicorn==0.32.0
psycopg2-binary==2.9.9
python-dotenv==1.0.1
```

**`start.sh`:**
```bash
#!/bin/bash
exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8080}"
```

**`render.yaml`:**
```yaml
services:
  - type: web
    name: brisen-lab
    runtime: python
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: bash start.sh
    envVars:
      # NOTE on naming: baker-master uses split POSTGRES_HOST/USER/DB/PASSWORD
      # env vars on this same Neon instance. Brisen Lab uses a single
      # DATABASE_URL DSN here. Same database, different env convention.
      # Set DATABASE_URL = "postgresql://<user>:<pass>@<host>/<db>?sslmode=require"
      # using the same credentials baker-master already uses.
      - key: DATABASE_URL
        sync: false
      - key: FORGE_KEY
        sync: false
      - key: ALLOWED_ORIGINS
        value: "https://brisen-lab.onrender.com"
```

**`db.py`:**
```python
import os
import re
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

DATABASE_URL = os.environ["DATABASE_URL"]

# Connection pool — protects baker-master's Neon from connection starvation.
# Brisen Lab shares the same Neon instance; uncapped psycopg2.connect() per
# request can exhaust the connection limit during event bursts.
#
# maxconn=10 (not 5) because handlers are sync `def` running in FastAPI's
# threadpool — concurrent requests can outnumber 5 under burst, and exhausting
# the pool would block threadpool workers waiting on getconn().
_pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)

@contextmanager
def get_conn():
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)

# Secret scrubber — defence-in-depth. Applied server-side before INSERT into
# forge_events; agent-side scrubber (in agent.py) is the first line of defence.
# Any user-pasted prompt could contain an API key — JSONL captures everything.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),               # OpenAI / Anthropic-style (incl. sk-ant-…)
    re.compile(r"sk_live_[A-Za-z0-9]{24,}"),              # Stripe live secret keys (underscore form)
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{20,}"),         # Slack tokens
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]+"),  # JWT
    re.compile(r"AKIA[A-Z0-9]{16}"),                       # AWS access key id
    re.compile(r"AC[a-f0-9]{32}"),                         # Twilio account SID / auth tokens
    re.compile(r"ghp_[A-Za-z0-9]{36}"),                    # GitHub classic PAT
    re.compile(r"github_pat_[A-Za-z0-9_]{60,}"),           # GitHub fine-grained PAT
    re.compile(r"voyage-[A-Za-z0-9]{20,}"),                # Voyage AI
    re.compile(r"AIza[A-Za-z0-9_\-]{35}"),                 # Google API key
    re.compile(r"1//0[A-Za-z0-9_\-]{40,}"),                # Google OAuth refresh tokens
]

def scrub_secrets(value):
    if isinstance(value, str):
        out = value
        for pat in _SECRET_PATTERNS:
            out = pat.sub("[REDACTED]", out)
        return out
    if isinstance(value, dict):
        return {k: scrub_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_secrets(v) for v in value]
    return value

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS forge_sessions (
    id SERIAL PRIMARY KEY,
    session_uuid TEXT NOT NULL UNIQUE,
    terminal_alias TEXT NOT NULL,
    project_path TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS forge_sessions_alias_idx ON forge_sessions(terminal_alias, started_at DESC);

CREATE TABLE IF NOT EXISTS forge_events (
    id BIGSERIAL PRIMARY KEY,
    session_uuid TEXT NOT NULL,
    terminal_alias TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS forge_events_alias_time_idx ON forge_events(terminal_alias, occurred_at DESC);
CREATE INDEX IF NOT EXISTS forge_events_session_time_idx ON forge_events(session_uuid, occurred_at DESC);

CREATE TABLE IF NOT EXISTS forge_snapshots (
    id BIGSERIAL PRIMARY KEY,
    terminal_alias TEXT NOT NULL,
    git_branch TEXT,
    git_head_sha TEXT,
    git_head_subject TEXT,
    mailbox_path TEXT,
    mailbox_status TEXT,
    mailbox_brief_name TEXT,
    open_pr_number INT,
    open_pr_title TEXT,
    daemon_last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (terminal_alias)
);
"""

def bootstrap():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
```

Allowed values for `event_type`: `user_prompt`, `assistant_message`, `tool_use`, `tool_result`, `session_start`, `session_stop`. (Stored as TEXT, not enum, for forward compatibility.)

**`app.py`** (skeleton — key endpoints shown; full file ~280 lines):
```python
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg2.extras import RealDictCursor

from db import get_conn, bootstrap, scrub_secrets

# Fail-fast on missing config, with a clear log line so Render's restart loop
# is diagnosable from logs (not just an opaque KeyError stack).
try:
    FORGE_KEY = os.environ["FORGE_KEY"]
except KeyError:
    print("FATAL: FORGE_KEY env var not set; service cannot start", file=sys.stderr, flush=True)
    raise

TERMINALS = ["lead", "deputy", "b1", "b2", "b3", "b4"]

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory pub/sub for SSE — single-instance, no clustering needed on Starter
_subscribers: list[asyncio.Queue] = []

@app.on_event("startup")
async def _startup():
    bootstrap()
    asyncio.create_task(_retention_loop())

async def _retention_loop():
    """Daily DELETE of forge_events older than 14 days. Prevents unbounded growth
    on shared Neon instance. Runs forever, swallows errors. DB block offloaded
    to a thread so the blocking pool doesn't stall the event loop."""
    def _do():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM forge_events WHERE occurred_at < NOW() - INTERVAL '14 days'"
                )
    while True:
        try:
            await asyncio.to_thread(_do)
        except Exception as e:
            print(f"[retention] {e}", file=sys.stderr, flush=True)
        await asyncio.sleep(86400)  # 24h

def _check_key(x_forge_key):
    if x_forge_key != FORGE_KEY:
        raise HTTPException(status_code=401, detail="bad forge key")

# Handlers that touch the blocking psycopg2 pool are declared `def` (NOT
# `async def`). FastAPI runs sync `def` handlers in a threadpool so blocking
# I/O does not stall the event loop. The /sse/stream handler stays async
# because it actually awaits the pub/sub queue. _broadcast is also sync since
# Queue.put_nowait does not await.

@app.get("/")
def index():
    return FileResponse("static/index.html")

@app.post("/api/register")
async def register(req: Request, x_forge_key: str = Header(None)):
    # async to await req.json(); DB block is offloaded to a sync helper run
    # in a thread to avoid blocking the event loop.
    _check_key(x_forge_key)
    body = await req.json()
    session_uuid = body["session_uuid"]
    terminal_alias = body["terminal_alias"]
    project_path = body.get("project_path", "")
    if terminal_alias not in TERMINALS:
        raise HTTPException(status_code=400, detail=f"unknown alias {terminal_alias}")
    def _do():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO forge_sessions (session_uuid, terminal_alias, project_path)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_uuid) DO UPDATE SET last_seen_at = NOW()
                """, (session_uuid, terminal_alias, project_path))
    await asyncio.to_thread(_do)
    _broadcast({"kind": "register", "terminal_alias": terminal_alias, "session_uuid": session_uuid})
    return {"ok": True}

@app.post("/api/event")
async def event(req: Request, x_forge_key: str = Header(None)):
    _check_key(x_forge_key)
    body = await req.json()
    session_uuid = body["session_uuid"]
    terminal_alias = body["terminal_alias"]
    event_type = body["event_type"]
    payload = scrub_secrets(body.get("payload", {}))   # defence-in-depth
    occurred_at = body.get("occurred_at") or datetime.now(timezone.utc).isoformat()
    def _do():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO forge_events (session_uuid, terminal_alias, event_type, payload, occurred_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (session_uuid, terminal_alias, event_type, json.dumps(payload), occurred_at))
                cur.execute("""
                    UPDATE forge_sessions SET last_seen_at = NOW() WHERE session_uuid = %s
                """, (session_uuid,))
    await asyncio.to_thread(_do)
    _broadcast({"kind": "event", "terminal_alias": terminal_alias,
                "event_type": event_type, "payload": payload, "occurred_at": occurred_at})
    return {"ok": True}

@app.post("/api/snapshot")
async def snapshot(req: Request, x_forge_key: str = Header(None)):
    _check_key(x_forge_key)
    body = await req.json()
    alias = body["terminal_alias"]
    if alias not in TERMINALS:
        raise HTTPException(status_code=400, detail=f"unknown alias {alias}")
    def _do():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO forge_snapshots
                      (terminal_alias, git_branch, git_head_sha, git_head_subject,
                       mailbox_path, mailbox_status, mailbox_brief_name,
                       open_pr_number, open_pr_title, daemon_last_seen)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (terminal_alias) DO UPDATE SET
                      git_branch = EXCLUDED.git_branch,
                      git_head_sha = EXCLUDED.git_head_sha,
                      git_head_subject = EXCLUDED.git_head_subject,
                      mailbox_path = EXCLUDED.mailbox_path,
                      mailbox_status = EXCLUDED.mailbox_status,
                      mailbox_brief_name = EXCLUDED.mailbox_brief_name,
                      open_pr_number = EXCLUDED.open_pr_number,
                      open_pr_title = EXCLUDED.open_pr_title,
                      daemon_last_seen = NOW()
                """, (alias, body.get("git_branch"), body.get("git_head_sha"),
                      body.get("git_head_subject"), body.get("mailbox_path"),
                      body.get("mailbox_status"), body.get("mailbox_brief_name"),
                      body.get("open_pr_number"), body.get("open_pr_title")))
    await asyncio.to_thread(_do)
    _broadcast({"kind": "snapshot", "terminal_alias": alias, "snapshot": body})
    return {"ok": True}

@app.get("/api/state")
def state():
    """Initial-paint state: snapshot per terminal + last 50 events."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT terminal_alias, git_branch, git_head_sha, git_head_subject,
                       mailbox_status, mailbox_brief_name, open_pr_number, open_pr_title,
                       daemon_last_seen
                FROM forge_snapshots
                LIMIT 20
            """)
            snapshots = {row["terminal_alias"]: dict(row) for row in cur.fetchall()}
            cur.execute("""
                SELECT terminal_alias, event_type, payload, occurred_at
                FROM forge_events
                WHERE occurred_at >= %s
                ORDER BY occurred_at DESC
                LIMIT 50
            """, (cutoff,))
            events = [dict(row) for row in cur.fetchall()]
    return JSONResponse({"snapshots": snapshots, "events": events,
                         "now": datetime.now(timezone.utc).isoformat()})

@app.get("/sse/stream")
async def sse_stream():
    queue = asyncio.Queue(maxsize=200)
    _subscribers.append(queue)
    async def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            # Heartbeat every 25s — Render cuts idle connections after ~110s.
            # SSE comments (`: …\n\n`) are ignored by EventSource but keep the
            # TCP connection alive.
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            try:
                _subscribers.remove(queue)
            except ValueError:
                pass
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

def _broadcast(msg):
    """Sync — Queue.put_nowait does not await. Callable from any context."""
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try: _subscribers.remove(q)
        except ValueError: pass

@app.get("/healthz")
def healthz():
    return {"ok": True}
```

### Key Constraints
- **No auth wall** — only `X-Forge-Key` header gates writes. Read endpoints (`/`, `/api/state`, `/sse/stream`) are public.
- **Single FastAPI instance** — Render Starter is one container; in-process `_subscribers` queue is fine. Do NOT add Redis or external pub/sub.
- **`bootstrap()` is idempotent** (`CREATE TABLE IF NOT EXISTS`) — safe to run on every startup.
- **All Postgres SELECTs have LIMIT** (per lessons.md unbounded-queries anti-pattern).
- **`conn.rollback()` is in the context manager** — applies to every except path.

### Verification
1. Push to `main` of `vallen300-bit/brisen-lab`. Render auto-deploys.
2. `curl https://brisen-lab.onrender.com/healthz` → `{"ok": true}`.
3. `curl -X POST https://brisen-lab.onrender.com/api/event -H "X-Forge-Key: $FORGE_KEY" -H "Content-Type: application/json" -d '{"session_uuid":"test-1","terminal_alias":"b1","event_type":"tool_use","payload":{"tool":"Read"}}'` → `{"ok":true}`.
4. `psql $DATABASE_URL -c "SELECT * FROM forge_events ORDER BY id DESC LIMIT 5"` shows the test row.
5. Open `https://brisen-lab.onrender.com/sse/stream` in browser — see `event: hello` then live events as you POST more.

---

## Part 2: MacBook daemon (`forge-agent`)

### Problem
Render needs events. Source is on MacBook (Claude Code JSONL files + git/mailbox state). Need a daemon that:
- Tails 6+ JSONL files in real time, parses each new line, POSTs structured events.
- Polls each worktree (git head, mailbox brief, last activity), POSTs snapshot every 30s.
- Auto-restarts on crash, auto-starts at login.

### Current State
None. JSONL files exist (`~/.claude/projects/<encoded-path>/<uuid>.jsonl`) and update live as Claude works. Each terminal runs a separate Claude session = separate JSONL file. For shared project dirs (Lead + Deputy share `~/Desktop/baker-code`), multiple JSONL files coexist in the same project folder — disambiguated by SessionStart hook (Part 3) which maps `session_uuid → terminal_alias`.

### Implementation

**Location:** `~/forge-agent/` (not in any git repo — local-only daemon).

**`~/forge-agent/agent.py`** (~380 lines):
```python
"""
Brisen Lab — MacBook agent.

Two loops in one process:
  1. JSONL tailer per terminal — emits structured events to /api/event.
  2. Worktree poller (30s) — emits state snapshots to /api/snapshot.

Identity: terminal_alias is registered by SessionStart hook (Part 3) —
this agent reads ~/forge-agent/sessions.json to map session_uuid → alias.

Race-tolerance: events for unmapped session_uuids are buffered (per session,
cap 50, TTL 30s). When the SessionStart hook eventually writes sessions.json,
the next tail-loop cycle picks up the alias and flushes the buffer. This means
the FIRST user_prompt of every session — the one that arrives before the bash
hook's python+curl chain finishes — is preserved instead of dropped.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from collections import deque
import httpx

LAB_URL = os.environ.get("LAB_URL", "https://brisen-lab.onrender.com")
FORGE_KEY = os.environ["FORGE_KEY"]
HOME = Path.home()
PROJECTS_DIR = HOME / ".claude" / "projects"
SESSIONS_FILE = HOME / "forge-agent" / "sessions.json"

WORKTREES = {
    "lead":   HOME / "Desktop" / "baker-code",
    "deputy": HOME / "Desktop" / "baker-code",
    "b1":     HOME / "bm-b1",
    "b2":     HOME / "bm-b2",
    "b3":     HOME / "bm-b3",
    "b4":     HOME / "bm-b4",
}

MAILBOX_FILE = {
    "b1": "briefs/_tasks/CODE_1_PENDING.md",
    "b2": "briefs/_tasks/CODE_2_PENDING.md",
    "b3": "briefs/_tasks/CODE_3_PENDING.md",
    "b4": "briefs/_tasks/CODE_4_PENDING.md",
}

# ---- Secret scrubber (first line of defence; db.py runs the same patterns server-side) ----
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"sk_live_[A-Za-z0-9]{24,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]+"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"AC[a-f0-9]{32}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{60,}"),
    re.compile(r"voyage-[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{35}"),
    re.compile(r"1//0[A-Za-z0-9_\-]{40,}"),
]

def _scrub(value):
    if isinstance(value, str):
        out = value
        for pat in _SECRET_PATTERNS:
            out = pat.sub("[REDACTED]", out)
        return out
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value

# ---- sessions.json cache (mtime-keyed) ----
# Re-reading the file per-line under tail load thrashes disk. Cache it and
# only reload when the file's mtime changes.
_sessions_cache: dict = {}
_sessions_mtime: float = 0.0

def _load_sessions():
    global _sessions_cache, _sessions_mtime
    try:
        st = SESSIONS_FILE.stat()
    except FileNotFoundError:
        _sessions_cache, _sessions_mtime = {}, 0.0
        return _sessions_cache
    if st.st_mtime != _sessions_mtime:
        try:
            _sessions_cache = json.loads(SESSIONS_FILE.read_text())
            _sessions_mtime = st.st_mtime
        except Exception:
            pass  # keep prior cache on parse error
    return _sessions_cache

# ---- Unmapped-event buffer (per session_uuid, cap 50, TTL 30s) ----
# When a JSONL line arrives before the SessionStart hook has registered the
# session, we buffer rather than drop. Flush on the next iteration that finds
# an alias mapping. Drop entries older than 30s — by then the hook has either
# succeeded or genuinely failed and the session is unmapped.
_BUF_CAP = 50
_BUF_TTL = 30.0
_unmapped: dict[str, deque] = {}   # sid -> deque[(monotonic_ts, evt_type, payload, occurred_at)]

def _buffer_unmapped(sid, evt_type, payload, occurred_at):
    dq = _unmapped.setdefault(sid, deque(maxlen=_BUF_CAP))
    dq.append((time.monotonic(), evt_type, payload, occurred_at))

def _drain_buffer(sid):
    """Return + clear all non-expired buffered events for sid."""
    dq = _unmapped.pop(sid, None)
    if not dq:
        return []
    now = time.monotonic()
    return [(et, pl, oc) for (ts, et, pl, oc) in dq if (now - ts) <= _BUF_TTL]

def _gc_buffer():
    """Drop expired entries; remove empty deques. Cheap to run frequently."""
    now = time.monotonic()
    dead = []
    for sid, dq in _unmapped.items():
        while dq and (now - dq[0][0]) > _BUF_TTL:
            dq.popleft()
        if not dq:
            dead.append(sid)
    for sid in dead:
        _unmapped.pop(sid, None)

def _project_dir_for(worktree):
    """Claude Code encodes project paths by replacing / with -."""
    encoded = "-" + str(worktree).replace("/", "-")
    return PROJECTS_DIR / encoded

def _classify(line):
    """Map a JSONL line to (event_type, payload). Skip uninteresting lines.
    All text fields are scrubbed before they leave the daemon."""
    t = line.get("type")
    if t == "user":
        msg = line.get("message", {})
        content = msg.get("content", "")
        text = content[:500] if isinstance(content, str) else json.dumps(content)[:500]
        return "user_prompt", _scrub({"text": text})
    if t == "assistant":
        msg = line.get("message", {})
        blocks = msg.get("content", []) if isinstance(msg.get("content"), list) else []
        text_chunks = [b.get("text","") for b in blocks if b.get("type") == "text"]
        tool_uses = [{"name": b.get("name"), "input_preview": json.dumps(b.get("input",{}))[:200]}
                     for b in blocks if b.get("type") == "tool_use"]
        return "assistant_message", _scrub({"text": (" ".join(text_chunks))[:500],
                                            "tool_uses": tool_uses})
    if t == "tool_result":
        return "tool_result", _scrub({"preview": json.dumps(line)[:500]})
    return "", {}

async def tail_jsonl(client, jsonl_path):
    """Tail one JSONL file. Buffers unmapped sessions; flushes on first registration."""
    # If the file was created in the last 60s, start at offset 0 — don't lose
    # the user_prompt that triggered file creation. For older files (daemon
    # restart while sessions exist), start at EOF to avoid replaying history.
    try:
        st = jsonl_path.stat()
        pos = 0 if (time.time() - st.st_mtime) < 60 else st.st_size
    except FileNotFoundError:
        pos = 0
    while True:
        try:
            sz = jsonl_path.stat().st_size
            if sz < pos:
                pos = 0  # file rotated/truncated
            if sz > pos:
                with jsonl_path.open("r") as f:
                    f.seek(pos)
                    for raw in f:
                        try:
                            line = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        sid = line.get("sessionId") or line.get("session_id")
                        if not sid:
                            continue
                        evt_type, payload = _classify(line)
                        if not evt_type:
                            continue
                        alias = _load_sessions().get(sid)
                        if not alias:
                            _buffer_unmapped(sid, evt_type, payload, line.get("timestamp"))
                            continue
                        # Flush any buffered events that arrived before registration
                        for (et, pl, oc) in _drain_buffer(sid):
                            await _post_event(client, sid, alias, et, pl, occurred_at=oc)
                        await _post_event(client, sid, alias, evt_type, payload,
                                          occurred_at=line.get("timestamp"))
                    pos = f.tell()
            _gc_buffer()
        except FileNotFoundError:
            pass
        except Exception as e:
            # Never log payload contents — only the path and exception class.
            print(f"[tail_jsonl {jsonl_path.name}] {type(e).__name__}: {e}",
                  file=sys.stderr, flush=True)
        await asyncio.sleep(1.0)

async def _post_event(client, session_uuid, alias, evt_type, payload, occurred_at=None):
    try:
        await client.post(f"{LAB_URL}/api/event",
                          headers={"X-Forge-Key": FORGE_KEY},
                          json={"session_uuid": session_uuid, "terminal_alias": alias,
                                "event_type": evt_type, "payload": payload,
                                "occurred_at": occurred_at},
                          timeout=10.0)
    except Exception as e:
        # Exception messages from httpx can include URL + sometimes body;
        # log only class + truncated message to keep agent.err.log clean.
        msg = str(e)[:200]
        print(f"[post_event] {type(e).__name__}: {msg}", file=sys.stderr, flush=True)

async def discover_jsonl_loop(client):
    """Every 2s, find newly-created JSONL files in tracked project dirs and spawn tailers.
    Faster than 5s so a session that finishes inside ~5s isn't entirely missed."""
    tracked = {}
    project_dirs = {_project_dir_for(wt) for wt in WORKTREES.values()}
    while True:
        for pdir in project_dirs:
            if not pdir.exists():
                continue
            for f in pdir.glob("*.jsonl"):
                if f not in tracked:
                    tracked[f] = asyncio.create_task(tail_jsonl(client, f))
        await asyncio.sleep(2.0)

def _git_info(worktree):
    if not (worktree / ".git").exists():
        return {}
    try:
        branch = subprocess.check_output(["git","-C",str(worktree),"branch","--show-current"],
                                         text=True, timeout=5).strip()
        sha = subprocess.check_output(["git","-C",str(worktree),"rev-parse","HEAD"],
                                      text=True, timeout=5).strip()
        subj = subprocess.check_output(["git","-C",str(worktree),"log","-1","--format=%s"],
                                       text=True, timeout=5).strip()
        return {"git_branch": branch, "git_head_sha": sha[:12], "git_head_subject": subj[:200]}
    except Exception:
        return {}

def _mailbox_info(alias, worktree):
    rel = MAILBOX_FILE.get(alias)
    if not rel:
        return {"mailbox_status": "n/a"}
    fp = worktree / rel
    if not fp.exists():
        return {"mailbox_path": str(fp), "mailbox_status": "empty"}
    txt = fp.read_text()[:2000]
    first_line = txt.splitlines()[0] if txt.strip() else ""
    status = "complete" if first_line.upper().startswith("COMPLETE") else "pending"
    brief_name = ""
    for line in txt.splitlines()[:10]:
        if "BRIEF_" in line.upper():
            brief_name = line.strip()[:120]
            break
    return {"mailbox_path": str(fp), "mailbox_status": status,
            "mailbox_brief_name": brief_name}

def _open_pr(worktree):
    try:
        branch = subprocess.check_output(
            ["git","-C",str(worktree),"branch","--show-current"], text=True, timeout=5).strip()
        out = subprocess.check_output(
            ["gh","pr","list","--head", branch,"--json","number,title","--limit","1"],
            cwd=str(worktree), text=True, timeout=8)
        arr = json.loads(out) if out else []
        if arr:
            return {"open_pr_number": arr[0].get("number"), "open_pr_title": arr[0].get("title","")[:200]}
    except Exception:
        pass
    return {}

async def snapshot_loop(client):
    while True:
        for alias, wt in WORKTREES.items():
            snap = {"terminal_alias": alias}
            snap.update(_git_info(wt))
            snap.update(_mailbox_info(alias, wt))
            snap.update(_open_pr(wt))
            try:
                await client.post(f"{LAB_URL}/api/snapshot",
                                  headers={"X-Forge-Key": FORGE_KEY},
                                  json=snap, timeout=15.0)
            except Exception as e:
                print(f"[snapshot {alias}] {e}", flush=True)
        await asyncio.sleep(30.0)

async def main():
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            discover_jsonl_loop(client),
            snapshot_loop(client),
        )

if __name__ == "__main__":
    asyncio.run(main())
```

**`~/forge-agent/requirements.txt`:**
```
httpx==0.27.2
```

**Setup commands** (run once on MacBook):
```bash
mkdir -p ~/forge-agent
python3 -m venv ~/forge-agent/.venv
~/forge-agent/.venv/bin/pip install -r ~/forge-agent/requirements.txt
echo '{}' > ~/forge-agent/sessions.json
```

**`~/Library/LaunchAgents/com.brisen.lab-agent.plist`:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.brisen.lab-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/dimitry/forge-agent/.venv/bin/python</string>
        <string>/Users/dimitry/forge-agent/agent.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>LAB_URL</key>
        <string>https://brisen-lab.onrender.com</string>
        <key>FORGE_KEY</key>
        <string>__SET_BY_DIRECTOR_BEFORE_LOAD__</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key>
    <string>/Users/dimitry/forge-agent/agent.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/dimitry/forge-agent/agent.err.log</string>
</dict>
</plist>
```

Director sets `FORGE_KEY` (same value as Render env var) in the plist before loading:
```bash
launchctl load ~/Library/LaunchAgents/com.brisen.lab-agent.plist
```

### Key Constraints
- **Daemon never edits any worktree.** Read-only on git, read-only on mailbox files.
- **Bounded reads:** mailbox file truncated to 2000 chars; tool-result preview to 500 chars.
- **Reads from EOF on first encounter** — does not replay historical JSONL on first start.
- **`gh` must be installed and authenticated** on MacBook (already is — verified `which gh`). If absent, `_open_pr()` silently returns `{}` — non-fatal.
- **`FORGE_KEY` is loaded from launchd plist env**, not from a checked-in file. Rotate by editing plist + `launchctl unload/load`.
- **Do NOT log full prompt/response text** to `agent.err.log` — only error lines.

### Verification
1. `launchctl load ~/Library/LaunchAgents/com.brisen.lab-agent.plist` — daemon starts.
2. `tail -f ~/forge-agent/agent.log` — see snapshot POSTs every 30s.
3. After Part 3 lands and you launch `aihead1`, `psql $DATABASE_URL -c "SELECT terminal_alias, COUNT(*) FROM forge_events GROUP BY 1"` shows event counts.
4. `psql $DATABASE_URL -c "SELECT terminal_alias, mailbox_status, git_branch, git_head_subject FROM forge_snapshots"` shows current state of all 6.

---

## Part 3: Claude Code SessionStart hook + shell function updates

### Problem
The daemon needs to know which `session_uuid` belongs to which terminal alias. Lead and Deputy share a project dir, so we cannot derive alias from the JSONL's path alone — we need a registration step at session start.

### Current State
- `~/.zshrc` has shell functions `aihead1`, `aihead2`, `b1`, `b2`, `b3`, `b4` — each sets a tab title and launches `claude`. (Verified by reading `~/Desktop/baker-code/00_WORKTREES.md` lines 116-122.)
- `~/Desktop/baker-code/.claude/settings.json` has hooks for `PostToolUse` (syntax-check) and `PreToolUse` (block-secrets). No `SessionStart` hook configured. (Verified by reading the file.)

### Implementation

**3a. Update `~/.zshrc`** — add `FORGE_TERMINAL` export to each function. Replace the existing block of 6 functions:
```bash
function aihead1() { printf "\033]0;Lead\007"; FORGE_TERMINAL=lead claude "$@"; }
function aihead2() { printf "\033]0;Deputy\007"; FORGE_TERMINAL=deputy claude "$@"; }
function b1()      { printf "\033]0;B1\007"; FORGE_TERMINAL=b1 claude "$@"; }
function b2()      { printf "\033]0;B2\007"; FORGE_TERMINAL=b2 claude "$@"; }
function b3()      { printf "\033]0;B3\007"; FORGE_TERMINAL=b3 claude "$@"; }
function b4()      { printf "\033]0;B4\007"; FORGE_TERMINAL=b4 claude "$@"; }
```

Add 2 export lines near the top of `~/.zshrc`:
```bash
export FORGE_KEY="__same_value_as_render__"
export LAB_URL="https://brisen-lab.onrender.com"
```

After saving: `source ~/.zshrc` in every open terminal (or just close + reopen tabs).

**3b. SessionStart hook script** at `/Users/dimitry/forge-agent/session-start-hook.sh` (chmod +x):
```bash
#!/bin/bash
# Brisen Lab — SessionStart hook. Reads $FORGE_TERMINAL and registers this
# Claude Code session with the agent's local sessions.json + Render Lab.

if [ -z "$FORGE_TERMINAL" ]; then
  exit 0   # not a watched terminal, do nothing
fi

# Claude Code passes hook input as JSON on stdin
INPUT=$(cat)
SESSION_UUID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null)
PROJECT_PATH=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cwd',''))" 2>/dev/null)

if [ -z "$SESSION_UUID" ]; then
  exit 0
fi

# 1. Append to local sessions.json (atomic via temp file)
SESSIONS_FILE="$HOME/forge-agent/sessions.json"
mkdir -p "$(dirname "$SESSIONS_FILE")"
[ -f "$SESSIONS_FILE" ] || echo '{}' > "$SESSIONS_FILE"

python3 - "$SESSIONS_FILE" "$SESSION_UUID" "$FORGE_TERMINAL" <<'PY'
import json, sys, os, tempfile
path, uuid, alias = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f: data = json.load(f)
data[uuid] = alias
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as f: json.dump(data, f)
os.replace(tmp, path)
PY

# 2. POST to Render so dashboard renders the new session immediately
if [ -n "$FORGE_KEY" ] && [ -n "$LAB_URL" ]; then
  curl -s -X POST "$LAB_URL/api/register" \
    -H "X-Forge-Key: $FORGE_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"session_uuid\":\"$SESSION_UUID\",\"terminal_alias\":\"$FORGE_TERMINAL\",\"project_path\":\"$PROJECT_PATH\"}" \
    --max-time 5 >/dev/null 2>&1 || true
fi

exit 0
```

**3c. Wire the hook into each watched project's `.claude/settings.json`.**

For `~/Desktop/baker-code/.claude/settings.json` — merge into existing hooks block:
```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/Users/dimitry/forge-agent/session-start-hook.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{"type":"command","command":"/Users/dimitry/Desktop/baker-code/.claude/hooks/syntax-check.sh","timeout":15}]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{"type":"command","command":"/Users/dimitry/Desktop/baker-code/.claude/hooks/block-secrets.sh","timeout":5}]
      }
    ]
  }
}
```

For `~/bm-b1/.claude/settings.json`, `~/bm-b2/.claude/settings.json`, `~/bm-b3/.claude/settings.json`, `~/bm-b4/.claude/settings.json` — add the `SessionStart` block (preserving existing `PostToolUse` / `PreToolUse` hooks if present).

### Key Constraints
- **Hook must exit 0** on every path. A failing hook would block Claude Code session start. Both `python3` calls have `2>/dev/null`; the `curl` ends with `|| true`.
- **Hook is idempotent.** Re-running for the same `session_uuid` overwrites the alias mapping, which is correct.
- **No secrets in the hook script.** `FORGE_KEY` comes from env. Never hardcode.
- **Add `FORGE_KEY` + `LAB_URL` to `~/.zshrc`** so they're exported in every shell that launches `claude` via the named functions.
- **Hook timeout is 10s, not 5s.** Cold-start of `python3` on macOS post-reboot can exceed 1s, and the hook calls it twice. 10s leaves headroom while still being well under any user-perceptible latency. (If the hook ever exceeds 10s, the daemon's unmapped-event buffer in Part 2 absorbs the first events anyway — defence-in-depth.)

### Verification
1. After updating `~/.zshrc` and reloading, run `aihead1`. Hook fires.
2. `cat ~/forge-agent/sessions.json` shows `{"<uuid>": "lead"}`.
3. `psql $DATABASE_URL -c "SELECT * FROM forge_sessions ORDER BY started_at DESC LIMIT 6"` shows new session row with `terminal_alias='lead'`.
4. Launch all 6 terminals (aihead1, aihead2, b1, b2, b3, b4). All 6 appear in `forge_sessions`.

---

## Part 4: Frontend — hub-and-spoke layout, vanilla HTML/JS, safe DOM construction

### Problem
v1 UI: 6 cards (Lead + Deputy on top large, B1–B4 below smaller), right-side activity timeline, click-to-expand event panel. No xterm.js — events render as structured cards (user prompt, assistant message, tool call, tool result).

**XSS surface elimination:** This file deliberately uses `document.createElement` + `textContent` everywhere. **No `innerHTML = ...` calls anywhere in `app.js`.** Per lessons.md anti-pattern: escape-then-innerHTML is fragile; safe DOM construction is the rule.

### Current State
None.

### Implementation

**`static/index.html`** — single page, tagged for cache busting (lesson 4):
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Brisen Lab</title>
  <link rel="stylesheet" href="/static/styles.css?v=1">
</head>
<body>
  <header>
    <h1>Brisen Lab</h1>
    <span id="conn-status" class="conn-disconnected">connecting…</span>
  </header>
  <main>
    <section class="board">
      <div class="row row-supervisors">
        <article class="card card-large" data-alias="lead"></article>
        <article class="card card-large" data-alias="deputy"></article>
      </div>
      <div class="row row-workers">
        <article class="card" data-alias="b1"></article>
        <article class="card" data-alias="b2"></article>
        <article class="card" data-alias="b3"></article>
        <article class="card" data-alias="b4"></article>
      </div>
    </section>
    <aside class="timeline">
      <h2>Activity</h2>
      <div id="timeline-feed"></div>
    </aside>
  </main>
  <dialog id="terminal-detail">
    <header>
      <h2 id="detail-title"></h2>
      <button id="detail-close">×</button>
    </header>
    <div id="detail-events"></div>
  </dialog>
  <script src="/static/app.js?v=1"></script>
</body>
</html>
```

**`static/styles.css`** (~150 lines, sketch only — Code Brisen polishes):
```css
:root { --bg: #0d1117; --panel: #161b22; --border: #30363d; --text: #e6edf3;
        --muted: #8b949e; --working: #2da44e; --idle: #6e7681; --waiting: #d29922; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
       font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", monospace; }
header { padding: 12px 20px; border-bottom: 1px solid var(--border);
         display: flex; align-items: center; gap: 12px; }
main { display: grid; grid-template-columns: 1fr 360px; gap: 20px; padding: 20px; }
.row { display: grid; gap: 16px; margin-bottom: 16px; }
.row-supervisors { grid-template-columns: 1fr 1fr; }
.row-workers     { grid-template-columns: repeat(4, 1fr); }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
        padding: 16px; cursor: pointer; transition: border-color 120ms; }
.card:hover { border-color: #58a6ff; }
.card.card-large { min-height: 180px; }
.card .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
.card.status-working .status-dot { background: var(--working); }
.card.status-idle    .status-dot { background: var(--idle); }
.card.status-waiting .status-dot { background: var(--waiting); }
.card .card-title  { font-weight: 600; }
.card .card-meta   { color: var(--muted); font-size: 11px; margin-top: 4px; }
.card .card-subj   { font-size: 12px; margin-top: 8px; }
.card .card-extra  { color: var(--muted); font-size: 11px; margin-top: 8px; }
.timeline { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
            padding: 16px; max-height: calc(100vh - 100px); overflow-y: auto; }
.timeline .event { padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 12px;
                   display: flex; gap: 8px; align-items: baseline; }
.timeline .event .alias { color: #58a6ff; font-weight: 600; }
.timeline .event .ago   { color: var(--muted); margin-left: auto; }
.conn-connected    { color: var(--working); }
.conn-disconnected { color: var(--waiting); }
dialog { background: var(--panel); color: var(--text); border: 1px solid var(--border);
         border-radius: 8px; width: min(900px, 90vw); max-height: 80vh; }
dialog header { display: flex; justify-content: space-between; }
#detail-events .event-card { background: var(--bg); padding: 10px; margin: 8px 0;
                              border-radius: 6px; font-size: 13px; }
.event-card .meta { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
```

**`static/app.js`** (~250 lines, **safe DOM construction throughout — no `innerHTML`**):
```javascript
const TERMINALS = ["lead", "deputy", "b1", "b2", "b3", "b4"];
const TERMINAL_LABELS = {lead:"Lead", deputy:"Deputy", b1:"B1", b2:"B2", b3:"B3", b4:"B4"};
const MAX_TIMELINE = 100;

const state = {
  snapshots: {},   // alias -> snapshot
  events: [],      // recent events (chronological, newest last)
  detailAlias: null,
};

// ---- Safe DOM helpers ----
function el(tag, opts) {
  const e = document.createElement(tag);
  if (!opts) return e;
  if (opts.cls)  e.className = Array.isArray(opts.cls) ? opts.cls.join(" ") : opts.cls;
  if (opts.text != null) e.textContent = String(opts.text);
  if (opts.attrs) for (const [k,v] of Object.entries(opts.attrs)) e.setAttribute(k, String(v));
  return e;
}
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

function timeAgo(iso) {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return Math.floor(ms/1000) + "s ago";
  if (ms < 3_600_000) return Math.floor(ms/60_000) + "m ago";
  return Math.floor(ms/3_600_000) + "h ago";
}

function statusFor(alias) {
  const now = Date.now();
  let recent = 0;
  for (const e of state.events) {
    if (e.terminal_alias === alias) {
      const t = new Date(e.occurred_at).getTime();
      if (t > recent) recent = t;
    }
  }
  if (recent && now - recent < 60_000) return "working";
  const snap = state.snapshots[alias] || {};
  if (snap.mailbox_status === "pending") return "waiting";
  return "idle";
}

function renderCard(alias) {
  const card = document.querySelector('.card[data-alias="' + alias + '"]');
  if (!card) return;
  const snap = state.snapshots[alias] || {};
  const status = statusFor(alias);
  card.classList.remove("status-idle","status-working","status-waiting");
  card.classList.add("status-" + status);

  let last = null;
  for (let i = state.events.length - 1; i >= 0; i--) {
    if (state.events[i].terminal_alias === alias) { last = state.events[i]; break; }
  }

  clear(card);

  const titleRow = el("div");
  titleRow.appendChild(el("span", {cls: "status-dot"}));
  titleRow.appendChild(el("span", {cls: "card-title", text: TERMINAL_LABELS[alias]}));
  card.appendChild(titleRow);

  card.appendChild(el("div", {cls: "card-meta",
    text: (snap.git_branch || "") + " · " + (snap.git_head_sha || "")}));
  card.appendChild(el("div", {cls: "card-subj",
    text: snap.git_head_subject || "no commits"}));

  const extra = [];
  if (snap.mailbox_status) extra.push("mailbox: " + snap.mailbox_status);
  if (snap.open_pr_number) extra.push("PR #" + snap.open_pr_number);
  card.appendChild(el("div", {cls: "card-extra", text: extra.join(" · ")}));

  card.appendChild(el("div", {cls: "card-extra",
    text: last ? ("last: " + last.event_type + " " + timeAgo(last.occurred_at))
                : "no events yet"}));
}

function renderTimeline() {
  const feed = document.getElementById("timeline-feed");
  clear(feed);
  const recent = state.events.slice(-MAX_TIMELINE).reverse();
  for (const e of recent) {
    const row = el("div", {cls: "event"});
    row.appendChild(el("span", {cls: "alias", text: TERMINAL_LABELS[e.terminal_alias] || e.terminal_alias}));
    row.appendChild(el("span", {text: e.event_type}));
    row.appendChild(el("span", {cls: "ago", text: timeAgo(e.occurred_at)}));
    feed.appendChild(row);
  }
}

function renderDetail() {
  const dlg = document.getElementById("terminal-detail");
  document.getElementById("detail-title").textContent = TERMINAL_LABELS[state.detailAlias] || "";
  const body = document.getElementById("detail-events");
  clear(body);
  const evs = state.events.filter(e => e.terminal_alias === state.detailAlias).slice(-100).reverse();
  for (const e of evs) {
    const card = el("div", {cls: "event-card"});
    card.appendChild(el("div", {cls: "meta", text: e.event_type + " · " + e.occurred_at}));
    card.appendChild(el("div", {text: JSON.stringify(e.payload).slice(0, 800)}));
    body.appendChild(card);
  }
  if (!dlg.open) dlg.showModal();
}

function ingest(msg) {
  if (msg.kind === "snapshot") {
    state.snapshots[msg.terminal_alias] = msg.snapshot;
    renderCard(msg.terminal_alias);
  } else if (msg.kind === "event") {
    state.events.push(msg);
    if (state.events.length > 500) state.events = state.events.slice(-500);
    renderCard(msg.terminal_alias);
    renderTimeline();
    if (state.detailAlias === msg.terminal_alias) renderDetail();
  } else if (msg.kind === "register") {
    renderCard(msg.terminal_alias);
  }
}

async function loadInitialState() {
  const r = await fetch("/api/state");
  const d = await r.json();
  state.snapshots = d.snapshots || {};
  state.events = (d.events || []).reverse(); // server returned newest-first
  TERMINALS.forEach(renderCard);
  renderTimeline();
}

function connectSSE() {
  const status = document.getElementById("conn-status");
  const es = new EventSource("/sse/stream");
  es.addEventListener("open", () => {
    status.textContent = "live"; status.className = "conn-connected";
  });
  es.addEventListener("error", () => {
    status.textContent = "reconnecting…"; status.className = "conn-disconnected";
  });
  es.addEventListener("message", ev => {
    try { ingest(JSON.parse(ev.data)); } catch (err) { console.error(err); }
  });
}

document.querySelectorAll(".card").forEach(c => {
  c.addEventListener("click", () => { state.detailAlias = c.dataset.alias; renderDetail(); });
});
document.getElementById("detail-close").addEventListener("click", () => {
  document.getElementById("terminal-detail").close();
  state.detailAlias = null;
});

loadInitialState().then(connectSSE);
setInterval(() => TERMINALS.forEach(renderCard), 5_000);  // re-eval status (stale → idle)
```

### Status semantics (technical default per Director's "follow your picks")

| Status | Definition |
|---|---|
| working | An event in `forge_events` for this `terminal_alias` within the last 60s. |
| waiting | No event in last 60s **AND** `mailbox_status = 'pending'` (only applies to b1–b4). |
| idle | Otherwise. |

### Key Constraints
- **Cache bust** — every static file referenced with `?v=1`. Bump on every CSS/JS change (lesson 4).
- **No `innerHTML` writes anywhere** — all DOM updates use `createElement`/`textContent`/`appendChild`/`clear`. Eliminates XSS surface. Lessons.md item: "Use `document.createTextNode()` for XSS safety in vanilla JS".
- **No external JS dependencies.** No CDN scripts. Everything bundled.
- **Reconnect on SSE drop** — `EventSource` does this natively.
- **Bound `state.events` to 500** to avoid DOM bloat over a long session.

### Verification
1. Open `https://brisen-lab.onrender.com`. 6 cards visible in hub-and-spoke.
2. All cards initially show "no events yet" + "no commits" (until daemon snapshots arrive).
3. Within 60s of daemon start: each card shows git branch, head SHA, last commit subject.
4. Launch `aihead1` from terminal, send a prompt. Within ~2s: Lead card flips to `status-working`, timeline shows a `user_prompt` event.
5. Click any card → modal opens with last 100 events for that terminal.
6. View source of any rendered card → no `<script>`, no `<img onerror=`, no encoded HTML — purely text nodes (visual confirmation that `innerHTML` was not used).

---

## Files Modified

This brief modifies / creates:

**New repo `vallen300-bit/brisen-lab`** (entire repo):
- `app.py`
- `db.py`
- `requirements.txt`
- `start.sh`
- `render.yaml`
- `static/index.html`
- `static/app.js`
- `static/styles.css`
- `README.md`

**Local on MacBook (NOT in any git repo):**
- `~/forge-agent/agent.py`
- `~/forge-agent/requirements.txt`
- `~/forge-agent/sessions.json` (initially `{}`)
- `~/forge-agent/session-start-hook.sh`
- `~/Library/LaunchAgents/com.brisen.lab-agent.plist`

**Edits to existing files (b5 must back these up before editing):**
- `~/.zshrc` — replace the 6 `aihead1`/`aihead2`/`b1`–`b4` functions; add 2 export lines for `FORGE_KEY`, `LAB_URL`.
- `~/Desktop/baker-code/.claude/settings.json` — add `SessionStart` hooks block (preserving existing `PostToolUse` + `PreToolUse`).
- `~/bm-b1/.claude/settings.json`, `~/bm-b2/.claude/settings.json`, `~/bm-b3/.claude/settings.json`, `~/bm-b4/.claude/settings.json` — same `SessionStart` hook addition.

## Do NOT Touch

- `outputs/dashboard.py` — baker-master, business-only. Brisen Lab is a separate service.
- Any other file in `~/Desktop/baker-code` (the baker-master repo) **except** the four `.claude/settings.json` files listed above.
- `baker-vault/` — out of scope.
- `briefs/_tasks/CODE_*_PENDING.md` mailboxes for b1–b4 — daemon reads them, never writes them.
- The existing `syntax-check.sh` and `block-secrets.sh` hook scripts — leave alone, just merge `SessionStart` alongside them.
- `tasks/lessons.md` — append-only; do not rewrite. b5 may add a new entry at the bottom after deploy if a new pattern emerges.

## Quality Checkpoints

After Code Brisen (b5) finishes:

1. ✅ `https://brisen-lab.onrender.com/healthz` returns `{"ok": true}`.
2. ✅ Postgres tables exist: `\dt forge_*` shows `forge_sessions`, `forge_events`, `forge_snapshots`.
3. ✅ launchd agent loaded: `launchctl list | grep brisen.lab-agent` shows the service running.
4. ✅ `cat ~/forge-agent/agent.log` after 2 minutes shows no errors and at least 12 snapshot POSTs.
5. ✅ All 6 shell functions in `~/.zshrc` carry `FORGE_TERMINAL=<alias>` prefix.
6. ✅ All five `.claude/settings.json` files contain the SessionStart hook entry; existing PostToolUse/PreToolUse hooks still present.
7. ✅ Launching `aihead1` registers a row in `forge_sessions` within 5 seconds.
8. ✅ Browser dashboard renders 6 cards in hub-and-spoke layout.
9. ✅ SSE connection indicator shows "live" within 3 seconds of page load.
10. ✅ Sending a prompt to a terminal flips its card to `status-working` within 2 seconds and adds a `user_prompt` row to the timeline.
11. ✅ Clicking a card opens the detail modal showing recent events for that terminal.
12. ✅ Restarting the dashboard browser tab — state hydrates from `/api/state` (recent snapshots + last 50 events appear before SSE reconnects).
13. ✅ Render restart simulation: Render → "Manual Deploy". Dashboard reconnects, daemon keeps POSTing.
14. ✅ No secret strings (`FORGE_KEY` value, `DATABASE_URL`) in any committed file. `git grep "$FORGE_KEY"` in brisen-lab returns empty.
15. ✅ Frontend XSS check: `grep -nE "innerHTML|outerHTML|insertAdjacentHTML|document\.write" static/app.js` returns zero matches.
16. ✅ Connection pool wired: open `app.py` and import + use `_pool` from `db.py`. Confirm by setting Render `DATABASE_URL` to a 5-conn-cap and verifying brisen-lab does not exhaust it under a 10-event/sec stress (`for i in $(seq 1 100); do curl -X POST … & done`).
17. ✅ Secret scrub working: send a test prompt to a watched terminal containing `sk-test1234567890123456789012345`, verify `psql … "SELECT payload FROM forge_events ORDER BY id DESC LIMIT 1"` shows `[REDACTED]`.
18. ✅ Retention loop scheduled: `psql $DATABASE_URL -c "EXPLAIN DELETE FROM forge_events WHERE occurred_at < NOW() - INTERVAL '14 days'"` runs without error; loop fires daily (verified after 24h via Render logs).
19. ✅ Unmapped-event buffer: launch `aihead1`, immediately type a prompt. After 5s (more than hook+post round-trip), confirm the prompt appears in `forge_events` for `terminal_alias='lead'`. (Pre-fix this was lost; post-fix it's preserved via buffer flush.)
20. ✅ SSE keepalive: open `/sse/stream` in a browser tab and leave idle for >2 minutes. Connection stays alive (no "reconnecting…" toggle). Server logs show no SSE drops.

## Verification SQL

Run after deploy + agent load + opening one terminal:

```sql
-- 1. Schema check
SELECT table_name FROM information_schema.tables
 WHERE table_name LIKE 'forge_%' LIMIT 10;
-- expect: forge_sessions, forge_events, forge_snapshots

-- 2. Sessions registered
SELECT terminal_alias, session_uuid, started_at
  FROM forge_sessions ORDER BY started_at DESC LIMIT 10;

-- 3. Recent events per terminal
SELECT terminal_alias, event_type, COUNT(*) AS n,
       MAX(occurred_at) AS last_seen
  FROM forge_events
 WHERE occurred_at > NOW() - INTERVAL '1 hour'
 GROUP BY 1, 2
 ORDER BY 1, 2
 LIMIT 50;

-- 4. Snapshots fresh
SELECT terminal_alias, git_branch, git_head_sha,
       mailbox_status, open_pr_number,
       NOW() - daemon_last_seen AS staleness
  FROM forge_snapshots
 ORDER BY terminal_alias
 LIMIT 10;
-- expect: staleness < 60s for every alias once daemon is running.
```

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `bootstrap()` fails because `DATABASE_URL` not set on Render → service can't start. | Set `DATABASE_URL` env var on Render BEFORE first deploy. Verify ALL expected vars via Render API after each set (lesson: env vars set but missing on deploy). |
| Hook fails on session start → blocks Claude Code from opening. | Hook script guards every step with `\|\| true` / `2>/dev/null`. Always exits 0. Tested in Verification step 7. |
| Daemon spams Render on JSONL file rotation. | Tailer compares `pos` vs `size`; if file shrank, resets `pos = 0`. Only emits new lines past last-seen offset. |
| `gh pr list` slow / hangs blocks snapshot loop. | `subprocess.check_output(timeout=8)`. Failure → `_open_pr` returns `{}`, snapshot still posts. |
| Lead and Deputy share project dir → events get cross-attributed. | SessionStart hook keys by Claude Code session UUID, not project path. JSONL `sessionId` field disambiguates. |
| `forge_events` table grows unbounded → bloats Neon shared with baker-master. | `_retention_loop()` runs at startup as an `asyncio.create_task`; daily DELETE of rows older than 14 days. ~5 lines in `app.py`. Lesson #25 (silent-failure deferral) applied — ship retention with v1, not v1.1. |
| Per-request `psycopg2.connect()` exhausts Neon connection limits during event bursts and starves baker-master. | `psycopg2.pool.ThreadedConnectionPool(min=1, max=5)` in `db.py`. Pool acquired in `get_conn()` context manager, released in `finally`. |
| User pastes an API key into a Claude prompt; it lands in `forge_events.payload` and renders on dashboard. | Two-layer scrubber: `_scrub()` in `agent.py` runs before POST; `scrub_secrets()` in `db.py` runs server-side before INSERT. Patterns cover OpenAI/Anthropic, Slack, JWT, AWS, GitHub PAT, Voyage, Google. Easy to add more. |
| First user_prompt of every session lost because hook + curl take longer than daemon's tail-loop. | Unmapped events buffered per `session_uuid` (cap 50, TTL 30s). Drained on first `_load_sessions()` lookup that returns an alias. Defence-in-depth: hook timeout bumped to 10s. |
| Tailer reads from EOF on first encounter → sessions that finish in <2s lose all events. | For JSONL files with `mtime < 60s ago`, start at offset 0. Older files (daemon restart while sessions exist) keep EOF behaviour to avoid history replay. Discover-loop interval reduced 5s → 2s. |
| Render idle-connection timeout (~110s) cuts SSE → dashboard flickers "reconnecting" every two minutes. | SSE generator emits `: keepalive\n\n` comment every 25s when idle (using `asyncio.wait_for` with timeout). Comment lines are ignored by `EventSource` clients. |
| `_load_sessions()` thrashes disk under tail load (re-reads file per JSONL line). | Cache by `mtime`; only re-parse when file changes. Per-line cost drops from disk read to dict lookup. |
| `agent.err.log` could capture pasted secrets via exception strings. | Exception handlers log only `type(e).__name__: <truncated str>`. `_post_event` truncates `httpx` exception messages to 200 chars. No payload bodies in logs. |
| FastAPI `_subscribers` queue full on slow client. | `asyncio.Queue(maxsize=200)` + drop-full pattern in `_broadcast()`. Slow viewer gets disconnected, doesn't block writes. |
| Render restart drops all SSE clients. | `EventSource` reconnects automatically. State hydrates from `/api/state`. |
| Director's `~/.zshrc` has unrelated customizations that conflict. | b5 must `cp ~/.zshrc ~/.zshrc.bak.$(date +%Y%m%d)` before editing, and only replace the specific 6-line `aihead1`/.../`b4` block (verified intact via `grep -c "^function aihead1"` returning exactly 1). |
| XSS via untrusted event payload. | Frontend uses `createElement` + `textContent` exclusively. No `innerHTML`. Even if Render returned attacker-controlled JSON, browser renders as text. Verified by grep in QC #15. |

## Deployment order (do not parallelize)

1. **Part 1 first** — push `brisen-lab` repo, create Render service, set `DATABASE_URL` + `FORGE_KEY` env vars, deploy, verify `/healthz` + tables created.
2. **Part 2 second** — deploy daemon to MacBook. Verify snapshots flow into `forge_snapshots`.
3. **Part 4 third (frontend works without Part 3)** — verify cards render with snapshot data; events panel empty.
4. **Part 3 last** — update `~/.zshrc`, settings.json hooks. Verify events flow from real Claude sessions.

This order means each step has a verifiable checkpoint and a clean rollback (revert one part at a time without breaking the others).

## Lessons appended after implementation

After deploy, b5 appends to `~/Desktop/baker-code/tasks/lessons.md` (append-only) any new patterns discovered, especially:
- JSONL parsing edge cases not covered by `_classify()`.
- launchd plist quirks specific to macOS 14/15.
- SSE behavior under network blips.
- Anything about `~/.zshrc` editing that should be standardized for future agents.
