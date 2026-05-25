# BRIEF: SUBSTACK_NATE_PATCH_1 — fix 3 defects from retro-gate on PR #248

## Context

PR #248 (SUBSTACK_NATE_INGEST_1, merged 2026-05-23 13:53Z @ `eeca2e09`) shipped without Gate 2 (`/security-review`) or Gate 4 (`feature-dev:code-reviewer` 2nd-pass) firing — both were unchecked in the PR body despite the brief flagging them as required for a Gmail external-surface change. Deputy ran retro gate 2026-05-25 16:30Z and surfaced 3 real defects (2 HIGH + 1 MEDIUM). Trigger is live in production code but the post-merge backfill was never run, so HIGH #2 is unmaterialized and HIGH #1 has not yet been exercised on a real Nate post.

This brief patches all three in one B-code cycle so the backfill can run safely.

Retro-reviewer report: agent `a5a275f9476184b2b`. Bus thread: deputy → lead #1097 (`verdict/substack-nate-request-changes`).

## Estimated time: ~1h
## Complexity: Low
## Prerequisites: none — files are all on `main` post-merge

---

## Fix 1: Add 10s timeout on `fetch_full_message` Gmail call (HIGH)

### Problem
`triggers/substack_ingest.py:115` calls `svc.users().messages().get(...).execute()` with no timeout. The `googleapiclient` `execute()` blocks indefinitely on a hung TCP connection — minutes until OS-level TCP timeout fires. This call happens inside the synchronous email-polling loop in `triggers/email_trigger.py`, so a single hung Gmail response would stall ingest of ALL emails (not just Substack) until the OS kills the socket.

### Current State
`triggers/substack_ingest.py:95-123` — `fetch_full_message()`:
```python
return svc.users().messages().get(
    userId="me", id=gmail_message_id, format="full",
).execute()
```
No timeout. The shared `_gmail_service` handle is built once at startup in `scripts/extract_gmail.py:1127` with `build("gmail", "v1", credentials=creds)` — no `http=` arg.

### Implementation
Wrap the `.execute()` call in a `concurrent.futures.ThreadPoolExecutor` with a 10s hard timeout. Local fix in `substack_ingest.py` only — does NOT modify the shared `_gmail_service` (other callers of that handle are out of scope for this patch).

Replace the `try`/`except` body of `fetch_full_message` (lines 106-123) with:

```python
    try:
        from scripts import extract_gmail
        svc = getattr(extract_gmail, "_gmail_service", None)
        if svc is None:
            logger.warning(
                "substack_ingest.fetch_full_message: _gmail_service not set; "
                "cannot fetch msg %s", gmail_message_id,
            )
            return None
        request = svc.users().messages().get(
            userId="me", id=gmail_message_id, format="full",
        )
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(request.execute)
            try:
                return future.result(timeout=10)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "substack_ingest.fetch_full_message: 10s timeout for msg %s "
                    "(Gmail API hung); abandoning ingest for this message",
                    gmail_message_id,
                )
                _safe_report_failure("substack_ingest", "fetch_full_message timeout 10s")
                return None
    except Exception as e:
        logger.warning(
            "substack_ingest.fetch_full_message failed for %s: %s",
            gmail_message_id, e,
        )
        return None
```

### Key Constraints
- `concurrent.futures` is stdlib — no requirements.txt change.
- Do NOT modify `_gmail_service` itself or `scripts/extract_gmail.py` — out of scope.
- Do NOT wrap any OTHER `.execute()` calls in the repo — this patch is scoped to the substack path only.
- Existing outer `try/except` stays — defence in depth.

### Verification
- `tests/test_substack_ingest.py::test_fetch_full_message_returns_payload_when_service_set` must still PASS.
- Add ONE new test: `test_fetch_full_message_returns_none_on_timeout` — monkeypatch the request's `.execute` to `time.sleep(15)` (or raise `concurrent.futures.TimeoutError` from a stub executor) and assert `fetch_full_message()` returns `None` within ~11s.

---

## Fix 2: Add `MAX_PAGES` guard on backfill pagination (HIGH)

### Problem
`scripts/backfill_nate_substack.py:61-102` is `while True: ...; if not page_token: break`. No upper bound on pages. A `--days 3650` invocation against a mailbox with broad List-Id matches (or a Gmail bug returning duplicate page tokens) could loop for hours, make thousands of API calls, and write an unbounded number of files into `~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/`.

Backfill was halted by deputy bus #1097 before AH1 ran it — this fix unblocks the run.

### Current State
`scripts/backfill_nate_substack.py:58-102`:
```python
page_token = None
written = 0
seen = 0
while True:
    resp = svc.users().messages().list(
        userId="me", q=query, maxResults=100, pageToken=page_token,
    ).execute()
    for m in resp.get("messages", []) or []:
        ...
    page_token = resp.get("nextPageToken")
    if not page_token:
        break
```

### Implementation
Add a module-level `MAX_PAGES = 200` constant (allows ~20k messages at 100/page — well beyond any sane Nate-only corpus). Increment a `pages` counter inside the loop and break with a warning log if it exceeds.

Replace lines 58-102 (the `page_token = None` through `if not page_token: break` block) with:

```python
    MAX_PAGES = 200  # Safety cap: ~20k messages at 100/page; guards against runaway pagination
    page_token = None
    written = 0
    seen = 0
    pages = 0
    while True:
        pages += 1
        if pages > MAX_PAGES:
            logger.warning(
                "backfill_nate_substack: hit MAX_PAGES=%d guard; stopping early "
                "(seen=%d written=%d). If this is expected, raise MAX_PAGES.",
                MAX_PAGES, seen, written,
            )
            break
        resp = svc.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token,
        ).execute()
        for m in resp.get("messages", []) or []:
            seen += 1
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="full",
            ).execute()
            payload = full.get("payload", {}) or {}
            headers = payload.get("headers", []) or []

            sender = _header(headers, "From")
            subject = _header(headers, "Subject")
            received = full.get("internalDate")
            if received:
                received_dt = datetime.fromtimestamp(int(received) / 1000, tz=timezone.utc)
            else:
                received_dt = datetime.now(timezone.utc)

            if not is_substack_nate(headers, sender):
                continue
            if dry_run:
                logger.info("DRY %s | %s | %s", received_dt.date(), subject[:60], m["id"])
                continue

            out = substack_ingest_run(
                gmail_message_id=m["id"],
                headers=headers,
                sender_email=sender,
                subject=subject,
                received_date=received_dt,
                raw_payload=payload,
            )
            if out:
                written += 1
                logger.info("WROTE %s", out.name)
            else:
                logger.info("SKIP %s (already-ingested or no-html)", subject[:60])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
```

### Key Constraints
- Constant lives inside `run()` or at module scope — your call. Module scope is easier to test.
- Do NOT add a `--max-pages` CLI flag in this patch (scope creep). Leave the constant as the only override path.
- Existing behaviour preserved: when pagination terminates naturally via `not page_token`, the guard is never reached.

### Verification
- `python3 scripts/backfill_nate_substack.py --dry-run --days 30` runs to completion without error (post-fix).
- Add ONE new test in `tests/test_substack_ingest.py` (or a new `tests/test_backfill_nate_substack.py`): stub `svc.users().messages().list().execute()` to ALWAYS return `{"nextPageToken": "x", "messages": []}` and assert `run()` returns 0 (not infinite loop) within ~1s with a `MAX_PAGES` warning in caplog.

---

## Fix 3: Tighten `_LIST_ID_RE` to canonical Nate List-Id (MEDIUM)

### Problem
`triggers/substack_ingest.py:58`:
```python
_LIST_ID_RE = re.compile(r"natesnewsletter\.substack\.com", re.IGNORECASE)
```

This substring-matches `natesnewsletter.substack.com` ANYWHERE in the `List-Id` header. An adversary controlling any Substack publisher's `List-Id` value (e.g., a `List-Id: foo.substack.com <id> (mentions natesnewsletter.substack.com)`) would pass `is_substack_nate()` and get ingested as if they were Nate. Low real-world exploit probability but the gap is real.

### Current State
`triggers/substack_ingest.py:58, 88`:
```python
_LIST_ID_RE = re.compile(r"natesnewsletter\.substack\.com", re.IGNORECASE)
...
if h.get("name", "").lower() == "list-id" and _LIST_ID_RE.search(h.get("value", "")):
    return True
```

Canonical Nate List-Id per `tests/test_substack_ingest.py:37` fixture:
```
post.natesnewsletter.substack.com <a8b9c0d1.list-id.substack.com>
```

### Implementation
Tighten the regex to require the `post.` prefix and word boundaries. Replace line 58:

```python
# Canonical Nate List-Id format: "post.natesnewsletter.substack.com <id.list-id.substack.com>"
# Word boundaries prevent substring spoofing from third-party Substack publishers.
_LIST_ID_RE = re.compile(r"\bpost\.natesnewsletter\.substack\.com\b", re.IGNORECASE)
```

Leave line 88 (`if h.get("name", "").lower() == "list-id" and _LIST_ID_RE.search(...)`) unchanged — same call, tighter pattern.

The `_SENDER_FALLBACK_RE` at line 59 (`r"@.*natesnewsletter\.substack\.com"`) is anchored on `@.*` and is already harder to spoof — leave unchanged in this patch.

### Key Constraints
- Existing `test_is_substack_nate_matches_list_id` fixture string `"post.natesnewsletter.substack.com <a8b9c0d1.list-id.substack.com>"` MUST still match — verify post-edit.
- Do NOT widen this in the other direction (no anchoring to `^` or `$` — Substack sometimes wraps the value in angle brackets at different positions).

### Verification
- All existing 15 tests in `tests/test_substack_ingest.py` MUST still PASS unchanged.
- Add ONE new test: `test_is_substack_nate_rejects_substring_spoofing` — header `{"name": "List-Id", "value": "foo.substack.com <id> (re: natesnewsletter.substack.com)"}` returns `False`.

---

## Files Modified
- `triggers/substack_ingest.py` — Fix 1 (timeout) + Fix 3 (regex tighten)
- `scripts/backfill_nate_substack.py` — Fix 2 (MAX_PAGES guard)
- `tests/test_substack_ingest.py` — 3 new tests (one per fix)

## Do NOT Touch
- `scripts/extract_gmail.py` — shared `_gmail_service` handle is out of scope for this patch.
- `triggers/email_trigger.py` — the insertion site (line ~1022) is unchanged; the divert call signature is unchanged.
- `requirements.txt` — `concurrent.futures` is stdlib; `httplib2` is already a transitive dep.
- The existing 15 tests in `tests/test_substack_ingest.py` — they must continue to PASS unchanged.

## Quality Checkpoints
- **QC1** — `python3 -c "import py_compile; py_compile.compile('triggers/substack_ingest.py', doraise=True); py_compile.compile('scripts/backfill_nate_substack.py', doraise=True); print('SYNTAX OK')"` returns SYNTAX OK.
- **QC2** — `bash scripts/check_singletons.sh` clean.
- **QC3** — `python3 -m pytest tests/test_substack_ingest.py -v` shows **18 passed** (15 existing + 3 new), 0 failed, in literal pytest output. Paste output into ship report. No "by inspection."
- **QC4** — `python3 scripts/backfill_nate_substack.py --dry-run --days 7` runs to completion without traceback (proves Fix 2 doesn't break the happy path; --days 7 is enough to validate, full backfill is AH1's post-merge step).
- **QC5** — Grep verification: `grep -n "concurrent.futures" triggers/substack_ingest.py` finds the timeout wrapper. `grep -n "MAX_PAGES" scripts/backfill_nate_substack.py` finds the guard. `grep -n "\\\\bpost\\\\." triggers/substack_ingest.py` finds the tightened regex.

## Ship reply target

`dispatched_by: deputy` in the mailbox header → ship report goes back to **deputy (AH2)**. CC lead per `_ops/processes/b-code-dispatch-coordination.md` Rule 0.5.

After ship:
1. Deputy runs Gate-1 static + Gate-2 `/security-review` + Gate-4 `feature-dev:code-reviewer` 2nd-pass on the patch PR (Gmail external surface remains MEDIUM trigger class).
2. If all clear → Tier-A merge (deputy lane per Director ratification 2026-05-24).
3. Bus-post lead with merge confirm.
4. Lead runs the post-merge backfill from `~/bm-aihead1`: `python3 scripts/backfill_nate_substack.py --dry-run` then real run.
5. Deputy verifies first dated `.md` lands in `~/baker-vault/wiki/_ai-it/aid-t/external-substack/nate/` within 30 min of next Nate Gmail arrival (or within the backfill window).
6. Delete PINNED §D.
