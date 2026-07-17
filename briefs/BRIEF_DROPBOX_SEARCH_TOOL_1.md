# BRIEF: DROPBOX_SEARCH_TOOL_1 — `baker_dropbox_search` MCP tool (full-Dropbox live search, no ingestion)

## Context
Cloud agents (CM-1 and any agent reaching Baker via the `/mcp` endpoint) can only search
the ingested corpus (Baker-Feed folders, ClaimsMax, email). Director wants ALL Dropbox
areas searchable — `BRISEN GROUP GENEVA`, `Dimitry vallen`, `Swiss Projects`,
`Vienna projects` — without mass ingestion. Director GO 2026-07-17 (cowork-ah1 chat).

Solution: expose Dropbox's own `files/search_v2` API as a new read-only MCP tool.
The OAuth plumbing already exists in `triggers/dropbox_client.py` (refresh-token flow,
rate limiting, 401/429 retry — re-minted with full scopes 2026-06-06, Lesson #97).

## Estimated time: ~2-3h
## Complexity: Low-Medium
## Prerequisites: existing Render env vars `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN` (no new secrets)

## Harness V2

### Context Contract
- **Inputs:** existing `DropboxClient` (triggers/dropbox_client.py), existing MCP TOOLS/_dispatch (baker_mcp/baker_mcp_server.py), Render env `DROPBOX_APP_KEY`/`DROPBOX_APP_SECRET`/`DROPBOX_REFRESH_TOKEN`.
- **Outputs:** one new read-only MCP tool `baker_dropbox_search` returning paths + metadata text; no DB writes, no UI, no new env vars.
- **Out of context:** ingestion pipeline, poll cadence, semantic search (kbl), dashboard frontend.

### Task class
`feature-small` — production implementation, single lane, no migration, no UI surface.

### Done rubric (done-state class: verified-live)
1. Unit tests green (4 cases listed in Verification).
2. `tools/list` on prod `/mcp` shows `baker_dropbox_search`.
3. Live probe returns matches whose paths span ≥2 distinct top-level Dropbox areas — cross-area coverage is THE acceptance criterion; single-area results = NOT done (path-root bug).
4. Existing Dropbox poller unaffected (one poll cycle clean post-deploy).

### Gate plan
1. codex G0 review of this brief before dispatch (gatekeeper — Director-mandated).
2. B-code implements; local prototype probe (Step 3) result pasted in ship report.
3. Ship report verified by codex (default deputy) incl. live-probe output.
4. post-deploy-ac-bus-gate verdict posted before DONE claim.

## Baker Agent Vault Rails
Relevant vault rails: standing-contract (read-only tool, audited surface), verification-surfaces (post-deploy live probe).
Ignore unrelated rails: bus-and-lanes, loop-runner, memory-and-lessons (no memory writes), skills-and-playbooks.

### Surface contract
N/A — no UI surface. MCP tool + client method only; no dashboard/frontend change.

---

## Fix/Feature 1: `DropboxClient.search()` + namespace-aware path root

### Problem
`DropboxClient` (triggers/dropbox_client.py, 293 lines) has `list_folder` and
`download_file` only — no search. Additionally, "Vallen Dropbox" is a team-space
account: the four Director areas may live in the team root, not the member home
namespace. A naive `files/search_v2` call could silently search only the home
namespace and miss entire areas — worst failure mode (looks working, wrong scope).

### Current State
- `triggers/dropbox_client.py:126` — `_api_post(url, json_body)` handles auth, rate limit, 401 refresh-retry, 429 sleep-retry. Reuse it; do NOT re-implement auth.
- `triggers/dropbox_client.py:152` — `list_folder` shows the existing call pattern.
- Singleton via `DropboxClient._get_global_instance()` (line 34) — never instantiate directly.

### Engineering Craft Gates
- Diagnose: N/A — new feature, no bug to reproduce.
- Prototype: applies — BEFORE wiring the MCP tool, run a throwaway local probe (Step 3 below) answering one question: "does search_v2 with path-root header reach all four areas?" Throwaway script, not committed; result pasted into the ship report.
- TDD/verification: applies — public seam is `_dispatch("baker_dropbox_search", ...)`. Write one vertical test first (mocked httpx) in `tests/test_dropbox_search_tool.py`, then implement.

### Implementation

**Step 1 — add namespace resolution + search to `triggers/dropbox_client.py`** (append inside the class):

```python
    def _resolve_path_root_header(self) -> dict:
        """Return Dropbox-API-Path-Root header pinning calls to the TEAM root.

        Team-space accounts (Vallen Dropbox): member home is a sub-namespace;
        top-level team folders (BRISEN GROUP GENEVA, Swiss Projects, ...) are
        only reachable when path root = root namespace. Cached after first call.
        """
        if getattr(self, "_path_root_header", None) is not None:
            return self._path_root_header
        try:
            account = self._api_post(
                "https://api.dropboxapi.com/2/users/get_current_account", json_body=None
            )
            root_info = account.get("root_info", {})
            root_ns = root_info.get("root_namespace_id")
            home_ns = root_info.get("home_namespace_id")
            if root_ns and root_ns != home_ns:
                import json as _json
                self._path_root_header = {
                    "Dropbox-API-Path-Root": _json.dumps({".tag": "root", "root": root_ns})
                }
            else:
                self._path_root_header = {}
        except Exception as e:
            logger.warning(f"Dropbox path-root resolution failed, using default: {e}")
            self._path_root_header = {}
        return self._path_root_header

    def search(self, query: str, path: str = "", max_results: int = 25,
               filename_only: bool = False) -> list[dict]:
        """Full-Dropbox search via /2/files/search_v2. Read-only.

        Returns list of {path, name, modified, size_bytes, match_type}.
        Content matching requires plan support; filename matching always works.
        """
        options = {
            "max_results": max(1, min(max_results, 25)),
            "file_status": "active",
            "filename_only": filename_only,
        }
        if path:
            options["path"] = path
        body = {"query": query[:1000], "options": options}
        data = self._api_post(
            "https://api.dropboxapi.com/2/files/search_v2",
            json_body=body,
            extra_headers=self._resolve_path_root_header(),
        )
        results = []
        for m in data.get("matches", []):
            md = m.get("metadata", {}).get("metadata", {})
            if md.get(".tag") != "file":
                continue
            results.append({
                "path": md.get("path_display", ""),
                "name": md.get("name", ""),
                "modified": md.get("server_modified", ""),
                "size_bytes": md.get("size", 0),
                "match_type": (m.get("match_type", {}) or {}).get(".tag", "unknown"),
            })
        return results
```

**Step 2 — extend `_api_post` signature** (surgical edit at line 126; keep all
existing retry logic; `json_body=None` must send an empty body for
`users/get_current_account`, which rejects a JSON body):

```python
    def _api_post(self, url: str, json_body: Optional[dict], extra_headers: Optional[dict] = None) -> dict:
        """POST to Dropbox API with auth, rate limiting, and auto-retry on 401."""
        self._check_rate_limit()
        headers = {**self._auth_headers(), "Content-Type": "application/json", **(extra_headers or {})}
        resp = self._client.post(url, headers=headers, json=json_body)
```
(then mirror `extra_headers` into the two retry re-posts inside the function —
rebuild `headers` the same way after `_refresh_access_token()`.)

All existing call sites pass `json_body` positionally — signature stays compatible.

**Step 3 — throwaway coverage probe (run locally, do NOT commit):** call
`search("Hagenauer")` and `search("Brisen")` with env vars from 1Password item
`API Dropbox`; assert result paths span at least 2 of the 4 top-level areas.
If only Baker-Feed/home paths return, the path-root header is wrong — fix before
proceeding. Paste probe output into the ship report.

**Step 4 — register MCP tool in `baker_mcp/baker_mcp_server.py`:**

Append to `TOOLS` list (before closing `]` at ~line 1007):

```python
    Tool(
        name="baker_dropbox_search",
        description=(
            "Live search across the ENTIRE Vallen Dropbox (all areas: BRISEN GROUP "
            "GENEVA, Dimitry vallen, Swiss Projects, Vienna projects) via Dropbox's "
            "own search API. Covers files NOT ingested into Baker. Matches filenames "
            "always; file content where plan supports it. Read-only; returns paths + "
            "metadata, not file bodies. Use baker_search for semantic search over "
            "the ingested corpus."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms (filename or content keywords).",
                    "minLength": 1,
                    "maxLength": 500,
                },
                "path": {
                    "type": "string",
                    "description": "Optional folder scope, e.g. '/Swiss Projects'. Empty = whole Dropbox.",
                    "default": "",
                },
                "filename_only": {
                    "type": "boolean",
                    "description": "Restrict matching to filenames (faster).",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 15, max 25).",
                    "default": 15,
                    "maximum": 25,
                },
            },
            "required": ["query"],
        },
    ),
```

Append to `_dispatch` (elif chain, before the final unknown-tool fallthrough):

```python
    elif name == "baker_dropbox_search":
        from triggers.dropbox_client import DropboxClient
        query = args.get("query", "").strip()
        if not query:
            return "Error: query is required."
        try:
            client = DropboxClient._get_global_instance()
            hits = client.search(
                query=query,
                path=args.get("path", ""),
                max_results=args.get("limit", 15),
                filename_only=args.get("filename_only", False),
            )
        except Exception as e:
            # Lesson #97: surface the Dropbox error_summary, never an opaque wrapper
            detail = ""
            resp = getattr(e, "response", None)
            if resp is not None:
                detail = f" status={resp.status_code} body={resp.text[:300]}"
            return f"Error: dropbox search failed: {e}{detail}"
        if not hits:
            return f"No Dropbox matches for '{query}'."
        lines = [f"Dropbox Search — {len(hits)} match(es) for '{query}':", ""]
        for h in hits:
            lines.append(
                f"- {h['path']} ({h['match_type']}, modified {h['modified']}, {h['size_bytes']} bytes)"
            )
        return "\n".join(lines)
```

### Key Constraints
- **Read-only.** No download, no file bodies in v1 — paths + metadata only.
- **No ingestion changes.** Do NOT touch `tools/ingest/`, poll cadence, or Baker-Feed watermarks.
- **No pagination in v1.** Single `search_v2` page (max 25). No `search/continue_v2` — keeps the sync MCP dispatch fast; the `/mcp` endpoint offloads sync dispatch to a thread (MCP_EVENTLOOP_OFFLOAD_502_FIX_1) but a bounded single call stays well under timeout.
- **Reuse `_api_post`** — its 401-refresh + 429 retry logic is battle-tested; do not add a second HTTP path.
- **Lazy import** of `DropboxClient` inside the dispatch branch — `baker_mcp_server` must not import `triggers.*` at module load.
- **No secrets in code or brief** — env var names only.
- Content-match may be unavailable on some plans: filename matches still return; do not treat `match_type != content` as an error.

### Verification
1. Unit tests (`tests/test_dropbox_search_tool.py`, mocked httpx): (a) `search()` parses matches + applies path-root header when `root_namespace_id != home_namespace_id`; (b) `_dispatch("baker_dropbox_search", {"query": "x"})` formats results; (c) empty query → error string; (d) HTTPStatusError surfaces status + body excerpt.
2. `pytest tests/test_dropbox_search_tool.py -v` green; `python3 -c "import py_compile; py_compile.compile('triggers/dropbox_client.py', doraise=True)"` + same for `baker_mcp/baker_mcp_server.py`.
3. Post-deploy live probe:
```bash
curl -s -X POST "https://baker-master.onrender.com/mcp" -H "X-Baker-Key: $BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_dropbox_search","arguments":{"query":"Hagenauer","limit":10}}}'
```
Expected: ≥1 match with paths from at least 2 distinct top-level areas (e.g. `/Dimitry vallen/14_HAGENAUER_MASTER/...` AND a team-folder path). If all paths are under one area → path-root bug, NOT done.

---

## Files Modified
- `triggers/dropbox_client.py` — add `search()`, `_resolve_path_root_header()`, extend `_api_post` with `extra_headers`
- `baker_mcp/baker_mcp_server.py` — 1 Tool entry + 1 dispatch branch
- `tests/test_dropbox_search_tool.py` — new

## Do NOT Touch
- `tools/ingest/*`, `tools/document_pipeline.py` — ingestion unchanged by design
- `triggers/embedded_scheduler.py` — poll cadence unchanged
- `outputs/dashboard.py` — MCP endpoint already dispatches by name; no edit needed
- `kbl/*` — semantic search path unrelated

## Quality Checkpoints
1. Existing Dropbox poller still works after `_api_post` signature change (run existing dropbox tests / poll once locally).
2. `tools/list` on `/mcp` shows `baker_dropbox_search` post-deploy.
3. Live probe returns cross-area paths (the acceptance criterion, not just 200 OK).
4. Error path returns Dropbox `error_summary` text, not opaque wrapper (Lesson #97).
5. No new env vars needed — confirm Render still has the 3 DROPBOX_* keys before deploy.

## Verification SQL
```sql
-- Tool calls are audited via MCP dispatch logging only; no DB writes in this feature.
-- Confirm no unexpected writes:
SELECT action_type, COUNT(*) FROM baker_actions
WHERE created_at > NOW() - INTERVAL '1 day' AND action_type ILIKE '%dropbox%'
GROUP BY action_type LIMIT 10;
```

## Dispatch metadata
- dispatched_by: lead (handed over by cowork-ah1 per Director instruction 2026-07-17)
- Gate: codex G0 review before dispatch (standard gatekeeper flow)
- Director GO: 2026-07-17, cowork-ah1 chat ("go")
