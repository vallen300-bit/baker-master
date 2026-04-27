# BRIEF: BAKER_MCP_EXTENSION_1 — Add 4 missing tools to live Baker MCP server

**Milestone:** M2 (Cortex stream foundation)
**Source spec:** `pm/briefs/BAKER-MCP-1_baker_mcp_server.md` (2026-03-05, pre-Rule-0 — superseded scope; see Context)
**Estimated time:** ~2-3h
**Complexity:** Low-Medium
**Trigger class:** MEDIUM (new MCP tools touching scan/search/ingest/health surfaces) → B1 second-pair-review pre-merge per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`
**Prerequisites:** Baker MCP server live (PR #28 vault tools precedent), all 4 underlying REST endpoints live (verified by EXPLORE)

---

## Context

Baker MCP server is **already live** at `outputs/dashboard.py:632` with 26 tools registered in `baker_mcp/baker_mcp_server.py:TOOLS`. Streamable HTTP transport, X-Baker-Key auth, JSON-RPC tools/list + tools/call dispatch. PR #28 (SOT_OBSIDIAN_1_PHASE_D_VAULT_READ) added the most recent tools (`baker_vault_list`, `baker_vault_read`).

**The gap:** 4 server-side REST endpoints lack MCP tool wrappers, blocking native Cowork access:
1. `POST /api/scan` + `POST /api/scan/client-pm` — capability-routed Q&A. Most acute gap: Director cannot query AO PM / MOVIE AM / domain capabilities through MCP today; he must open the Baker dashboard.
2. `GET /api/search/unified` — cross-source semantic search.
3. `POST /api/ingest` — knowledge-base ingest (file path).
4. `GET /api/health` — programmatic system status.

**Director ratified scope 2026-04-26:** Option A on both design questions — unified `baker_scan` with optional `capability_slug` arg, text-only `baker_ingest_text`. The original 2026-03-05 brief at `pm/briefs/BAKER-MCP-1_baker_mcp_server.md` is **superseded by this brief** (Lesson #51 retroactive validation: original was greenfield-shaped, real state is extension-shaped).

---

## Problem

| Use case | Today | Blocked because |
|---|---|---|
| Director asks AO PM via Code App | Must use dashboard or curl loopback | No MCP tool routes to capability scan |
| Cowork session does semantic search across Baker memory | Curl to `/api/search/unified` with X-Baker-Key | No MCP tool wrapper |
| AI Dennis ingests an IT memo into Baker | Multipart upload to dashboard UI only | No MCP ingest tool |
| Sentinel health probe from Cowork | Curl `/api/health` | No MCP tool wrapper |

## Solution

Add 4 tool entries to `baker_mcp/baker_mcp_server.py:TOOLS` (after the vault tools, before the closing `]` at line 493) + 4 dispatch cases in `_dispatch()` (matching the existing `if name == "...":` chain pattern).

**Implementation pattern: HTTP loopback to `BAKER_INTERNAL_URL` (default `http://localhost:8080`) with `X-Baker-Key` header.** This reuses ALL endpoint logic (action handlers, RAG retrieval, Claude streaming, store-back logging, scheduler reads) without duplication. Works in embedded mode (loopback to own process) and in standalone mode (configure URL to point at production Render service).

`httpx` is already in `requirements.txt:27`. Use sync `httpx.Client` from `_dispatch()` (which is sync per existing pattern).

For SSE-returning endpoints (`/api/scan`), collect the full stream into a single text string and return.

---

## Fix/Feature 1: `baker_scan` — capability-routed Q&A

### Problem

Director cannot ask AO PM / MOVIE AM / capability-specific questions from a Code App or any MCP-connected client. The capability-routing surface is Baker's flagship multi-agent pattern, and it is invisible at the MCP layer.

### Current State

- `POST /api/scan` (`outputs/dashboard.py:7351`) — auto-routes via `classify_intent()`; SSE streaming response. Request shape: `ScanRequest{question, history, project, role, owner, alert_context}` (verified `outputs/dashboard.py:275-281`).
- `POST /api/scan/client-pm` (`outputs/dashboard.py:5586`) — explicit capability routing via `SpecialistScanRequest{question, capability_slug, history}` (verified `outputs/dashboard.py:313-316`); delegates to `scan_specialist`.
- Both require `X-Baker-Key` header (`Depends(verify_api_key)`).
- Active client_pm capabilities: query `GET /api/client-pms` (`outputs/dashboard.py:5606`) returns the live list (`ao_pm`, `movie_am`, etc.).

### Implementation

**Tool entry** (insert in `TOOLS` list in `baker_mcp/baker_mcp_server.py`, after the vault_read tool at line 492, before closing `]`):

```python
Tool(
    name="baker_scan",
    description=(
        "Run a Baker Scan — interactive Q&A across Baker's memory (emails, meetings, "
        "WhatsApp, ClickUp, contacts, deadlines). If `capability_slug` is provided, "
        "routes to the named client-PM or domain capability (e.g. `ao_pm` for "
        "Andrey Oskolkov, `movie_am` for Mandarin Vienna asset management); "
        "otherwise auto-routes via Baker's intent classifier. Returns the final "
        "answer text (SSE stream collected into one string)."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The question to ask Baker.",
                "minLength": 1,
                "maxLength": 4000,
            },
            "capability_slug": {
                "type": "string",
                "description": (
                    "Optional. Route to a specific capability instead of auto-classify. "
                    "Examples: ao_pm, movie_am, finance, legal, sales, asset_management."
                ),
            },
            "history": {
                "type": "array",
                "description": "Optional prior turns: [{role, content}, ...]",
                "default": [],
            },
            "project": {
                "type": "string",
                "description": "Optional scope: rg7, hagenauer, movie-hotel-asset-management.",
            },
            "role": {
                "type": "string",
                "description": "Optional scope: chairman, network, private, travel.",
            },
        },
        "required": ["query"],
    },
),
```

**Dispatch case** (insert in `_dispatch()` in `baker_mcp/baker_mcp_server.py` immediately AFTER the `baker_vault_read` block ends at line 1024 and BEFORE the `else: return f"Unknown tool: {name}"` at line 1026):

```python
elif name == "baker_scan":
    return _baker_scan_via_loopback(args)
```

The other 3 dispatch cases (`baker_search`, `baker_ingest_text`, `baker_health`) follow the same insertion location, in order.

**Imports to add at top of `baker_mcp/baker_mcp_server.py`** (after existing `import psycopg2` block at line 33):

```python
import httpx
import tempfile
import pathlib
```

Note: `json` is already imported at line 24. `os` is already imported at line 26. Do NOT re-import.

**Helper function** (add as a new module-level function in `baker_mcp_server.py`, BEFORE the `_dispatch()` function at line 511):

```python
def _internal_base_url() -> str:
    """Loopback URL for in-process MCP calls; override via BAKER_INTERNAL_URL env."""
    return os.getenv("BAKER_INTERNAL_URL", "http://localhost:8080")

def _internal_api_key() -> str:
    """API key for X-Baker-Key header (same as dashboard)."""
    return os.getenv("BAKER_API_KEY", "")

def _baker_scan_via_loopback(args: dict) -> str:
    """Route to /api/scan or /api/scan/client-pm based on capability_slug presence.
    Collect SSE stream into single text string."""
    query = args.get("query", "").strip()
    if not query:
        return "Error: query is required"
    capability_slug = args.get("capability_slug")
    history = args.get("history") or []

    base = _internal_base_url()
    headers = {"X-Baker-Key": _internal_api_key(), "Accept": "text/event-stream"}

    if capability_slug:
        url = f"{base}/api/scan/client-pm"
        payload = {"question": query, "capability_slug": capability_slug, "history": history}
    else:
        url = f"{base}/api/scan"
        payload = {
            "question": query,
            "history": history,
            "project": args.get("project"),
            "role": args.get("role"),
        }

    chunks: list[str] = []
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            with client.stream("POST", url, json={k: v for k, v in payload.items() if v is not None}, headers=headers) as resp:
                if resp.status_code != 200:
                    return f"Error: scan returned HTTP {resp.status_code}: {resp.text[:300]}"
                # SSE format: lines starting "data: " carry JSON event payloads.
                # CANONICAL CONTENT KEY = 'token' (verified: outputs/dashboard.py:8240,
                # 7441, etc.). Other event types (status / capabilities / tool_call /
                # screenshot / task_id / error / __citations__ prefix) are
                # metadata — append only 'token' deltas to the answer text.
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload_str = line[6:]
                    # Citations marker uses a non-JSON prefix — skip in V1
                    if payload_str.startswith("__citations__"):
                        continue
                    try:
                        evt = _json.loads(payload_str)
                    except Exception:
                        continue
                    if isinstance(evt, dict):
                        token = evt.get("token")
                        if token and isinstance(token, str):
                            chunks.append(token)
                        # Surface server-side errors as the answer
                        err = evt.get("error")
                        if err and isinstance(err, str):
                            return f"Error from scan: {err}"
    except httpx.TimeoutException:
        return "Error: scan timed out after 60s"
    except Exception as e:
        return f"Error: scan failed: {e}"

    if not chunks:
        return "(empty response — check capability_slug or query)"
    return "".join(chunks).strip()
```

**EXPLORE step before implementation**: B-code MUST grep `outputs/dashboard.py` for the actual SSE event shape emitted by `/api/scan` and `/api/scan/client-pm`. The keys `text`/`delta`/`content` are best-guess defaults — verify the canonical key name and adjust the chunk-extraction logic accordingly. Look for `yield f"data: {json.dumps(...)`}\n\n"` patterns in `scan_chat` and the SSE helper functions it calls.

### Key Constraints

- Reject empty `query` (return error string, do NOT raise — matches existing `_dispatch` error pattern).
- Pass `capability_slug` verbatim — server-side `/api/scan/client-pm` validates against `capability_sets` table.
- 60s timeout — SSE may run long for complex multi-source RAG.
- Do NOT log query content (only log boolean `has_capability_slug`) — emails/contacts are PII.

### Verification

```bash
# Test from Code CLI with MCP loaded
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_scan","arguments":{"query":"What is the status of the AO settlement?","capability_slug":"ao_pm"}}}' | \
  curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" -d @-
```

Expected: response `result.content[0].text` is non-empty string with AO PM capability output.

---

## Fix/Feature 2: `baker_search` — unified semantic search

### Problem

No MCP wrapper for cross-source Qdrant + Postgres semantic search. Cowork sessions cannot search Baker memory natively.

### Current State

- `GET /api/search/unified?q=...&limit=...` (`outputs/dashboard.py:6677`) — verified live route.
- `GET /api/search?q=...` (`outputs/dashboard.py:6769`) — narrower, kept for back-compat.

### Implementation

**Tool entry** (insert after `baker_scan`):

```python
Tool(
    name="baker_search",
    description=(
        "Semantic search across all Baker memory (emails, meetings, WhatsApp, "
        "documents, contacts, deadlines). Returns top-N matching items with "
        "relevance scores. Use for fact-finding queries; use baker_scan for "
        "conversational answers."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
                "minLength": 1,
                "maxLength": 500,
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 20, max 50).",
                "default": 20,
                "maximum": 50,
            },
        },
        "required": ["query"],
    },
),
```

**Dispatch case**:

```python
elif name == "baker_search":
    return _baker_search_via_loopback(args)
```

**Helper function** (place AFTER `_baker_scan_via_loopback`, BEFORE `_dispatch`):

```python
def _baker_search_via_loopback(args: dict) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "Error: query is required"
    limit = min(int(args.get("limit", 20)), 50)

    url = f"{_internal_base_url()}/api/search/unified"
    headers = {"X-Baker-Key": _internal_api_key()}
    params = {"q": query, "limit": limit}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code != 200:
                return f"Error: search returned HTTP {resp.status_code}: {resp.text[:300]}"
            data = resp.json()
    except Exception as e:
        return f"Error: search failed: {e}"

    # Render results as readable text — match _format_results style
    items = data.get("results") or data.get("items") or []
    if not items:
        return f"No results for: {query}"
    lines = [f"Search results for: {query} ({len(items)} hits)\n{'='*60}"]
    for r in items:
        parts = [f"  {k}: {v}" for k, v in r.items() if v is not None]
        lines.append("\n".join(parts))
    return "\n---\n".join(lines)
```

**EXPLORE step**: B-code MUST verify the actual response shape from `/api/search/unified` — adjust the `data.get("results")` lookup to match real keys. Read `outputs/dashboard.py:6677-...` for the response model.

### Verification

`curl /mcp` with `baker_search {"query": "MO Vienna GOP"}` returns formatted hit list.

---

## Fix/Feature 3: `baker_ingest_text` — text-only ingest

### Problem

No MCP wrapper for ingesting text content into Baker's knowledge base. Existing `/api/ingest` is multipart (file upload) — not callable from JSON-RPC MCP cleanly.

### Current State

- `POST /api/ingest` (`outputs/dashboard.py:8833`) — multipart `UploadFile`, not JSON. Cannot be wrapped in MCP without base64-encoding ugliness (Director ratified Option A: skip file upload from MCP scope).
- Underlying ingest function: `ingest_file(filepath, collection, image_type, project, role)` (called at `outputs/dashboard.py:8896-8903`) — accepts a Path. Will need a thin text→tempfile shim.

### Implementation

**Tool entry**:

```python
Tool(
    name="baker_ingest_text",
    description=(
        "Ingest a text document into Baker's knowledge base. Use for memos, "
        "notes, transcripts, or any text content. For binary files (PDFs, "
        "images), upload via the dashboard UI instead."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Filename for the document (e.g. 'it-memo-2026-04-26.md').",
                "minLength": 1,
                "maxLength": 200,
            },
            "content": {
                "type": "string",
                "description": "Text body to ingest.",
                "minLength": 1,
                "maxLength": 100000,
            },
            "collection": {
                "type": "string",
                "description": "Optional Qdrant collection override.",
            },
            "project": {
                "type": "string",
                "description": "Optional project tag: rg7, hagenauer, movie-hotel-asset-management.",
            },
            "role": {
                "type": "string",
                "description": "Optional role tag: chairman, network, private, travel.",
            },
        },
        "required": ["title", "content"],
    },
),
```

**Dispatch case**:

```python
elif name == "baker_ingest_text":
    return _baker_ingest_text_via_loopback(args)
```

**Helper function** (uses multipart upload from temp file; reuses existing endpoint. `tempfile` and `pathlib` already imported at top of file per Feature 1):

```python
def _baker_ingest_text_via_loopback(args: dict) -> str:
    title = (args.get("title") or "").strip()
    content = args.get("content") or ""
    if not title or not content:
        return "Error: title and content are required"

    # Enforce safe extension — append .md if missing
    if not any(title.lower().endswith(ext) for ext in (".md", ".txt", ".markdown")):
        title = title + ".md"

    url = f"{_internal_base_url()}/api/ingest"
    headers = {"X-Baker-Key": _internal_api_key()}

    # Server validates project/role/collection against allowlists; pass through
    form_data = {}
    if args.get("project"):
        form_data["project"] = args["project"]
    if args.get("role"):
        form_data["role"] = args["role"]
    params = {}
    if args.get("collection"):
        params["collection"] = args["collection"]

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=pathlib.Path(title).suffix, delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as fh:
            files = {"file": (title, fh, "text/plain")}
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    url, headers=headers, params=params, data=form_data, files=files
                )
                if resp.status_code != 200:
                    return f"Error: ingest returned HTTP {resp.status_code}: {resp.text[:300]}"
                result = resp.json()
                return (
                    f"Ingested: {result.get('filename', title)}\n"
                    f"Status: {result.get('status', 'unknown')}\n"
                    f"Collection: {result.get('collection', '')}\n"
                    f"Chunks: {result.get('chunks', 0)}\n"
                    f"Dedup: {result.get('dedup', False)}"
                )
    except Exception as e:
        return f"Error: ingest failed: {e}"
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
```

### Key Constraints

- 100K character cap on `content` (matches typical document size; larger files belong in dashboard upload).
- Auto-append `.md` if user provides no extension.
- Server-side `/api/ingest` already validates `project` against `{rg7, hagenauer, movie-hotel-asset-management}` and `role` against `{chairman, network, private, travel}` — pass-through, do NOT duplicate validation here.
- Clean up tempfile in `finally`.

### Verification

`baker_ingest_text {"title": "test-mcp.md", "content": "Hello Baker MCP."}` returns success JSON with `chunks > 0`.

---

## Fix/Feature 4: `baker_health` — programmatic health probe

### Problem

No MCP wrapper for system health. Cowork sessions cannot programmatically check Baker status (sentinels, scheduler, DB).

### Current State

- `GET /health` (`outputs/dashboard.py:1317`) — basic public health (no auth).
- `GET /api/health` (`outputs/dashboard.py:1965`) — auth-gated, fuller status.
- `GET /api/health/scheduler` (`outputs/dashboard.py:1295`) — scheduler-only.

### Implementation

**Tool entry**:

```python
Tool(
    name="baker_health",
    description=(
        "Get Baker system health: database connectivity, scheduler status, "
        "active sentinels, vault mirror state, last update timestamps. Returns "
        "a structured health summary for monitoring or pre-flight checks."
    ),
    inputSchema={
        "type": "object",
        "properties": {},
    },
),
```

**Dispatch case**:

```python
elif name == "baker_health":
    return _baker_health_via_loopback()
```

**Helper function**:

```python
def _baker_health_via_loopback() -> str:
    url = f"{_internal_base_url()}/health"   # public path; unauth-gated
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return f"Error: health returned HTTP {resp.status_code}: {resp.text[:300]}"
            data = resp.json()
    except Exception as e:
        return f"Error: health probe failed: {e}"

    parts = [
        f"Status: {data.get('status', 'unknown')}",
        f"Database: {data.get('database', '?')}",
        f"Scheduler: {data.get('scheduler', '?')}",
        f"Scheduled jobs: {data.get('scheduled_jobs', '?')}",
        f"Sentinels healthy: {data.get('sentinels_healthy', '?')}",
        f"Sentinels down: {data.get('sentinels_down', 0)}",
    ]
    if data.get("sentinels_down_list"):
        parts.append(f"  ↳ down: {', '.join(data['sentinels_down_list'])}")
    if data.get("vault_mirror_last_pull"):
        parts.append(f"Vault mirror last pull: {data['vault_mirror_last_pull']}")
    if data.get("vault_mirror_commit_sha"):
        parts.append(f"Vault mirror sha: {data['vault_mirror_commit_sha'][:12]}")
    parts.append(f"Timestamp: {data.get('timestamp', '?')}")
    return "\n".join(parts)
```

### Key Constraints

- Use `/health` (public, no auth). Avoids X-Baker-Key dependency for the simplest probe — which is also what an external monitor would hit.
- 10s timeout; quick fail.
- Graceful degradation: if any field missing in response, render `?` placeholder, do NOT crash.

### Verification

`baker_health {}` returns multi-line status block. Verify all 7 fields render even if some are absent in the response.

---

## Files Modified

- `baker_mcp/baker_mcp_server.py` — add 4 Tool entries, 4 dispatch cases, 4 helper functions, 2 internal-URL/key helpers, `httpx`/`tempfile`/`pathlib` imports
- `tests/test_mcp_baker_extension_1.py` (NEW) — 4+ test cases per tool (28+ tests total)

## Do NOT Touch

- `outputs/dashboard.py` — endpoints already exist; no new routes, no edits to existing
- Existing 26 tools in `baker_mcp/baker_mcp_server.py:TOOLS` (lines 145-492) — additions only, no edits
- `_handle_mcp_message` in `outputs/dashboard.py:574` — JSON-RPC dispatch already handles tools/list + tools/call generically
- `requirements.txt` — `httpx` already present (line 27); no new deps

---

## Code Brief Standards (mandatory)

- **API version:** Baker FastAPI internal API (no external version dep). Endpoints verified live 2026-04-26 via `grep -n` on `outputs/dashboard.py`.
- **Deprecation check date:** All 4 endpoints production-active as of 2026-04-26 (verified by grep + recent CLAUDE.md entry listing 24+ MCP tools).
- **Fallback:** None needed — tools default-fail with error string per `_dispatch` pattern. No env-var feature flag (tools are additive; no risk to existing surface).
- **DDL drift check:** N/A — no Postgres writes. Verify via grep: `rg "INSERT|UPDATE|DELETE|CREATE TABLE|ALTER" baker_mcp/baker_mcp_server.py | grep -v "^baker_mcp/baker_mcp_server.py:.*#"` returns 0 net new lines from this brief.
- **Literal pytest output mandatory:** Ship report MUST include literal `pytest tests/test_mcp_baker_extension_1.py -v` stdout. ≥28 tests expected (4 tools × ~7 cases: happy path / empty input / timeout / HTTP error / capability_slug present-vs-absent / response-shape variations). NO "passes by inspection."
- **Function-signature verification (Lesson #44):** before writing code, B-code MUST grep:
  - `def scan_chat\|def scan_specialist\|def scan_client_pm` in `outputs/dashboard.py`
  - The actual SSE event shape emitted (look for `yield f"data: {...`)
  - The `/api/search/unified` response keys
  - The `/api/health` response keys (compare to live curl output above)

## Verification Criteria

1. `pytest tests/test_mcp_baker_extension_1.py -v` ≥28 tests pass, 0 regressions in existing test suite.
2. `python -c "from baker_mcp.baker_mcp_server import TOOLS; print(len(TOOLS))"` → **30** (was 26 + 4 new).
3. `python -c "from baker_mcp.baker_mcp_server import _dispatch; print(_dispatch('baker_health', {}))"` (with live local Baker on `:8080`) → multi-line status block.
4. Live MCP smoke test against Render:
   ```bash
   curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq '.result.tools | map(.name)'
   ```
   Output includes `baker_scan`, `baker_search`, `baker_ingest_text`, `baker_health`.
5. `tools/call` for `baker_scan` with `{"query":"hello","capability_slug":"ao_pm"}` returns non-empty text.
6. `python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"` exits 0.
7. PR description lists the 4 new tool names + which endpoints they wrap + any deviations from this brief (e.g., SSE key name found in EXPLORE step).
8. Lesson #52 compliance: AI Head reviewer MUST invoke `/security-review` skill against PR branch before merge — manual diff-read NOT substitute.

## Quality Checkpoints

1. SSE event-shape match: `_baker_scan_via_loopback` extracts the canonical text key (verified by EXPLORE grep).
2. Empty-query rejection in all 3 tools that take `query` (return error string, not exception).
3. 60s/15s/60s/10s timeouts on scan/search/ingest/health respectively.
4. Tempfile cleanup in `_baker_ingest_text_via_loopback` `finally`.
5. `BAKER_INTERNAL_URL` env override works (test by setting `http://invalid:9999` and confirming graceful error).
6. `BAKER_API_KEY` not logged anywhere (audit log statements before push).
7. `tools/list` advertises all 4 new tools with correct inputSchema.
8. Existing 26 tools still work post-merge (regression test on `baker_deadlines` and `baker_vault_read`).
9. No new entries in `requirements.txt`.
10. Render auto-deploy completes; live smoke test (verification #4) passes within 5 min of merge.

## Verification SQL

N/A — this brief adds no DB writes, no migrations.

To confirm the 4 new tools are advertised post-deploy (HTTP, not SQL):

```bash
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | jq '.result.tools | map(.name) | sort'
```

Expected: array contains `baker_scan`, `baker_search`, `baker_ingest_text`, `baker_health` plus the existing 26.

## Out of scope

- File-upload via MCP (Director ratified Option A: text-only `baker_ingest_text`).
- Streaming responses for `baker_scan` (collected to single text — MCP tools/call protocol is request/response, not stream).
- New scan capability slugs / new client_pm capabilities — server-side capability registry change is a separate brief.
- Authentication beyond X-Baker-Key (no per-user auth on MCP — same auth model as existing 26 tools).
- Vault-write MCP tools (separate brief; current vault tools are read-only).
- Migrating standalone-mode (`python baker_mcp_server.py`) to support these 4 new tools — they require FastAPI loopback, so standalone mode returns "not available standalone" or routes to production URL via `BAKER_INTERNAL_URL`.

## Branch + PR

- Branch: `baker-mcp-extension-1`
- PR title: `BAKER_MCP_EXTENSION_1: 4 new MCP tools (scan / search / ingest_text / health)`
- Reviewer: B1 second-pair (MEDIUM trigger class) → AI Head B Tier-A merge on APPROVE + `/security-review` skill PASS

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
