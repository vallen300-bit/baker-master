---
brief_id: GMAIL_ATTACHMENT_VISIBILITY_V2_1
authored_by: lead (AH1)
authored_at: 2026-05-25
director_ratified: 2026-05-25 (chat — "go" after V1 deployed + backfill observation surfaced new silent-skip paths missed by V1)
target: b4
reply_target: lead (AH1)
expected_time: ~30-45 min
complexity: Low
type: visibility-only backend patch (no behavior change) + 1 SQL verification
target_repo: baker-master (single repo)
matter_slug: baker-internal
extends: GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 (V1 merged PR #259 11:00:44Z, visibility on FAILURE paths; V2 adds visibility on SKIP paths)
peer_brief: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1 (separate defect; queued after V2 ships)
followup_brief: GMAIL_POLLING_FIX_1 (sized from V2's observation window — Hagenauer-class emails should either fire WARNs or fire SKIP INFOs after V2 ships)
---

# BRIEF: GMAIL_ATTACHMENT_VISIBILITY_V2_1 — instrument the SKIP paths in extract_attachments_text + fix silent-swallow in backfill_missed_attachments.py + verify Hagenauer-class email handling

## Context

### Surface contract: N/A — pure backend log-level + 1 SQL verification. No dashboard, modal, button, anchor, frontend route, or any user-clickable surface touched.

**V1 deployed cleanly, but the observation window revealed a new silent-skip class.**

After PR #259 (`GMAIL_ATTACHMENT_VISIBILITY_PATCH_1`) shipped + deployed 2026-05-25 11:00:44Z, lead triggered a 9-day backfill via `POST /api/emails/backfill-attachments?days=9` (background task in `outputs/dashboard.py:1003-1021`). Result:

- **692 emails checked across 9 days**
- **310 existing email-prefix docs**
- **Only 1 "missing" attachment identified, 0 stored**
- **ZERO `err_type=` WARNs surfaced.** Zero `sentinel.gmail` logs. Zero patched-except-block fires.

This is wildly inconsistent with b4's GMAIL_POLLING_DIAGNOSTIC_1 §2c which named 53 counterparty emails since 2026-05-17 with no `documents` row. Lead's spot-check confirmed the inconsistency:

```sql
SELECT source_path, ingested_at FROM documents WHERE source_path LIKE 'email:19e4aefec5c46b97%';
-- (0 rows) — Hagenauer "Investigation reports : water damage" 2026-05-21 with 2 attachments per Gmail API

SELECT source_path, ingested_at FROM documents WHERE source_path LIKE 'email:19e54aae0d0caf0c%';
-- (0 rows) — Edita "Recharge costs hagenur case" 2026-05-23 with 1 .xlsx per Gmail API
```

Lead also verified via `baker_gmail_read_message` MCP that BOTH emails return real attachment metadata + `baker_gmail_attachment_read` successfully extracted the Hagenauer PDF (16,610 chars). So `_collect_attachment_parts` works on these emails when called from the on-demand MCP path. But the backfill script ran across the same email and reported it as "not missing."

**Two silent-skip classes V1 didn't cover:**

1. **`extract_attachments_text` decision tree silently skips at 4 sites BEFORE reaching any except block** — `_collect_attachment_parts` returns empty (line 631), unsupported extension (line 641), oversize (line 647), missing attachmentId + no inline data (line 651-664 None-path), Gmail returns empty data (line 671-672 None-path). Each is a legitimate skip but invisible in logs. We can't distinguish "no attachments to process" from "attachments dropped silently."

2. **`scripts/backfill_missed_attachments.py:87-88` has the SAME silent-swallow anti-pattern V1 fixed in extract_gmail.py.** The line is:
   ```python
   except Exception as e:
       logger.debug(f"Failed to check {mid}: {e}")
   ```
   Production logger at INFO → debug invisible. If 691 of 692 emails threw an exception during `service.users().messages().get()` or `_collect_attachment_parts(payload)` per-message, they're silently skipped from the "missing" count. That explains the "1 missing across 692 emails" result if the script is actually crashing on most emails. The script even has `import logging` (line 9) and a `logger = logging.getLogger("backfill_attachments")` (line 18) — but uses `.debug()` so production loses everything.

This brief installs full visibility on BOTH paths in one ship, then re-runs the backfill to verify the Hagenauer-class emails surface in logs as either FAILED (with `err_type=`) or SKIPPED (with the new INFO logs naming the skip class).

**Anchor:**
- V1 brief: `briefs/BRIEF_GMAIL_ATTACHMENT_VISIBILITY_PATCH_1.md` (PR #259, squash 45ba6c7).
- B4 diagnostic: `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md` §2c (53 counterparty emails with no doc).
- Backfill endpoint: `outputs/dashboard.py:1003-1021` (POST `/api/emails/backfill-attachments?days=N`, `X-Baker-Key` auth, background task).
- Same anti-pattern Lesson: `tasks/lessons.md` §"Sequential pollers blocked by upstream failure" + §"Missing import / `JSONResponse`" silent-swallow class.

## Estimated time: ~30-45 min
## Complexity: Low
## Prerequisites
- Read access to `scripts/extract_gmail.py`, `scripts/backfill_missed_attachments.py`.
- Local pytest run capability.
- Branch from `main` HEAD or newer (post PR #259 merge).
- Lead handles the backfill re-trigger + log observation post-merge (NOT b4).

---

## Fix 1 — Add 4 INFO logs to `extract_attachments_text` skip paths (15 min)

### Problem
4 silent skip sites in `extract_attachments_text` mask the difference between "no attachments to process" and "attachments dropped." V1 added WARNs on except paths but skip paths still don't log. Without skip-class visibility, we can't tell if the document-write blackout is due to no attachments arriving or attachments being silently filtered.

### Current state (verified by lead 2026-05-25 via Read tool, post-V1 merge)

| Line | Code path | Current behavior |
|---|---|---|
| 631-632 | `_collect_attachment_parts(payload)` returns empty | early `return results` (empty list). No log. |
| 636-637 | part has empty filename | `continue` (skip part). No log. |
| 641-642 | extension not in `_ATTACHMENT_EXTENSIONS` | `continue`. No log. |
| 647-648 | size > `_MAX_ATTACHMENT_SIZE` | `continue`. No log. |
| 651-664 | inline data path: `if data:` False (no inline bytes) | implicit `continue` via no `if text` branch. No log. |
| 671-672 | API download `if data:` False (Gmail returned empty bytes) | implicit fall-through, no append. No log. |

### Implementation

Edit `scripts/extract_gmail.py`:

**Site 1a (line 631-632) — `_collect_attachment_parts` returns empty:**

Find:
```python
    attachment_parts = _collect_attachment_parts(payload)
    if not attachment_parts:
        return results
```

Replace with:
```python
    attachment_parts = _collect_attachment_parts(payload)
    if not attachment_parts:
        logging.getLogger("sentinel.gmail").info(
            f"extract_attachments_text SKIP mid={message_id} reason=no_attachment_parts payload_keys={list(payload.keys())[:5]}"
        )
        return results
```

**Site 1b (line 641-642) — unsupported extension:**

Find:
```python
        ext = Path(filename).suffix.lower()
        if ext not in _ATTACHMENT_EXTENSIONS:
            continue
```

Replace with:
```python
        ext = Path(filename).suffix.lower()
        if ext not in _ATTACHMENT_EXTENSIONS:
            logging.getLogger("sentinel.gmail").info(
                f"extract_attachments_text SKIP mid={message_id} file={filename} reason=unsupported_ext ext={ext!r}"
            )
            continue
```

**Site 1c (line 647-648) — oversize attachment:**

Find:
```python
        size = body.get("size", 0)
        if size > _MAX_ATTACHMENT_SIZE:
            continue
```

Replace with:
```python
        size = body.get("size", 0)
        if size > _MAX_ATTACHMENT_SIZE:
            logging.getLogger("sentinel.gmail").info(
                f"extract_attachments_text SKIP mid={message_id} file={filename} reason=oversize size={size} cap={_MAX_ATTACHMENT_SIZE}"
            )
            continue
```

**Site 1d (line 651-664) — inline data path no-data fall-through:**

Find:
```python
        attachment_id = body.get("attachmentId")
        if not attachment_id:
            # Inline small attachment — data might be in body directly
            data = body.get("data")
            if data:
                try:
                    file_bytes = base64.urlsafe_b64decode(data)
                    text = _extract_text_from_bytes(file_bytes, filename, ext)
                    if text:
                        results.append({"filename": filename, "text": text})
                except Exception as e:
                    logging.getLogger("sentinel.gmail").warning(
                        f"inline-attachment extract FAILED mid={message_id} file={filename} ext={ext} err_type={type(e).__name__} err={e}"
                    )
            continue
```

Replace with:
```python
        attachment_id = body.get("attachmentId")
        if not attachment_id:
            # Inline small attachment — data might be in body directly
            data = body.get("data")
            if not data:
                logging.getLogger("sentinel.gmail").info(
                    f"extract_attachments_text SKIP mid={message_id} file={filename} reason=inline_no_data"
                )
                continue
            try:
                file_bytes = base64.urlsafe_b64decode(data)
                text = _extract_text_from_bytes(file_bytes, filename, ext)
                if text:
                    results.append({"filename": filename, "text": text})
                else:
                    logging.getLogger("sentinel.gmail").info(
                        f"extract_attachments_text SKIP mid={message_id} file={filename} reason=inline_extractor_returned_none ext={ext}"
                    )
            except Exception as e:
                logging.getLogger("sentinel.gmail").warning(
                    f"inline-attachment extract FAILED mid={message_id} file={filename} ext={ext} err_type={type(e).__name__} err={e}"
                )
            continue
```

**Site 1e (line 671-680) — API download empty-data + extractor-returned-none:**

Find:
```python
        # Download attachment via Gmail API
        try:
            att = service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=attachment_id
            ).execute()
            data = att.get("data", "")
            if data:
                file_bytes = base64.urlsafe_b64decode(data)
                text = _extract_text_from_bytes(file_bytes, filename, ext)
                if text:
                    results.append({"filename": filename, "text": text})
        except Exception as e:
            logging.getLogger("sentinel.gmail").warning(
                f"gmail-attachment-download FAILED mid={message_id} file={filename} ext={ext} err_type={type(e).__name__} err={e}"
            )
```

Replace with:
```python
        # Download attachment via Gmail API
        try:
            att = service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=attachment_id
            ).execute()
            data = att.get("data", "")
            if not data:
                logging.getLogger("sentinel.gmail").info(
                    f"extract_attachments_text SKIP mid={message_id} file={filename} reason=gmail_returned_empty_data ext={ext}"
                )
                continue
            file_bytes = base64.urlsafe_b64decode(data)
            text = _extract_text_from_bytes(file_bytes, filename, ext)
            if text:
                results.append({"filename": filename, "text": text})
            else:
                logging.getLogger("sentinel.gmail").info(
                    f"extract_attachments_text SKIP mid={message_id} file={filename} reason=api_extractor_returned_none ext={ext}"
                )
        except Exception as e:
            logging.getLogger("sentinel.gmail").warning(
                f"gmail-attachment-download FAILED mid={message_id} file={filename} ext={ext} err_type={type(e).__name__} err={e}"
            )
```

### Key constraints
- DO NOT change control flow. Every `continue` / `return` stays as-is. Only ADD `.info()` calls before each silent skip.
- DO NOT log empty-filename skips (line 636-637). Empty filenames are body parts; logging them every email floods. Skip silently is correct for that case.
- DO NOT change the logger name (`sentinel.gmail`). Production log aggregation filters by that prefix.
- KEEP the existing 5 WARN calls from V1 untouched. This brief ADDS to coverage, doesn't modify V1.
- The `reason=<value>` token is the key field for diagnosing root cause. Keep the 6 reason values exactly: `no_attachment_parts`, `unsupported_ext`, `oversize`, `inline_no_data`, `inline_extractor_returned_none`, `gmail_returned_empty_data`, `api_extractor_returned_none`.

### Verification
```bash
grep -c '\.info(' scripts/extract_gmail.py
# Expected: 7 (was 1; +6 from this fix — sites 1a,1b,1c,1d_no_data,1d_extractor_none,1e_no_data,1e_extractor_none)

grep -c 'reason=' scripts/extract_gmail.py
# Expected: 6 (one per skip class)

grep -c 'extract_attachments_text SKIP' scripts/extract_gmail.py
# Expected: 6

python3 -c "import py_compile; py_compile.compile('scripts/extract_gmail.py', doraise=True)"
# Expected: clean
```

---

## Fix 2 — Convert `backfill_missed_attachments.py:87-88` silent debug to WARN with err_type (5 min)

### Problem
The backfill script (`scripts/backfill_missed_attachments.py`) has the SAME silent-swallow anti-pattern V1 fixed in `scripts/extract_gmail.py`. If the per-email Gmail fetch or `_collect_attachment_parts` raises, the script swallows it and treats the email as "not missing." This is why lead's 9-day backfill returned "1 missing across 692 emails" — the other 691 may have crashed silently.

### Current state — `scripts/backfill_missed_attachments.py:86-88`:

```python
        except Exception as e:
            logger.debug(f"Failed to check {mid}: {e}")
```

`logger = logging.getLogger("backfill_attachments")` at line 18; `logging.basicConfig(level=logging.INFO)` at line 17. So `.debug` is suppressed by the basicConfig INFO floor in this script — but `logger.debug` honors basicConfig level, so .debug never emits.

### Implementation

Edit `scripts/backfill_missed_attachments.py` line 87-88:

Find:
```python
        except Exception as e:
            logger.debug(f"Failed to check {mid}: {e}")
```

Replace with:
```python
        except Exception as e:
            logger.warning(f"backfill check FAILED mid={mid} err_type={type(e).__name__} err={e}")
```

### Key constraints
- DO NOT change script control flow. The except still allows the loop to continue to the next email (correct behavior — one bad email shouldn't block the backfill).
- DO NOT add an `import logging` line — already present at line 9.
- KEEP the existing `logger` variable name.

### Verification
```bash
grep -c '\.debug(' scripts/backfill_missed_attachments.py
# Expected: 0 (was 1; converted)

grep -c 'err_type=' scripts/backfill_missed_attachments.py
# Expected: 1

python3 -c "import py_compile; py_compile.compile('scripts/backfill_missed_attachments.py', doraise=True)"
# Expected: clean
```

---

## Fix 3 — Add unit test for one new SKIP path (5 min)

### Problem
We need a regression-proof test that at least one new SKIP INFO path fires. Most-likely-to-regress is `unsupported_ext` (it's the path test PDFs/Excels won't trigger; easy to silently re-suppress).

### Implementation

Append to existing `tests/test_extract_gmail_visibility.py` (created by V1):

```python
def test_extract_attachments_text_unsupported_ext_emits_info_skip(caplog):
    """When attachment has unsupported extension, INFO log must fire with reason=unsupported_ext."""
    from unittest.mock import MagicMock
    from scripts import extract_gmail

    # Build a message payload with one .xyz attachment (unsupported)
    message = {
        "id": "mid_unsupp",
        "payload": {
            "parts": [
                {
                    "filename": "presentation.xyz",
                    "mimeType": "application/octet-stream",
                    "body": {"size": 1000, "attachmentId": "ATT_X"},
                },
            ],
        },
    }
    service = MagicMock()

    with caplog.at_level(logging.INFO, logger="sentinel.gmail"):
        result = extract_gmail.extract_attachments_text(service, message)

    assert result == []
    matching = [
        r for r in caplog.records
        if r.name == "sentinel.gmail" and r.levelno == logging.INFO
        and "SKIP" in r.message and "reason=unsupported_ext" in r.message
        and "mid=mid_unsupp" in r.message and "presentation.xyz" in r.message
    ]
    assert len(matching) == 1, (
        f"Expected exactly 1 INFO SKIP with reason=unsupported_ext, got {len(matching)}. "
        f"All sentinel.gmail records: {[(r.levelname, r.message) for r in caplog.records if r.name == 'sentinel.gmail']}"
    )
```

### Key constraints
- Append to existing `tests/test_extract_gmail_visibility.py` — do NOT create new test file.
- Test name follows V1's pattern (`test_<function>_<condition>_<expected>`).
- Acceptance: this 1 test PASSES (3 total in the file post-V2 — V1's 2 + this 1).

### Verification
```bash
pytest tests/test_extract_gmail_visibility.py -v
# Expected: 3 passed
```

---

## Files Modified

- `scripts/extract_gmail.py` — ~25 LOC added (6 new `.info()` calls + 2 extractor-returned-none branches). Net ~25 line additions.
- `scripts/backfill_missed_attachments.py` — 1 line edit (debug→warning at line 87-88).
- `tests/test_extract_gmail_visibility.py` — 1 new test function appended.

## Do NOT Touch

- V1's 5 `.warning()` calls in `scripts/extract_gmail.py` — leave them as-is.
- `format_thread:447-453` (V1's added WARNING) — leave as-is.
- `_extract_text_from_bytes:711-728` (V1's WARNING + None return) — leave as-is. Note: line 722 already returns None when extractor returns falsy text — this is BEFORE the INFO logs we want at the CALLER. So the new INFO logs go in `extract_attachments_text` at the call sites, not inside `_extract_text_from_bytes` itself.
- `memory/store_back.py`, `tools/document_pipeline.py`, `tools/ingest/extractors.py`, `orchestrator/cost_monitor.py`, `triggers/email_trigger.py` — all out of scope per V1's Do-NOT list.
- `outputs/dashboard.py:1003-1021` (backfill endpoint) — leave as-is. Lead handles the re-trigger post-merge.
- `requirements.txt` — out of scope.
- The pre-existing `logger.debug(...)` calls anywhere else in the codebase — scope is `scripts/extract_gmail.py` + `scripts/backfill_missed_attachments.py` ONLY.

## Quality Checkpoints

1. `grep -c '\.info(' scripts/extract_gmail.py` → 7 (was 1 + 6 new).
2. `grep -c 'reason=' scripts/extract_gmail.py` → 6.
3. `grep -c 'extract_attachments_text SKIP' scripts/extract_gmail.py` → 6.
4. `grep -c '\.warning(' scripts/extract_gmail.py` → still 5 (V1's WARNs untouched).
5. `grep -c '\.debug(' scripts/extract_gmail.py` → still 0.
6. `grep -c '\.debug(' scripts/backfill_missed_attachments.py` → 0 (was 1; converted).
7. `grep -c 'err_type=' scripts/backfill_missed_attachments.py` → 1.
8. `python3 -c "import py_compile; py_compile.compile('scripts/extract_gmail.py', doraise=True)"` clean.
9. `python3 -c "import py_compile; py_compile.compile('scripts/backfill_missed_attachments.py', doraise=True)"` clean.
10. `pytest tests/test_extract_gmail_visibility.py -v` → 3 passed (V1's 2 + new 1).
11. `pytest tests/ -x` clean (no regressions in adjacent gmail/email/extract/poll tests).
12. `bash scripts/check_singletons.sh` clean.
13. Branch `b4/gmail-attachment-visibility-v2-1`. PR title: `GMAIL_ATTACHMENT_VISIBILITY_V2_1 — instrument skip paths + fix backfill silent-swallow`.
14. Ship report bus message to `lead` includes: PR number, commit SHA, **literal** pytest output, **literal** grep counts (warning=, info=, reason=, SKIP=, debug=).

## Verification SQL

N/A — visibility-only. Lead handles post-merge SQL verification by re-running the backfill + checking for SKIP/FAILED logs naming the actual reason for the Hagenauer-class blackout.

## Gate chain (after ship)

- Gate-1 architecture: lead (AH1) — light pass (~25 LOC backend).
- Gate-2 security: lead (AH1) — verify no secret bleed in INFO log lines (filenames + payload_keys — same exposure class as V1's WARNs, already-stored in email_messages).
- Gate-3 picker-architect: SKIP (no install / picker / harness change).
- Gate-4 code-reviewer 2nd-pass: SKIP per V1 standard (≤30 LOC backend-only, no auth/DB/concurrency surface).
- Gate-5 merge: lead (AH1).
- Post-merge: lead re-triggers `POST /api/emails/backfill-attachments?days=9` via `X-Baker-Key`, observes Render logs ~3 min for SKIP/FAILED log surface, then authors `GMAIL_POLLING_FIX_1` brief sized from the observed skip/fail distribution.

## Reply target

Post your ship report bus message to **lead (AH1)** with topic `ship/gmail-attachment-visibility-v2-1`. Include: PR number, commit SHA, **literal** pytest output for `test_extract_gmail_visibility.py`, **literal** grep counts (warning, info, reason, SKIP, debug).

If pre-flight surfaces a defect outside Fixes 1-3 scope, DO NOT scope-creep. Surface to lead with `blocker/<reason>` or `ambiguity/<topic>` bus topic.

## Director context

Director ratified this brief's authorization at 2026-05-25 ~11:40Z chat after lead surfaced the backfill observation result: "0 stored, 1 missing across 692 emails, ZERO err_type WARNs" — implying V1 missed the silent-skip paths. Ratification phrase: "go". Authority class: Tier A (lead-authored brief on an open operational defect, ~30 LOC scope, zero behavior change).

This brief is **strictly visibility-only.** It does NOT fix the underlying defect (whatever's blocking documents writes for `email:%` source paths). After V2 ships + observation cycle, lead authors `GMAIL_POLLING_FIX_1` sized from the distribution of SKIP reasons + WARN err_types that surface.

The cost-monitor circuit breaker remains a separate compounding defect — `CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1` (also lead-authored 2026-05-25, queued for b4 post this brief) addresses it.

## What NOT to do

- Do NOT change any control flow. Every `continue` / `return` stays as-is. Only ADD `.info()` calls before each silent skip.
- Do NOT log empty-filename skips (line 636-637). Empty filenames are body parts; logging them every email floods.
- Do NOT bulk-convert other `.debug(` calls in the codebase. Scope is `scripts/extract_gmail.py` + `scripts/backfill_missed_attachments.py` ONLY.
- Do NOT modify V1's existing 5 WARNs. They're correct; V2 adds new INFO coverage.
- Do NOT re-trigger the backfill yourself. Lead handles that post-merge from lead shell (has `X-Baker-Key` + log API access).
- Do NOT edit any reason string. The 6 reason values (`no_attachment_parts`, `unsupported_ext`, `oversize`, `inline_no_data`, `inline_extractor_returned_none`, `gmail_returned_empty_data`, `api_extractor_returned_none`) are the diagnostic keys.
- Do NOT skip the unit test "by inspection" — pytest output must appear literally in the ship report.
- Do NOT bypass git hooks (`--no-verify`).
- Do NOT touch `outputs/dashboard.py` backfill endpoint. Out of scope.
