---
brief_id: CLAIMSMAX_API_CAPABILITY_1
shipped_by: b4
shipped_at: 2026-05-17T09:25:00Z
branch: b4/claimsmax-api-capability-1
trigger_class: MEDIUM
review_gates:
  - "Gate 1: pytest GREEN (28/28)"
  - "Gate 2: /security-review (pending AH1)"
  - "Gate 3: /code-review (pending AH1)"
---

# Ship report — CLAIMSMAX_API_CAPABILITY_1

Wires ClaimsMax v1 REST API into Baker as a permanent capability. Includes the
Director-ratified 2026-05-17 amendment (bus #316 / commit `f63d0cd`):
JSON-by-default investigation output + Director-gated PDF/HTML conversion.
**No auto-render heuristic anywhere** — every conversion is an explicit
Director instruction.

## Touched files

| File | LOC ± | Purpose |
|---|---|---|
| `kbl/claimsmax_client.py` (new) | +273 | Sync httpx wrapper; 8 public methods (7 impl + `ask()` placeholder); 7 exception classes; 429 Retry-After backoff (max 3 retries); try/except wrapped per repo hard rule. |
| `kbl/report_renderer.py` (new) | +221 | 3 functions: `save_investigation_json` (always; cheap default), `convert_to_pdf` + `convert_to_html` (Director-gated). pandoc-backed; raises `RendererUnavailableError` cleanly when binary absent. |
| `tools/claimsmax.py` (new) | +258 | 7 MCP `Tool` defs + `dispatch_claimsmax(name, args) -> str`. Returns JSON-formatted strings; uniformly fault-tolerant. |
| `baker_mcp/baker_mcp_server.py` | +13 / -0 | Import ClaimsMax tools into the global `TOOLS` list + route via `_dispatch` when name matches `CLAIMSMAX_TOOL_NAMES`. Defensive try/except on import keeps server bootable if module fails. |
| `migrations/20260517_claimsmax_capability_set.sql` (new) | +44 | Idempotent INSERT for the `claimsmax_archive` row; `ON CONFLICT (slug) DO NOTHING`. Schema unchanged — bootstrap DDL in `store_back.py:_ensure_capability_sets_table` is authoritative. |
| `tests/test_claimsmax_client.py` (new) | +211 | 17 tests — auth/env, search, get_document, investigate_start, investigate_status flow, 401/404/422/5xx error mapping, 429 retry + budget exhaustion, transport errors, `/ask` placeholder. |
| `tests/test_report_renderer.py` (new) | +189 | 11 tests — JSON save happy path + edge cases, pandoc invocation, missing pandoc → `RendererUnavailableError`, non-zero exit, null-report stub body, invalid JSON. |
| `.claude/docs/baker-mcp-api.md` | +18 / -0 | New "ClaimsMax archive tools (7)" section: tool table + `/ask`-disabled note + sample query. |

## Ship gate — literal pytest output

```
$ python3.12 -m pytest tests/test_claimsmax_client.py tests/test_report_renderer.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 28 items

tests/test_claimsmax_client.py::test_missing_api_key_raises PASSED       [  3%]
tests/test_claimsmax_client.py::test_default_base_url_trailing_slash_normalized PASSED [  7%]
tests/test_claimsmax_client.py::test_auth_header_uses_bearer PASSED      [ 10%]
tests/test_claimsmax_client.py::test_search_parses_response PASSED       [ 14%]
tests/test_claimsmax_client.py::test_get_document_passes_include_text_param PASSED [ 17%]
tests/test_claimsmax_client.py::test_investigate_start_returns_run_id PASSED [ 21%]
tests/test_claimsmax_client.py::test_investigate_status_flow PASSED      [ 25%]
tests/test_claimsmax_client.py::test_401_raises_auth_error PASSED        [ 28%]
tests/test_claimsmax_client.py::test_404_raises_not_found PASSED         [ 32%]
tests/test_claimsmax_client.py::test_422_raises_validation_error PASSED  [ 35%]
tests/test_claimsmax_client.py::test_5xx_raises_server_error_no_retry PASSED [ 39%]
tests/test_claimsmax_client.py::test_429_retries_then_succeeds PASSED    [ 42%]
tests/test_claimsmax_client.py::test_429_budget_exhaustion_raises PASSED [ 46%]
tests/test_claimsmax_client.py::test_parse_retry_after_fallback PASSED   [ 50%]
tests/test_claimsmax_client.py::test_timeout_raises_transport_error PASSED [ 53%]
tests/test_claimsmax_client.py::test_http_error_raises_transport_error PASSED [ 57%]
tests/test_claimsmax_client.py::test_ask_raises_not_implemented PASSED   [ 60%]
tests/test_report_renderer.py::test_save_investigation_json_writes_parseable_file PASSED [ 64%]
tests/test_report_renderer.py::test_save_investigation_json_creates_missing_parent_dirs PASSED [ 67%]
tests/test_report_renderer.py::test_save_investigation_json_requires_args PASSED [ 71%]
tests/test_report_renderer.py::test_convert_to_pdf_runs_pandoc_and_returns_path PASSED [ 75%]
tests/test_report_renderer.py::test_convert_to_pdf_missing_pandoc_raises_unavailable PASSED [ 78%]
tests/test_report_renderer.py::test_convert_to_pdf_pandoc_nonzero_exit_raises_unavailable PASSED [ 82%]
tests/test_report_renderer.py::test_convert_to_pdf_missing_json_raises PASSED [ 85%]
tests/test_report_renderer.py::test_convert_to_html_writes_under_docs_site PASSED [ 89%]
tests/test_report_renderer.py::test_convert_to_html_falls_back_to_misc_when_path_not_under_research PASSED [ 92%]
tests/test_report_renderer.py::test_renderer_uses_stub_when_report_null PASSED [ 96%]
tests/test_report_renderer.py::test_renderer_raises_on_invalid_json PASSED [100%]

============================== 28 passed in 0.05s ==============================
```

## Acceptance criteria

1. ☑ `kbl/claimsmax_client.py` exists with 8 methods (7 implemented + `ask()` placeholder).
2. ☑ 7 MCP tools registered (4 search/investigate + 3 renderer); discoverable via standard Baker MCP `tools/list`.
3. ☑ Capability-set row inserted via new migration `20260517_claimsmax_capability_set.sql` (idempotent).
4. ☑ All HTTP calls try/except wrapped; 429 retry verified by test (`test_429_retries_then_succeeds`).
5. ☑ Tests pass: `pytest tests/test_claimsmax_client.py -v` AND `pytest tests/test_report_renderer.py -v` — 28/28 GREEN.
6. ☑ `.claude/docs/baker-mcp-api.md` updated with the 7-tool table.
7. ☑ Zero hardcoded keys; `CLAIMSMAX_API_KEY` read from env at client construction; missing key raises `ClaimsmaxAuthError`.
8. ☐ Render env var set by AH1 before merge (separate Tier B action — B4 cannot satisfy).
9. ☑ `kbl/report_renderer.py` exists with three functions; 3 MCP renderer tools registered; **pandoc availability surfaced as deploy-blocker for conversion tools only** (see below). No auto-render heuristic anywhere.

## Pandoc on Render — flagged as deploy blocker for conversion tools

**Baker's Render service uses the default Python buildpack** (`build.sh` = `pip install -r requirements.txt`); no Dockerfile, no Aptfile. Pandoc is **not** present on this runtime.

**Impact is bounded**:
- `baker_claimsmax_save_investigation` — works (no pandoc dep). Default flow ships clean.
- `baker_claimsmax_convert_to_pdf` / `_convert_to_html` — will raise `RendererUnavailableError` with clear remediation on Render until pandoc is added. Local dev (macOS with `brew install pandoc`) works today.

**Recommendation to AH1**: ship this PR as-is. Conversion tools fail loud on Render; default JSON save works everywhere. Pandoc install is a separate deploy decision (Dockerfile migration or Aptfile buildpack) that does not block the capability framework or the search/investigate surface.

## Constraints — confirmed honoured

- **No `cmx_` literal anywhere in the diff.** Test fixtures use a stub token via `monkeypatch.setenv`; no live key committed. PR review can grep `cmx_` to verify.
- Surgical edits — touched `kbl/`, `tools/`, `tests/`, `.claude/docs/`, `migrations/`, plus 13 lines of `baker_mcp/baker_mcp_server.py` to wire the import + dispatch routing. Nothing else.
- Followed existing MCP `Tool(name=..., description=..., inputSchema=...)` registration pattern; reused `_dispatch` switch.
- Fault-tolerant: every HTTP call wrapped; every renderer call wrapped; missing pandoc raises a clear typed exception.
- `/ask` deliberately NotImplementedError'd — vendor bug pending.

## Bus reporting

- Claim: bus #317 (`claim/claimsmax-api-capability-1`).
- PR-open: pending after `gh pr create`.
- Topic on ship: `pr-open/claimsmax-api-capability-1`.

## Co-authored-by

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
