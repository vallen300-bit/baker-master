---
agent: b1
brief: BAKER_CAPTURE_BLINDSPOTS_1
brief_version: v4 (commit 49e2050)
status: SHIPPED
shipped_at: 2026-05-30T07:55Z
branch: b1/baker-capture-blindspots-1
commit: 81d9cb7
pr: https://github.com/vallen300-bit/baker-master/pull/270
reply_to: lead
bus_topic: ship/baker-capture-blindspots-1
ack_bus_msgs:
  - 1340 (initial dispatch)
  - 1347 (dispatch-update v4 codex-pass)
---

# B1 ship report — BAKER_CAPTURE_BLINDSPOTS_1

## Summary

Both Director outbound capture gaps closed. PR #270 against `main`.

- **Phase 1 — Exchange Sent-Items polling:** `poll_exchange_sent()` sibling poller mirrors `poll_exchange()` body; runtime-probes Sent folder; separate `exchange_poll_sent` watermark; independent try/except in `triggers/email_trigger.py:643-652` per lesson #45. Direction is implicit via `sender_email = dvallen@brisengroup.com` — no schema change.
- **Phase 2 — iPhone WhatsApp export ingest:** `POST /api/whatsapp/import_iphone_export` accepts iPhone "Export Chat" .txt, parses continuations + multi-locale dates + system placeholders, upserts via `SentinelStoreBack.store_whatsapp_message()` with deterministic `iphone:<chat>:<ts>:<bit>:<md5>` id for idempotency + `WHERE id LIKE 'iphone:%'` filterability. `.zip` returns 501. No migrations.

## Files modified (per `git diff --stat`)

```
outputs/dashboard.py                 | 193 ++++++++++++++++++++++++++++++++++
tests/test_exchange_sent_poller.py   | 156 +++++++++++++++++++++++++++
tests/test_iphone_export_endpoint.py | 198 +++++++++++++++++++++++++++++++++++
tests/test_iphone_export_parser.py   |  98 +++++++++++++++++
triggers/email_trigger.py            |  11 ++
triggers/exchange_poller.py          | 182 ++++++++++++++++++++++++++++++++
6 files changed, 838 insertions(+)
```

Matches the Files Modified list in brief v4 exactly.

## Pytest output (literal — python3.12, 20 new tests)

```
$ python3.12 -m pytest tests/test_exchange_sent_poller.py tests/test_iphone_export_parser.py tests/test_iphone_export_endpoint.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.38, anyio-4.12.1
collected 20 items

tests/test_exchange_sent_poller.py::test_detect_sent_folder_finds_sent_items PASSED [  5%]
tests/test_exchange_sent_poller.py::test_detect_sent_folder_prefers_first_candidate PASSED [ 10%]
tests/test_exchange_sent_poller.py::test_detect_sent_folder_returns_none_when_absent PASSED [ 15%]
tests/test_exchange_sent_poller.py::test_detect_sent_folder_swallows_list_failure PASSED [ 20%]
tests/test_exchange_sent_poller.py::test_poll_exchange_sent_skips_when_no_password PASSED [ 25%]
tests/test_exchange_sent_poller.py::test_poll_exchange_sent_returns_outbound_and_advances_watermark PASSED [ 30%]
tests/test_exchange_sent_poller.py::test_poll_exchange_sent_returns_empty_when_sent_folder_missing PASSED [ 35%]
tests/test_iphone_export_parser.py::test_parses_three_messages_with_continuation PASSED [ 40%]
tests/test_iphone_export_parser.py::test_drops_deleted_and_encrypted_placeholders PASSED [ 45%]
tests/test_iphone_export_parser.py::test_auto_detects_dd_mm_yyyy_locale PASSED [ 50%]
tests/test_iphone_export_parser.py::test_is_director_flag_case_insensitive_substring PASSED [ 55%]
tests/test_iphone_export_parser.py::test_returns_empty_when_no_parseable_lines PASSED [ 60%]
tests/test_iphone_export_parser.py::test_iphone_export_id_is_deterministic_and_prefixed PASSED [ 65%]
tests/test_iphone_export_endpoint.py::test_endpoint_route_is_registered_in_source PASSED [ 70%]
tests/test_iphone_export_endpoint.py::test_endpoint_does_not_collide_with_existing_whatsapp_routes PASSED [ 75%]
tests/test_iphone_export_endpoint.py::test_endpoint_401_without_auth_header PASSED [ 80%]
tests/test_iphone_export_endpoint.py::test_endpoint_200_with_valid_auth_and_payload PASSED [ 85%]
tests/test_iphone_export_endpoint.py::test_endpoint_idempotent_on_repeated_upload PASSED [ 90%]
tests/test_iphone_export_endpoint.py::test_endpoint_422_on_empty_or_garbage_upload PASSED [ 95%]
tests/test_iphone_export_endpoint.py::test_endpoint_501_on_zip_upload PASSED [100%]
========================= 20 passed, 7 warnings in 0.57s =========================
```

## Regression check

Full pytest run produced 8 failures touching email/whatsapp-adjacent tests. Verified pre-existing on bare main by stashing this branch's six changed files and re-running the same subset (8 failures, identical names). My changes introduce zero new failures.

Pre-existing baseline failures (NOT regressed by this PR):
- `tests/test_whatsapp_sender_lid.py` — 6 tests (LID resolution scenarios)
- `tests/test_dashboard_cortex_ratify.py::test_pending_tab_button_in_static_index_html`
- `tests/test_hot_md_weekly_nudge.py::test_nudge_sends_whatsapp_with_expected_text`

Broader 116 failures + 40 errors in full suite are dependency-environment issues (Gmail credentials, MCP vault tools) unrelated to email/exchange/whatsapp paths.

## Quality checkpoints (brief §10)

1. `poll_exchange()` (INBOX) untouched — only sibling added. ✅
2. Sent poller wrapped in independent try/except — INBOX failure cannot kill Sent and vice-versa. ✅
3. `EXCHANGE_PASS` env-var: pollers return [] with a warning on missing env (covered by `test_poll_exchange_sent_skips_when_no_password`). Post-deploy presence is AH1/Render-side verification. ⏳
4. iPhone parser drops `<This message was deleted>`, `<This message was edited>`, U+200E-prefixed `<encrypted>`, and empty bodies (covered by `test_drops_deleted_and_encrypted_placeholders`). ✅
5. Endpoint returns 401 without `X-Baker-Key` (covered by `test_endpoint_401_without_auth_header`). ✅
6. Idempotency proven via DB-state assertion: second upload → `len(stub.rows)` unchanged (covered by `test_endpoint_idempotent_on_repeated_upload`). ✅
7. No route collision — `src.count('"/api/whatsapp/import_iphone_export"') == 1` (covered by `test_endpoint_does_not_collide_with_existing_whatsapp_routes`). ✅
8. NO migrations shipped. Direction encoded via existing `sender_email` + `is_director` columns. ✅
9. Outbound email queryable via `sender_email = 'dvallen@brisengroup.com'`. ✅
10. Historical WA queryable via `id LIKE 'iphone:%'`. ✅

## Verification SQL (post-deploy)

```sql
-- Phase 1: outbound rows landing
SELECT COUNT(*) AS outbound_24h
FROM email_messages
WHERE sender_email = 'dvallen@brisengroup.com'
  AND ingested_at > NOW() - INTERVAL '24 hours';

-- Phase 1: in/outbound mix sanity
SELECT
  CASE WHEN sender_email = 'dvallen@brisengroup.com' THEN 'outbound' ELSE 'inbound' END AS dir,
  COUNT(*)
FROM email_messages
WHERE ingested_at > NOW() - INTERVAL '7 days'
GROUP BY 1;

-- Phase 2: iPhone-export rows present
SELECT COUNT(*) AS rows,
       COUNT(DISTINCT chat_id) AS counterparties,
       MIN(timestamp) AS earliest
FROM whatsapp_messages
WHERE id LIKE 'iphone:%';
```

To be run by AH1 post-Render-deploy and after Director's smoke test.

## Manual smoke (gated on AH1 Render deploy + Director action)

- Director sends test email from Outlook → wait one poll cycle (~5 min) → AH1 runs Phase 1 outbound SQL → ≥1 row.
- Director taps "Export Chat" in iPhone WhatsApp for Storer thread → AirDrops .txt to MacBook → `curl -F file=@storer.txt -F counterparty_phone=+393358345678 -F counterparty_name='Peter Storer' -H 'X-Baker-Key: $KEY' https://baker-master.onrender.com/api/whatsapp/import_iphone_export` → 200 with `ingested`/`skipped_duplicates` body → AH1 runs Phase 2 SQL.

## Anchors

- Brief v4 (canonical): `briefs/BRIEF_BAKER_CAPTURE_BLINDSPOTS_1.md` (commit `49e2050`)
- Dispatch chain: v1 `a77ea78` → v2 `ac3e5fd` → v3 `493d682` → v4 `49e2050` → mailbox metadata `7aed1ac`
- Codex review history: bus #1342 (FAIL-LIGHT v1) → #1344 (FAIL-LIGHT v2) → #1346 (PASS-WITH-NOTE v3 / PASS final v4)
- Dispatch bus IDs ACK'd: #1340 (initial), #1347 (v4 update)
- Director directive 2026-05-29: *"If we have a gap in what I send to other people by WhatsApp or email, there is a problem. Baker is blind."*
