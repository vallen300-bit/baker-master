# BRIEF: MCP-SSE-STABLE — Fix Baker MCP Remote Reconnection for Claude Code Web

## Context
Baker MCP server is deployed as a remote SSE endpoint at `/mcp/sse` on baker-master. Claude Code web sessions connect to it as a custom connector. The initial connection works (ListToolsRequest processed), but Claude Code web frequently reconnects the SSE stream, and each reconnection creates a new session ID. POST messages sent to the old session ID return 404 ("Could not find session"). Tools appear stuck "connecting" indefinitely.

Director needs Code Brisen (via claude.ai/code) to have reliable Baker MCP access for database queries, VIP contacts, decisions, etc.

## Estimated time: ~2h
## Complexity: Medium
## Prerequisites: Current `/mcp/sse` endpoint already deployed (commit 9d0d459)

---

## The Problem

**Render logs show:**
```
GET /mcp/sse?key=... → 200 OK (session A created)
POST /mcp/messages/?session_id=A → 202 Accepted (ListToolsRequest works!)
GET /mcp/sse?key=... → 200 OK (reconnect → session B created, session A lost)
POST /mcp/messages/?session_id=A → 404 Not Found ("Could not find session")
```

Each `GET /mcp/sse` creates a new `SseServerTransport` session. When Claude Code web reconnects (which it does after any network hiccup or timeout), the old session is gone. The MCP SDK's `SseServerTransport` stores sessions in memory — no persistence.

## Current State

`outputs/dashboard.py` lines ~118-152 (BAKER-MCP-REMOTE block):
- `SseServerTransport("/mcp/messages/")` created at module level
- `GET /mcp/sse` → `connect_sse()` context manager → runs `baker_mcp_app.run()`
- `POST /mcp/messages/` → `handle_post_message()`
- Auth via `X-Baker-Key` header or `?key=` query param

`baker-mcp/baker_mcp_server.py`:
- `app = Server("baker-mcp")` with 23 tools (read + write)
- Uses `psycopg2` to connect to Neon PostgreSQL

## Solution Options

### Option A: Switch to Streamable HTTP Transport (Recommended)
The MCP SDK (v1.0+) supports `StreamableHTTPTransport` which handles reconnections properly. Instead of SSE (one-way server→client with separate POST endpoint), it uses standard HTTP request/response with optional streaming. No session state to lose.

**Implementation:**
```python
from mcp.server.streamable_http import StreamableHTTPServer

# Replace the SSE endpoints with a single HTTP endpoint
@app.post("/mcp/http", dependencies=[Depends(verify_api_key)])
async def mcp_http_handler(request: Request):
    """Streamable HTTP endpoint for remote MCP access."""
    # ... handle MCP request/response over HTTP
```

**Check first:** Verify `StreamableHTTPServer` or equivalent exists in the installed `mcp` package version. Run: `python3 -c "from mcp.server.streamable_http import StreamableHTTPServer; print('OK')"`

If it doesn't exist, use Option B.

### Option B: Fix SSE with Session Persistence
Keep SSE transport but make sessions survive reconnections:

1. Store session mapping in a dict at module level (survives across requests)
2. On reconnect, reuse the existing session if the client sends a session ID
3. Add session TTL (clean up after 30 min of inactivity)

**Implementation sketch:**
```python
import time
import threading

_mcp_sessions = {}  # session_id → (transport, last_activity)
_mcp_lock = threading.Lock()

@app.get("/mcp/sse")
async def mcp_sse_handler(request: Request):
    # Auth check...

    # Create or reuse transport
    session_id = request.query_params.get("session_id")
    with _mcp_lock:
        if session_id and session_id in _mcp_sessions:
            sse_transport = _mcp_sessions[session_id][0]
        else:
            sse_transport = SseServerTransport("/mcp/messages/")

    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as (read, write):
        # Store session
        new_session_id = ...  # extract from transport
        with _mcp_lock:
            _mcp_sessions[new_session_id] = (sse_transport, time.time())

        await baker_mcp_app.run(read, write, baker_mcp_app.create_initialization_options())
```

**Risk:** The `SseServerTransport` may not support reuse — need to verify the SDK source.

### Option C: Simplest — Increase SSE Timeout + Keep-Alive
Add SSE keep-alive pings to prevent the connection from dropping in the first place:

```python
# In the SSE handler, send periodic keep-alive comments
# SSE spec: lines starting with ":" are comments (keep-alive)
```

This doesn't fix the root cause but reduces reconnection frequency.

## Recommended Approach

**Try Option A first** (Streamable HTTP). If the SDK doesn't support it, fall back to **Option C** (keep-alive) as a quick fix while designing Option B properly.

## Files to Modify
- `outputs/dashboard.py` — Replace or fix the MCP SSE endpoints (~lines 118-152)
- `requirements.txt` — May need to pin a specific `mcp` version that supports the chosen transport

## Do NOT Touch
- `baker-mcp/baker_mcp_server.py` — The MCP server app itself works perfectly
- Any other dashboard endpoints
- WAHA or WhatsApp code

## Quality Checkpoints
1. Syntax check: `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`
2. After deploy: `curl -s -H "X-Baker-Key: bakerbhavanga" https://baker-master.onrender.com/mcp/sse` should return SSE stream
3. Open Claude Code web → new session → ask "Use baker_vip_contacts to search for Constantinos"
4. Wait 2 minutes → ask again → tools should still work (reconnection survived)
5. Check Render logs for 404 errors on `/mcp/messages/` — should be zero
6. Verify baker-master `/health` still reports healthy after deploy

## Verification
```bash
# Test SSE endpoint responds
curl -s -N -H "X-Baker-Key: bakerbhavanga" "https://baker-master.onrender.com/mcp/sse" --max-time 5

# Check for session errors in logs
# Render logs → filter "Could not find session" — should be zero after fix
```
