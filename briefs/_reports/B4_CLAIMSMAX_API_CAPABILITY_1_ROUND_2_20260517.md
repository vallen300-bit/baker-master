---
brief_id: CLAIMSMAX_API_CAPABILITY_1
round: 2
pr: 213
pr_head_before_round_2: 26dc3dc
pr_head_round_2: d6d6df8
target_branch: b4/claimsmax-api-capability-1
status: ROUND_2_PUSHED
shipped_at: 2026-05-17T10:55:00Z
shipped_by: b4
---

# B4 — CLAIMSMAX_API_CAPABILITY_1 ROUND_2 ship report

ROUND_2 of PR #213 addresses every finding from AH1's REQUEST_CHANGES_ROUND_1
(bus #328) except the L1-L7 fast-follow set (L1 dead variable + L4 cosmetic
output_format folded in opportunistically since they were single-line edits).

## Mandatory fixes (C1 + H1 + H2)

| ID | File | Fix |
|---|---|---|
| **C1** | `migrations/20260517_claimsmax_capability_set.sql` | `capability_type` flipped `'domain'` → `'archive'`; `trigger_patterns` trimmed to `["claimsmax", "Pagitsch", "Hagenauer.*defects"]`; `output_format` `'prose'` → `'json'` (L4); docstring spells out why generic triggers would hijack Cortex Phase 3. |
| **H1** | `kbl/report_renderer.py::convert_to_pdf` | Mirrored convert_to_html's try/finally cleanup so the .md sibling is removed on success AND failure. Two new tests cover both paths. |
| **H2** | `kbl/report_renderer.py::convert_to_html` + new `_resolve_docs_site_root()` | `_DOCS_SITE_ROOT` constant removed. Docs-site root resolved at call time from `BAKER_DOCS_SITE_ROOT` env var or kwarg; raises `RendererUnavailableError` when unset OR when the resolved path's parent does not exist. Three new tests (env unset / env set / parent missing). |

## Optional same-round fixes (M1-M6, all bundled)

| ID | Fix | Test coverage |
|---|---|---|
| **M1** | `httpx.Client` promoted from per-request `with` block to `ClaimsmaxClient` instance state via injectable `_http_client` kwarg; new `close()` method. | `test_http_client_reused_across_requests` + `test_close_releases_underlying_client` |
| **M2** | `_validate_safe_slug` helper rejects `..`, `/`, `\`, NUL, and `.` / `..` exact values on matter_slug + topic_slug. | `test_save_investigation_json_rejects_path_traversal_slugs` parametrised across 8 attack shapes |
| **M3** | `subprocess.run(..., timeout=120.0)` plus dedicated `TimeoutExpired` → `RendererUnavailableError("...exceeded 120s timeout...")` branch. | `test_convert_to_pdf_pandoc_timeout_raises_unavailable` |
| **M4** | `tools/claimsmax.py` caches a module-level `ClaimsmaxClient` behind `threading.Lock`; new `_get_client()` + `_reset_client_for_tests()`. Eliminates per-call construction during /investigate polling. | Existing dispatch tests still green |
| **M5** | `_format_search_result` slim projection now carries `l3` alongside `l1`/`l2`. | Covered by existing search test contracts (projection shape) |
| **M6** | `logging.getLogger("baker.tools.claimsmax")` added; generic `Exception` fallback in `dispatch_claimsmax` now `logger.exception(...)`s before returning the string form. | Lint-style; behaviour preserved |

## Fast-follow remaining (L1-L7)

- L1 — dead `last_429` variable gone (rewritten _request loop).
- L2 — `_DROPBOX_ROOT` still constant. Defer per AH1 fast-follow OK.
- L3 — pandoc + PDF-engine requirement spelled out in `convert_to_pdf` docstring + `baker-mcp-api.md`.
- L4 — migration `output_format` flipped `'prose'` → `'json'`.
- L5 — `page` + `sort` still hidden from MCP schema. Defer.
- L6 — 3 unreachable methods left intentionally for future MCP wiring. Defer.
- L7 — `_extract_detail` HTML-error-page handling unchanged. Defer.

## Tests (literal Py3.12 pytest output)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 44 items

tests/test_claimsmax_client.py::test_missing_api_key_raises PASSED       [  2%]
tests/test_claimsmax_client.py::test_default_base_url_trailing_slash_normalized PASSED [  4%]
tests/test_claimsmax_client.py::test_auth_header_uses_bearer PASSED      [  6%]
tests/test_claimsmax_client.py::test_search_parses_response PASSED       [  9%]
tests/test_claimsmax_client.py::test_get_document_passes_include_text_param PASSED [ 11%]
tests/test_claimsmax_client.py::test_investigate_start_returns_run_id PASSED [ 13%]
tests/test_claimsmax_client.py::test_investigate_status_flow PASSED      [ 15%]
tests/test_claimsmax_client.py::test_http_client_reused_across_requests PASSED [ 18%]
tests/test_claimsmax_client.py::test_close_releases_underlying_client PASSED [ 20%]
tests/test_claimsmax_client.py::test_401_raises_auth_error PASSED        [ 22%]
tests/test_claimsmax_client.py::test_404_raises_not_found PASSED         [ 25%]
tests/test_claimsmax_client.py::test_422_raises_validation_error PASSED  [ 27%]
tests/test_claimsmax_client.py::test_5xx_raises_server_error_no_retry PASSED [ 29%]
tests/test_claimsmax_client.py::test_429_retries_then_succeeds PASSED    [ 31%]
tests/test_claimsmax_client.py::test_429_budget_exhaustion_raises PASSED [ 34%]
tests/test_claimsmax_client.py::test_parse_retry_after_fallback PASSED   [ 36%]
tests/test_claimsmax_client.py::test_timeout_raises_transport_error PASSED [ 38%]
tests/test_claimsmax_client.py::test_http_error_raises_transport_error PASSED [ 40%]
tests/test_claimsmax_client.py::test_ask_raises_not_implemented PASSED   [ 43%]
tests/test_report_renderer.py::test_save_investigation_json_writes_parseable_file PASSED [ 45%]
tests/test_report_renderer.py::test_save_investigation_json_creates_missing_parent_dirs PASSED [ 47%]
tests/test_report_renderer.py::test_save_investigation_json_requires_args PASSED [ 50%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[..] PASSED [ 52%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[../etc] PASSED [ 54%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[a/../b] PASSED [ 56%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[..\\windows] PASSED [ 59%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[with/slash] PASSED [ 61%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[with\\backslash] PASSED [ 63%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[null\x00byte] PASSED [ 65%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[.] PASSED [ 68%]
tests/test_report_renderer.py::test_convert_to_pdf_runs_pandoc_and_returns_path PASSED [ 70%]
tests/test_report_renderer.py::test_convert_to_pdf_missing_pandoc_raises_unavailable PASSED [ 72%]
tests/test_report_renderer.py::test_convert_to_pdf_pandoc_nonzero_exit_raises_unavailable PASSED [ 75%]
tests/test_report_renderer.py::test_convert_to_pdf_missing_json_raises PASSED [ 77%]
tests/test_report_renderer.py::test_convert_to_pdf_cleans_up_md_sibling_on_success PASSED [ 79%]
tests/test_report_renderer.py::test_convert_to_pdf_cleans_up_md_sibling_on_failure PASSED [ 81%]
tests/test_report_renderer.py::test_convert_to_pdf_pandoc_timeout_raises_unavailable PASSED [ 84%]
tests/test_report_renderer.py::test_convert_to_html_writes_under_docs_site PASSED [ 86%]
tests/test_report_renderer.py::test_convert_to_html_raises_when_docs_site_root_unset PASSED [ 88%]
tests/test_report_renderer.py::test_convert_to_html_uses_env_var_when_no_kwarg PASSED [ 90%]
tests/test_report_renderer.py::test_convert_to_html_raises_when_docs_site_parent_missing PASSED [ 93%]
tests/test_report_renderer.py::test_convert_to_html_falls_back_to_misc_when_path_not_under_research PASSED [ 95%]
tests/test_report_renderer.py::test_renderer_uses_stub_when_report_null PASSED [ 97%]
tests/test_report_renderer.py::test_renderer_raises_on_invalid_json PASSED [100%]

============================== 44 passed in 0.08s ==============================
```

44/44 green (28 baseline preserved + 16 net-new covering H1/H2/M1/M2/M3).
Pre-existing fastapi/jose ModuleNotFoundError collection failures in the
broader suite are unchanged by this diff.

## Diff stat

```
 .claude/docs/baker-mcp-api.md                    |   5 +-
 kbl/claimsmax_client.py                          |  38 ++++--
 kbl/report_renderer.py                           |  99 ++++++++++++--
 migrations/20260517_claimsmax_capability_set.sql |  21 ++-
 tests/test_claimsmax_client.py                   | 164 +++++++++++------------
 tests/test_report_renderer.py                    |  87 ++++++++++++
 tools/claimsmax.py                               |  73 ++++++++--
 7 files changed, 366 insertions(+), 121 deletions(-)
```

## Hand-back to AH1

- Push HEAD: `d6d6df8`
- Bus-post topic: `ship/claimsmax-api-capability-1-round-2`
- AH1 re-fires gate chain (gates 3+4, plus gate-2 AH2 via #326 still
  independent track) on the new HEAD.
- BAKER_DOCS_SITE_ROOT env var: AH1 sets on Mac Mini LaunchAgent + AH1
  picker shell post-merge (Tier-A; mac-local — convert is Director-gated).
