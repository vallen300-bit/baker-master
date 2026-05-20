---
brief_id: CLAIMSMAX_ASK_ENDPOINT_1
author: AH1-Terminal (lead)
dispatched_by: lead
target: b4
created: 2026-05-20
status: dispatched
parent_brief: CLAIMSMAX_API_CAPABILITY_1
unblocks: PINNED §N F3
---

# BRIEF_CLAIMSMAX_ASK_ENDPOINT_1 — wire `/api/v1/ask`

### Surface contract: N/A — backend client method + MCP tool dispatch; no clickable surface.

## Problem

`kbl/claimsmax_client.py::ClaimsmaxClient.ask()` raises `NotImplementedError`
("vendor bug pending Ellie Technologies fix"). The vendor shipped the fix
2026-05-20 — `temperature` is no longer passed to Anthropic for affected
models. AH1 verified the endpoint live 2026-05-20 ~23:50Z (HTTP 200, real
RAG-grounded answer + citations).

Last remaining ClaimsMax fast-follow blocker (PINNED §N F3). Clearing it
finalises the integration.

## Constraints

1. **API version/endpoint:** `POST /api/v1/ask` on
   `https://brisen.claimsmax.co.uk` (base URL from `CLAIMSMAX_BASE_URL`).
2. **Deprecation check date:** verified live 2026-05-20 by AH1.
3. **Fallback note:** none — vendor confirms `/ask` stable; no migration
   pending.
4. **Migration-vs-bootstrap DDL check:** N/A (no DDL).
5. **Ship gate:** literal `pytest tests/test_claimsmax_client.py -v` green
   + new MCP-tool test green; full suite delta ≥ 0 failures.
6. **Test plan:** unit-test the new `ask()` path with mocked `httpx`; flip
   the existing `test_ask_raises_not_implemented` to assert the real
   return shape; add an MCP-surface test mirroring
   `baker_claimsmax_search`'s pattern.
7. **`file:line` citation verification:** all paths cited below verified
   against current `main` HEAD `5af2971`.
8. **Singleton pattern:** N/A (`ClaimsmaxClient` is module-cached via
   `tools/claimsmax.py::_get_client`, already singleton-equivalent).
9. **Post-merge script handoff:** N/A.
10. **Invocation-path audit (Amendment H):** N/A — ClaimsMax tools are
    Pattern-1 (raw read/write), not Pattern-2 (capability_sets).

## Live response shape (verified by AH1 2026-05-20 ~23:50Z)

Request body fields used:
- `question`: str (required)
- `claim_id`: optional (server accepts `null`; passed in our probe)

Response (top-level keys):
- `question`: str (echo)
- `language`: str (default `"en"`)
- `model`: str (e.g. `"claude-opus-4-7"`)
- `answer`: str (markdown-style with inline `[D1]`-style citation refs)
- `citations`: list of dicts. Each:
  `id` (str, e.g. `"D1"`), `doc_id` (str/UUID), `original_filename` (str),
  `doc_date` (str/null, ISO date), `l1` (str), `l2` (str), `chunk_index`
  (int/null), `score` (float), `snippet` (str). Optional on large
  snippets: `truncated` (bool), `full_char_count` (int),
  `included_char_count` (int).
- `used_chunks`: list of dicts. Each: `citation_id` (str), `doc_id` (str),
  `chunk_index` (int/null), `score` (float).
- `confidence`: float in `[0.0, 1.0]`.
- `query_terms`: list[str].
- `retrieval`: dict — `docs_considered` (int), `docs_included` (int),
  `total_context_chars` (int), `chunks_searched` (int), `query_ms` (int),
  `generation_ms` (int), `total_ms` (int).

Latency observed: ~17.7s end-to-end for a trivial query against a 747-doc
corpus. Acceptable; do NOT lower default `_DEFAULT_TIMEOUT` (120s) — leave
headroom for larger contexts.

## Acceptance criteria

### Required

1. **`kbl/claimsmax_client.py::ClaimsmaxClient.ask()` implemented.**
   Signature:
   ```python
   def ask(
       self,
       question: str,
       claim_id: Optional[str] = None,
       language: str = "en",
   ) -> dict:
       """POST /ask — RAG-grounded synthesis with citations."""
   ```
   Body construction: include `question` always, `claim_id` only when not
   `None`, `language` always (default `"en"` — matches investigate
   default). Route through `self._request("POST", "ask", json=body)`.
   Returns raw response dict (caller responsible for shape).

2. **Existing test flipped.**
   `tests/test_claimsmax_client.py::test_ask_raises_not_implemented`
   (line 236) → rename to `test_ask_returns_response` and assert against
   a mocked 200 response carrying the documented shape (answer +
   citations + confidence + retrieval). Use the existing mock-`httpx`
   pattern from `test_search_parses_response` (line 82).

3. **New MCP tool `baker_claimsmax_ask` added to `tools/claimsmax.py`.**
   Mirror `baker_claimsmax_search`'s definition pattern (Tool schema +
   dispatch function + return JSON). Schema args: `question` (required
   str), `claim_id` (optional str), `language` (optional str, default
   `"en"`). Add to the tool list comment block at top of file
   (`tools/claimsmax.py:5-14`) under a new `Ask synthesis:` subsection.

4. **New test for the MCP tool dispatch.** Add to
   `tests/test_claimsmax_client.py` (single test file for this surface;
   no separate MCP test file exists today). Mock `_get_client` to
   return a stub returning the documented shape; assert JSON
   serialization is clean.

5. **Module docstring updated.** Both `kbl/claimsmax_client.py` lines
   20-22 ("`/ask` is deliberately unimplemented…") AND the relevant
   header comment in `tools/claimsmax.py` — strike the
   "pending vendor fix" framing; replace with one-line current state.

### Required (verification)

6. **Live smoke after merge.** AH1 runs one `baker_claimsmax_ask` call
   against the live brisen.claimsmax.co.uk instance after Render
   redeploy completes; asserts 200 + non-empty `answer` + ≥1
   `citations` entry. Failure → REQUEST_CHANGES.

### Out of scope

- Director-gated PDF/HTML render of `/ask` output (separate brief if
  Director ratifies).
- Caching, dedup, or budget enforcement.
- Per-matter routing logic (matter Desks will call
  `baker_claimsmax_ask` directly; no orchestration logic in this brief).

## Files to modify (verified against `main` HEAD `5af2971`)

- `kbl/claimsmax_client.py:266-277` — replace `ask()` method body.
- `kbl/claimsmax_client.py:20-22` — strip vendor-fix-pending docstring.
- `tools/claimsmax.py:5-14` — add `baker_claimsmax_ask` to tool list.
- `tools/claimsmax.py` — add Tool schema + dispatch + JSON return.
- `tests/test_claimsmax_client.py:236-238` — flip
  `test_ask_raises_not_implemented` to `test_ask_returns_response`.
- `tests/test_claimsmax_client.py` — append MCP-surface test for
  `baker_claimsmax_ask`.

## Reporting

On PR open: bus-post `lead` with PR number + `pytest` summary line +
diff stats.

On merge by AH1: AH1 will update PINNED §N (mark F3 RESOLVED) and run
the live smoke per §6.

## Anchor

- Philip Vallen email 2026-05-20 confirming Ellie Technologies fix shipped.
- Live AH1 probe 2026-05-20 ~23:50Z: `POST /api/v1/ask` HTTP 200,
  `model=claude-opus-4-7`, 16 citations returned, confidence 0.585,
  total_ms 17700.
- Parent brief: `CLAIMSMAX_API_CAPABILITY_1` (merged 2026-05-17 as
  `3cbc287` via PR #213).
- PINNED §N F3 (unblocked this session).
