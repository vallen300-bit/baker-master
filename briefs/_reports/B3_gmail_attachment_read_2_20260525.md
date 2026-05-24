# B3 Ship Report — GMAIL_ATTACHMENT_READ_2 (2026-05-25)

**Brief:** `briefs/BRIEF_GMAIL_ATTACHMENT_READ_2.md` (commit `7fcf13c`)
**Dispatch:** `briefs/_tasks/CODE_3_PENDING.md` (bus #986, `dispatched_by: lead`, Director-ratified 2026-05-24 ~22:55Z "go")
**PR:** [baker-master #257](https://github.com/vallen300-bit/baker-master/pull/257)
**Branch:** `b3/gmail-attachment-read-2`
**Ship commit:** `e8c0fde`
**Director-Q locks:** Q1=case-sensitive exact filename match, Q2=1-based attachment_index tiebreaker default 1, Q3=E2E skipif TEST_GMAIL_LIVE != "1" (all lead recommendations, locked in dispatch frontmatter)

## Bottom line

**12 mocked PASS + 1 E2E SKIPPED locally.** Amends READ_1 (PR #256). Swaps `inputSchema` from `(message_id, attachment_id)` to `(message_id, filename)` + optional 1-based `attachment_index` tiebreaker. The tool resolves the session-valid `attachmentId` internally via depth-first walk of `_collect_attachment_parts` and case-sensitive exact filename match.

Adds 1 real-Gmail E2E test (`skipif TEST_GMAIL_LIVE != "1"`) — the structural fix for the READ_1 failure mode where mocked-only tests shipped a broken surface (anchor: `tasks/lessons.md:211`).

`tools/gmail.py` +98 / −62. `tests/test_gmail_attachment_read.py` +170 / −21. No changes to `baker_mcp/baker_mcp_server.py` (name-based registration unchanged).

## AC verification matrix

| AC | Description | Status | Evidence |
|---|---|---|---|
| AC1 | `pytest tests/test_gmail_attachment_read.py -v` → 12 passed, 1 skipped (E2E auto-skipped) | PASS | QC #1 |
| AC2 | `py_compile` clean on `tools/gmail.py` | PASS | QC #2 |
| AC3 | `GMAIL_TOOL_NAMES == ['baker_gmail_attachment_read']` | PASS | QC #3 |
| AC4 | Local E2E run (TEST_GMAIL_LIVE=1 + fixture env + Gmail OAuth) → 1 PASS | SKIPPED LOCALLY | QC #4 (lead runs post-merge) |
| AC5 | `bash scripts/check_singletons.sh` clean | PASS | QC #5 |
| AC6 | `inputSchema` validates: `message_id` + `filename` required; `attachment_index` int ≥ 1 default 1; `include_bytes` bool default false | PASS | QC #6 |
| AC7 | Render `/health` returns 200 post-deploy | DEFERRED | Post-merge / post-deploy step |

## Files modified

| File | Type | LOC | Purpose |
|---|---|---|---|
| `tools/gmail.py` | EDIT | +98 / −62 | `inputSchema` swap (attachment_id → filename + attachment_index); `_attachment_read()` rewrite — filename match, internal session-id resolution, match_count + attachment_index in response, `available_filenames` on not-found |
| `tests/test_gmail_attachment_read.py` | EDIT | +170 / −21 | 10 mocked cases adapted to new API + 2 new mocked (duplicate filenames + index out-of-range) + 1 gated real-Gmail E2E |

## Quality Checkpoints (literal output)

### QC #1 — `pytest tests/test_gmail_attachment_read.py -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 13 items

tests/test_gmail_attachment_read.py::test_happy_path_text_only PASSED    [  7%]
tests/test_gmail_attachment_read.py::test_happy_path_include_bytes PASSED [ 15%]
tests/test_gmail_attachment_read.py::test_missing_message_id PASSED      [ 23%]
tests/test_gmail_attachment_read.py::test_missing_filename PASSED        [ 30%]
tests/test_gmail_attachment_read.py::test_filename_not_found PASSED      [ 38%]
tests/test_gmail_attachment_read.py::test_oversize_attachment PASSED     [ 46%]
tests/test_gmail_attachment_read.py::test_unsupported_extension PASSED   [ 53%]
tests/test_gmail_attachment_read.py::test_empty_gmail_data_response PASSED [ 61%]
tests/test_gmail_attachment_read.py::test_message_fetch_exception PASSED [ 69%]
tests/test_gmail_attachment_read.py::test_attachment_download_exception PASSED [ 76%]
tests/test_gmail_attachment_read.py::test_duplicate_filenames_with_index PASSED [ 84%]
tests/test_gmail_attachment_read.py::test_attachment_index_out_of_range PASSED [ 92%]
tests/test_gmail_attachment_read.py::test_e2e_real_gmail_attachment_read SKIPPED [100%]

======================== 12 passed, 1 skipped, 1 warning in 0.33s ========================
```

(Single warning is upstream qdrant_client server-version probe, unrelated.)

### QC #2 — `py_compile`

```
OK: py_compile clean on tools/gmail.py
```

### QC #3 — `GMAIL_TOOL_NAMES`

```
['baker_gmail_attachment_read']
```

### QC #4 — E2E local run — SKIPPED with reason

The E2E test requires Gmail OAuth credentials loaded by `scripts/extract_gmail.authenticate()`, which reads from `config/gmail_credentials.json` (not just `BAKER_GMAIL_*` env vars). That file is not present in b3's shell; only Render carries it as a Secret File at `/etc/secrets/gmail_credentials.json`.

Fixture chosen (most recent PDF attachment in `documents`):

```sql
SELECT id, source_path, filename, ingested_at FROM documents
WHERE source_path LIKE 'email:%/%.pdf'
ORDER BY ingested_at DESC LIMIT 5;
-- top row: 104538 | email:19e2ff37f48fed12/1.1.01.01 Month End Profit & Loss March 2026.pdf
```

```
E2E_GMAIL_MESSAGE_ID=19e2ff37f48fed12
E2E_GMAIL_FILENAME="1.1.01.01 Month End Profit & Loss March 2026.pdf"
```

Suggested lead command (post-merge, lead shell with `config/gmail_credentials.json` wired):

```bash
export TEST_GMAIL_LIVE=1
export E2E_GMAIL_MESSAGE_ID=19e2ff37f48fed12
export E2E_GMAIL_FILENAME="1.1.01.01 Month End Profit & Loss March 2026.pdf"
.venv-b3/bin/python -m pytest tests/test_gmail_attachment_read.py::test_e2e_real_gmail_attachment_read -v
# expected: 1 passed
```

### QC #5 — `bash scripts/check_singletons.sh`

```
OK: No singleton violations found.
```

### QC #6 — `inputSchema` validation

```
required: ['message_id', 'filename']
properties: ['attachment_index', 'filename', 'include_bytes', 'message_id']
attachment_index default: 1
attachment_index minimum: 1
```

### QC #7 — Tool registration (TOOLS count main → branch)

```
main TOOLS count: 47
branch TOOLS count: 47
baker_gmail_attachment_read in TOOLS: True
```

(Same single-tool registration as READ_1 — only the schema changed, not the count.)

## Bus reporting

- bus #988 → `lead` (`ship/gmail-attachment-read-2`)
- bus #989 → `deputy` (`ship-cc/gmail-attachment-read-2`)

## References

- Brief: `briefs/BRIEF_GMAIL_ATTACHMENT_READ_2.md`
- Anchor bus: deputy #973 (post-deploy/ac5-fail-architectural) 2026-05-24 22:17Z
- READ_1 PR: #256 (squash `f030344`) — merged but non-functional in practice
- READ_1 ship report: `briefs/_reports/B3_GMAIL_ATTACHMENT_READ_1_20260524.md`
- Lessons reference: `tasks/lessons.md:211` (mocked-only tests shipped broken — same pattern bit READ_1; gated E2E in READ_2 is the structural fix)
- Hag-desk filing deadline: 2026-05-26/27 (LG Wien Forderungsanmeldung) — manual workaround runs in parallel
