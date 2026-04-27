# CODE_3_PENDING — B3: BAKER_MCP_EXTENSION_1 — 2026-04-26

**Dispatcher:** AI Head B (M2 lane)
**Brief:** `briefs/BRIEF_BAKER_MCP_EXTENSION_1.md`
**Trigger class:** MEDIUM (new MCP tools touching scan/search/ingest/health) → B1 second-pair-review pre-merge per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`
**Branch:** `baker-mcp-extension-1` (cut from `main`)
**Estimated time:** 2-3h
**Authority:** Director ratified 2026-04-26 evening — "a on both, proceed" (Q1 unified `baker_scan` with optional `capability_slug`; Q2 text-only `baker_ingest_text`).

## What you're building

4 new MCP tools wrapping existing live REST endpoints:

1. **`baker_scan`** — capability-routed Q&A. If `capability_slug` provided → routes to `/api/scan/client-pm`; else `/api/scan` auto-route. Collects SSE stream into single text. **The AO PM / MOVIE AM / capability channel.**
2. **`baker_search`** — wraps `GET /api/search/unified` for cross-source semantic search.
3. **`baker_ingest_text`** — wraps `POST /api/ingest` (text via tempfile→multipart). File upload is out-of-scope per Director ratification.
4. **`baker_health`** — wraps `GET /health` (public, no auth).

## Implementation pattern

HTTP loopback to `BAKER_INTERNAL_URL` (default `http://localhost:8080`) using `httpx` (already in `requirements.txt:27`). Reuses ALL endpoint logic — no duplication.

## Critical EXPLORE step before coding (Lesson #44)

Brief specifies SSE canonical content key as `token` (verified at `outputs/dashboard.py:8240` etc.). **You MUST grep `outputs/dashboard.py` to confirm the SSE event shape emitted by `scan_specialist` (line 5483) for the `/api/scan/client-pm` path** — verify that path also uses `token` for content deltas. Adjust `_baker_scan_via_loopback` extraction logic if a different key is canonical for that route. Other event types (`status`, `capabilities`, `tool_call`, `screenshot`, `task_id`, `error`, `__citations__` prefix) are metadata — skip.

## Files to modify

- `baker_mcp/baker_mcp_server.py` — add 4 Tool entries (after line 492, before closing `]` at 493), 4 dispatch cases (after line 1024 `baker_vault_read` block, before line 1026 `else: Unknown tool`), 4 helper functions + 2 internal-URL/key helpers (BEFORE `_dispatch` at line 511), top-level imports `httpx` / `tempfile` / `pathlib`
- `tests/test_mcp_baker_extension_1.py` (NEW) — ≥28 tests (4 tools × ~7 cases each)

## Files NOT to touch

- `outputs/dashboard.py` — endpoints already exist; no new routes
- `baker_mcp/baker_mcp_server.py:TOOLS[0..25]` — additions only, no edits
- `requirements.txt` — `httpx` already present
- `_handle_mcp_message` in `outputs/dashboard.py:574` — JSON-RPC dispatch already handles tools/list + tools/call generically

## Ship gate (literal pytest mandatory — Lesson #47)

```bash
cd ~/bm-b3
pytest tests/test_mcp_baker_extension_1.py -v 2>&1 | tail -40
```

Paste literal stdout into ship report. ≥28 tests pass. NO "by inspection."

## Verification

1. ≥28 pytest pass + 0 regressions in existing test suite
2. `python -c "from baker_mcp.baker_mcp_server import TOOLS; print(len(TOOLS))"` → **30** (was 26 + 4 new)
3. `python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"` exits 0
4. Live MCP smoke test (post-merge against Render):
   ```bash
   curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq '.result.tools | map(.name)'
   ```
   Output includes `baker_scan`, `baker_search`, `baker_ingest_text`, `baker_health`.

## Process

1. `cd ~/bm-b3 && git checkout main && git pull -q`
2. `git checkout -b baker-mcp-extension-1`
3. EXPLORE: grep `outputs/dashboard.py` for SSE event shape on `scan_specialist` path (Lesson #44 — verify before coding)
4. Implement per brief §"Fix/Feature 1..4" (read full brief at `briefs/BRIEF_BAKER_MCP_EXTENSION_1.md`)
5. Write tests at `tests/test_mcp_baker_extension_1.py`
6. Run ship gate (pytest literal output)
7. Syntax check: `python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"`
8. Commit + push, open PR titled `BAKER_MCP_EXTENSION_1: 4 new MCP tools (scan / search / ingest_text / health)`
9. Write ship report at `briefs/_reports/B3_baker_mcp_extension_1_<date>.md` with literal pytest stdout
10. Mark this mailbox COMPLETE on PR-merge per §3 hygiene

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
