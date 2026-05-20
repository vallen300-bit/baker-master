---
brief_id: CLAIMSMAX_ASK_ENDPOINT_1
agent: b4
date: 2026-05-21
pr: 236
branch: b4/claimsmax-ask-endpoint-1
parent_brief: CLAIMSMAX_API_CAPABILITY_1
status: SHIPPED — awaiting AH1 review + live smoke
---

# B4 ship report — CLAIMSMAX_ASK_ENDPOINT_1

## Summary

Wired the live `POST /api/v1/ask` endpoint on `brisen.claimsmax.co.uk`
into `ClaimsmaxClient.ask()` and exposed it through a new
`baker_claimsmax_ask` MCP tool. Vendor (Ellie Technologies) shipped the
temperature-parameter fix 2026-05-20; endpoint live-verified by AH1 the
same day (HTTP 200, real RAG response with 16 citations, confidence
0.585, ~17.7s total_ms).

## Acceptance criteria — status

| # | Requirement | Status |
|---|---|---|
| 1 | `ClaimsmaxClient.ask(question, claim_id=None, language="en") -> dict` | done — routed through `_request("POST", "ask", json=body)`; `claim_id` omitted when `None`; `language` always sent |
| 2 | Flip `test_ask_raises_not_implemented` → `test_ask_returns_response` against mocked 200 with documented shape | done — new fixture carries `answer` + `citations` + `confidence` + `retrieval`; also added `test_ask_omits_claim_id_when_none` to lock the omit semantics |
| 3 | Add `baker_claimsmax_ask` MCP tool mirroring `baker_claimsmax_search` | done — schema requires `question`, optional `claim_id` + `language` (default `"en"`); dispatch branch returns raw JSON; tool-list comment block in `tools/claimsmax.py` extended with new `Ask synthesis:` subsection |
| 4 | MCP-surface test added | done — two tests: `test_mcp_baker_claimsmax_ask_dispatch` (monkeypatches `_get_client` with stub, asserts JSON round-trip + call args) + `test_mcp_baker_claimsmax_ask_registered` (catalog + schema integrity) |
| 5 | Strip "pending vendor fix" framing from module docstrings | done — `kbl/claimsmax_client.py` lines 20-22 replaced with one-line current state; `tools/claimsmax.py` top docstring updated (`Seven` → `Eight`, new `Ask synthesis:` subsection) |
| 6 | Live smoke after merge | PENDING — AH1 to run post-merge per brief §6 |

## Test evidence

Targeted run on the touched test file:

```
$ python3.12 -m pytest tests/test_claimsmax_client.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 22 items

tests/test_claimsmax_client.py::test_missing_api_key_raises PASSED       [  4%]
tests/test_claimsmax_client.py::test_default_base_url_trailing_slash_normalized PASSED [  9%]
tests/test_claimsmax_client.py::test_auth_header_uses_bearer PASSED      [ 13%]
tests/test_claimsmax_client.py::test_search_parses_response PASSED       [ 18%]
tests/test_claimsmax_client.py::test_get_document_passes_include_text_param PASSED [ 22%]
tests/test_claimsmax_client.py::test_investigate_start_returns_run_id PASSED [ 27%]
tests/test_claimsmax_client.py::test_investigate_status_flow PASSED      [ 31%]
tests/test_claimsmax_client.py::test_http_client_reused_across_requests PASSED [ 36%]
tests/test_claimsmax_client.py::test_close_releases_underlying_client PASSED [ 40%]
tests/test_claimsmax_client.py::test_401_raises_auth_error PASSED        [ 45%]
tests/test_claimsmax_client.py::test_404_raises_not_found PASSED         [ 50%]
tests/test_claimsmax_client.py::test_422_raises_validation_error PASSED  [ 54%]
tests/test_claimsmax_client.py::test_5xx_raises_server_error_no_retry PASSED [ 59%]
tests/test_claimsmax_client.py::test_429_retries_then_succeeds PASSED    [ 63%]
tests/test_claimsmax_client.py::test_429_budget_exhaustion_raises PASSED [ 68%]
tests/test_claimsmax_client.py::test_parse_retry_after_fallback PASSED   [ 72%]
tests/test_claimsmax_client.py::test_timeout_raises_transport_error PASSED [ 77%]
tests/test_claimsmax_client.py::test_http_error_raises_transport_error PASSED [ 81%]
tests/test_claimsmax_client.py::test_ask_returns_response PASSED         [ 86%]
tests/test_claimsmax_client.py::test_ask_omits_claim_id_when_none PASSED [ 90%]
tests/test_claimsmax_client.py::test_mcp_baker_claimsmax_ask_dispatch PASSED [ 95%]
tests/test_claimsmax_client.py::test_mcp_baker_claimsmax_ask_registered PASSED [100%]

============================== 22 passed in 0.22s ==============================
```

Full suite delta: baseline `2213 passed / 79 failed` (brief §5) →
`2216 passed / 79 failed` after the change. Net +3 new tests (added 4
new `ask`/MCP tests, removed 1 stale `NotImplementedError` assertion);
no new failures.

## Diff stats

```
 kbl/claimsmax_client.py        |  26 +++++-----
 tests/test_claimsmax_client.py | 111 +++++++++++++++++++++++++++++++++++++++--
 tools/claimsmax.py             |  41 ++++++++++++++-
 3 files changed, 157 insertions(+), 21 deletions(-)
```

## Notes / non-issues surfaced

- Local default Python 3.9 hits `int | None` PEP-604 issues in
  `memory/store_back.py:6002`; ran the suite under
  `/opt/homebrew/bin/python3.12` per repo's documented 3.11+ baseline.
  Not a regression introduced by this brief.

## Links

- PR #236 — https://github.com/vallen300-bit/baker-master/pull/236
- Bus-post: msg #626 (topic `ship/claimsmax-ask-endpoint-1`, recipient `lead`)
- Parent brief PR #213 (`3cbc287`).
