---
brief: GMAIL_ATTACHMENT_READ_1
authored_by: deputy (AH2) — delegated by lead bus #907
target: b3
dispatched_by: deputy (Director-ratified b3/b4 deputy lane 2026-05-24)
canonical_authoring_anchor: bus #902 (deputy → lead Director-build-now priority bump) + bus #907 (lead → deputy delegation) + Director chat 2026-05-24 "use b3 and b4, I will reserve b1 and b2 for lead"
priority: HIGH (Director-ratified "build now, live during sessions" 2026-05-24)
estimated_complexity: Low (~2-3h)
supersedes: none
director_q_locks:
  - q1_include_bytes_default: false (text-only default; opt-in for bytes) — deputy recommendation, no redirect within 15min window = locked
  - q2_image_scope_v1: text-extractable types only (pdf/docx/xlsx/csv/txt/md/json); image support deferred to follow-up brief — deputy recommendation, no redirect within 15min window = locked
---

# BRIEF: GMAIL_ATTACHMENT_READ_1 — On-demand Gmail attachment read MCP tool

## Context

Baker agents (hag-desk first, all matter desks next) need to read specific email attachments **on-demand during a live session**. Today the backend extracts attachment text at poll-time (`scripts/extract_gmail.py:618 extract_attachments_text()`) and stores each attachment as a standalone document (`SPECIALIST-UPGRADE-1B` path) — searchable via `baker_search`. But there is **no MCP-surface tool** for an agent to fetch a NAMED attachment's text or bytes mid-session against a freshly-arrived or already-known message.

**Anchor:** Director chat 2026-05-24 "start building the capability to read attachments of emails now, live during sessions." Hag-desk capability gap bus #882 (Spanyi/Ofenheimer Schadensblatt markups + Bauer xlsx + Krakow court PDFs + KSV1870 release PDFs unreadable on-demand). Director-ratified (a)-then-(b) path bus #888.

This brief = phase (a). Phase (b) = label-triggered auto-ingest into ClaimsMax. Separate brief.

## Estimated time: ~2-3h
## Complexity: Low
## Prerequisites: Gmail OAuth credentials already provisioned (Render Secret File `/etc/secrets/gmail_credentials.json` + `gmail_token.json`); existing polling pipeline operational

---

## Fix/Feature 1: New MCP tool `baker_gmail_attachment_read`

### Problem

No on-demand Gmail attachment read tool exists in Baker's MCP surface (`baker_mcp/baker_mcp_server.py` TOOLS list). Agents can list attachment filenames via existing thread reads but cannot pull a specific attachment's content during a live session without waiting for the poll cycle to index it.

### Current State

- `scripts/extract_gmail.py:618` defines `extract_attachments_text(service, message: dict) -> List[Dict]` — bulk extractor invoked by polling pipeline. Iterates all attachment parts, downloads each, extracts text via `_extract_text_from_bytes()`. Side-effects: stores each as a doc (lines 682-705). Filters by `_ATTACHMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".json"}` and `_MAX_ATTACHMENT_SIZE = 10 MB`.
- `triggers/email_trigger.py:214` defines `_get_gmail_service()` — authenticates + builds Gmail API service. Used by poll loop; safe to reuse.
- `tools/ingest/extractors.py:29` defines `extract(filepath: Path) -> str` — generic extractor for pdf/docx/xlsx/csv/txt/md/json + images (jpg/jpeg/png/heic/webp via Claude Vision).
- `baker_mcp/baker_mcp_server.py` TOOLS list (line 243) + `_dispatch()` (line 1509) are the canonical tool-registration sites. External-API tool groups (ClaimsMax line 949, Grok line 962) use a separate-module + defensive-import pattern. This brief follows that pattern for `tools/gmail.py`.

### Implementation

#### Step 1.1 — Create `tools/gmail.py` (NEW file)

```python
"""Gmail MCP tool surface — on-demand attachment read.

Wraps the existing extract_gmail attachment pipeline as an MCP-callable tool.
Reuses _get_gmail_service from triggers.email_trigger (no new credential
surface). Uses _extract_text_from_bytes from scripts.extract_gmail for
extraction parity with poll-time path.

Anchor: BRIEF_GMAIL_ATTACHMENT_READ_1 — Director-ratified 2026-05-24
"start building now, live during sessions." Phase (a) of the (a)-then-(b)
plan (b = label-triggered auto-ingest, separate brief).
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
from typing import Any

from mcp.types import Tool  # type: ignore[import-not-found]

logger = logging.getLogger("baker.tools.gmail")


GMAIL_TOOLS: list[Tool] = [
    Tool(
        name="baker_gmail_attachment_read",
        description=(
            "Read a single Gmail attachment on-demand. Returns extracted text "
            "(for PDF/DOCX/XLSX/CSV/TXT/MD/JSON) plus optional base64-encoded "
            "raw bytes. Reuses the existing poll-time extraction pipeline + "
            "Gmail service singleton (no new credential surface). "
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
                "attachment_id": {
                    "type": "string",
                    "description": (
                        "Gmail attachment ID for the specific attachment. "
                        "Required when message has multiple attachments."
                    ),
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
            "required": ["message_id", "attachment_id"],
        },
    ),
]

GMAIL_TOOL_NAMES = frozenset(t.name for t in GMAIL_TOOLS)


def dispatch_gmail(name: str, args: dict) -> str:
    """Route gmail-namespace tool calls. Returns JSON string for MCP transport."""
    if name == "baker_gmail_attachment_read":
        return _attachment_read(args)
    return json.dumps({"error": f"unknown gmail tool: {name}"})


def _attachment_read(args: dict) -> str:
    message_id = args.get("message_id", "").strip()
    attachment_id = args.get("attachment_id", "").strip()
    include_bytes = bool(args.get("include_bytes", False))

    if not message_id or not attachment_id:
        return json.dumps({
            "error": "message_id and attachment_id are both required",
        })

    # Reuse poll-time Gmail service singleton — no new credential surface.
    try:
        from triggers.email_trigger import _get_gmail_service
        service = _get_gmail_service()
    except Exception as e:
        logger.error(f"Gmail service init failed: {e}")
        return json.dumps({"error": f"gmail service init failed: {e}"})

    # Fetch the message to get attachment metadata (filename + size).
    try:
        message = service.users().messages().get(
            userId="me", id=message_id, format="full",
        ).execute()
    except Exception as e:
        logger.warning(f"gmail message fetch failed (message_id={message_id}): {e}")
        return json.dumps({"error": f"message fetch failed: {e}"})

    # Locate the attachment part by attachment_id (recursive — handles
    # forwarded emails with nested attachments per EMAIL-ATTACH-FIX-1).
    from scripts.extract_gmail import (
        _collect_attachment_parts,
        _extract_text_from_bytes,
        _ATTACHMENT_EXTENSIONS,
        _MAX_ATTACHMENT_SIZE,
    )
    payload = message.get("payload", {})
    parts = _collect_attachment_parts(payload)
    target_part = None
    for part in parts:
        body = part.get("body", {})
        if body.get("attachmentId") == attachment_id:
            target_part = part
            break
    if target_part is None:
        return json.dumps({"error": f"attachment_id not found in message: {attachment_id}"})

    filename = target_part.get("filename", "")
    body = target_part.get("body", {})
    size = body.get("size", 0)

    # Size guard — mirror poll-time cap. Foot-gun: caller could request a
    # multi-hundred-MB attachment and OOM the worker.
    if size > _MAX_ATTACHMENT_SIZE:
        return json.dumps({
            "error": f"attachment too large: {size} bytes (cap {_MAX_ATTACHMENT_SIZE})",
            "filename": filename,
            "size": size,
        })

    # Download attachment bytes.
    try:
        att = service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id,
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

    # Extract text via existing pipeline. Empty text is non-fatal — may be
    # an image attachment (out of v1 scope) or extractor returned empty.
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
    }
    if include_bytes:
        result["bytes_base64"] = base64.standard_b64encode(file_bytes).decode("ascii")

    return json.dumps(result)
```

#### Step 1.2 — Wire into `baker_mcp/baker_mcp_server.py`

Add defensive-import block after the existing Grok block (around line 971 — mirror ClaimsMax + Grok pattern):

```python
# Gmail on-demand attachment read — defensive import mirroring ClaimsMax + Grok.
try:
    from tools.gmail import GMAIL_TOOLS, GMAIL_TOOL_NAMES, dispatch_gmail
    TOOLS.extend(GMAIL_TOOLS)
except Exception as _gmail_import_err:  # pragma: no cover — defensive import
    logger.warning("Gmail tools unavailable: %s", _gmail_import_err)
    GMAIL_TOOL_NAMES = frozenset()

    def dispatch_gmail(name: str, args: dict) -> str:  # type: ignore[no-redef]
        return f"Error: Gmail tools failed to load: {_gmail_import_err}"
```

Add dispatch route in `_dispatch()` after Grok (around line 2128 — mirror ClaimsMax + Grok pattern):

```python
    elif name in GMAIL_TOOL_NAMES:
        return dispatch_gmail(name, args)
```

### Key Constraints

- **Do NOT modify** `scripts/extract_gmail.py` — preserve poll-time bulk extractor unchanged. New tool inlines the per-attachment download + extraction using the helpers `_collect_attachment_parts` + `_extract_text_from_bytes` + `_ATTACHMENT_EXTENSIONS` + `_MAX_ATTACHMENT_SIZE` (all importable as-is).
- **Do NOT modify** `triggers/email_trigger.py` — reuse `_get_gmail_service()` import unchanged.
- **Do NOT modify** `tools/ingest/extractors.py` — used transitively via `_extract_text_from_bytes`.
- **Image attachments out of v1 scope** — `_ATTACHMENT_EXTENSIONS` excludes jpg/jpeg/png/heic/webp. If `include_bytes=true`, raw bytes returned; text stays empty. v1 deliberately matches poll-time scope; image support = follow-up brief (would route through Claude Vision in `tools/ingest/extractors.py:extract_image` — adds cost + latency).
- **Size cap 10 MB hardcoded** — mirrors `_MAX_ATTACHMENT_SIZE` from poll path. Caller of `include_bytes=true` may still get up to ~13.4 MB base64 payload; acceptable for MCP response envelope.
- **Auth surface unchanged** — reuses existing Gmail OAuth credentials (Render Secret File `/etc/secrets/gmail_credentials.json` + `gmail_token.json`). No new 1Password items. Per Lesson #70, do NOT introduce new vault-keyed secret reads in this brief.
- **No `dashboard.py` edits** — MCP endpoint already wired (line 752 `/mcp`); new tools auto-discovered via `TOOLS` list extension.
- **No timeout wrap** — sync tool; caller wraps in `asyncio.wait_for` if called from async context. (Per existing ClaimsMax/Grok pattern — no internal asyncio.)

### Verification

Literal pytest output required in PR description (no "pass by inspection"):

```bash
cd ~/bm-b3 && pytest tests/test_gmail_attachment_read.py -v
```

Plus syntax + singleton + smoke:

```bash
cd ~/bm-b3
python3 -c "import py_compile; py_compile.compile('tools/gmail.py', doraise=True); py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"
bash scripts/check_singletons.sh
python3 -c "from baker_mcp.baker_mcp_server import TOOLS, _dispatch; \
  names = {t.name for t in TOOLS}; \
  assert 'baker_gmail_attachment_read' in names, names; \
  print('OK: baker_gmail_attachment_read registered in TOOLS')"
```

---

## Fix/Feature 2: Test coverage `tests/test_gmail_attachment_read.py`

### Problem

New tool needs regression coverage for happy path + edge cases. Existing test patterns (`tests/test_grok_client.py:450`, etc.) use mock objects for external API calls.

### Implementation

Create `tests/test_gmail_attachment_read.py` covering at minimum:

| Case | Scenario | Expected |
|---|---|---|
| 1 | Happy path — small PDF attachment, text-only mode | `text` non-empty, `text_extracted=true`, `bytes_base64` absent |
| 2 | Happy path — include_bytes=true | `bytes_base64` present + decodes to original bytes; `text` present |
| 3 | Missing message_id | `error` field set |
| 4 | Missing attachment_id | `error` field set |
| 5 | attachment_id not found in message | `error` field "attachment_id not found" |
| 6 | Oversize attachment (size > 10 MB) | `error` field "attachment too large" |
| 7 | Unsupported extension (e.g. `.png` in v1) | `text=""`, `text_extracted=false`, no error (graceful) |
| 8 | Empty Gmail data response | `error` field "gmail returned empty" |
| 9 | Gmail API exception on message.get() | `error` field "message fetch failed" |
| 10 | Gmail API exception on attachments.get() | `error` field "download failed" |

Use `unittest.mock.MagicMock` to fake `service.users().messages()...` call chain. Mirror the test pattern in `tests/test_grok_client.py`.

### Key Constraints

- **No real Gmail API calls in tests** — all mocked. Tests run in CI without network.
- **No `conftest.py` modifications** — use local fixtures in the test file (matches existing pattern).
- **Cover the EMAIL-ATTACH-FIX-1 path** — at least one test with nested multipart parts (forwarded email scenario) — confirms `_collect_attachment_parts` recursion works through the new tool.

### Verification

```bash
cd ~/bm-b3 && pytest tests/test_gmail_attachment_read.py -v
```

Expected: all 10 cases PASS, literal output captured in PR description.

---

## Files Modified

- `tools/gmail.py` — (NEW) GMAIL_TOOLS + GMAIL_TOOL_NAMES + dispatch_gmail + _attachment_read
- `baker_mcp/baker_mcp_server.py` — (EDIT) +1 defensive-import block after line 971 (Grok); +1 elif branch in `_dispatch()` after line 2127
- `tests/test_gmail_attachment_read.py` — (NEW) 10-case coverage

## Do NOT Touch

- `scripts/extract_gmail.py` — poll-time bulk extractor stays unchanged. Imported as-is.
- `triggers/email_trigger.py` — `_get_gmail_service` reused without modification.
- `tools/ingest/extractors.py` — used transitively via `_extract_text_from_bytes`.
- `outputs/dashboard.py` — MCP endpoint already wired; tools auto-pick up.
- `requirements.txt` — no new deps. All needed packages (`google-api-python-client`, `pdfplumber`, `openpyxl`, `python-docx`) already in tree per poll pipeline.

## Quality Checkpoints

1. `pytest tests/test_gmail_attachment_read.py -v` — 10/10 PASS, literal output in PR body.
2. `python3 -c "from baker_mcp.baker_mcp_server import TOOLS; print(len(TOOLS))"` — count incremented by 1 vs main.
3. `bash scripts/check_singletons.sh` — clean.
4. `python3 -c "import py_compile; py_compile.compile('tools/gmail.py', doraise=True)"` — clean.
5. Post-deploy live smoke: from a live agent session (deputy or hag-desk picker), invoke `mcp__baker__baker_gmail_attachment_read` with a recent real message_id + attachment_id (deputy can supply test pair). Confirm extracted text matches expected document content.
6. Render deploy succeeded (check `https://baker-master.onrender.com/health` for 200).
7. Tool listed in `tools/list` MCP response — `curl -s -X POST -H "X-Baker-Key: $KEY" -H "Content-Type: application/json" "https://baker-master.onrender.com/mcp" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[] | select(.name=="baker_gmail_attachment_read")'` returns non-empty.

## Verification SQL

No DB writes in this brief — no SQL verification needed. (Poll-time extractor still writes to `documents` table via `SPECIALIST-UPGRADE-1B`; on-demand tool deliberately bypasses that store-side-effect to avoid double-indexing.)

## Out of scope (deferred to follow-up briefs)

1. Image attachment support (jpg/png/heic/webp) — would route via `tools/ingest/extractors.py:extract_image` Claude Vision path. Cost + latency analysis needed. Future brief `GMAIL_ATTACHMENT_READ_IMAGES_2`.
2. Phase (b) label-triggered auto-ingest into ClaimsMax — Director-ratified bus #888. Future brief `GMAIL_LABEL_AUTOINGEST_1`. ~6-10h.
3. Outlook / Graph API attachment read — Director dropped option (d) in #888 ("if M365 cutover firms up later"). Future brief if it lands.
4. Attachment list-helper tool (`baker_gmail_attachment_list(message_id)`) — current MCP picker thread reads already expose attachment metadata; not blocking. Future brief if multiple agents repeat the same list-then-read pattern.
5. Bulk attachment read across a thread — composition pattern; caller calls `baker_gmail_attachment_read` per attachment. No bulk tool in v1.

---

## OPEN DIRECTOR QUESTIONS (lock before dispatch)

**Q1 — `include_bytes` default behavior**

Two options:
- **(a)** Default `include_bytes=false`; caller opts in. Text-only response by default keeps MCP envelope small (typical PDF text ~50KB, base64 bytes can be 10MB+). My recommendation.
- **(b)** Default `include_bytes=true`; caller opts out. More information by default; bigger envelope.

**Recommendation: (a)** — keeps default response small for the common case (agent wants text content to reason over), bytes is opt-in for the rarer case (file dump, hash verify, visual diff). Matches the existing pattern in poll-time pipeline where text is the primary product + bytes go to the doc store separately.

**Q2 — Image attachment scope in v1**

Two options:
- **(a)** v1 text-only (matches `_ATTACHMENT_EXTENSIONS` from poll path: pdf/docx/xlsx/csv/txt/md/json). Images return `text=""` + `text_extracted=false`; bytes available via `include_bytes=true` only. Image extraction = separate brief `GMAIL_ATTACHMENT_READ_IMAGES_2`. My recommendation.
- **(b)** v1 includes images via Claude Vision (extends `_ATTACHMENT_EXTENSIONS` for this tool). Adds cost per call (~$0.01-0.03 per image via vision) + latency (~2-5s).

**Recommendation: (a)** — keeps v1 scope tight + matches Director's "narrow capability, then composition" pattern. Hag-desk's named attachment types (Schadensblatt PDF markups, Bauer xlsx, Krakow court PDFs, KSV1870 PDFs, redline drafts) are all in the text-extractable set. Images can wait for a separate brief with explicit cost ratification.

---

## Ship report routes to

`lead` via bus (topic: `ship/gmail-attachment-read-1`). Include:
- PR URL (single repo: `baker-master`)
- Literal pytest output for `tests/test_gmail_attachment_read.py -v`
- `bash scripts/check_singletons.sh` output
- Quality Checkpoint 5 (live smoke against a real message_id) result
- Tool-list curl output (Quality Checkpoint 7)

## Anchors

- Director ratification: 2026-05-24 chat "start building now, live during sessions" + (a)-then-(b) plan via bus #888
- Lead delegation: bus #907 (lead → deputy 2026-05-24)
- Hag-desk capability gap: bus #882 (hag-desk → deputy 2026-05-24)
- Deputy priority bump to lead: bus #902
- Lessons applied: anti-pattern "Slow external calls need timeouts" (caller responsibility documented), anti-pattern "Function name guessing" (all signatures verified inline)
