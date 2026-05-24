---
brief_id: GMAIL_ATTACHMENT_READ_2
authored_by: aihead1
dispatched_by: aihead1
target: b3
created: 2026-05-24
amends: BRIEF_GMAIL_ATTACHMENT_READ_1.md (PR #256, squash f030344)
anchor: deputy bus #973 (post-deploy/ac5-fail-architectural) 2026-05-24 22:17Z
---

# BRIEF: GMAIL_ATTACHMENT_READ_2 — filename-based API + real-Gmail E2E coverage

## Context

`baker_gmail_attachment_read` (shipped READ_1, PR #256 merged 2026-05-24 21:10Z) is non-functional in practice. Root cause: Gmail attachment IDs are OAuth-session-scoped — they only resolve in the session that minted them. The tool's input schema requires `(message_id, attachment_id)`, but autonomous agent callers (hag-desk, etc.) cannot mint a baker-session attachment_id. Every cross-session call returns `attachment_id not found in message`.

### Surface contract: N/A — pure backend MCP tool surface. No user-clickable UI (no dashboard panel, modal, button, anchor, or frontend route). Tool is invoked over MCP/JSON-RPC by autonomous agents and pytest fixtures only.

Deputy verified post-OAuth-fix:
1. Lead AC4 PASS (click-to-wake) confirmed unrelated.
2. AC5 retry against test pair (msg `19e2c1b1e2bdd4c0` + PDF attachment) → `attachment_id not found`.
3. Fresh attachment_id from Director's `claude_ai_Gmail` session → SAME error. Cross-session lookup is the fundamental defect.
4. Documents table confirms baker's poll DID extract the same attachment via its own session-scoped ID (`id=104536`, ingested 2026-05-16) — proves the pipeline works internally; only the cross-session input contract is broken.
5. `tests/test_gmail_attachment_read.py` — all 10 cases mocked. Zero real-Gmail end-to-end coverage. Brief shipped on green mocks, never proved live.

This brief replaces the input contract with `filename` (which the caller CAN supply: from `claude_ai_Gmail get_thread` part metadata, from a Plaud transcript, from Director paste-in, etc.) and resolves the session-scoped `attachmentId` internally, in baker's session, where it's valid.

Adds one real-Gmail end-to-end test gated on `TEST_GMAIL_LIVE=1` so future ship gates cannot pass on mocks alone for this surface.

Hag-desk LG Wien Forderungsanmeldung filing deadline: 2026-05-26/27. This unblocks autonomous attachment pulls for filing prep. Manual Director-pull workaround remains in parallel — Tuesday filing is NOT bet on READ_2 shipping in time.

## Estimated time: ~2-3h
## Complexity: Low
## Prerequisites
- Baker Gmail OAuth credentials live on baker-master Render (`BAKER_GMAIL_CLIENT_ID`, `BAKER_GMAIL_CLIENT_SECRET`, `BAKER_GMAIL_REFRESH_TOKEN`) — verified 2026-05-24 21:48Z post env-var DELETE redeploy
- For local E2E test execution: same three env vars present in b3's shell + a known-stable Gmail message id (see Fix 2 §E2E fixture selection)

---

## Fix 1 — Swap `attachment_id` → `filename` (with optional `attachment_index` tiebreaker)

### Problem
`tools/gmail.py:46-51` requires caller to provide `attachment_id`. Attachment IDs are not portable across OAuth sessions. Cross-session callers always hit the `attachment_id not found in message` branch at `tools/gmail.py:121`.

### Current state (`tools/gmail.py:25-65`)
```python
GMAIL_TOOLS: list[Tool] = [
    Tool(
        name="baker_gmail_attachment_read",
        description=(...),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID..."},
                "attachment_id": {"type": "string", "description": "Gmail attachment ID..."},
                "include_bytes": {"type": "boolean", "default": False},
            },
            "required": ["message_id", "attachment_id"],
        },
    ),
]
```

### Implementation

**1a. Update `inputSchema`** — replace `attachment_id` with `filename` (required) and add `attachment_index` (optional, integer ≥ 1, default 1):

```python
GMAIL_TOOLS: list[Tool] = [
    Tool(
        name="baker_gmail_attachment_read",
        description=(
            "Read a single Gmail attachment on-demand by filename. Returns "
            "extracted text (for PDF/DOCX/XLSX/CSV/TXT/MD/JSON) plus optional "
            "base64-encoded raw bytes. Reuses the existing poll-time extraction "
            "pipeline + Gmail service singleton (no new credential surface). "
            "Use when an agent needs to pull a specific named attachment "
            "mid-session without waiting for the poll cycle to index it."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": (
                        "Gmail message ID (from get_thread or search_threads "
                        "response). NOT the thread_id."
                    ),
                },
                "filename": {
                    "type": "string",
                    "description": (
                        "Attachment filename as it appears in the message "
                        "(case-sensitive, exact match). Gmail preserves the "
                        "original filename."
                    ),
                },
                "attachment_index": {
                    "type": "integer",
                    "description": (
                        "1-based index used as a tiebreaker when multiple "
                        "attachments share the same filename. Default 1 "
                        "(first match). If filename matches >1 attachment "
                        "and index is out of range, returns an error listing "
                        "all matches with their indexes."
                    ),
                    "default": 1,
                    "minimum": 1,
                },
                "include_bytes": {
                    "type": "boolean",
                    "description": (
                        "If true, return base64-encoded raw bytes alongside "
                        "extracted text. Default false (text-only)."
                    ),
                    "default": False,
                },
            },
            "required": ["message_id", "filename"],
        },
    ),
]
```

**1b. Update `_attachment_read()`** in `tools/gmail.py:77-180`. Replace the body wholesale. New logic:

```python
def _attachment_read(args: dict) -> str:
    message_id = args.get("message_id", "").strip()
    filename = args.get("filename", "").strip()
    attachment_index = args.get("attachment_index", 1)
    include_bytes = bool(args.get("include_bytes", False))

    if not message_id or not filename:
        return json.dumps({
            "error": "message_id and filename are both required",
        })

    if not isinstance(attachment_index, int) or attachment_index < 1:
        return json.dumps({
            "error": f"attachment_index must be a positive integer (got {attachment_index!r})",
        })

    # Reuse poll-time Gmail service singleton — no new credential surface.
    try:
        from triggers.email_trigger import _get_gmail_service
        service = _get_gmail_service()
    except Exception as e:
        logger.error(f"Gmail service init failed: {e}")
        return json.dumps({"error": f"gmail service init failed: {e}"})

    # Fetch the message in baker's own OAuth session so the attachmentId
    # we get from body.attachmentId is valid for the matching attachments.get() call.
    try:
        message = service.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()
    except Exception as e:
        logger.warning(f"gmail message fetch failed (message_id={message_id}): {e}")
        return json.dumps({"error": f"message fetch failed: {e}"})

    from scripts.extract_gmail import (
        _collect_attachment_parts,
        _extract_text_from_bytes,
        _ATTACHMENT_EXTENSIONS,
        _MAX_ATTACHMENT_SIZE,
    )
    payload = message.get("payload", {})
    parts = _collect_attachment_parts(payload)

    # Match by filename (case-sensitive exact). Build list of all matches
    # in walk order so attachment_index is deterministic.
    matches = [p for p in parts if p.get("filename", "") == filename]

    if not matches:
        available = sorted({p.get("filename", "") for p in parts if p.get("filename")})
        return json.dumps({
            "error": f"filename not found in message: {filename}",
            "available_filenames": available,
        })

    if attachment_index > len(matches):
        return json.dumps({
            "error": (
                f"attachment_index {attachment_index} out of range "
                f"({len(matches)} attachment(s) named {filename!r})"
            ),
            "filename": filename,
            "match_count": len(matches),
        })

    target_part = matches[attachment_index - 1]
    body = target_part.get("body", {})
    size = body.get("size", 0)
    session_attachment_id = body.get("attachmentId", "")

    if not session_attachment_id:
        return json.dumps({
            "error": "matched attachment has no attachmentId (inline-data only path not supported)",
            "filename": filename,
        })

    # Size guard — mirror poll-time cap.
    if size > _MAX_ATTACHMENT_SIZE:
        return json.dumps({
            "error": f"attachment too large: {size} bytes (cap {_MAX_ATTACHMENT_SIZE})",
            "filename": filename,
            "size": size,
        })

    # Download attachment bytes using the session-valid attachmentId.
    try:
        att = service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=session_attachment_id,
        ).execute()
        data = att.get("data", "")
        if not data:
            return json.dumps({
                "error": "gmail returned empty attachment data",
                "filename": filename,
            })
        file_bytes = base64.urlsafe_b64decode(data)
    except Exception as e:
        logger.warning(f"attachment download failed ({filename}): {e}")
        return json.dumps({
            "error": f"download failed: {e}",
            "filename": filename,
        })

    # Extract text via existing pipeline.
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    text = ""
    if ext in _ATTACHMENT_EXTENSIONS:
        try:
            extracted = _extract_text_from_bytes(file_bytes, filename, ext)
            text = extracted or ""
        except Exception as e:
            logger.warning(f"extraction failed ({filename}): {e}")

    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/octet-stream"

    result: dict[str, Any] = {
        "filename": filename,
        "mime_type": mime_type,
        "size": size,
        "text": text,
        "text_extracted": bool(text),
        "match_count": len(matches),
        "attachment_index": attachment_index,
    }
    if include_bytes:
        result["bytes_base64"] = base64.standard_b64encode(file_bytes).decode("ascii")

    return json.dumps(result)
```

### Key constraints
- DO NOT touch `scripts/extract_gmail.py` — the poll-time path is independent and works. Only the on-demand tool surface is broken.
- DO NOT touch `baker_mcp/baker_mcp_server.py` — registration is name-based via `GMAIL_TOOL_NAMES`, no schema change needed there. (Defensive import at lines 974-983 stays as is.)
- Filename match MUST be case-sensitive exact. Gmail preserves filename casing; loose matching hides bugs.
- The `available_filenames` field in the not-found error is intentional — it tells the caller what to retry with. Sort it for stable agent retries.
- Walk order for `attachment_index` MUST be deterministic: it's the order `_collect_attachment_parts()` returns (depth-first via the existing recursion in `scripts/extract_gmail.py:601-615`). Do not re-sort.

### Verification
Syntax check the modified file:
```bash
python3 -c "import py_compile; py_compile.compile('tools/gmail.py', doraise=True)"
```

Confirm the tool registration still loads via the defensive-import path:
```bash
python3 -c "from baker_mcp.baker_mcp_server import GMAIL_TOOL_NAMES; print(sorted(GMAIL_TOOL_NAMES))"
# expected: ['baker_gmail_attachment_read']
```

---

## Fix 2 — Adapt mocked tests + add real-Gmail E2E test

### Problem
`tests/test_gmail_attachment_read.py` has 10 cases, all mocked. The original brief shipped on those green mocks. The architectural defect surfaced only post-deploy when deputy ran a real Gmail call. Anchor: `tasks/lessons.md` line 211 (`build_eval_seed.py` shipped with only structural tests; production-shape failure surfaced same way).

### Current state
- File: `tests/test_gmail_attachment_read.py` (372 lines)
- 10 cases, all using `MagicMock` for the Gmail service chain
- `_patch_gmail_service` fixture (auto-applied) injects a fake service
- `_patch_extractor` fixture stubs text extraction

### Implementation

**2a. Adapt existing 10 cases to new API.** Each case currently passes `{"message_id": "MSG_1", "attachment_id": "ATT_PDF_1"}`. New API uses `{"message_id": "MSG_1", "filename": "Schadensblatt-Top4.pdf"}` (or `"photo.png"`, `"huge.pdf"` per fixture).

Case-by-case adjustments:
- **Case 1 / `test_happy_path_text_only`** — change `attachment_id` arg → `filename: "Schadensblatt-Top4.pdf"`. Add assertion `result["match_count"] == 1` and `result["attachment_index"] == 1`.
- **Case 2 / `test_happy_path_include_bytes`** — same arg swap.
- **Case 3 / `test_missing_message_id`** — pass `{"message_id": "", "filename": "x.pdf"}`. Assert error mentions `message_id`.
- **Case 4 / `test_missing_attachment_id`** — rename to `test_missing_filename`. Pass `{"message_id": "MSG_1", "filename": ""}`. Assert error mentions `filename`.
- **Case 5 / `test_attachment_id_not_found`** — rename to `test_filename_not_found`. Fixture stays (PDF with attachment_id `DIFFERENT_ID` is irrelevant under new contract). Pass filename `"NotInMessage.pdf"`. Assert error mentions `filename not found in message` and assert `result["available_filenames"]` is non-empty and includes `"Schadensblatt-Top4.pdf"`.
- **Case 6 / `test_oversize_attachment`** — arg swap to `filename: "huge.pdf"`.
- **Case 7 / `test_unsupported_extension`** — arg swap to `filename: "photo.png"`.
- **Case 8 / `test_empty_gmail_data_response`** — arg swap.
- **Case 9 / `test_message_fetch_exception`** — arg swap.
- **Case 10 / `test_attachment_download_exception`** — arg swap.

**2b. Add 2 new mocked cases for the new behaviors:**

```python
def test_duplicate_filenames_with_index(_patch_gmail_service, _patch_extractor):
    """Two attachments share filename → caller picks via attachment_index."""
    import tools.gmail as gmail_mod
    payload = {
        "parts": [
            {
                "filename": "invoice.pdf",
                "body": {"size": len(_PDF_BYTES), "attachmentId": "ATT_INV_A"},
            },
            {
                "filename": "invoice.pdf",
                "body": {"size": len(_PDF_BYTES), "attachmentId": "ATT_INV_B"},
            },
        ],
    }
    service = _build_service_mock(
        message_payload=payload,
        attachment_data=base64.urlsafe_b64encode(_PDF_BYTES).decode("ascii"),
    )
    _patch_gmail_service["set_service"](service)

    # Default index=1 → first match
    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "invoice.pdf"},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["match_count"] == 2
    assert result["attachment_index"] == 1

    # Explicit index=2 → second match (different attachmentId resolved internally)
    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "invoice.pdf", "attachment_index": 2},
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["match_count"] == 2
    assert result["attachment_index"] == 2


def test_attachment_index_out_of_range(_patch_gmail_service, _patch_extractor):
    """attachment_index > match_count → error listing match_count."""
    import tools.gmail as gmail_mod
    service = _build_service_mock(
        message_payload=_build_payload_nested_pdf(),
        attachment_data=base64.urlsafe_b64encode(_PDF_BYTES).decode("ascii"),
    )
    _patch_gmail_service["set_service"](service)

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": "MSG_1", "filename": "Schadensblatt-Top4.pdf", "attachment_index": 5},
    )
    result = json.loads(raw)
    assert "error" in result
    assert "out of range" in result["error"]
    assert result["match_count"] == 1
```

**2c. Add 1 real-Gmail E2E test** (gated, NOT auto-running in CI):

```python
import os
import pytest


@pytest.mark.skipif(
    os.getenv("TEST_GMAIL_LIVE") != "1",
    reason="Real-Gmail E2E. Set TEST_GMAIL_LIVE=1 + BAKER_GMAIL_* env vars to run.",
)
def test_e2e_real_gmail_attachment_read():
    """End-to-end test against the real Gmail API using baker's OAuth creds.

    Fixture: a known-stable poll-indexed message + attachment from baker's
    documents table. Selected by querying:
        SELECT source_path FROM documents
        WHERE source_path LIKE 'email:%/%.pdf'
        ORDER BY ingested_at DESC LIMIT 1
    Extract the Gmail message_id (the substring between 'email:' and '/').

    Gated on TEST_GMAIL_LIVE=1 to avoid hitting the live API in CI.
    Must NOT be part of the standard pytest run.
    """
    # NB: bypass the autouse mock fixtures by reading the real env.
    import importlib
    import tools.gmail as gmail_mod
    importlib.reload(gmail_mod)  # drop any stale patches

    # Pick a known-stable message — update if the underlying message is deleted.
    # Selection: documents.source_path LIKE 'email:%/%.pdf' ORDER BY ingested_at DESC LIMIT 1
    # Confirm fixture before merge by running the SQL above and pasting the path.
    fixture_message_id = os.getenv("E2E_GMAIL_MESSAGE_ID", "")
    fixture_filename = os.getenv("E2E_GMAIL_FILENAME", "")
    if not fixture_message_id or not fixture_filename:
        pytest.skip("E2E fixture env vars E2E_GMAIL_MESSAGE_ID / E2E_GMAIL_FILENAME not set")

    raw = gmail_mod.dispatch_gmail(
        "baker_gmail_attachment_read",
        {"message_id": fixture_message_id, "filename": fixture_filename},
    )
    result = json.loads(raw)

    assert "error" not in result, f"E2E call returned error: {result}"
    assert result["filename"] == fixture_filename
    assert result["size"] > 0
    assert result["match_count"] >= 1
    # PDF/DOCX/etc. should extract text; raw bytes path also valid.
    # Skip text non-empty assertion — depends on fixture file content.
```

**2d. Update the file docstring** (lines 1-23) to reflect the new test layout: "12 cases (10 adapted from READ_1 + 2 new for duplicate-filename handling) + 1 gated E2E test."

### Key constraints
- The E2E test MUST be `skipif`-gated on `TEST_GMAIL_LIVE=1`. CI must continue to pass without setting the var. b3 manually runs the E2E once locally pre-merge with the env var set.
- Fixture selection: pick a recent PDF attachment from baker's documents table. Set `E2E_GMAIL_MESSAGE_ID` + `E2E_GMAIL_FILENAME` in b3's local shell before running the gated test. The brief does NOT hardcode the message_id — it could be deleted.
- All 12 mocked cases MUST still pass under standard `pytest tests/test_gmail_attachment_read.py -v` (no env vars set, E2E auto-skipped).

### Verification

Standard mocked run (must pass green in CI):
```bash
pytest tests/test_gmail_attachment_read.py -v
# expected: 12 passed, 1 skipped (E2E)
```

Local E2E run pre-merge (b3 only; document in ship report):
```bash
# 1. Pick fixture from production data:
psql "$DATABASE_URL" -c "SELECT source_path FROM documents WHERE source_path LIKE 'email:%%/%%.pdf' ORDER BY ingested_at DESC LIMIT 1;"
# Output looks like: email:19e2c1b1e2bdd4c0/Schadensblatt-Top4.pdf

# 2. Extract message_id + filename and set env:
export E2E_GMAIL_MESSAGE_ID=19e2c1b1e2bdd4c0  # the part before /
export E2E_GMAIL_FILENAME=Schadensblatt-Top4.pdf  # the part after /
export TEST_GMAIL_LIVE=1

# 3. Confirm Baker Gmail OAuth env is local (b3 should already have these from
#    its bm-b3 shell, mirrored from Render via 1Password):
[ -n "$BAKER_GMAIL_CLIENT_ID" ] && [ -n "$BAKER_GMAIL_CLIENT_SECRET" ] && [ -n "$BAKER_GMAIL_REFRESH_TOKEN" ] && echo "creds present" || echo "MISSING"

# 4. Run the E2E test:
pytest tests/test_gmail_attachment_read.py::test_e2e_real_gmail_attachment_read -v
# expected: 1 passed
```

If creds are missing locally, the b3 ship report MUST note that the E2E test was skipped + why, and AH1 (lead) will run it from the lead shell post-merge as the gate-clear step. Better: b3 obtains creds and runs it pre-merge.

---

## Files Modified
- `tools/gmail.py` — `inputSchema` swap + `_attachment_read()` rewrite (~80 LOC delta)
- `tests/test_gmail_attachment_read.py` — adapt 10 cases + add 2 mocked + add 1 gated E2E (~150 LOC delta)

## Files NOT to Touch
- `scripts/extract_gmail.py` — poll-time path; works; out of scope
- `baker_mcp/baker_mcp_server.py` — name-based registration; no change needed
- Any other tool in `tools/` — independent

## Quality Checkpoints

After implementation, before opening PR:

1. `python3 -c "import py_compile; py_compile.compile('tools/gmail.py', doraise=True)"` returns clean.
2. `pytest tests/test_gmail_attachment_read.py -v` shows 12 passed, 1 skipped (E2E).
3. `python3 -c "from baker_mcp.baker_mcp_server import GMAIL_TOOL_NAMES; print(sorted(GMAIL_TOOL_NAMES))"` returns `['baker_gmail_attachment_read']`.
4. Defensive-import path (`baker_mcp/baker_mcp_server.py:975-983`) still loads — manually import the module after the change.
5. E2E test runs green locally with `TEST_GMAIL_LIVE=1` + fixture env vars + Gmail OAuth creds present. If b3 cannot run it locally, document this in the ship report so AH1 can run it post-merge as the gate-clear step.
6. Tool `inputSchema` validates: `message_id` + `filename` are required; `attachment_index` is optional integer ≥ 1 with default 1; `include_bytes` optional boolean default false.
7. `match_count` and `attachment_index` fields present in every non-error response (informational — agents can use them to detect duplicate-filename situations).

## Verification SQL

Confirm the fixture for the E2E test still exists in baker's documents table (before merge):
```sql
SELECT id, source_path, filename, ingested_at
FROM documents
WHERE source_path LIKE 'email:%%/%%.pdf'
ORDER BY ingested_at DESC
LIMIT 5;
```

Pick the top row, extract the substring between `email:` and `/` as the message_id, and the substring after `/` as the filename. These are the E2E fixture values. Confirm the message still exists in Gmail by running the gated E2E test against them.

Post-deploy capability sanity check (AH1 runs from lead shell once PR merges + Render deploy is live):
```bash
# Call the MCP tool via baker-master directly:
curl -sS -X POST "https://baker-master.onrender.com/mcp?key=$BAKER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_gmail_attachment_read","arguments":{"message_id":"<FIXTURE_MESSAGE_ID>","filename":"<FIXTURE_FILENAME>"}}}'
# expected: result.content[0].text JSON contains "text_extracted": true, no "error" field
```

## Anti-pattern guard

Direct reference to `tasks/lessons.md` line 211 (build_eval_seed.py mocked-tests-shipped-broken). Same pattern bit READ_1. The gated E2E test in this brief is the structural fix — every future Gmail-surface change MUST exercise this E2E test before claiming green.

## Ship report contract

When b3 ships:
1. Open PR against `main` with title `GMAIL_ATTACHMENT_READ_2: filename-based API + real-Gmail E2E coverage`.
2. Ship report goes to `briefs/_reports/B3_gmail_attachment_read_2_20260525.md`.
3. Bus-post to `lead` with topic `ship/gmail-attachment-read-2`. Include: PR #, mocked-test count + result, E2E test status (ran locally / skipped + why), fixture message_id used.
4. AH1 (lead) gates → architect → security-review → merge → confirm capability live with a curl against the deployed tool.
5. Once capability live, AH1 buses hag-desk so they know on-demand attachment-read is restored ahead of the Tuesday filing.
