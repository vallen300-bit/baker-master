# BRIEF: WHATSAPP_API_SENDER_PROBE_1 — add sender column to /api/whatsapp/messages WHERE clause

## Context

Brisen Desk surfaced (2026-05-20) that a known live WhatsApp contact "Julia Kvashnina Stadnik" (chat at +41 79 672 00 83 = `41796720083@c.us`) sent Director 4 messages on 2026-05-18 19:01 UTC, but every `/api/whatsapp/messages` probe — phone substrings, name variants, Cyrillic forms, full chat_id — returned 0 results. Director worked around it by pasting transcript manually, but the pattern is generalizable: every future "pull WA with X" ask risks the same wall.

AH1 diagnostic via Brisen Lab raw_query confirmed the rows are in `whatsapp_messages` and were captured cleanly within 1 second of arrival. The capture path is fine.

The bug is in the **endpoint SQL**:

```python
# outputs/dashboard.py:1042-1054
WHERE (sender_name ILIKE %s OR chat_id ILIKE %s)
```

The endpoint probes `sender_name` and `chat_id` only. With WhatsApp's new LID encoding (rolled out by WAHA between Sep 2025 and May 2026), both columns now hold the LID string (`16462794231969@lid`) — neither contains the human-readable name nor the phone digits. The phone substring lives only in the `sender` column (`41796720083@c.us`), which the WHERE clause never touches.

Result: every phone-substring or human-name probe returns 0 even when the rows exist and are time-correct. The desk's first 14 of 16 probes hit this exact case.

Director-ratified 2026-05-20: "fire it" — AH1 dispatched the smallest fix (add `sender` to the WHERE).

### Surface contract: N/A — pure backend SQL fix in a single FastAPI endpoint + 1 new pytest. No UI, no frontend, no Slack, no email, no DB schema change, no migration, no env vars.

## Estimated time: ~10-15 builder-minutes
## Complexity: Low (1-line SQL + 1-line params + docstring/Query refresh + 1 test)
## Prerequisites
- None. Endpoint is stable — last touched per `outputs/dashboard.py` history; canonical media column already `media_dropbox_path` (referenced in existing docstring).
- `tests/test_whatsapp_pull_api.py` already exists with `_DEFAULT_COLS = ["id", "timestamp", "sender", "sender_name", "chat_id", "full_text", "has_media"]` (line 74) — the test fixture knows about the `sender` column.

## API version / deprecation / fallback
- Endpoint: `GET /api/whatsapp/messages`, mounted at `outputs/dashboard.py:1016` (verified by AH1 via Read). FastAPI route already gated by `Depends(verify_api_key)`. No vendor API involved; pure internal DB read.
- WAHA LID migration: between 2025-09-18 (historical row found by AH1 raw_query with old `@s.whatsapp.net` chat_id format) and 2026-05-18 (new LID rows), WAHA migrated chat_id encoding to `<digits>@lid`. No vendor announcement to act on; this PR adapts our endpoint reader to the new shape on the read side. Capture path needs no change.
- Fallback: parallel work (LID → human-name resolver) lives in a separate, longer-track brief. Not in scope here.

---

## Fix/Feature 1: probe sender column too

### Problem

Endpoint at `outputs/dashboard.py:1042-1054` ILIKEs only `sender_name` + `chat_id`. For LID-encoded rows (the new default), both fields hold the LID string. Phone-substring queries — the most common desk usage — return 0 even when the row exists with `sender = '41xxxxxxxxx@c.us'`. Confirmed live 2026-05-20 on `chat_id 41796720083` (4 rows present, all 16 probes returned 0).

### Current state — verified file:line refs (AH1 Read tool)

`outputs/dashboard.py:1016-1088` — `whatsapp_messages_endpoint(...)`:

```python
@app.get("/api/whatsapp/messages", tags=["whatsapp"], dependencies=[Depends(verify_api_key)])
async def whatsapp_messages_endpoint(
    contact: str = Query(..., min_length=1, description="Match on sender_name ILIKE or chat_id substring"),   # ← line 1018
    from_date: date = Query(..., alias="from", description="Inclusive lower bound (YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="Inclusive upper bound (YYYY-MM-DD)"),
    limit: int = Query(200, ge=1, le=1000),
    fmt: Literal["json", "md"] = Query("json", alias="format"),
):
    """Read-only WhatsApp message pull for desk consumption.

    Matches sender_name OR chat_id via ILIKE %contact%, timestamp inclusive    # ← line 1026 docstring (also stale)
    between `from` and `to` (end-of-day on `to`). Returns oldest-first.
    ...
    """
    ...
    cur.execute(
        """
        SELECT id, timestamp, sender, sender_name, chat_id, full_text,
               (media_dropbox_path IS NOT NULL) AS has_media
        FROM whatsapp_messages
        WHERE (sender_name ILIKE %s OR chat_id ILIKE %s)                       # ← line 1047 — THE BUG
          AND timestamp >= %s
          AND timestamp < %s::date + INTERVAL '1 day'
        ORDER BY timestamp ASC
        LIMIT %s
        """,
        (f"%{contact}%", f"%{contact}%", from_date, to_date, limit),           # ← line 1053
    )
```

Schema reference — `whatsapp_messages` table verified live by AH1 via `information_schema.columns`:
- `id`, `sender`, `sender_name`, `chat_id`, `full_text`, `timestamp` (timestamptz), `is_director`, `ingested_at`, `media_mimetype`, `media_dropbox_path`, `media_size_bytes`. No column rename, no schema change.

### Implementation — 4 surgical edits

**A. `outputs/dashboard.py:1018` — refresh `contact` Query description.**

```python
contact: str = Query(..., min_length=1, description="Match on sender, sender_name OR chat_id substring (ILIKE)"),
```

**B. `outputs/dashboard.py:1026-1027` — refresh docstring line.**

```python
"""Read-only WhatsApp message pull for desk consumption.

Matches sender, sender_name OR chat_id via ILIKE %contact%, timestamp inclusive
between `from` and `to` (end-of-day on `to`). Returns oldest-first.

WAHA migrated to LID-encoded chat_ids in early-mid 2026; sender_name + chat_id
now often hold `<digits>@lid` strings, so the phone substring only lives in
the `sender` column. Probing all three keeps phone-fragment queries surfacing
the rows. Human-name resolution for LID-only rows is out of scope here —
separate brief.

has_media derives from `media_dropbox_path IS NOT NULL` (the canonical
media-presence flag per `_ensure_whatsapp_messages_table`; the brief's
reference to `media_path` is stale).
"""
```

(Preserve existing `has_media` paragraph verbatim — it's still correct.)

**C. `outputs/dashboard.py:1047` — extend WHERE clause.**

```python
WHERE (sender ILIKE %s OR sender_name ILIKE %s OR chat_id ILIKE %s)
```

**D. `outputs/dashboard.py:1053` — pass `contact` a third time in params tuple.**

```python
(f"%{contact}%", f"%{contact}%", f"%{contact}%", from_date, to_date, limit),
```

The order of the three `%{contact}%` repeats must match the WHERE-clause column order (sender, sender_name, chat_id). All three are the same string anyway, so order doesn't change behavior — but the params slot count must equal placeholder count or psycopg2 raises.

### New test in `tests/test_whatsapp_pull_api.py`

Add one test next to the existing happy-path test (after `test_whatsapp_messages_happy_path_json` at line 113). The existing fixture pattern (`_DEFAULT_COLS` at line 74) already includes `sender` — extend it with a LID-shaped row + assert phone-substring query surfaces it.

```python
def test_whatsapp_messages_lid_row_surfaces_via_phone_substring(client_authed, monkeypatch):
    """LID-encoded row (post-2026 WAHA migration): sender_name and chat_id hold
    `<digits>@lid`, phone digits only in sender column. Phone-substring probe
    must still find it. Anchor: 2026-05-20 Brisen Desk diagnostic on Julia
    Kvashnina Stadnik (chat 41796720083) — endpoint was half-blind to LID rows."""
    from datetime import datetime, timezone
    lid_row = (
        "false_16462794231969@lid_3AA3613A1FBABBF17384",      # id
        datetime(2026, 5, 18, 19, 1, 4, tzinfo=timezone.utc),  # timestamp
        "41796720083@c.us",                                    # sender — phone HERE
        "16462794231969@lid",                                  # sender_name — LID
        "16462794231969@lid",                                  # chat_id — LID
        "Дима, привет!",                                       # full_text
        False,                                                 # has_media
    )
    # _patch_db is the helper this file uses to inject fake rows; pattern from
    # existing test_whatsapp_messages_happy_path_json. Verify the helper name
    # before adapting (it may be _install_fake_db or similar in this file).
    _patch_db_with_rows(monkeypatch, [lid_row])

    resp = client_authed.get(
        "/api/whatsapp/messages",
        params={"contact": "796720083", "from": "2026-05-18", "to": "2026-05-18"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["count"] == 1
    msg = body["messages"][0]
    assert msg["sender"] == "41796720083@c.us"
    assert msg["sender_name"] == "16462794231969@lid"
    assert msg["chat_id"] == "16462794231969@lid"
    assert msg["full_text"] == "Дима, привет!"
```

**Important:** the exact name of the DB-mock helper differs by codebase convention — `tests/test_whatsapp_pull_api.py` line 74 references `_DEFAULT_COLS` so there IS a helper pattern. B1 should read the file's existing test setup pattern (lines ~70-115 around the happy-path test) and reuse the same monkeypatch / fixture mechanism. The test ABOVE is the shape; B1 adapts the helper name to match the file's conventions.

### Key constraints

- **Do NOT touch the WAHA capture path.** Captures are fine. This PR fixes the read side only.
- **Do NOT add a normalised-phone column.** That was option (c) in the desk's recommendation set; we're explicitly picking option (b) — the smallest fix that closes the gap. A normalised-phone column would be useful but requires a migration + backfill + index; out of scope here, file separately if Director ratifies.
- **Do NOT change the response shape.** Endpoint already returns `sender`, `sender_name`, `chat_id` in the JSON; adding `sender` to the WHERE doesn't change what's returned per row.
- **Do NOT touch `from_date` / `to_date` semantics** — the time window is fine; the diagnostic already proved the time math works.
- **Singleton pattern unchanged** — `store = _get_store()` + `_put_conn` stays.
- **conn.rollback() in except** — already present at line 1060. Don't touch.

### Verification

1. **Literal pytest run:**
   ```
   pytest tests/test_whatsapp_pull_api.py -v
   ```
   All existing tests must still pass, plus the new `test_whatsapp_messages_lid_row_surfaces_via_phone_substring`. Paste literal stdout in ship report.

2. **py_compile clean:**
   ```
   python3.12 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True); print('compile OK')"
   ```

3. **Pre-merge live probe (AH1 will run post-merge):** hit the deployed endpoint with `contact=796720083&from=2026-05-17&to=2026-05-20` and assert count > 0 (should return 14+ rows: 4 from 2026-05-18 + 9+ from 2026-05-20 + 1 historical from Sep 2025 that's also visible via this fix).

---

## Files Modified

- `outputs/dashboard.py` — 4 edits (Query description line 1018, docstring lines 1026-1027, WHERE clause line 1047, params tuple line 1053).
- `tests/test_whatsapp_pull_api.py` — 1 new test inserted next to `test_whatsapp_messages_happy_path_json` (line 113).

## Do NOT Touch

- `whatsapp_messages` schema / migrations — no schema change.
- WAHA capture path (`triggers/waha_*.py`, `outputs/whatsapp_sender.py`, etc.) — capture is fine; LID rows ARE landing.
- `whatsapp_lid_map` (existing LID→phone resolver used by outbound sender). Read-side endpoint doesn't need it; phone substring on `sender` is sufficient.
- Other WhatsApp endpoints in `outputs/dashboard.py` (status, search, etc.) — only `/api/whatsapp/messages` is in scope.
- `tests/test_whatsapp_sender_lid.py` — that file covers OUTBOUND LID resolution; unrelated to this read-side fix.

## Quality Checkpoints

1. Literal `pytest tests/test_whatsapp_pull_api.py -v` output in PR description — no "by inspection".
2. New test name + status appear in the pytest output (proves it actually ran, not just got collected).
3. Existing 14 tests in the file still pass (the change is additive — adding a column to WHERE doesn't remove matches).
4. `bash scripts/check_singletons.sh` OK (no singleton touch — verify anyway per repo convention).
5. Pre-commit hook Parts 1-4 all clear (no migration edit, no subagent file add, no retired model ID, no `/env-vars` PUT — diff is bounded).
6. `py_compile` clean.
7. Diff size sanity: ≤10 LOC in dashboard.py + ≤30 LOC in test file. Larger means scope creep — push back.

## Anti-pattern checks (lessons.md applied proactively)

| Anti-pattern | Applied mitigation |
|---|---|
| Column name guessing | All 4 column refs (`sender`, `sender_name`, `chat_id`, `media_dropbox_path`) verified live by AH1 via `information_schema.columns` |
| Brief code snippet wrong signature | All snippets above are direct quotes / minimal edits of the actual endpoint at outputs/dashboard.py:1016-1088 (AH1 Read tool, not memory) |
| No rollback in except | Already at line 1060 — untouched |
| Unbounded query | Existing `LIMIT %s` preserved (line 1051, default 200, capped 1000 at Query level) |
| Duplicate endpoint | This brief modifies an existing endpoint; no new route. Verified by AH1 |
| Missing import | No new imports needed; everything used is already imported in dashboard.py |
| Render restart survival | Endpoint is stateless; no startup state to worry about |
| Cost impact | Zero — DB-only read; no API call added |
| Untracked briefs | This brief will be `git add`'ed + committed before dispatch |
| Secrets in brief | None — no creds, only the chat_id `41796720083@c.us` which is Director's contact (low sensitivity, already in vault people-table) |

## Branch / PR

- Branch: `b1/whatsapp-api-sender-probe-1`
- PR title: `fix(whatsapp): /api/whatsapp/messages probes sender column too (LID-row blindness)`
- Reply target on PR open: bus-post `lead` topic `ship/whatsapp-api-sender-probe-1`.

## Reporting

`dispatched_by: lead` — bus-post `lead` on PR open per brief-reply-to-sender rule (2026-05-17 ratification).

## Anchors

- Brisen Desk diagnostic — 2026-05-20 chat, paste-block "WAHA capture / name-mapping gap" listing 16 zero-return probes on `41796720083` / `Julia Kvashnina Stadnik`.
- Raw-query proof — AH1 via `mcp__baker__baker_raw_query` 2026-05-20: 4 rows at `sender='41796720083@c.us'`, `sender_name='16462794231969@lid'`, `chat_id='16462794231969@lid'`, timestamps 2026-05-18 19:01:04…19:01:55Z.
- Buggy WHERE clause — `outputs/dashboard.py:1047` (verified by AH1 Read).
- Schema confirmation — `whatsapp_messages` 11 columns, AH1 via `information_schema.columns` 2026-05-20.
- Director ratification — 2026-05-20 chat "fire it".
- Surface contract: pure backend; no clickable surface (auto-satisfied N/A line).
- Sister brief deferred — LID → human-name resolver (separate, longer track, file when Director ratifies the trade-off).
