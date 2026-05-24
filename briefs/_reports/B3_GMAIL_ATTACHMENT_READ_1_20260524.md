# B3 Ship Report — GMAIL_ATTACHMENT_READ_1 (2026-05-24)

**Brief:** `briefs/BRIEF_GMAIL_ATTACHMENT_READ_1.md` (commit `c87fec7`)
**Dispatch:** `briefs/_tasks/CODE_3_PENDING.md` (bus #912, `dispatched_by: deputy`, Director-ratified b3/b4 deputy lane 2026-05-24)
**PR:** baker-master — opened on push (URL in bus reply)
**Branch:** `b3/gmail-attachment-read-1`
**Director-Q locks:** Q1=text-only default, Q2=text-extractable types only (both deputy recommendations, locked in dispatch frontmatter)

## Bottom line

**10/10 PASS.** Single repo, +267 LOC across 3 files (1 new + 1 edit + 1 new). Wraps existing poll-time Gmail attachment extractor as MCP tool `baker_gmail_attachment_read`. Pattern parity with ClaimsMax + Grok defensive-import blocks. No new credential surface — reuses `_get_gmail_service` from `triggers.email_trigger`. TOOLS list: 46 → 47.

## AC verification matrix

| AC | Description | Status | Evidence |
|---|---|---|---|
| AC1 | `pytest tests/test_gmail_attachment_read.py -v` → 10/10 PASS, literal output below | PASS | QC #1 |
| AC2 | TOOLS count incremented by 1 (46 → 47) | PASS | QC #4 |
| AC3 | `bash scripts/check_singletons.sh` clean | PASS | QC #2 |
| AC4 | `py_compile` clean on `tools/gmail.py` + `baker_mcp/baker_mcp_server.py` | PASS | QC #3 |
| AC5 | Post-deploy live smoke against real message_id + attachment_id | DEFERRED | Deputy gate-chain step (post-merge, post-Render-deploy) |
| AC6 | Render `/health` returns 200 post-deploy | DEFERRED | Deputy gate-chain step (post-merge) |
| AC7 | Tool listed in `tools/list` MCP response via curl | DEFERRED | Deputy gate-chain step (post-merge) |

## Files modified

| File | Type | LOC | Purpose |
|---|---|---|---|
| `tools/gmail.py` | NEW | 188 | GMAIL_TOOLS + GMAIL_TOOL_NAMES + dispatch_gmail + _attachment_read |
| `baker_mcp/baker_mcp_server.py` | EDIT | +14 | Defensive-import block after Grok (line 974) + dispatch elif after Grok (line 2129) |
| `tests/test_gmail_attachment_read.py` | NEW | 312 | 10 cases covering happy path + 9 edge cases including EMAIL-ATTACH-FIX-1 nested-multipart |

## Quality Checkpoints (literal output)

### QC #1 — `pytest tests/test_gmail_attachment_read.py -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 10 items

tests/test_gmail_attachment_read.py::test_happy_path_text_only PASSED    [ 10%]
tests/test_gmail_attachment_read.py::test_happy_path_include_bytes PASSED [ 20%]
tests/test_gmail_attachment_read.py::test_missing_message_id PASSED      [ 30%]
tests/test_gmail_attachment_read.py::test_missing_attachment_id PASSED   [ 40%]
tests/test_gmail_attachment_read.py::test_attachment_id_not_found PASSED [ 50%]
tests/test_gmail_attachment_read.py::test_oversize_attachment PASSED     [ 60%]
tests/test_gmail_attachment_read.py::test_unsupported_extension PASSED   [ 70%]
tests/test_gmail_attachment_read.py::test_empty_gmail_data_response PASSED [ 80%]
tests/test_gmail_attachment_read.py::test_message_fetch_exception PASSED [ 90%]
tests/test_gmail_attachment_read.py::test_attachment_download_exception PASSED [100%]

======================== 10 passed, 1 warning in 0.21s =========================
```

(Single warning is upstream qdrant_client server-version probe, unrelated.)

### QC #2 — `bash scripts/check_singletons.sh`

```
OK: No singleton violations found.
```

### QC #3 — `py_compile`

```
OK: py_compile clean
```

(Both `tools/gmail.py` and `baker_mcp/baker_mcp_server.py` compile cleanly.)

### QC #4 — Tool registration (TOOLS count main → branch)

```
main TOOLS count: 46
branch TOOLS count: 47
baker_gmail_attachment_read in TOOLS: True
```

Verified via `git stash` of branch changes → import on main → diff against branch import.

## Constraint compliance

- `scripts/extract_gmail.py` — not modified (imports `_collect_attachment_parts`, `_extract_text_from_bytes`, `_ATTACHMENT_EXTENSIONS`, `_MAX_ATTACHMENT_SIZE` as-is)
- `triggers/email_trigger.py` — not modified (imports `_get_gmail_service` as-is)
- `tools/ingest/extractors.py` — not modified (used transitively via `_extract_text_from_bytes`)
- `outputs/dashboard.py` — not modified (MCP endpoint auto-discovers new TOOLS entries)
- `requirements.txt` — not modified (no new deps)
- No new 1Password items, no new Render env vars (per Lesson #70)
- Sync tool, no internal asyncio (matches ClaimsMax + Grok pattern)
- Built per Q1=(a) + Q2=(a) locks; not relitigated

## EMAIL-ATTACH-FIX-1 coverage

Case 1 (happy path text-only) uses a 2-level nested multipart payload: outer `parts` contains a text/plain body part PLUS a `multipart/mixed` wrapper whose own `parts` array holds the PDF. Exercises `_collect_attachment_parts` recursion via the new tool surface — confirms forwarded-email scenarios resolve correctly post-MCP-wrap.

## Note on brief Ship-gate `bash -n` line

Brief §Ship gate lists `bash -n` syntax-clean on `tools/gmail.py`. `bash -n` checks Bourne-shell syntax; `tools/gmail.py` is Python. Reading the intent as "syntax check", `py_compile` (QC #3) is the correct equivalent and passes. Surfacing this as a likely copy-paste from the prior Bash-heavy brief (`WRITE_BRIEF_SOP_ENFORCER_HOOK_1`) rather than silently substituting — fail-loud per project rule.

## Gate chain — awaiting

- Gate-1 architecture review (deputy, light — pattern parity)
- Gate-2 security review (deputy, NO_FINDINGS expected — no new auth/credential surface)
- Gate-3 picker architect — SKIP per dispatch frontmatter (no agent-install pattern)
- Gate-4 second-pass code review (deputy feature-dev:code-reviewer, light — verify test assertions match names)
- Gate-5 lead merge

Post-merge: deputy runs AC5/AC6/AC7 live smoke + tool-list curl per brief §Quality Checkpoints.

## Heartbeat

Single push — no intermediate heartbeat needed (scope ~2h, well under 12h cadence).
