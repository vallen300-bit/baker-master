# B4 Ship Report — DROPBOX_SEARCH_TOOL_1

- **Brief:** `briefs/BRIEF_DROPBOX_SEARCH_TOOL_1.md` (codex G0 PASS #12346)
- **Dispatched by:** lead (bus #12348), Director GO 2026-07-17
- **PR:** #592 — `b4/dropbox-search-tool-1` → `main` @ ad3ce72c
- **Task class:** feature-small (verified-live)

## What shipped
New read-only MCP tool `baker_dropbox_search` — live `files/search_v2` over the
entire Vallen Dropbox (all 4 top-level areas), no ingestion.

- `triggers/dropbox_client.py`: `search()`, `_resolve_path_root_header()`
  (team-root namespace pinning, **fail-closed** `DropboxPathRootError` — no silent
  home-namespace fallback), `_api_post` extended with `extra_headers`.
- `baker_mcp/baker_mcp_server.py`: `baker_dropbox_search` Tool + dispatch branch.
- `tests/test_dropbox_search_tool.py`: 8 tests.
- `tests/test_mcp_baker_extension_1.py`: tool-count lock 54 → 55.

## Brief-assumption correction (deviation, live-verified)
The brief said `users/get_current_account` needs an **empty body**. Live curl:

| body variant | result |
|---|---|
| empty body + `Content-Type: application/json` (brief's spec) | **500 "unexpected error occurred"** |
| literal `null` + `Content-Type: application/json` | **200** + full `root_info` |
| no body, no content-type | 200 |

The fail-closed guard correctly blocked ALL searches on the 500 (proof the guard
works live). Fixed `_api_post` to send `content=b"null"` for no-arg endpoints.
Added a regression-lock unit test. This is a factual correction, not a design
change — no ruling needed.

## Done rubric
1. **Unit tests green** — literal output:
   ```
   tests/test_dropbox_search_tool.py .......  (8 passed)
   tests/test_mcp_baker_extension_1.py ...... (48 passed) → 49 passed together
   79 passed (adding test_clerk_runtime + test_ocr_reextract_missing importers)
   ```
2. **`tools/list` shows `baker_dropbox_search`** — pending post-deploy.
3. **Cross-area coverage (THE acceptance criterion) — PASS.** Live prototype probe
   (throwaway, not committed), path-root header resolved to team root
   `{".tag":"root","root":"1929832467"}` (≠ home namespace):
   - `list_folder("")` at team root → all 4 areas visible: `/Dimitry vallen`,
     `/BRISEN GROUP GENEVA`, `/Vienna projects`, `/Swiss Projects`.
   - `search("Projekt")` → 9 hits spanning **`/Dimitry vallen` + `/Vienna projects`**
     (2 distinct top-level areas → cross-area PASS).
   - `search("Vertrag")` → 3 hits spanning root + `/Dimitry vallen`.
   - Note: sparse terms return few/zero hits (`Hagenauer`=0, `Brisen`=1) — filename/
     content match sparsity, NOT a scope bug (all areas reachable per list_folder).
4. **Poller unaffected** — `_api_post` change additive (optional 3rd param;
   positional callers intact); compile-clean; importer tests (clerk_runtime,
   ocr_reextract) pass. One clean post-deploy poll to confirm.

## Post-deploy AC (2026-07-17, main @e67ce6d7 live on Render — PASS)
Probes run against prod `/mcp` (`https://baker-master.onrender.com`), health
reported `main` live, 22/22 sentinels healthy, 0 down.

1. **`tools/list` shows `baker_dropbox_search`** — PASS. Tool count 55 live
   (matches the 54→55 lock); `baker_dropbox_search` present.
2. **Cross-area live search (THE acceptance criterion) — PASS.** Live tool call
   via prod `/mcp`, deterministic team-root-resolved evidence:
   - `search("Projekt")` → 9 matches spanning **`/Dimitry vallen` + `/Vienna projects`**.
   - `search("RG7")` → 10 matches spanning **`/BRISEN GROUP GENEVA` + `/Dimitry vallen`**.
   - Path-root-resolved proof: hits under `/BRISEN GROUP GENEVA` and `/Vienna
     projects` are OUTSIDE the member home namespace — reachable ONLY when the
     path-root header pins the team root. Their presence in live results is
     deterministic evidence the resolver did not degrade to home-namespace.
   - Sparse terms (`Vertrag`=2 single-area, `Hagenauer`=0) reflect content-index
     sparsity, not a scope bug — RG7/Projekt prove all areas reachable live.
3. **Poller unaffected — PASS.** Health: 22 sentinels healthy / 0 down post-deploy;
   `_api_post` change additive (optional `extra_headers`; positional callers intact);
   `baker_actions` shows 0 dropbox writes in 24h (read-only tool, no side effects).

## Verification
- codex ship-report verification (default deputy) — cc'd on the verdict.

## Files
- `triggers/dropbox_client.py`
- `baker_mcp/baker_mcp_server.py`
- `tests/test_dropbox_search_tool.py` (new)
- `tests/test_mcp_baker_extension_1.py`
