# BRIEF 5B — Dashboard API Server

**Punch:** 5B of 5 (CEO Cockpit)
**Goal:** FastAPI server that exposes Baker's PostgreSQL data as REST endpoints. Serves the dashboard frontend (5C) and provides the live data backbone.

---

## What Exists Today

| Layer | What exists | What's missing |
|-------|------------|----------------|
| **PostgreSQL read** | `store_back.py` has `get_pending_alerts()`, `get_active_deals()`, `acknowledge_alert()`, `resolve_alert()` | No HTTP API — only callable from Python |
| **Retriever** | `retriever.py` has `get_contact_profile()`, `get_active_deals()`, `get_pending_alerts()`, `get_recent_decisions()` | Wraps data in `RetrievedContext` (pipeline-oriented, not API-friendly) |
| **State** | `triggers/state.py` has `get_watermark()`, `get_briefing_queue()` | Only used by scheduler |
| **Config** | `OutputConfig.dashboard_url` defaults to `http://localhost:8080` | No server exists yet |
| **Slack** | `outputs/slack_notifier.py` (5A) ✅ | Working, no dependency on dashboard |

**Key insight:** The data read layer already exists in `store_back.py` and `retriever.py`. This brief adds a thin FastAPI shell that calls those existing methods and returns JSON. We do NOT rewrite any SQL.

---

## Files to Create

### 1. `outputs/dashboard.py` (~250 lines)

The FastAPI application. Single file, no router splitting needed at this scale.

```python
"""
Baker AI — CEO Dashboard API Server
FastAPI app serving REST endpoints for the Baker Dashboard.
Reads from PostgreSQL via existing store_back + retriever.
Serves static frontend from outputs/static/.
"""
```

**Framework:** FastAPI + uvicorn

**Startup flow:**
1. Import `SentinelStoreBack` from `memory.store_back`
2. Import `SentinelRetriever` from `memory.retriever`
3. Create singleton instances on startup (`@app.on_event("startup")`)
4. Add CORS middleware (allow `*` for local dev — dashboard served from same origin in prod)
5. Mount `outputs/static/` as static file directory at `/static`
6. Serve `index.html` at `/` (the dashboard)

**Endpoints:**

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| `GET` | `/` | `index.html` from `outputs/static/` | `FileResponse` |
| `GET` | `/api/alerts` | Pending alerts (all tiers) | `store_back.get_pending_alerts()` |
| `GET` | `/api/alerts?tier=1` | Filtered by tier | `store_back.get_pending_alerts(tier=1)` |
| `POST` | `/api/alerts/{id}/acknowledge` | Acknowledge an alert | `store_back.acknowledge_alert(id)` |
| `POST` | `/api/alerts/{id}/resolve` | Resolve an alert | `store_back.resolve_alert(id)` |
| `GET` | `/api/deals` | Active deals | `store_back.get_active_deals()` |
| `GET` | `/api/contacts/{name}` | Contact profile | `store_back.get_contact_by_name(name)` |
| `GET` | `/api/decisions` | Recent decisions (last 10) | Direct SQL (see below) |
| `GET` | `/api/briefing/latest` | Latest briefing file content | Read newest file from `04_outputs/briefings/` |
| `GET` | `/api/status` | System health summary | Aggregated (see below) |

**Endpoint details:**

#### `/api/alerts` (GET)
```python
@app.get("/api/alerts")
async def get_alerts(tier: int = None):
    alerts = store.get_pending_alerts(tier=tier)
    # Serialize datetime fields to ISO strings
    for a in alerts:
        for k, v in a.items():
            if isinstance(v, datetime):
                a[k] = v.isoformat()
    return {"alerts": alerts, "count": len(alerts)}
```

#### `/api/alerts/{id}/acknowledge` (POST)
```python
@app.post("/api/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    store.acknowledge_alert(alert_id)
    return {"status": "acknowledged", "id": alert_id}
```

#### `/api/alerts/{id}/resolve` (POST)
```python
@app.post("/api/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    store.resolve_alert(alert_id)
    return {"status": "resolved", "id": alert_id}
```

#### `/api/deals` (GET)
```python
@app.get("/api/deals")
async def get_deals():
    deals = store.get_active_deals()
    for d in deals:
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
    return {"deals": deals, "count": len(deals)}
```

#### `/api/contacts/{name}` (GET)
```python
@app.get("/api/contacts/{name}")
async def get_contact(name: str):
    contact = store.get_contact_by_name(name)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    for k, v in contact.items():
        if isinstance(v, datetime):
            contact[k] = v.isoformat()
    return contact
```

#### `/api/decisions` (GET)

**New method needed in `store_back.py`:** `get_recent_decisions(limit: int = 10) -> list`

```python
@app.get("/api/decisions")
async def get_decisions(limit: int = 10):
    decisions = store.get_recent_decisions(limit=min(limit, 50))
    for d in decisions:
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
    return {"decisions": decisions, "count": len(decisions)}
```

#### `/api/briefing/latest` (GET)
```python
@app.get("/api/briefing/latest")
async def get_latest_briefing():
    briefing_dir = Path(__file__).parent.parent / "04_outputs" / "briefings"
    # Adjusted: also check the path used by briefing_trigger.py
    alt_dir = Path.home() / "Dropbox" / "Dimitry vallen" / "15_Baker_Master" / "04_outputs" / "briefings"

    for d in [briefing_dir, alt_dir]:
        if d.exists():
            files = sorted(d.glob("briefing_*.md"), reverse=True)
            if files:
                content = files[0].read_text(encoding="utf-8")
                return {
                    "date": files[0].stem.replace("briefing_", ""),
                    "content": content,
                    "filename": files[0].name,
                }
    return {"date": None, "content": "No briefings found.", "filename": None}
```

#### `/api/status` (GET)
System health — returns aggregated status for the dashboard header.

```python
@app.get("/api/status")
async def get_status():
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
```

**Static file serving:**
```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Mount static dir for CSS/JS assets
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def root():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Baker Dashboard — no frontend deployed yet"}
```

---

## Files to Modify

### 2. `memory/store_back.py` — Add `get_recent_decisions()`

The retriever has this method but it wraps results in `RetrievedContext`. The store_back needs a raw-dict version for the API.

**Add after `resolve_alert()` (line ~400):**

```python
def get_recent_decisions(self, limit: int = 10) -> list:
    """Fetch recent decisions for dashboard display."""
    conn = self._get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, decision, reasoning, confidence, trigger_type, created_at
            FROM decisions
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_recent_decisions failed: {e}")
        return []
    finally:
        self._put_conn(conn)
```

### 3. `outputs/static/` — Create directory

```bash
mkdir -p outputs/static
```

Create a placeholder `outputs/static/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Baker Dashboard</title>
    <style>
        body { font-family: system-ui; background: #0a0a0a; color: #ccc; display: flex;
               align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .msg { text-align: center; }
        h1 { color: #fff; font-size: 1.5rem; }
        p { color: #888; }
    </style>
</head>
<body>
    <div class="msg">
        <h1>Baker CEO Dashboard</h1>
        <p>API is running. Frontend will be deployed in Brief 5C.</p>
        <p>Try: <a href="/api/status" style="color:#60a5fa">/api/status</a> |
               <a href="/api/alerts" style="color:#60a5fa">/api/alerts</a> |
               <a href="/api/deals" style="color:#60a5fa">/api/deals</a></p>
    </div>
</body>
</html>
```

---

## Dependencies

**Add to `requirements.txt`:**
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
```

(`httpx` already present from 5A.)

---

## How to Run

```bash
# From 01_build/ directory:
uvicorn outputs.dashboard:app --host 0.0.0.0 --port 8080 --reload

# Then open: http://localhost:8080
# API docs: http://localhost:8080/docs (FastAPI auto-generates Swagger UI)
```

**Production note:** The scheduler (`triggers/scheduler.py`) and the dashboard server run as separate processes. They share the same PostgreSQL database. No conflict — both use connection pools.

---

## Test Plan

### Manual tests (run in order):

```bash
# 1. Install dependencies
pip install fastapi uvicorn[standard]

# 2. Start the server
uvicorn outputs.dashboard:app --host 0.0.0.0 --port 8080 &
sleep 2

# 3. Test status endpoint
curl -s http://localhost:8080/api/status | python -m json.tool
# Expected: {"system": "operational", "alerts_pending": N, ...}

# 4. Test alerts endpoint
curl -s http://localhost:8080/api/alerts | python -m json.tool
# Expected: {"alerts": [...], "count": N}

# 5. Test alerts with tier filter
curl -s "http://localhost:8080/api/alerts?tier=1" | python -m json.tool

# 6. Test deals endpoint
curl -s http://localhost:8080/api/deals | python -m json.tool
# Expected: {"deals": [...], "count": N}

# 7. Test decisions endpoint
curl -s http://localhost:8080/api/decisions | python -m json.tool

# 8. Test latest briefing
curl -s http://localhost:8080/api/briefing/latest | python -m json.tool

# 9. Test contact lookup
curl -s http://localhost:8080/api/contacts/Mykola | python -m json.tool

# 10. Test static serving (index.html)
curl -s http://localhost:8080 | head -5
# Expected: <!DOCTYPE html>...

# 11. Test Swagger docs load
curl -s http://localhost:8080/docs | head -3
# Expected: HTML with "Swagger UI"

# 12. Stop server
kill %1
```

### Success criteria:
1. All 7 API endpoints return valid JSON with correct structure
2. `/api/status` returns `"system": "operational"` when PostgreSQL is reachable
3. `/api/alerts` returns alerts from PostgreSQL (may be empty list if no pending alerts)
4. `/api/deals` returns active deals from PostgreSQL
5. `/api/briefing/latest` returns the most recent briefing markdown
6. `/` serves the placeholder HTML
7. `/docs` serves FastAPI Swagger UI (auto-generated)
8. All endpoints handle DB connection failures gracefully (return empty results, not 500)

---

## What NOT to build in 5B

- ❌ No authentication (local-only dashboard, not exposed to internet)
- ❌ No WebSocket (polling from frontend is sufficient at this scale)
- ❌ No write endpoints beyond alert acknowledge/resolve (Baker's brain writes via pipeline, not via dashboard)
- ❌ No frontend (that's 5C)
- ❌ No Slack integration (that's 5A, already done)

---

## Architecture Note

```
┌─────────────────────┐     ┌────────────────────┐     ┌──────────────┐
│  Scheduler Process   │────▶│   PostgreSQL (Neon) │◀────│  Dashboard   │
│  (triggers + pipeline)│     └────────────────────┘     │  API (8080)  │
└─────────────────────┘              ▲                   └──────┬───────┘
                                     │                          │
                                     │                   ┌──────┴───────┐
                                     └───────────────────│  Browser     │
                                                         │  (index.html)│
                                                         └──────────────┘
```

Both processes read/write the same PostgreSQL. No shared state in memory. No process coordination needed.

---

## File Checklist

| # | Action | File |
|---|--------|------|
| 1 | CREATE | `outputs/dashboard.py` (~250 lines) |
| 2 | MODIFY | `memory/store_back.py` (add `get_recent_decisions()` ~20 lines) |
| 3 | CREATE | `outputs/static/index.html` (placeholder) |
| 4 | MODIFY | `requirements.txt` (add `fastapi`, `uvicorn[standard]`) |
