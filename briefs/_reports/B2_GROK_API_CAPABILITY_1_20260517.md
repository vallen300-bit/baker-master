---
brief_id: GROK_API_CAPABILITY_1
trigger_class: MEDIUM
target_branch: b2/grok-api-capability-1
pr: 214
commit_sha: 1bff10d6fa62a1382a6371d9bf967e577a8a43e4
ship_date: 2026-05-17
builder: b2
pattern_source: BRIEF_CLAIMSMAX_API_CAPABILITY_1 (commit 3cbc287)
director_auth: 2026-05-17 chat — "Draft the brief now. Send it to B2. By bus. Don't worry about confidentiality. Let's try to use it. See what happens."
---

# B2 ship report — GROK_API_CAPABILITY_1

## TL;DR

Wired xAI Grok Heavy API into Baker as a permanent capability. 3 MCP tools (`baker_grok_x_search` / `baker_grok_web_search` / `baker_grok_ask`) replace the fragile Chrome-MCP port-9222 X path and the manual Director-runs-Grok workaround. Mirrored CLAIMSMAX_API_CAPABILITY_1 (`3cbc287`) end-to-end. **PR #214 open** against `main`, 28/28 pytest green under python3.12, 6 files / +1,212 LOC.

## Pre-flight WebFetch surfaced 4 spec divergences — all bus-posted BEFORE coding

Bus msg 347 (topic `grok-api-spec-mismatch`) posted 2026-05-17T14:21:40Z. Resolutions baked into PR:

| # | Brief assumption | Verified xAI spec | Resolution |
|---|---|---|---|
| 1 | Live Search via `tools=[{type:web_search}]` | Native pattern is `search_parameters` dict on `/v1/responses` (mode/sources/from_date/to_date/max_search_results/return_citations) | Client uses `search_parameters`; this is xAI's documented Live Search path |
| 2 | Model `grok-4.20-reasoning` | Actual `grok-4.20-0309-reasoning`; docs recommend `grok-4.3` ("most intelligent and fastest") | Default `grok-4.3`; reasoning variant available via `model=` on `ask` per brief's "pick whichever xAI docs recommend" latitude |
| 3 | Pricing $2/M in $6/M out | $1.25/M in $2.50/M out for all text models | Cost helper uses docs rate; prefers `usage.cost_in_usd_ticks` when xAI returns it |
| 4 | Separate `x_search` / `web_search` endpoints | One endpoint, `sources` array filter | 3-tool MCP surface preserved per brief; client parameterizes `search_parameters.sources` per call |

## Files shipped (6)

| File | LOC | Status |
|---|---|---|
| `kbl/grok_client.py` | ~360 | NEW — sync httpx wrapper, 3 public methods + typed exceptions + 429 backoff |
| `tools/grok.py` | ~210 | NEW — 3 MCP Tool defs + dispatch_grok + module-level client cache |
| `migrations/20260517_grok_capability_set.sql` | ~50 | NEW — idempotent INSERT, `capability_type='archive'` |
| `tests/test_grok_client.py` | ~290 | NEW — 28 mocked-httpx tests |
| `baker_mcp/baker_mcp_server.py` | +15 | MODIFIED — defensive Grok import + dispatch branch |
| `.claude/docs/baker-mcp-api.md` | +16 | MODIFIED — "Grok real-time tools (3)" section |

## Literal pytest output

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b2
plugins: langsmith-0.7.38, anyio-4.12.1
collected 28 items

tests/test_grok_client.py::test_missing_api_key_raises PASSED            [  3%]
tests/test_grok_client.py::test_default_base_url PASSED                  [  7%]
tests/test_grok_client.py::test_base_url_trailing_slash_stripped PASSED  [ 10%]
tests/test_grok_client.py::test_auth_header_uses_bearer PASSED           [ 14%]
tests/test_grok_client.py::test_ask_parses_response_and_returns_text PASSED [ 17%]
tests/test_grok_client.py::test_ask_body_uses_default_model_and_passes_overrides PASSED [ 21%]
tests/test_grok_client.py::test_x_search_returns_summary_and_tweets PASSED [ 25%]
tests/test_grok_client.py::test_web_search_adds_news_source_and_freshness_window PASSED [ 28%]
tests/test_grok_client.py::test_web_search_skip_news_and_no_freshness PASSED [ 32%]
tests/test_grok_client.py::test_web_search_citations_are_shaped PASSED   [ 35%]
tests/test_grok_client.py::test_401_raises_auth_error PASSED             [ 39%]
tests/test_grok_client.py::test_403_raises_forbidden PASSED              [ 42%]
tests/test_grok_client.py::test_422_raises_validation_error PASSED       [ 46%]
tests/test_grok_client.py::test_5xx_raises_server_error_no_retry PASSED  [ 50%]
tests/test_grok_client.py::test_non_json_2xx_raises_server_error PASSED  [ 53%]
tests/test_grok_client.py::test_429_retries_then_succeeds PASSED         [ 57%]
tests/test_grok_client.py::test_429_budget_exhaustion_raises PASSED      [ 60%]
tests/test_grok_client.py::test_parse_retry_after_fallback PASSED        [ 64%]
tests/test_grok_client.py::test_timeout_raises_transport_error PASSED    [ 67%]
tests/test_grok_client.py::test_http_error_raises_transport_error PASSED [ 71%]
tests/test_grok_client.py::test_flatten_output_text_handles_mixed_blocks PASSED [ 75%]
tests/test_grok_client.py::test_shape_tweet_citation_handles_string_and_dict PASSED [ 78%]
tests/test_grok_client.py::test_shape_web_citation_handles_string_and_dict PASSED [ 82%]
tests/test_grok_client.py::test_cost_usd_prefers_ticks_when_provided PASSED [ 85%]
tests/test_grok_client.py::test_cost_usd_falls_back_to_token_rates PASSED [ 89%]
tests/test_grok_client.py::test_cost_usd_zero_when_empty PASSED          [ 92%]
tests/test_grok_client.py::test_http_client_reused_across_requests PASSED [ 96%]
tests/test_grok_client.py::test_close_releases_underlying_client PASSED  [100%]

============================== 28 passed in 0.05s ==============================
```

## Acceptance criteria

- [x] All 6 files committed on branch `b2/grok-api-capability-1`
- [x] PR #214 opened against `main` with literal pytest output in description
- [x] Migration shape validated (idempotent INSERT into existing `capability_sets`; bootstrap schema verified in `memory/store_back.py:_ensure_capability_sets_table`; no DDL drift risk per Lesson #50)
- [x] `.claude/docs/baker-mcp-api.md` updated
- [x] Ship report (this file)
- [x] Bus-post `lead` on PR open — `pr-open/grok-api-capability-1`
- [ ] **AH1 to run:** `/security-review` + `feature-dev:code-reviewer` 2nd-pass (mandatory per trigger_class MEDIUM)
- [ ] **AH1 to push:** Render env var `XAI_API_KEY` before merge (Tier B, separate action — parallel to review)
- [ ] **AH1 to run:** post-merge smoke tests against prod (`baker_grok_x_search("Brisen Group")` + `baker_grok_web_search("EU construction defect law 2026")`)

## Hard rules — all satisfied

| # | Rule | Status |
|---|---|---|
| 1 | NO hardcoded keys | ✅ `XAI_API_KEY` env var only; no literal key in code/tests/migration |
| 2 | `capability_type='archive'` (not 'domain') | ✅ Migration uses 'archive'; matches ClaimsMax C1 fix |
| 3 | Narrow `trigger_patterns` | ✅ `["grok","x search","twitter search","real-time web","realtime news"]` — no generic 'search'/'lookup' |
| 4 | Fault-tolerant | ✅ Every HTTP call wrapped try/except; `dispatch_grok` catches all and returns `Error: <msg>` |
| 5 | Singleton pattern | ✅ Module-level `_CLIENT` with double-checked locking; `bash scripts/check_singletons.sh` → OK |
| 6 | Literal pytest in PR | ✅ Pasted above + in PR #214 description; no "pass by inspection" |

## Notes for AH1 / reviewers

1. **Pre-coding bus-post (msg 347):** I surfaced the 4 spec divergences and proposed resolutions BEFORE coding per brief §First step. Since pilot framing + brief gave explicit latitude on model choice, I proceeded with the resolutions baked in rather than blocking on a sync. If reviewers want different defaults, the changes are localized: `_DEFAULT_MODEL` constant in `kbl/grok_client.py`, and the dispatch arg defaults in `tools/grok.py`.
2. **Live Search vs `tools[]`:** I chose `search_parameters` (native Live Search) over `tools=[{type:web_search}]` because xAI documents `search_parameters` as the Live Search production feature with structured citations. The `tools[]` web_search form is older and was explicitly documented as having only 3 web-search parameters (`allowed_domains`, `excluded_domains`, `enable_image_understanding`) without X-source support. If AH1 wants the `tools[]` form for any reason, that's a follow-up.
3. **Tweet citation shape:** xAI docs do not fully specify the X-source citation schema (Live Search docs page didn't enumerate per-tweet fields). The shaping helper `_shape_tweet_citation` accepts both string-URL and dict-with-metadata forms and projects defensively across multiple plausible key names (`url`/`link`, `author`/`handle`, `created_at`/`date`, `favorite_count`/`favorites`, etc.). The post-merge smoke test will reveal the actual shape; the helper can be tightened in a follow-up if real responses use different keys.
4. **Cost math:** Falls back to token-rate math at $1.25/$2.50 per M (the docs-stated rate for all text models). xAI also returns `usage.cost_in_usd_ticks` (1 tick = $0.0001) — the helper prefers this when present. Both paths covered in tests.
5. **Render env var:** `XAI_API_KEY` is gated to AH1 per brief — not in scope for this PR.

## Pattern source

Commit `3cbc287` (BRIEF_CLAIMSMAX_API_CAPABILITY_1, B4 / PR #213). File-level decisions mirrored: client structure, exception hierarchy, dispatch shape, module-level cache w/ thread-safe lazy init, defensive MCP-server import, `capability_type='archive'` migration shape, doc-section format.

## Commit + PR refs

- Branch: `b2/grok-api-capability-1`
- Commit: `1bff10d6fa62a1382a6371d9bf967e577a8a43e4`
- PR: https://github.com/vallen300-bit/baker-master/pull/214
- Bus claim: msg 346 (topic `claim/grok-api-capability-1`)
- Bus spec-mismatch: msg 347 (topic `grok-api-spec-mismatch`)
