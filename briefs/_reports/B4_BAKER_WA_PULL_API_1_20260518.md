---
brief_id: BAKER_WA_PULL_API_1
status: SHIPPED
shipped_at: 2026-05-18T11:05:00Z
shipped_by: b4
pr: https://github.com/vallen300-bit/baker-master/pull/218
commit: 712ca17
branch: b4/baker-wa-pull-api-1
dispatched_by: lead
brief_authored_by: AH2
trigger_class: MEDIUM
---

# B4 ship — BAKER_WA_PULL_API_1

PR: https://github.com/vallen300-bit/baker-master/pull/218
Commit: `712ca17` on `b4/baker-wa-pull-api-1`.

## Scope shipped

`GET /api/whatsapp/messages` added to `outputs/dashboard.py`. X-Baker-Key auth (reuses `Depends(verify_api_key)`). Required `contact` (ILIKE on `sender_name` OR `chat_id`), `from`, `to` (date range, inclusive — end-of-day on `to` via `%s::date + INTERVAL '1 day'`). Optional `limit` (1..1000, default 200) + `format=json|md`. JSON shape per brief; `format=md` returns `text/plain` markdown thread oldest-first via `_format_wa_md` helper.

## Schema drift (brief §92)

Brief specified `media_path IS NOT NULL` for `has_media`. The canonical column per `_ensure_whatsapp_messages_table` (`memory/store_back.py:1523`) is `media_dropbox_path` (WHATSAPP-MEDIA-DROPBOX-1 — alongside `media_mimetype` + `media_size_bytes`). No `media_path` column exists. Endpoint uses `media_dropbox_path IS NOT NULL` and a regression test (`test_whatsapp_messages_sql_uses_canonical_media_column`) locks the SQL.

## Acceptance criteria — verification

1. ✅ `GET /api/whatsapp/messages` registered with `tags=["whatsapp"]` + `Depends(verify_api_key)`
2. ✅ Required params enforced — 422 via FastAPI (tests #6-7)
3. ✅ `limit` clamped via `Query(200, ge=1, le=1000)` — test #5
4. ✅ `format` validated via `Literal["json","md"]` — test #8 (422 on `xml`)
5. ✅ Parameterised binds, LIMIT, `conn.rollback()` on exception — test #12
6. ✅ JSON shape matches spec — test #1
7. ✅ MD response is `text/plain`, oldest-first — test #3
8. ✅ Test file `tests/test_whatsapp_pull_api.py` covers all required cases + more (13 total)
9. ✅ Pytest green (see below)
10. ✅ py_compile clean (see below)
11. — Render smoke is AH1's post-merge step (per brief acceptance §11 + dispatch ship-gate §3)

## Ship-gate evidence

### `pytest tests/test_whatsapp_pull_api.py -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b4
plugins: langsmith-0.7.38, anyio-4.12.1
collecting ... collected 13 items

tests/test_whatsapp_pull_api.py::test_whatsapp_messages_happy_path_json PASSED [  7%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_sql_uses_canonical_media_column PASSED [ 15%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_markdown_format PASSED [ 23%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_empty_result_is_200 PASSED [ 30%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_limit_clamped PASSED [ 38%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_missing_contact_422 PASSED [ 46%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_missing_from_422 PASSED [ 53%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_bad_format_422 PASSED [ 61%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_bad_date_422 PASSED [ 69%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_no_api_key_returns_401 PASSED [ 76%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_wrong_api_key_returns_401 PASSED [ 84%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_db_failure_returns_200_status_error PASSED [ 92%]
tests/test_whatsapp_pull_api.py::test_whatsapp_messages_no_db_conn_returns_200_status_error PASSED [100%]

======================== 13 passed, 7 warnings in 0.38s ========================
```

Warnings unrelated (pre-existing `on_event` deprecation + `regex=` → `pattern=` in `slug_registry_api` at line 7459; qdrant client compat warning).

### `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`

Exit 0 (`COMPILE_OK`).

## Files touched

- `outputs/dashboard.py` — +102 LOC (3 import additions on existing lines + endpoint + `_format_wa_md` helper; no existing lines modified beyond imports)
- `tests/test_whatsapp_pull_api.py` — new file, 257 LOC

No migrations, no schema changes, no frontend, no new dependencies.

## Not done (out of scope per brief §111-118 + dispatch §57-64)

- Desk picker CLAUDE.md curl examples — AH1 dispatches follow-up post-Render-smoke
- Render smoke (AH1)
- `/security-review` + AH2 static review (AH1 chain on MEDIUM trigger class)

## Next

AH1 to run cross-lane review chain: AH2 static review (mandatory MEDIUM) + `/security-review` (mandatory — exposes PII surface). On both clean, AH1 merges.
