---
brief_id: GMAIL_SEARCH_AND_READ_1
authored_by: aihead1
dispatched_by: aihead1
target: b3
created: 2026-05-25
extends: BRIEF_GMAIL_ATTACHMENT_READ_2.md (PR #257, squash 89008e0a)
anchor: Director directive 2026-05-25 ~08:50Z — give desks full Gmail reach (search + read body) ahead of Tuesday LG Wien filing window + recurring future need
---

# BRIEF: GMAIL_SEARCH_AND_READ_1 — full Gmail reach for desks (search + read message body)

## Context

Desks (hag-desk, movie-desk, ben, ao-desk, bb-desk, brisen-desk, origination-desk) can today call exactly one Gmail MCP tool: `baker_gmail_attachment_read` (shipped 2026-05-25 in PR #257). To USE it they need a `message_id` + `filename`. They have no MCP-level way to FIND that message_id — they currently depend on:

1. The auto-poll pipeline ingesting the email into baker's `email_messages` table (5-min poll lag + noise filters that routinely drop counterparty mail), then querying via `baker_search` / `baker_raw_query`.
2. Director paste-in of a Gmail link / message_id.

This brief closes the gap by giving desks direct MCP-level Gmail search + read-body, mirroring the proven `baker_gmail_attachment_read` pattern: same OAuth singleton (`triggers.email_trigger._get_gmail_service`), same dispatch table (`tools/gmail.py:dispatch_gmail`), same gated E2E test discipline (lesson 211 anti-pattern guard — every Gmail-surface change must exercise a live-Gmail call before claiming green).

### Surface contract: N/A — pure backend MCP tool surface. No user-clickable UI (no dashboard panel, modal, button, anchor, or frontend route). Tools invoked over MCP/JSON-RPC by autonomous agents and pytest fixtures only.

## Estimated time: ~3-5h
## Complexity: Low-Medium
## Prerequisites
- Baker Gmail OAuth credentials live on baker-master Render — verified live 2026-05-25 08:28Z post-deploy of PR #257 (E2E PASS against hag-desk fixture).
- For local E2E test execution: same Gmail OAuth env vars present in b3's shell (same pattern as READ_2 §Fix 2c).

---

## Fix 1 — Add `baker_gmail_search` MCP tool

### Problem
Desks have no MCP-level way to search Gmail with arbitrary query syntax. The auto-poll pipeline persists only emails that pass noise filters; counterparty mail to addresses outside the watched senders is invisible to desks unless Director paste-in.

### Current state
`tools/gmail.py:26-79` defines exactly one Tool entry: `baker_gmail_attachment_read`. The `dispatch_gmail()` function at lines 84-88 routes one tool name. `GMAIL_TOOL_NAMES = frozenset(t.name for t in GMAIL_TOOLS)` auto-includes any Tool appended to `GMAIL_TOOLS`; name-based registration in `baker_mcp/baker_mcp_server.py:976-983` picks up new tools without further wiring.

### Implementation

**1a. Append TWO new Tool entries to `GMAIL_TOOLS` list** in `tools/gmail.py` (after the existing `baker_gmail_attachment_read` entry, before the closing `]`):

```python
    Tool(
        name="baker_gmail_search",
        description=(
            "Search Gmail with full Gmail query syntax. Returns a list of "
            "matching messages with id, threadId, snippet, From, Subject, and "
            "Date. Reuses baker's existing OAuth session (no new credential "
            "surface). Use to find specific emails by sender/subject/date/"
            "keyword/attachment-presence/label ahead of calling "
            "baker_gmail_read_message or baker_gmail_attachment_read. "
            "Gmail query syntax examples: 'from:counterparty@example.com', "
            "'subject:filing AND has:attachment', 'after:2026/05/01 before:2026/05/15', "
            "'label:Baker', '\"exact phrase\"'. See "
            "https://support.google.com/mail/answer/7190 for full syntax."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query using standard Gmail query syntax. "
                        "Empty string is rejected (returns error). Caller must "
                        "supply at least one query term."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": (
                        "Cap on number of matches returned. Default 20. Hard "
                        "max 50 (server-side enforced; values >50 are clamped "
                        "to 50). Each match costs ~5 Gmail quota units for the "
                        "metadata fetch on top of the list call."
                    ),
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
                "page_token": {
                    "type": "string",
                    "description": (
                        "Opaque pagination token from a prior response's "
                        "next_page_token field. Omit on first call."
                    ),
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="baker_gmail_read_message",
        description=(
            "Read a single Gmail message body + headers + attachment metadata "
            "by message_id. Returns from/to/cc/subject/date/snippet/body_text "
            "plus attachments list ({filename, mime_type, size}). Body extracted "
            "via baker's existing extract_body_text helper (text/plain preferred, "
            "text/html stripped as fallback). Body text capped at 50,000 chars "
            "with truncation marker. Attachment BYTES are NOT included — call "
            "baker_gmail_attachment_read with the filename for bytes/text "
            "extraction. Reuses baker's OAuth session."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": (
                        "Gmail message ID (e.g. from baker_gmail_search results). "
                        "NOT the thread_id."
                    ),
                },
            },
            "required": ["message_id"],
        },
    ),
```

**1b. Add dispatch branches** in `dispatch_gmail()` at `tools/gmail.py:84-88`. Replace the function body with:

```python
def dispatch_gmail(name: str, args: dict) -> str:
    """Route gmail-namespace tool calls. Returns JSON string for MCP transport."""
    if name == "baker_gmail_attachment_read":
        return _attachment_read(args)
    if name == "baker_gmail_search":
        return _search(args)
    if name == "baker_gmail_read_message":
        return _read_message(args)
    return json.dumps({"error": f"unknown gmail tool: {name}"})
```

**1c. Add `_search()` function** at the bottom of `tools/gmail.py` (after `_attachment_read`):

```python
_SEARCH_MAX_RESULTS_HARD_CAP = 50


def _search(args: dict) -> str:
    query = args.get("query", "").strip()
    max_results = args.get("max_results", 20)
    page_token = args.get("page_token", "").strip()

    if not query:
        return json.dumps({"error": "query is required and cannot be empty"})

    if not isinstance(max_results, int) or isinstance(max_results, bool) or max_results < 1:
        return json.dumps({
            "error": f"max_results must be a positive integer (got {max_results!r})",
        })

    # Defensive server-side clamp (schema also clamps to 50)
    if max_results > _SEARCH_MAX_RESULTS_HARD_CAP:
        max_results = _SEARCH_MAX_RESULTS_HARD_CAP

    # Reuse poll-time Gmail service singleton — no new credential surface.
    try:
        from triggers.email_trigger import _get_gmail_service
        service = _get_gmail_service()
    except Exception as e:
        logger.error(f"Gmail service init failed: {e}")
        return json.dumps({"error": f"gmail service init failed: {e}"})

    # Step 1: list message IDs matching the query
    try:
        list_kwargs: dict[str, Any] = {
            "userId": "me",
            "q": query,
            "maxResults": max_results,
        }
        if page_token:
            list_kwargs["pageToken"] = page_token
        list_resp = service.users().messages().list(**list_kwargs).execute()
    except Exception as e:
        logger.warning(f"gmail search list failed (query={query!r}): {e}")
        return json.dumps({"error": f"search list failed: {e}"})

    msg_stubs = list_resp.get("messages", []) or []
    next_page_token = list_resp.get("nextPageToken", "")
    result_size_estimate = list_resp.get("resultSizeEstimate", 0)

    # Step 2: fetch metadata + snippet for each match (sequential — cap of 50
    # keeps total cost ≤ ~255 quota units against Gmail's 250/sec user limit.
    # Do NOT parallelize; do NOT swap to batchRequest in v1 — keep simple.)
    from scripts.extract_gmail import get_header
    matches: list[dict[str, Any]] = []
    for stub in msg_stubs:
        msg_id = stub.get("id", "")
        if not msg_id:
            continue
        try:
            md = service.users().messages().get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
        except Exception as e:
            logger.warning(f"gmail metadata fetch failed (msg_id={msg_id}): {e}")
            # NON-FATAL: surface the per-message error, continue with the rest
            matches.append({
                "id": msg_id,
                "thread_id": stub.get("threadId", ""),
                "error": f"metadata fetch failed: {e}",
            })
            continue
        headers = md.get("payload", {}).get("headers", []) or []
        matches.append({
            "id": msg_id,
            "thread_id": md.get("threadId", "") or stub.get("threadId", ""),
            "snippet": md.get("snippet", ""),
            "from": get_header(headers, "From"),
            "to": get_header(headers, "To"),
            "subject": get_header(headers, "Subject"),
            "date": get_header(headers, "Date"),
            "label_ids": md.get("labelIds", []) or [],
        })

    result: dict[str, Any] = {
        "query": query,
        "match_count": len(matches),
        "result_size_estimate": result_size_estimate,
        "matches": matches,
    }
    if next_page_token:
        result["next_page_token"] = next_page_token

    return json.dumps(result)
```

### Key constraints
- HARD CAP at 50 results per call — both in inputSchema (`maximum: 50`) AND server-side defensive clamp (`_SEARCH_MAX_RESULTS_HARD_CAP`). Both layers.
- Gmail quota: `messages.list` = 5 units, each `messages.get(format=metadata)` = 5 units. 50 results = 255 units. Gmail's per-user limit is 250 units/SECOND so the loop MUST stay sequential. Document this in the code comment.
- Metadata fetch errors per individual message are NON-FATAL — append the stub with an `error` field and continue. One bad message ID must not poison the whole search response.
- Empty `query` → error response, no Gmail call attempted. Gmail accepts empty `q=` and returns recent mail; that's a dangerous default for autonomous callers.
- DO NOT add OR-batching, DO NOT parallelize, DO NOT cache — premature optimization. Ship simple; observe usage; add complexity only on real load signal.

### Verification

Syntax check:
```bash
python3 -c "import py_compile; py_compile.compile('tools/gmail.py', doraise=True)"
```

Tool registration now includes three tools:
```bash
python3 -c "from baker_mcp.baker_mcp_server import GMAIL_TOOL_NAMES; print(sorted(GMAIL_TOOL_NAMES))"
# expected: ['baker_gmail_attachment_read', 'baker_gmail_read_message', 'baker_gmail_search']
```

---

## Fix 2 — Add `baker_gmail_read_message` MCP tool

### Problem
Desks have no MCP-level way to read an email body once they have a message_id. The poll-pipeline persists `email_messages.body_text` only for emails that survive noise filtering. Direct MCP read closes the gap.

### Current state
No existing tool reads message body. Pipeline-side helper `scripts/extract_gmail.py:extract_body_text(payload)` (lines 294-340) already handles text/plain preference + text/html stripped fallback + multipart recursion. Reuse it.

### Implementation

**2a. Tool entry already added in Fix 1a** (both tool entries listed together so the reviewer sees the full `GMAIL_TOOLS` array shape in one place).

**2b. Add `_read_message()` function** at the bottom of `tools/gmail.py` (after `_search`):

```python
_BODY_TEXT_CAP_CHARS = 50_000
_BODY_TRUNCATION_MARKER = "\n\n[... truncated by baker_gmail_read_message at 50,000 chars]"


def _read_message(args: dict) -> str:
    message_id = args.get("message_id", "").strip()

    if not message_id:
        return json.dumps({"error": "message_id is required"})

    try:
        from triggers.email_trigger import _get_gmail_service
        service = _get_gmail_service()
    except Exception as e:
        logger.error(f"Gmail service init failed: {e}")
        return json.dumps({"error": f"gmail service init failed: {e}"})

    try:
        message = service.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()
    except Exception as e:
        logger.warning(f"gmail message fetch failed (message_id={message_id}): {e}")
        return json.dumps({"error": f"message fetch failed: {e}"})

    payload = message.get("payload", {})
    headers = payload.get("headers", []) or []

    from scripts.extract_gmail import extract_body_text, get_header, _collect_attachment_parts
    body_text = extract_body_text(payload) or ""
    truncated = False
    if len(body_text) > _BODY_TEXT_CAP_CHARS:
        body_text = body_text[:_BODY_TEXT_CAP_CHARS] + _BODY_TRUNCATION_MARKER
        truncated = True

    # Attachment metadata only — BYTES come from baker_gmail_attachment_read.
    attachment_parts = _collect_attachment_parts(payload)
    attachments: list[dict[str, Any]] = []
    for part in attachment_parts:
        filename = part.get("filename", "")
        if not filename:
            continue
        body = part.get("body", {}) or {}
        guessed, _ = mimetypes.guess_type(filename)
        attachments.append({
            "filename": filename,
            "mime_type": guessed or part.get("mimeType", "application/octet-stream"),
            "size": body.get("size", 0),
        })

    result: dict[str, Any] = {
        "message_id": message.get("id", message_id),
        "thread_id": message.get("threadId", ""),
        "snippet": message.get("snippet", ""),
        "from": get_header(headers, "From"),
        "to": get_header(headers, "To"),
        "cc": get_header(headers, "Cc"),
        "subject": get_header(headers, "Subject"),
        "date": get_header(headers, "Date"),
        "label_ids": message.get("labelIds", []) or [],
        "body_text": body_text,
        "body_truncated": truncated,
        "attachments": attachments,
    }
    return json.dumps(result)
```

### Key constraints
- Body text HARD CAP at 50,000 chars + truncation marker. Long forwarded threads otherwise blow up the JSON response size + caller token budgets.
- Attachment BYTES are NOT included — only metadata. Callers needing bytes call `baker_gmail_attachment_read` with the filename. Mentioned in the tool description (1a). Don't add an `include_bytes` flag here — keep responsibilities split.
- `extract_body_text` already handles text/plain → text/html fallback + multipart recursion. Do NOT reimplement.
- Missing Cc header → `get_header` returns `""`. Surface as empty string, not absent key (consistent shape).
- DO NOT add reply-thread reconstruction, DO NOT parse HTML beyond `strip_html` — out of scope.

### Verification

Same syntax check + tool-registration check as Fix 1.

---

## Fix 3 — Test coverage (mocked + gated real-Gmail E2E)

### Problem
Lesson 211 (`tasks/lessons.md:211`) and the READ_1 → READ_2 trip-up established the rule: every Gmail-surface change must exercise a live-Gmail call before claiming green. Mocked-only ship shipped READ_1 broken because the architectural defect (cross-session attachment IDs) was undetectable from mocks.

### Current state
`tests/test_gmail_attachment_read.py` exists (504 lines) with 12 mocked cases + 1 gated E2E for the existing attachment-read tool. The `_build_service_mock()` factory + `_patch_gmail_service` fixture are reusable.

### Implementation

**3a. Rename `tests/test_gmail_attachment_read.py` → `tests/test_gmail.py`** since the file will now cover all three Gmail tools. Use `git mv` so history follows the rename:

```bash
git mv tests/test_gmail_attachment_read.py tests/test_gmail.py
```

Update the module docstring at the top of the renamed file to reflect the wider scope:

```python
"""Tests for tools.gmail.dispatch_gmail — three MCP tools:

  baker_gmail_attachment_read  — 12 mocked cases + 1 gated E2E (from READ_2)
  baker_gmail_search           —  6 mocked cases + 1 gated E2E (this brief)
  baker_gmail_read_message     —  6 mocked cases + 1 gated E2E (this brief)

The 24 mocked cases use unittest.mock.MagicMock — no real Gmail API calls.
The 3 E2E tests hit live Gmail and require TEST_GMAIL_LIVE=1 plus
BAKER_GMAIL_* OAuth env vars; auto-skipped in CI.
"""
```

**3b. Extend `_build_service_mock()` factory** (currently at `tests/test_gmail.py:77-114` post-rename) to support `messages.list()` and format-aware `messages.get()`. Add new keyword args + chain setup:

```python
def _build_service_mock(
    *,
    message_payload: dict | None = None,
    attachment_data: str | None = None,
    message_raises: Exception | None = None,
    attachment_raises: Exception | None = None,
    # NEW for search + read_message:
    list_response: dict | None = None,
    list_raises: Exception | None = None,
    metadata_responses: dict | None = None,        # {msg_id: metadata_dict}
    metadata_raises: dict | None = None,           # {msg_id: Exception}
    full_message_response: dict | None = None,     # full payload for read_message
    full_message_raises: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics the Gmail service call chains:
       service.users().messages().get(...).execute()                          [existing]
       service.users().messages().attachments().get(...).execute()            [existing]
       service.users().messages().list(...).execute()                         [new — search]
       service.users().messages().get(format='metadata', ...).execute()       [new — search]
       service.users().messages().get(format='full', id=X, ...).execute()     [new — read_message]
    """
    service = MagicMock(name="gmail_service")

    # NEW: messages().list() chain
    list_exec = MagicMock(name="messages_list_execute")
    if list_raises is not None:
        list_exec.execute.side_effect = list_raises
    else:
        list_exec.execute.return_value = list_response or {"messages": [], "resultSizeEstimate": 0}
    service.users.return_value.messages.return_value.list.return_value = list_exec

    # NEW: messages().get() — format-aware router replacing the prior
    # return_value-style mock. Routes on the `format` kwarg + `id` kwarg.
    def _route_messages_get(**kwargs):
        fmt = kwargs.get("format", "")
        msg_id = kwargs.get("id", "")
        exec_mock = MagicMock(name=f"messages_get_execute(format={fmt},id={msg_id})")
        if fmt == "metadata":
            if metadata_raises and msg_id in metadata_raises:
                exec_mock.execute.side_effect = metadata_raises[msg_id]
            else:
                md = (metadata_responses or {}).get(msg_id, {})
                exec_mock.execute.return_value = md
        elif fmt == "full":
            if full_message_raises is not None:
                exec_mock.execute.side_effect = full_message_raises
            elif full_message_response is not None:
                exec_mock.execute.return_value = full_message_response
            else:
                # Legacy fallback for baker_gmail_attachment_read tests that
                # use the existing `message_payload=` path.
                if message_raises is not None:
                    exec_mock.execute.side_effect = message_raises
                else:
                    exec_mock.execute.return_value = {
                        "id": msg_id or "MSG_1",
                        "payload": message_payload or {},
                    }
        else:
            exec_mock.execute.return_value = {}
        return exec_mock

    service.users.return_value.messages.return_value.get.side_effect = _route_messages_get

    # [existing attachments.get chain — keep as is]
    att_exec = MagicMock(name="attachments_get_execute")
    if attachment_raises is not None:
        att_exec.execute.side_effect = attachment_raises
    else:
        att_exec.execute.return_value = {"data": attachment_data or ""}
    (
        service.users.return_value
        .messages.return_value
        .attachments.return_value
        .get.return_value
    ) = att_exec

    return service
```

**Key constraint on 3b:** rewriting `get()` from `return_value` to `side_effect` is the breaking change. ALL 12 existing attachment-read tests MUST still pass after the factory rewrite — keep their existing pattern (passing `message_payload=` continues to work via the legacy-fallback branch). Run `pytest tests/test_gmail.py -v -k attachment_read` after the factory rewrite to verify all 12 are still green BEFORE adding the new search/read_message tests.

**3c. Add 6 mocked cases for `baker_gmail_search`:**

| # | Case | Setup |
|---|---|---|
| 1 | `test_search_empty_query_rejected` | No service call expected. Pass `{"query": ""}` → error mentions `query`. |
| 2 | `test_search_no_matches` | `list_response={"messages": [], "resultSizeEstimate": 0}` → `match_count == 0`, `matches == []`, no metadata calls. |
| 3 | `test_search_happy_path_three_matches` | `list_response={"messages":[{"id":"M1","threadId":"T1"},{"id":"M2","threadId":"T2"},{"id":"M3","threadId":"T3"}]}` + `metadata_responses={"M1":..., "M2":..., "M3":...}` with realistic headers + snippet. Assert `match_count == 3`, each match has `from/to/subject/date/snippet/label_ids` populated. |
| 4 | `test_search_metadata_fetch_partial_failure` | 3 matches, but `metadata_raises={"M2": RuntimeError("rate limited")}`. Assert `match_count == 3`, M2 entry has `error` field, M1/M3 have normal fields. NON-FATAL behavior verified. |
| 5 | `test_search_max_results_clamped` | Pass `{"query": "x", "max_results": 100}`. Use `service.users().messages().list.assert_called_with(...)` (or inspect call_args) to assert `maxResults=50`. |
| 6 | `test_search_pagination_passthrough` | `list_response={"messages":[...], "nextPageToken":"PT_42"}` → response includes `next_page_token: "PT_42"`. Pass `page_token="PT_PRIOR"`; assert the kwargs to `list()` included `pageToken="PT_PRIOR"`. |

**3d. Add 6 mocked cases for `baker_gmail_read_message`:**

| # | Case | Setup |
|---|---|---|
| 1 | `test_read_missing_message_id` | `{"message_id":""}` → error. |
| 2 | `test_read_happy_path_text_plain_body` | `full_message_response` with text/plain body + From/To/Subject/Date headers + 2 attachments. Assert `body_text` non-empty, attachments list length 2 with correct {filename, mime_type, size}, `body_truncated is False`. |
| 3 | `test_read_html_only_body_stripped` | `full_message_response` with ONLY text/html body. Assert `body_text` contains stripped text (no tags), HTML-entity decoded. |
| 4 | `test_read_body_truncation` | `full_message_response` with text/plain body of 60,000 chars. Assert `body_truncated is True`, `body_text.endswith(_BODY_TRUNCATION_MARKER)`, total length ≤ 50,000 + len(marker). |
| 5 | `test_read_message_fetch_exception` | `full_message_raises=RuntimeError("gmail down")` → error response mentions `message fetch failed`. |
| 6 | `test_read_no_attachments` | `full_message_response` with only text/plain part, no attachment parts. Assert `attachments == []`. |

**3e. Add 2 new gated E2E tests** (one per new tool):

```python
@pytest.mark.skipif(
    os.getenv("TEST_GMAIL_LIVE") != "1",
    reason="Real-Gmail E2E. Set TEST_GMAIL_LIVE=1 + BAKER_GMAIL_* env vars to run.",
)
def test_e2e_real_gmail_search():
    """E2E: search for a known-stable query. Asserts ≥0 matches returned (no error)."""
    import tools.gmail as gmail_mod

    # 'from:me' should always match SOMETHING in baker's mailbox (baker sends
    # daily). E2E_GMAIL_SEARCH_QUERY overrides for ad-hoc local testing.
    query = os.getenv("E2E_GMAIL_SEARCH_QUERY", "from:me")

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_search",
        {"query": query, "max_results": 3},
    )
    result = json.loads(raw)

    assert "error" not in result, f"E2E search returned error: {result}"
    assert "matches" in result
    assert isinstance(result["matches"], list)
    # If mailbox is empty, match_count could be 0 — that's still a valid response.
    if result["match_count"] > 0:
        first = result["matches"][0]
        assert "id" in first
        assert "thread_id" in first
        if "error" not in first:
            assert "snippet" in first
            assert "from" in first


@pytest.mark.skipif(
    os.getenv("TEST_GMAIL_LIVE") != "1",
    reason="Real-Gmail E2E. Set TEST_GMAIL_LIVE=1 + BAKER_GMAIL_* env vars to run.",
)
def test_e2e_real_gmail_read_message():
    """E2E: read a known-stable message body. Uses E2E_GMAIL_MESSAGE_ID fixture."""
    import tools.gmail as gmail_mod

    fixture_message_id = os.getenv("E2E_GMAIL_MESSAGE_ID", "")
    if not fixture_message_id:
        pytest.skip("E2E fixture env var E2E_GMAIL_MESSAGE_ID not set")

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_read_message",
        {"message_id": fixture_message_id},
    )
    result = json.loads(raw)

    assert "error" not in result, f"E2E read returned error: {result}"
    assert result["message_id"] == fixture_message_id
    assert "from" in result
    assert "subject" in result
    assert "body_text" in result
    assert "attachments" in result
    assert isinstance(result["attachments"], list)
```

### Key constraints
- The 12 existing attachment-read tests MUST still pass after the `_build_service_mock` factory rewrite. Run `pytest tests/test_gmail.py -v -k attachment_read` FIRST after the factory change, before adding any new tests.
- Total expected after this brief: 24 mocked passed + 3 skipped E2E (in CI without TEST_GMAIL_LIVE=1).
- E2E tests MUST NOT auto-run — they hit live Gmail and consume real quota. Strict `skipif(TEST_GMAIL_LIVE != "1")` gating.

### Verification

Standard CI run:
```bash
pytest tests/test_gmail.py -v
# expected: 24 passed, 3 skipped
```

Local E2E pre-merge (b3, if creds available):
```bash
export TEST_GMAIL_LIVE=1
export E2E_GMAIL_MESSAGE_ID=19e2ff37f48fed12   # any stable poll-indexed Gmail msg
export E2E_GMAIL_SEARCH_QUERY="from:me"         # default also works
pytest tests/test_gmail.py -v -k e2e
# expected: 3 passed
```

If b3 cannot run E2E locally (creds not in shell), document explicitly in ship report. AH1 runs the 3 E2E tests post-merge from the lead shell as the gate-clear step.

---

## Files Modified
- `tools/gmail.py` — +2 Tool defs in `GMAIL_TOOLS`, +2 dispatch branches in `dispatch_gmail()`, +2 internal functions (`_search`, `_read_message`). ~180 LOC delta.
- `tests/test_gmail_attachment_read.py` → `tests/test_gmail.py` (renamed via `git mv`). Factory extended for list/metadata/full-format chains (~60 LOC delta), +12 mocked cases (~250 LOC), +2 gated E2E tests (~50 LOC). Total ~360 LOC delta.

## Files NOT to Touch
- `scripts/extract_gmail.py` — reuse `extract_body_text`, `get_header`, `_collect_attachment_parts`, `strip_html` as-is.
- `triggers/email_trigger.py` — reuse `_get_gmail_service` singleton as-is.
- `baker_mcp/baker_mcp_server.py` — name-based registration via `GMAIL_TOOL_NAMES` picks up new tools automatically (`TOOLS.extend(GMAIL_TOOLS)` at line 977, dispatch at lines 2141-2142).
- Any other tool in `tools/` — independent.

## Quality Checkpoints

After implementation, before opening PR:

1. `python3 -c "import py_compile; py_compile.compile('tools/gmail.py', doraise=True)"` returns clean.
2. `pytest tests/test_gmail.py -v` shows **24 passed, 3 skipped**.
3. `pytest tests/test_gmail.py -v -k attachment_read` shows **12 passed, 1 skipped** (regression guard — factory rewrite did not break READ_2's tests).
4. `python3 -c "from baker_mcp.baker_mcp_server import GMAIL_TOOL_NAMES; print(sorted(GMAIL_TOOL_NAMES))"` returns `['baker_gmail_attachment_read', 'baker_gmail_read_message', 'baker_gmail_search']`.
5. Defensive-import path (`baker_mcp/baker_mcp_server.py:975-983`) still loads — manually import after the change.
6. Tool inputSchemas validate:
   - `baker_gmail_search`: `query` required string; `max_results` optional int [1,50] default 20; `page_token` optional string.
   - `baker_gmail_read_message`: `message_id` required string.
7. `_SEARCH_MAX_RESULTS_HARD_CAP = 50` constant present in `tools/gmail.py` (defensive server-side clamp).
8. `_BODY_TEXT_CAP_CHARS = 50_000` constant + truncation marker appended when body > cap, `body_truncated: true` field flipped.
9. Search metadata-fetch errors per-message are NON-FATAL (one bad msg does not poison response).
10. E2E tests gated on `TEST_GMAIL_LIVE=1` — no surprise live-API calls in CI.
11. If b3 runs E2E locally, ship report includes the 3 PASS lines.

## Verification SQL

Not strictly required (no DB schema touched). For fixture selection if b3 wants to pick a recent message for `E2E_GMAIL_MESSAGE_ID`:

```sql
SELECT message_id, subject, sender, received_at
FROM email_messages
ORDER BY received_at DESC
LIMIT 5;
```

Post-deploy capability sanity check (AH1 runs from lead shell once PR merges + Render deploy live):

```bash
# search
curl -sS -X POST "https://baker-master.onrender.com/mcp?key=$BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_gmail_search","arguments":{"query":"from:me","max_results":3}}}'
# expected: result.content[0].text JSON with matches array

# read_message (using a msg id from the search above)
curl -sS -X POST "https://baker-master.onrender.com/mcp?key=$BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"baker_gmail_read_message","arguments":{"message_id":"<MSG_ID>"}}}'
# expected: result.content[0].text JSON with from/subject/body_text/attachments
```

## Anti-pattern guard

Direct reference to `tasks/lessons.md:211` (build_eval_seed.py mocked-tests-shipped-broken) + the READ_1 → READ_2 architecture-defect-invisible-to-mocks pattern. The 3 gated E2E tests in this brief continue the structural fix established in READ_2: every Gmail-surface change MUST exercise live-Gmail calls before claiming green. b3 — if you cannot run E2E locally (no creds in b3 shell), document this explicitly in the ship report; AH1 runs E2E from lead shell post-merge as the gate-clear step. Silent skip = REQUEST_CHANGES.

## Ship report contract

When b3 ships:
1. Open PR against `main` with title `GMAIL_SEARCH_AND_READ_1: baker_gmail_search + baker_gmail_read_message MCP tools`.
2. Ship report goes to `briefs/_reports/B3_gmail_search_and_read_1_20260525.md`.
3. Bus-post to `lead` with topic `ship/gmail-search-and-read-1`. Include: PR #, mocked-test count + result (expected 24 passed + 3 skipped), E2E test status (ran locally / skipped + why), tool count assertion (47 → 49).
4. AH1 (lead) gates → architect + security-review + code-reviewer 2nd-pass → merge → confirm capability live with curl against deployed tools.
5. Once capability live, AH1 broadcasts to desk pickers (via desk SKILL.md update path; desks are not on the bus) that full Gmail reach is now available — these tools join `baker_gmail_attachment_read` to give desks search + read + attachment-pull triple.
