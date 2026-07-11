# B2 — M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1 — Phase 2 ship report

Date: 2026-06-09
Brief: `briefs/_tasks/CODE_2_PENDING.md` (dispatch 7526dff, from lead)
PR: **#342** — branch `b2/m365-mail-blindspot`, head `a8238d6`, base `main`
Phase 1 diagnosis: `B2_M365_MAIL_BLINDSPOT_DIAGNOSE_1_PHASE1_20260609.md`

## What shipped
Tool-surface fix making Director's M365/Outlook mail findable + killing the fail-silent. Reliable Postgres `email_messages` surface (Qdrant embed gap is b3's separate lane).

- **`tools/email.py` (new)** — `baker_email_search` / `baker_email_read` over the merged `email_messages` store (Gmail + Graph). **Tokenized + field-aware** matching (each term ANDed, OR across subject/sender/body) — not the whole-query ILIKE that silently misses multi-term queries (lead #2631 / codex #2627). `source` filter. Backend outage → `backend_unavailable=true` (never silent "no mail"). providers: store (default), graph (live M365), all.
- **`tools/gmail.py`** — fail-loud: brisengroup-scoped + any zero-result carry `m365_warning` → `baker_email_search`; descriptions say "Gmail ONLY, NOT Outlook/M365".
- **`email_messages.source` column** — migration `20260609` + self-heal `ALTER` in store_back bootstrap + `store_email_message(source=…)` at all 3 ingest call sites (from trigger metadata; graph_mail carries `source=graph`).
- **`triggers/sentinel_health.py`** — `graph_mail_poll` in stale-watchdog (6h); skipped when dormant (no watermark row).
- **`baker_mcp_server.py`** — registers email tools (defensive import + dispatch).

## Reuse decision (lead #2628)
Clerk's `_email_search` is Clerk-class-coupled (`self._query_rows`, `_parse_tool_json`, fuzzy fallback). Reused the underlying retriever store + connection + `SearchBackendUnavailable` signal, but wrote the tokenized query directly per lead's explicit #2631 directive ("do NOT just wrap the existing whole-string ILIKE").

## Verification (literal, python3.12)
```
$ python3.12 -m pytest tests/test_m365_mail_surface.py -q
........                                                                 [100%]
8 passed, 1 warning in 0.39s
```
Touched-module regression (`test_gmail`, `test_clerk_runtime`, `test_graph_mail_trigger`, `test_retire_dead_evok_sentinels`, `test_clerk_gmail_claimsmax_reads`, `test_attachment_two_write_parity`, `test_extract_gmail_visibility`): **136 passed, 3 skipped**. Singleton guard: OK.

**Pre-existing red (NOT this PR):** `test_migration_runner.py::test_migration_file_has_up_marker` fails for 13 migrations that predate this PR (applied/locked, out of scope). This PR's migration is marker-compliant (`-- == migrate:up ==`).

## Done rubric — verified POST-merge (per gate flow: lead merges, then I live-verify)
1. Live prod `baker_email_search` returns Spanyi 6 Jun email.
2. New M365 email searchable within one ingestion cycle.
3. No fail-silent path for brisengroup mail.
4. `POST_DEPLOY_AC_VERDICT v1` on bus with live evidence.

## Gates
- Bused lead #2633 (PR up). Bused codex #2634 (G0 plan + G3 diff).
- G2 `/security-review` requested (touches mail tool surface) — lead orchestrates.
- Qdrant embed gap → b3 (`M365_QDRANT_EMBED_GAP`), coordinate on bus if paths touch.
