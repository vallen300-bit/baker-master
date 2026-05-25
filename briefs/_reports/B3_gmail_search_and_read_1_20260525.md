---
report_id: B3_gmail_search_and_read_1_20260525
brief_id: GMAIL_SEARCH_AND_READ_1
target: b3
status: SHIPPED — awaiting deputy gates (1+2+4) + lead merge (5); gate 3 SKIP
shipped_at: 2026-05-25T10:25:00Z
pr_baker_master: 258
branch_baker_master: b3/gmail-search-and-read-1
extends: GMAIL_ATTACHMENT_READ_2 (PR #257)
bus_posts: lead #1026 ship/gmail-search-and-read-1; deputy #1027 ship-cc/gmail-search-and-read-1
---

# B3 — GMAIL_SEARCH_AND_READ_1 ship report — 2026-05-25

## Bottom line

PR #258 open. Two new MCP tools (`baker_gmail_search`, `baker_gmail_read_message`) live in `tools/gmail.py`, joining `baker_gmail_attachment_read` from PR #257. Tool count expected 47 → 49 post-deploy. All AC1-AC8 green except AC7 (E2E) — 3 SKIPPED locally because b3 shell has no `BAKER_GMAIL_*` env vars; lead runs E2E from lead shell post-merge per brief §Anti-pattern guard.

## Scope shipped

### Fix 1 + Fix 2 — `tools/gmail.py` (+263 LOC)
- +2 `Tool` defs in `GMAIL_TOOLS` (baker_gmail_search, baker_gmail_read_message).
- +2 dispatch branches in `dispatch_gmail()`.
- `_search()` — wraps `messages.list` + sequential N+1 metadata fetch via `messages.get(format=metadata, metadataHeaders=[From,To,Subject,Date])`. Hard cap 50 at schema (`maximum: 50`) AND server-side defensive clamp (`_SEARCH_MAX_RESULTS_HARD_CAP`). Per-message metadata errors NON-FATAL (failed entry has `error` field, search returns all other matches).
- `_read_message()` — wraps `messages.get(format=full)` + `scripts/extract_gmail.extract_body_text` (text/plain preferred, text/html stripped fallback via `strip_html`) + `_collect_attachment_parts`. Body cap `_BODY_TEXT_CAP_CHARS = 50_000` + truncation marker + `body_truncated` bool. Attachment metadata only (filename, mime_type, size) — bytes stay with `baker_gmail_attachment_read`.

### Fix 3 — `tests/test_gmail.py` (renamed from `tests/test_gmail_attachment_read.py`, +609 net LOC)
- `git mv` performed; `git log --follow tests/test_gmail.py` reaches PR #256 + #257. (Note: git stat shows rename only at `-M20%` threshold because the file changed substantially; the commit still preserves history.)
- `_build_service_mock()` factory extended with `list_response` / `list_raises` / `metadata_responses` / `metadata_raises` / `full_message_response` / `full_message_raises` kwargs + format-aware `messages.get()` router (routes on `format` + `id` kwargs; legacy fallback branch keeps the 12 attachment_read tests green).
- 12 existing attachment_read tests renamed `test_attachment_read_*` so AC2 regression guard `-k attachment_read` matches the full set (the prior names — `test_happy_path_*`, `test_missing_*`, etc. — did not contain "attachment_read" and would have made AC2's literal output unverifiable).
- +6 mocked cases for `baker_gmail_search` (Fix 3c): empty query, no matches, happy 3 matches, partial metadata failure (NON-FATAL verified), max_results clamp from 100 → 50 (verified via `list.call_args.kwargs["maxResults"] == 50`), pagination passthrough (verified via `pageToken="PT_PRIOR"` kwarg + `next_page_token: "PT_42"` response).
- +6 mocked cases for `baker_gmail_read_message` (Fix 3d): missing message_id, happy text/plain body + 2 attachments + Cc, html-only body stripped (no tags, `&amp;` decoded), 60K body truncation (`body_truncated is True`, length == cap + marker), fetch exception, no attachments.
- +2 gated E2E (`test_e2e_real_gmail_search` + `test_e2e_real_gmail_read_message`) — `skipif TEST_GMAIL_LIVE != "1"`.
- Module docstring updated to reflect 24 mocked + 3 gated E2E across three tools.

## Acceptance criteria — results

| AC | Check | Result |
|---|---|---|
| AC1 | `pytest tests/test_gmail.py -v` | **24 passed, 3 skipped** ✅ |
| AC2 | `pytest tests/test_gmail.py -v -k attachment_read` | **12 passed, 1 skipped** ✅ (regression guard) |
| AC3 | `py_compile tools/gmail.py` | clean ✅ |
| AC4 | `GMAIL_TOOL_NAMES` listing | `['baker_gmail_attachment_read', 'baker_gmail_read_message', 'baker_gmail_search']` ✅ |
| AC5 | inputSchema validation | both new tools' schemas validate per brief §1a ✅ |
| AC6 | `_SEARCH_MAX_RESULTS_HARD_CAP=50` + `_BODY_TEXT_CAP_CHARS=50_000` | both present ✅ |
| AC7 | Local E2E (3 tests) | **3 SKIPPED locally** — b3 shell has no `BAKER_GMAIL_*` env. Lead runs post-merge from lead shell per brief §Anti-pattern guard. Explicit documented skip — silent skip = REQUEST_CHANGES per brief. |
| AC8 | `bash scripts/check_singletons.sh` | `OK: No singleton violations found.` ✅ |
| AC9 | Render `/health` HTTP 200 post-deploy | not yet — lead verifies post-merge |

## Hard-constraint compliance

- ✅ Did NOT modify `scripts/extract_gmail.py`, `baker_mcp/baker_mcp_server.py`, `triggers/email_trigger.py`, `outputs/dashboard.py`. New tools auto-pick up via name-based registration.
- ✅ No new 1Password items, no new Render env vars.
- ✅ `max_results` hard cap = 50 at BOTH layers (schema + server-side clamp).
- ✅ Sequential metadata fetch loop — no parallelization, no batchRequest, no cache.
- ✅ No `include_bytes` flag on `baker_gmail_read_message` — bytes responsibility stays with `baker_gmail_attachment_read`.
- ✅ E2E tests skipif-gated on `TEST_GMAIL_LIVE=1` — CI passes without it.
- ✅ Literal pytest output in PR body (no "by inspection").
- ✅ Factory rewrite regression guard run BEFORE adding new tests — 12 attachment_read tests stayed green.

## Director Q-locks honoured

All 5 dispatch-envelope Q-locks shipped as locked:

1. ✅ `max_results` cap = 50 hard / 20 default.
2. ✅ Body text cap = 50,000 chars + truncation marker + `body_truncated` bool.
3. ✅ `baker_gmail_read_message` returns attachment metadata only (no bytes).
4. ✅ Per-message metadata fetch errors NON-FATAL.
5. ✅ E2E tests `skipif TEST_GMAIL_LIVE != "1"`.

## Files changed

- `tools/gmail.py` — +263 LOC (modified)
- `tests/test_gmail.py` — +609 net LOC (renamed from `tests/test_gmail_attachment_read.py` via `git mv`)

## Bus posts

- Lead — bus #1026, topic `ship/gmail-search-and-read-1`.
- Deputy — bus #1027, topic `ship-cc/gmail-search-and-read-1`.

## Gate chain status

- gate_1 architecture review — pending deputy
- gate_2 security review — pending deputy (expected NO_FINDINGS: no new auth/credential surface; query parameterized into Gmail `q=`, never concatenated into shell/SQL/eval)
- gate_3 picker-architect — SKIP per dispatch envelope (no desk-picker SKILL.md changes wired in this brief)
- gate_4 code-reviewer 2nd pass — pending deputy (regression-guard pass, factory-rewrite safety, hard-cap dual-layer, NON-FATAL behavior all addressable from PR diff)
- gate_5 lead merge — pending lead

Post-merge: lead curls live MCP for `tools/list` (assert 49 tools, both new tool names present) + sanity calls (`baker_gmail_search` with `from:me`, `baker_gmail_read_message` with a returned msg id) + runs the 3 gated E2E from lead shell.

## Anchor

- Brief: `briefs/BRIEF_GMAIL_SEARCH_AND_READ_1.md`
- Dispatch envelope: `briefs/_tasks/CODE_3_PENDING.md` (overwritten by mailbox-hygiene flip → COMPLETE post-merge)
- Director directive: 2026-05-25 ~09:00Z "go"
- Extends: PR #257 (GMAIL_ATTACHMENT_READ_2, squash `89008e0a`)
- Lesson reference: `tasks/lessons.md:211` (mocked-only ships broken; 3 gated E2E continue the structural fix from READ_2)
