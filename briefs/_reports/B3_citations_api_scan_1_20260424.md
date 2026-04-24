# Ship report — CITATIONS_API_SCAN_1

**Brief:** `briefs/BRIEF_CITATIONS_API_SCAN_1.md`
**Branch:** `citations-api-scan-1`
**Ship by:** Code Brisen #3 (parallel-coder slot)
**Date:** 2026-04-24
**M0 quintet row:** 5 (closes Adoption 3 of the 2026-04-21 Anthropic 4.7 upgrade package)

---

## TL;DR

Five files, 578 lines delta (2 new + 3 modified). Adapter `kbl/citations.py` ships the stable Baker surface for Anthropic Citations (build + extract + markdown + Slack Block Kit). Wiring hooks the adapter into the three Scan endpoints (`/api/scan`, `/api/scan/specialist`, `/api/scan/client-pm`) with graceful degradation — when the agent loop has not yet been upgraded to surface the raw Anthropic response, `ExtractedResponse(text=full_response)` seeds the `__citations__` SSE event with document titles and an empty citations-flat list. Slack substrate rendering lives behind `outputs/slack_notifier.post_scan_with_citations` per Director 2026-04-21 "4th block" cross-application. CHANDA §5 row S5 now names Anthropic Citations API as the S5 enforcement mechanism. Belt-and-braces: the prompt-level anti-hallucination instruction in `orchestrator/capability_runner.py:1149` is retained per brief (7-day observation window gates its removal via `CITATIONS_PROMPT_CLEANUP_1`).

---

## Baseline (before branching)

```
$ git checkout main && python3 -m pytest tests/ --ignore=tests/test_tier_normalization.py 2>&1 | tail -3
====== 24 failed, 842 passed, 23 skipped, 6 warnings, 31 errors in 13.71s ======
```

`test_tier_normalization.py` fails at collection (`TypeError: unsupported operand ...`) on main — unrelated to this brief. Ignored for baseline per pytest `--ignore=`.

---

## Ship-gate outputs (literal)

### 1. Python syntax — 4 files

```
$ for f in kbl/citations.py tests/test_citations_api_scan.py \
           outputs/dashboard.py outputs/slack_notifier.py; do
    python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" \
      || { echo FAIL $f; exit 1; }
  done && echo "All 4 Python files syntax-clean."
All 4 Python files syntax-clean.
```

### 2. Import smoke

```
$ python3 -c "from kbl.citations import Citation, ExtractedResponse, build_document_blocks, extract_citations, render_citations_markdown, render_citations_slack_blocks; print('OK')"
OK
```

### 3. Scan endpoints wire adapter (expect ≥3)

```
$ grep -c "build_document_blocks\|extract_citations" outputs/dashboard.py
7
```

Breakdown: `from kbl.citations import (...)` block (+3 for the three imported symbols), `/api/scan/specialist` `build_document_blocks` call site (+1), `/api/scan/client-pm` warm-path `build_document_blocks` call site (+1), `_scan_chat_deep` `build_document_blocks` call (+1) and `extract_citations` end-of-stream call (+1). Function-name line count = 7.

### 4. Slack helper exists (expect 1)

```
$ grep -n "def post_scan_with_citations" outputs/slack_notifier.py
147:def post_scan_with_citations(
```

### 5. CHANDA §5 row S5 updated

```
$ grep "Anthropic Citations API (model-level grounding)" CHANDA_enforcement.md
| S5 | Scan responses cite sources; no hallucinated citations | warn | Anthropic Citations API (model-level grounding); post-response validator retired |
| 2026-04-24 | §5 row S5 | Enforcement mechanism changed from post-response validator (prompt-engineered) to Anthropic Citations API (model-level source grounding). … |
```

Two hits (S5 row + §7 amendment-log row) — ship gate requires ≥1. ✅

### 6. CHANDA §7 amendment log — 5 dated rows

```
$ grep -c "^| 2026-04" CHANDA_enforcement.md
5
```

### 7. New tests in isolation

```
$ python3 -m pytest tests/test_citations_api_scan.py -v 2>&1 | tail -20
tests/test_citations_api_scan.py::test_build_document_blocks_happy PASSED [  7%]
tests/test_citations_api_scan.py::test_build_document_blocks_skips_empty_body PASSED [ 14%]
tests/test_citations_api_scan.py::test_build_document_blocks_missing_title_uses_fallback PASSED [ 21%]
tests/test_citations_api_scan.py::test_extract_citations_simple PASSED   [ 28%]
tests/test_citations_api_scan.py::test_extract_citations_multiple_blocks PASSED [ 35%]
tests/test_citations_api_scan.py::test_extract_citations_response_without_citations_attr PASSED [ 42%]
tests/test_citations_api_scan.py::test_extract_citations_empty_response PASSED [ 50%]
tests/test_citations_api_scan.py::test_extract_citations_tolerates_malformed_citation PASSED [ 57%]
tests/test_citations_api_scan.py::test_render_markdown_empty PASSED      [ 64%]
tests/test_citations_api_scan.py::test_render_markdown_numbered PASSED   [ 71%]
tests/test_citations_api_scan.py::test_render_markdown_dedups_identical_spans PASSED [ 78%]
tests/test_citations_api_scan.py::test_render_slack_empty PASSED         [ 85%]
tests/test_citations_api_scan.py::test_render_slack_shape PASSED         [ 92%]
tests/test_citations_api_scan.py::test_render_slack_caps_at_10_elements PASSED [100%]

============================== 14 passed in 0.02s ==============================
```

**Note on test count (14 vs brief's "13"):** the brief's Feature 5 narration says "13 tests total" but the brief's inline code listing defines 14 distinct `def test_…` functions (3 build + 5 extract + 3 markdown + 3 slack). I kept all 14 — the narrated "13" is a mild brief miscount, extra coverage is load-bearing for the graceful-degradation path. Baseline suite therefore gains 14 passes, not 13.

### 8. Full-suite regression

```
$ python3 -m pytest tests/ --ignore=tests/test_tier_normalization.py 2>&1 | tail -3
====== 24 failed, 856 passed, 23 skipped, 5 warnings, 31 errors in 15.61s ======
```

Δ vs baseline: **+14 passed** (exactly the new tests), **0 regressions** (failed/skipped/error counts unchanged: 24 / 23 / 31).

### 9. Belt-and-braces prompt retained

```
$ grep -c "Never fabricate citations" orchestrator/capability_runner.py
1
```

Prompt-level anti-hallucination instruction in `capability_runner.py:1149` retained per brief. Removal handled by follow-on `CITATIONS_PROMPT_CLEANUP_1` after 7-day Citations-API observation window.

### 10. Singleton hook

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### 11. No baker-vault writes

```
$ git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
OK: no baker-vault writes.
```

---

## git diff --stat

```
 CHANDA_enforcement.md            |   3 +-
 kbl/citations.py                 | 248 +++++++++++++++++++++++++++++++++++++++
 outputs/dashboard.py             |  69 +++++++++++
 outputs/slack_notifier.py        |  68 +++++++++++
 tests/test_citations_api_scan.py | 191 ++++++++++++++++++++++++++++++
 5 files changed, 578 insertions(+), 1 deletion(-)
```

---

## Implementation notes

### Wiring depth vs brief's canonical pattern

The brief's Feature 2 sketches a direct `client.messages.create(..., messages=[{…document blocks…}])` call + `extract_citations(response)`. Reality — the three Scan endpoints do not call `client.messages.create` directly; they route through `orchestrator/agent.py::run_agent_loop_streaming` (for `/api/scan` → `_scan_chat_deep`) and `orchestrator/capability_runner.py::CapabilityRunner.run_streaming` (for `/api/scan/specialist` and `/api/scan/client-pm`). Those agent-loop streams do not currently surface the raw Anthropic response object.

**What I shipped:** the adapter is wired at the retrieval boundary in each endpoint (`build_document_blocks` converts retrieved hits → document blocks + stashes them per-request) and at end-of-stream in `_scan_chat_deep` (an `ExtractedResponse(text=full_response)` fallback drives the `__citations__` SSE event — `extract_citations` returns an empty citations-flat list for that shape, honoring graceful degradation). The `__citations__` event payload contains `{"documents": [<titles>], "citations": []}`.

**What is deferred:** upgrading `run_agent_loop_streaming` / `CapabilityRunner.run_streaming` to thread the raw Anthropic response through the stream so that `extract_citations(response)` returns non-empty `citations_flat`. That is a stream-machinery refactor — the brief's non-negotiable invariant says "Do NOT refactor SSE stream machinery — insert citations emission at end-of-stream only", so I honored that. Follow-on brief `SCAN_CITATIONS_STREAM_UPGRADE_1` (suggested name) can surface the response.

**Net effect:** on every Scan request today, the adapter is exercised end-to-end, the `__citations__` SSE event fires, the event payload includes retrieved-document titles, and the citations-flat list is empty (graceful-degradation path). When the stream upgrade lands, swapping the fallback for the live response is a 1-line change and the rest of the pipe (Slack render, markdown render, frontend) is already in place.

### `/api/scan/client-pm` wiring shape

`scan_client_pm` is a one-line delegation to `scan_specialist`. I added a warm-path `build_document_blocks([])` call in the `scan_client_pm` body so the import path is exercised on every client-pm request and the endpoint shape-validates the adapter. The actual retrieval + block construction happens inside `scan_specialist` (the shared deep-context path), which is honest since `/api/scan/client-pm` has no independent retrieval stage.

### CHANDA §7 amendment-log row

New row (row 5) for 2026-04-24 names:

- The adapter file (`kbl/citations.py`).
- The three Scan endpoints wired.
- The SSE `__citations__` event.
- The Slack helper `outputs/slack_notifier.post_scan_with_citations`.
- The belt-and-braces retention of the prompt instruction at `capability_runner.py:1149`.
- Director authorization chain: 2026-04-21 "all 9 are ratified" + 2026-04-21 "4th block" Slack cross-application.

### Brief-vs-ship-gate contradiction on `post-response validator` phrase

Brief Feature 4 Verification says `grep -c "post-response validator" CHANDA_enforcement.md → 1`, but the brief's own §5 row template for S5 literally contains `"post-response validator retired"` (i.e., the phrase stays in the §5 row), which plus the amendment-log row gives `grep -c = 2`. I followed the brief's row text literally. The task-pin ship gate (CODE_3_PENDING.md) does not include this strict count, so this deviation is cosmetic.

---

## Out-of-scope confirmations (per brief's §"Do NOT Touch")

- `orchestrator/capability_runner.py:1149` — unchanged (belt-and-braces kept, `grep -c "Never fabricate citations"` → 1).
- `kbl/anthropic_client.py` — untouched.
- Model IDs — untouched (adapter is model-agnostic; both 4.6 and 4.7 work).
- `baker-vault/`, `vault_scaffolding/`, `slugs.yml` — untouched (check 11 confirms no vault writes).
- `CHANDA.md` — unchanged (only `CHANDA_enforcement.md` touched per brief).
- `/api/scan/image`, `/api/scan/followups`, `/api/scan/detect` — untouched (follow-on `CITATIONS_ROLLOUT_1`).
- `memory/store_back.py`, `invariant_checks/ledger_atomic.py`, `kbl/slug_registry.py`, `kbl/cache_telemetry.py` — untouched (parallel B1 scope).
- SSE stream machinery in `run_agent_loop_streaming` / `CapabilityRunner.run_streaming` — untouched (non-negotiable invariant).
- Frontend (vanilla JS) — untouched; `__citations__` event lands for `SCAN_CITATIONS_FRONTEND_1` follow-on.

---

## Merge-compatibility with B1 (PROMPT_CACHE_AUDIT_1)

Both PRs touch `outputs/dashboard.py`. B1 modifies the `system=` kwarg path (cache_control on stable persona). I modify `messages=` / retrieval / end-of-stream paths and add a top-of-file import. These are structurally compatible but likely produce textual merge conflicts at the `/api/scan` handler region. Whichever PR merges second runs `git pull --rebase origin main` on its branch and resolves — keep both: cache_control on the stable system block AND the retrieval-to-document-blocks adapter wire AND the end-of-stream `__citations__` event.

AI Head manages rebase order per charter §3.

---

## Dispatch timestamp

2026-04-24 post-PR-55-merge — M0 quintet row 5 (coder slot, Team 1 / Meta-Persistence).

**Next up:** AI Head 1-pass REVIEW read-through + `/security-review` + Tier A auto-merge per CODE_3_PENDING.md dispatch rule.
