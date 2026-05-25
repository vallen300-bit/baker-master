---
brief_id: GMAIL_ATTACHMENT_VISIBILITY_PATCH_1
authored_by: lead (AH1)
authored_at: 2026-05-25
director_ratified: 2026-05-25 (chat — "go" after lead surfaced the missing `import logging` finding on top of b4's diagnostic)
target: b4
reply_target: lead (AH1)
expected_time: ~20-30 min
complexity: Low
target_repo: baker-master (single repo)
matter_slug: baker-internal
extends: GMAIL_POLLING_DIAGNOSTIC_1 (b4's read-only diagnostic report `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md`)
followup_brief: GMAIL_POLLING_FIX_1 (NOT this brief — sized by lead after 1-2 poll cycles surface the real error class via the WARN logs this brief installs)
---

# BRIEF: GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 — surface the silently-swallowed error class blocking `documents` writes for `email:%` source paths

## Context

### Surface contract: N/A — pure backend log-level change in `scripts/extract_gmail.py` + 1 new pytest unit test file. No dashboard, modal, button, anchor, frontend route, Slack/email render, or any user-clickable surface touched.

**Defect:** `documents` rows with `source_path LIKE 'email:%'` have been silently failing since **2026-05-16 08:44:33Z** (9-day blackout, ongoing). Polling appears healthy (`email_messages` advances, watermarks tick every 5 min, Render shows zero errors), but attachment text never lands in `documents`. Counterparty mail reasoning has been blind for 9 days — 53 confirmed-attachment threads in the gap window with zero downstream extraction (EDF invoice, Brisengroup internal threads, Hagenauer evidence, Annaberg valuation proposal).

**b4 diagnosed** the proximate fault path in `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md` (commit `d3c23bf`, branch `b4/gmail-polling-diagnostic-1`): silent-swallow in `scripts/extract_gmail.py` — 4 `except` blocks emit `.debug()` (invisible at production INFO log level) + an outer `except Exception: pass` at `format_thread:449` that wholesale-eats everything else.

**Lead caught one more layer (CRITICAL):** `scripts/extract_gmail.py` references `logging.getLogger(...)` on lines 661, 678, 700, 704, 724 **but never imports the `logging` module.** Run `grep -n '^import logging\|^from logging' scripts/extract_gmail.py` — returns empty. Every one of those log calls raises `NameError: name 'logging' is not defined`. The `NameError` is then silently swallowed by `format_thread:449`'s wholesale `except`. So before 2026-05-16 the success path completed enough work (`store_document_full` + `queue_extraction` both ran before the NameError on the success-info log line), and after 2026-05-16 the same NameError cycle masks whatever new failure mode started raising in `_extract_text_from_bytes`.

Without `import logging`, b4's recommended debug→warning conversion accomplishes nothing — the WARN calls still NameError and still get silently swallowed.

This brief installs visibility ONLY. Zero behavior change. After it ships and 1-2 poll cycles fire (~10 min on prod), Render logs will name the actual exception class + filename. Lead then sizes a separate `GMAIL_POLLING_FIX_1` brief from real data.

**Director context:** `BRIEF_GMAIL_POLLING_DIAGNOSTIC_1` was deliberately read-only-no-edits because "polling code intersects multiple systems; naive one-spot fix can mask the real defect" (lead 2026-05-25 09:35Z dispatch reasoning). Same constraint applies here — visibility patch only, no functional change, no compounding-defect fix (e.g. the cost-monitor circuit breaker at €100/day; that's a separate brief).

Anchor lessons (`tasks/lessons.md` line 146): *"`JSONResponse` was used in 10+ endpoints across `dashboard.py` but never imported from `fastapi.responses`. The 'Save to Dossiers' button returned 500 (`name 'JSONResponse' is not defined`) on every click. Other endpoints using it were also silently broken."* — same exact anti-pattern.

## Estimated time: ~20-30 min
## Complexity: Low
## Prerequisites
- Read access to `scripts/extract_gmail.py`, `tests/test_gmail_attachment_read.py` (or `tests/test_gmail.py` if PR #258 has merged before pickup — confirm with `ls tests/test_gmail*.py`).
- Local pytest run capability.
- Branch from `main` HEAD or newer.

---

## Fix 1 — Add missing `import logging` (CRITICAL — pre-condition for Fixes 2-4)

### Problem
`scripts/extract_gmail.py` calls `logging.getLogger(...)` in 5 places but never imports the `logging` module. Every call raises `NameError`, swallowed by `format_thread:449`'s wholesale `except`. This is the root reason b4's recommended visibility fix would otherwise be a no-op.

### Current state
File header (lines 26-49) imports `argparse base64 json os re sys time` + selective `from` imports. No `import logging` anywhere. Verify before edit:

```bash
grep -n '^import logging\|^from logging' scripts/extract_gmail.py
# Expected: empty output (no matches)
```

### Implementation

Add ONE line to the stdlib import block — alphabetical position is between `json` (line 28) and `os` (line 29):

Edit `scripts/extract_gmail.py`:
```python
# After line 28 (`import json`), before line 29 (`import os`):
import logging
```

Final import block top-12 lines should read:
```python
import argparse
import base64
import json
import logging       # NEW
import os
import re
import sys
import time
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
```

### Key constraints
- DO NOT use `from logging import getLogger` — keeps the existing `logging.getLogger("sentinel.gmail")` call sites unchanged.
- DO NOT add a module-level `logger = logging.getLogger("sentinel.gmail")` convenience binding. The 5 existing call sites use `logging.getLogger("sentinel.gmail").<level>(...)` — leave them as-is; Fix 2 changes level, not pattern. Reduces diff churn and review surface.

### Verification
```bash
grep -c '^import logging$' scripts/extract_gmail.py
# Expected: 1

python3 -c "import py_compile; py_compile.compile('scripts/extract_gmail.py', doraise=True)"
# Expected: no output (clean)
```

---

## Fix 2 — Convert 4 silent `.debug(...)` calls to `.warning(...)` with structured `err_type`

### Problem
4 `except Exception as e:` blocks log only at `.debug` level. Render production logger filters at INFO → all 4 are invisible. Without surfaced WARNINGs we can't name which exception class is firing (pdfplumber drift? OAuth scope? content-hash dedup?).

### Current state — exact lines (verified by lead 2026-05-25 via Read tool)

| Line | Function | Current call |
|---|---|---|
| 660-663 | `extract_attachments_text` (inline-attachment path) | `logging.getLogger("sentinel.gmail").debug(f"Failed to extract inline attachment {filename}: {e}")` |
| 677-680 | `extract_attachments_text` (Gmail-API download path) | `logging.getLogger("sentinel.gmail").debug(f"Failed to download attachment {filename}: {e}")` |
| 703-706 | `extract_attachments_text` (storage path — already WARNING) | `logging.getLogger("sentinel.gmail").warning(f"Email attachment document storage failed (non-fatal): {e}")` |
| 723-725 | `_extract_text_from_bytes` (extractor crash) | `logging.getLogger("sentinel.gmail").debug(f"Text extraction failed for {filename}: {e}")` |

### Implementation

Edit `scripts/extract_gmail.py`:

**Site 1 (lines 660-663) — inline-attachment extract failure:**
```python
except Exception as e:
    logging.getLogger("sentinel.gmail").warning(
        f"inline-attachment extract FAILED mid={message_id} file={filename} ext={ext} err_type={type(e).__name__} err={e}"
    )
```

**Site 2 (lines 677-680) — Gmail-API attachment download failure:**
```python
except Exception as e:
    logging.getLogger("sentinel.gmail").warning(
        f"gmail-attachment-download FAILED mid={message_id} file={filename} ext={ext} err_type={type(e).__name__} err={e}"
    )
```

**Site 3 (lines 703-706) — storage-back failure (already WARNING — extend with structured err_type):**
```python
except Exception as e:
    logging.getLogger("sentinel.gmail").warning(
        f"email-attachment-storage FAILED mid={message_id} err_type={type(e).__name__} err={e}"
    )
```

**Site 4 (lines 723-725) — `_extract_text_from_bytes` extractor crash:**
```python
except Exception as e:
    logging.getLogger("sentinel.gmail").warning(
        f"_extract_text_from_bytes FAILED file={filename} ext={ext} err_type={type(e).__name__} err={e}"
    )
    return None
```

### Key constraints
- Preserve the existing `return None` at site 4 — that's the control-flow signal to upstream that extraction failed. Behavior unchanged.
- DO NOT change the logger name (`sentinel.gmail`). Production log aggregation filters by that prefix.
- DO NOT change exception variable name (`e`) — keeps the diff tight + readable.
- The `err_type={type(e).__name__}` token is the single most useful field for naming the root cause from Render logs (e.g. `err_type=PDFSyntaxError`, `err_type=HttpError`, `err_type=KeyError`). KEEP this token spelled exactly that way across all 4 sites so logs grep cleanly.
- DO NOT inline-format multi-line. One `.warning(...)` per site, one f-string. Trivial to grep.

### Verification
```bash
grep -c '\.warning(' scripts/extract_gmail.py
# Expected: 5 (was 1; +4 from .debug→.warning conversions)

grep -c '\.debug(' scripts/extract_gmail.py
# Expected: 0 (was 4; all converted)

grep -c 'err_type=' scripts/extract_gmail.py
# Expected: 5 (4 converted sites + 1 in Fix 3)
```

---

## Fix 3 — Convert wholesale `except Exception: pass` at `format_thread:449` to a logged WARNING

### Problem
`format_thread` (lines 442-450) wraps the entire `extract_attachments_text` call in a bare `except Exception: pass`. This catches and silently discards EVERY error type — including the `NameError` chain Fixes 1-2 are designed to surface, AND any new failure class that emerges post-Brief-B. Wholesale silent-swallow is the meta-anti-pattern this brief is designed to retire.

### Current state — `scripts/extract_gmail.py:442-450` (verified by lead 2026-05-25 via Read tool):

```python
    if _gmail_service:
        for msg in messages:
            try:
                attachments = extract_attachments_text(_gmail_service, msg)
                for att in attachments:
                    attachment_blocks.append(
                        f"--- Attachment: {att['filename']} ---\n{att['text']}"
                    )
            except Exception:
                pass
```

### Implementation

Edit `scripts/extract_gmail.py` lines 442-450:

```python
    if _gmail_service:
        for msg in messages:
            try:
                attachments = extract_attachments_text(_gmail_service, msg)
                for att in attachments:
                    attachment_blocks.append(
                        f"--- Attachment: {att['filename']} ---\n{att['text']}"
                    )
            except Exception as _ae:
                logging.getLogger("sentinel.gmail").warning(
                    f"format_thread: extract_attachments_text raised mid={msg.get('id','?')} err_type={type(_ae).__name__} err={_ae}"
                )
```

### Key constraints
- Use distinct exception variable name `_ae` (not `e`) — avoids shadowing the per-attachment loop variable in `extract_attachments_text`. The leading underscore signals "logged-and-discarded" intent to future readers.
- DO NOT `raise` after logging. This catch is intentionally non-fatal at the thread level — losing one thread's attachments must not block the whole poll cycle (per Lesson #10 anti-pattern "Sequential pollers blocked by upstream failure"). Visibility ≠ propagation.
- DO NOT change the loop structure. We're swapping the except body only.
- KEEP `msg.get('id', '?')` — defensive against malformed Gmail responses where `id` field could be absent.

### Verification
```bash
grep -n 'except Exception:' scripts/extract_gmail.py
# Expected: no matches at line 449 (was bare-pass; now `except Exception as _ae:`)

grep -n 'format_thread: extract_attachments_text raised' scripts/extract_gmail.py
# Expected: 1 match (line ~450)

python3 -c "import py_compile; py_compile.compile('scripts/extract_gmail.py', doraise=True)"
# Expected: clean
```

---

## Fix 4 — Add 1 unit test asserting a WARNING fires when `_extract_text_from_bytes` raises

### Problem
We need a regression-proof test that the WARN-on-failure path actually emits. Without it, a future refactor could re-introduce the silent-swallow (most likely failure mode: someone "cleans up" the warning by routing through a custom helper that quietly swallows).

### Current state
`tests/test_gmail_attachment_read.py` exists (will become `tests/test_gmail.py` after PR #258 squash-merge — confirm via `ls tests/test_gmail*.py` at brief start). Existing tests cover the `tools/gmail.py` MCP tool surface, NOT the `scripts/extract_gmail.py` `extract_attachments_text` function. Net-new test surface — place in a new file to avoid coupling to PR #258's rename.

### Implementation

Create new file `tests/test_extract_gmail_visibility.py`:

```python
"""Visibility-patch regression test for scripts/extract_gmail.py.

Asserts that when _extract_text_from_bytes raises, a WARNING log line
is emitted carrying `err_type=` so production logs can name the actual
exception class from a single grep.

Anchor: BRIEF_GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 (Director-ratified 2026-05-25).
"""
from __future__ import annotations

import base64
import logging
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _fake_gmail_part_inline():
    """A Gmail attachment part where data is inline (not behind attachmentId)."""
    return {
        "filename": "test.pdf",
        "body": {
            "data": base64.urlsafe_b64encode(b"%PDF-1.4 fake-bytes").decode(),
            "size": 100,
        },
    }


def test_extract_text_from_bytes_failure_emits_warning_with_err_type(caplog):
    """When the extractor raises, _extract_text_from_bytes must log WARNING with err_type=."""
    from scripts import extract_gmail

    with patch("tools.ingest.extractors.extract", side_effect=ValueError("boom-test")):
        with caplog.at_level(logging.WARNING, logger="sentinel.gmail"):
            result = extract_gmail._extract_text_from_bytes(
                file_bytes=b"%PDF-1.4 fake-bytes",
                filename="test.pdf",
                ext=".pdf",
            )

    assert result is None, "_extract_text_from_bytes must return None on extractor failure"
    matching = [
        r for r in caplog.records
        if r.name == "sentinel.gmail" and r.levelno == logging.WARNING
        and "err_type=ValueError" in r.message
        and "_extract_text_from_bytes FAILED" in r.message
    ]
    assert len(matching) == 1, (
        f"Expected exactly 1 WARNING with err_type=ValueError, got {len(matching)}. "
        f"All sentinel.gmail records: {[(r.levelname, r.message) for r in caplog.records if r.name == 'sentinel.gmail']}"
    )


def test_format_thread_swallow_emits_warning_with_err_type(caplog, _fake_gmail_part_inline):
    """format_thread's wholesale except block must log WARNING with err_type= when called downstream raises."""
    from scripts import extract_gmail

    # Force the per-thread service binding to a non-None value so the attachment path runs.
    extract_gmail._gmail_service = MagicMock()
    # Force extract_attachments_text to raise.
    with patch.object(extract_gmail, "extract_attachments_text", side_effect=RuntimeError("boom-thread")):
        thread_data = {"id": "thr_test", "messages": []}
        messages = [{
            "id": "mid_test",
            "payload": {
                "headers": [
                    {"name": "From", "value": "test@example.com"},
                    {"name": "Subject", "value": "Subject test"},
                    {"name": "Date", "value": "Mon, 25 May 2026 10:00:00 +0000"},
                ],
                "body": {"data": base64.urlsafe_b64encode(("x" * 200).encode()).decode()},
            },
        }]

        with caplog.at_level(logging.WARNING, logger="sentinel.gmail"):
            try:
                extract_gmail.format_thread(thread_data, messages)
            except Exception:
                # format_thread may legitimately return None or partial; we care only about the log.
                pass

    matching = [
        r for r in caplog.records
        if r.name == "sentinel.gmail" and r.levelno == logging.WARNING
        and "err_type=RuntimeError" in r.message
        and "format_thread: extract_attachments_text raised" in r.message
    ]
    assert len(matching) == 1, (
        f"Expected exactly 1 WARNING with err_type=RuntimeError for format_thread swallow, got {len(matching)}. "
        f"All sentinel.gmail records: {[(r.levelname, r.message) for r in caplog.records if r.name == 'sentinel.gmail']}"
    )
```

### Key constraints
- Use `pytest`'s built-in `caplog` fixture — no third-party logging-capture dep.
- `caplog.at_level(logging.WARNING, logger="sentinel.gmail")` scopes capture to the right logger; avoids cross-test interference.
- The second test (`test_format_thread_swallow_...`) needs a viable thread shape. If the minimal shape above doesn't reach the `if _gmail_service:` block (because of upstream short-circuit logic — e.g. messages list filtering, header parsing), b4 may need to extend the fixture. The acceptance is "WARNING was emitted from format_thread:449" not "format_thread returned a specific value." If the minimal shape can't reach the attachment path, MARK the test `@pytest.mark.skip(reason="format_thread requires deeper fixture — covered by Fix 1+2+3 grep verification")` and surface to lead in ship report — Test 1 alone is sufficient acceptance for Fix 4 (validates the WARN-on-extractor-crash path, which is the primary visibility win).
- DO NOT mock `logging` itself — mock the upstream raise and capture real log records.
- DO NOT add fixtures to a global `conftest.py` — keep the test self-contained.

### Verification
```bash
pytest tests/test_extract_gmail_visibility.py -v
# Expected: 1 or 2 PASSED (depending on whether test 2 needs the skip marker)
# Acceptable: 1 PASSED + 1 SKIPPED with a clear skip reason linking to Fix 4 Key Constraints
```

---

## Files Modified

- `scripts/extract_gmail.py` — 1 line added (Fix 1 `import logging`), 4 `.debug` calls converted to `.warning` (Fix 2), 1 bare-pass except converted to logged WARNING (Fix 3). Net ~7 line additions, ~5 line edits.
- `tests/test_extract_gmail_visibility.py` — new file (~80 LOC) with 1-2 pytest functions covering the WARN path.

## Do NOT Touch

- `memory/store_back.py` — out of scope. `store_document_full` may be a fix target later (Brief B option 3, content-hash dedup tweak), but this brief is visibility-only.
- `tools/document_pipeline.py` — out of scope (cost-breaker classify-blocked WARNs are a separate-defect peer brief).
- `tools/ingest/extractors.py` — out of scope. PDF extractor drift might be the underlying cause (Brief B option 1), but we don't pin/swap extractors in this brief.
- `orchestrator/cost_monitor.py` — out of scope. The `COST_HARD_STOP_EUR=100.0` breaker is compounding the visibility problem (not causal — first tripped 2026-05-21, gap began 2026-05-16) but is a separate peer brief.
- `triggers/email_trigger.py` — out of scope. The poll loop is healthy; the defect is downstream in attachment extraction.
- `requirements.txt` — out of scope. Brief B option 1 might pin `pdfminer.six` after we see the actual error class; this brief is visibility-first.
- Other `.debug(...)` calls in the codebase — scope is `scripts/extract_gmail.py` ONLY. Do not bulk-convert debug→warning anywhere else.
- `tests/test_gmail_attachment_read.py` / `tests/test_gmail.py` (the renamed file post-PR #258) — out of scope. New test goes in a new file (`test_extract_gmail_visibility.py`) to avoid coupling to PR #258's merge state.

## Quality Checkpoints

1. `import logging` present exactly once at file top, alphabetical position between `import json` and `import os`.
2. Zero `.debug(` calls remain in `scripts/extract_gmail.py` (grep should return 0).
3. Five `.warning(` calls present in `scripts/extract_gmail.py` (one pre-existing storage WARN + four converted from debug + the format_thread one = 5).
4. `err_type=` token appears 5 times (4 from converted sites + 1 in format_thread swallow).
5. `except Exception: pass` no longer present at `format_thread:449` (grep `'except Exception: pass'` should return zero matches in `scripts/extract_gmail.py`).
6. `python3 -c "import py_compile; py_compile.compile('scripts/extract_gmail.py', doraise=True)"` clean.
7. `pytest tests/test_extract_gmail_visibility.py -v` → 1+ PASSED (acceptable: 1 PASSED + 1 SKIPPED with documented reason per Fix 4 Key Constraints).
8. Full pytest suite `pytest tests/ -x` clean (no regressions in adjacent gmail / poll / extractor tests).
9. Singleton-pattern CI guard clean: `bash scripts/check_singletons.sh` exit 0.
10. Branch named `b4/gmail-attachment-visibility-patch-1`. PR title `GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 — surface silent-swallow in extract_gmail.py`. PR description references this brief id + b4's diagnostic report path.
11. Ship report (bus message to lead) includes: PR number, commit SHA, **literal** `pytest tests/test_extract_gmail_visibility.py -v` output, **literal** `grep -c '\.warning(' scripts/extract_gmail.py` output.
12. NO behavior change beyond log level. If b4 finds themselves editing `if`/`return`/`raise`/control flow logic, STOP and surface to lead — that's Brief B territory.

## Verification SQL

N/A — this brief makes no DB writes. The downstream signal that the brief succeeded (`documents` rows with `source_path LIKE 'email:%'` resuming) is Brief B's success criterion, not this brief's.

Post-deploy lead-side verification (NOT b4's responsibility) — for awareness:
```sql
-- Run ~10 min post-deploy to confirm WARN lines are surfacing in production logs
-- (grep Render logs for 'err_type=' from sentinel.gmail).
-- This brief PASSES if WARNs fire. It does NOT pass/fail on whether docs resume —
-- that's Brief B.
```

## Gate chain (after ship)

- Gate-1 architecture: lead (AH1) — light pass (5 line edits + 1 file added; architecture-trivial).
- Gate-2 security: lead (AH1) — verify no secret bleed in log lines (filenames + err messages can leak metadata; risk class same as existing `email_messages.full_body` already-stored data; nothing new exposed).
- Gate-3 picker-architect: SKIP (no install / picker / harness change).
- Gate-4 code-reviewer 2nd-pass: SKIP per existing AH1 standard for ≤30 LOC backend-only diffs with no auth/DB/concurrency surface.
- Gate-5 merge: lead (AH1).
- Post-merge: lead observes Render logs ~10 min post-deploy + drafts `GMAIL_POLLING_FIX_1` brief sized from the surfaced `err_type=`.

## Reply target

Post your ship report bus message to **lead (AH1)** with topic `ship/gmail-attachment-visibility-patch-1`. Include: PR number, commit SHA, **literal** pytest output for the new test file, **literal** grep counts (warning calls, debug calls, err_type tokens).

If you discover a defect surfacing in pre-flight that's NOT covered by Fixes 1-4 (e.g. additional silent-swallow sites in adjacent functions), DO NOT scope-creep. Surface to lead as a bus reply with `blocker/<reason>` or `ambiguity/<topic>` topic — lead writes a follow-up brief.

## Director context

Director ratified this brief's authorization at 2026-05-25 ~10:30Z chat after lead surfaced the missing-import finding b4's diagnostic missed. The ratification phrase: "go". Authority class: Tier A (lead-authored brief on an open operational defect, ≤30 LOC scope, zero behavior change).

This brief is **strictly visibility-only.** It does NOT fix the underlying defect (whatever's causing `_extract_text_from_bytes` to raise post-2026-05-16). That's `GMAIL_POLLING_FIX_1`, which lead authors AFTER this brief ships + 1-2 poll cycles emit the actual `err_type=` in Render logs.

The cost-monitor breaker at €100/day hard stop is a **compounding** defect (b4 §2e), NOT the cause of the gap. A separate brief `CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1` will diagnose the €92/day capability_runner spend that's driving the breaker daily.

## What NOT to do

- Do NOT change `_extract_text_from_bytes`'s `return None` on failure — that's the upstream control signal. Visibility ≠ propagation.
- Do NOT add a global `logger = logging.getLogger("sentinel.gmail")` module-level binding. Existing call sites use the verbose form; keep them as-is to minimize diff churn.
- Do NOT bulk-convert `.debug(` calls in any other file. Scope is `scripts/extract_gmail.py` ONLY.
- Do NOT delete or "clean up" the existing `# EMAIL-ATTACH-FIX-1` and `# SPECIALIST-UPGRADE-1B` provenance comments. They're audit trail.
- Do NOT modify `pdfplumber` / `pdfminer.six` / any extractor pinning. Brief B handles that after we see the error class.
- Do NOT re-mint Gmail OAuth credentials. Brief B option 2 handles that if `err_type=HttpError 403 Insufficient Permission` shows up post-deploy.
- Do NOT touch the cost-monitor circuit breaker. Separate peer brief.
- Do NOT skip the unit test "by inspection" — pytest output must appear literally in the ship report (Lesson #8: compile-clean ≠ done; "pass by inspection" → REQUEST_CHANGES).
- Do NOT bypass git hooks (`--no-verify`). The cascade-backprop check should not fire (no `_ops/agents/` changes). If it does, surface to lead — do not bypass.
- Do NOT commit the failing-side experiment scratch (e.g. local print-debugging). Commit is the 1+4+1 edits in scripts/extract_gmail.py + the new test file only.
