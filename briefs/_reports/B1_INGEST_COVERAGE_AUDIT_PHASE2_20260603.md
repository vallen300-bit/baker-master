# B1 Phase-2 report — ingestion COVERAGE audit (map + gap-list, not a build)

**Date:** 2026-06-03 · **Author:** B1 · **For:** lead
**Parent dispatch:** INGEST_RETRIEVAL_GAP_DIAGNOSE_FIX_1 (#1701), Phase 2 extension
**Scope:** map what reaches **Qdrant** + **Postgres** today, per source; document the **M365 gap**. Read-only. No build.

> Method note: this is a coverage MAP at trigger/store altitude, not a line-by-line forensic audit. Items marked **VERIFY** are characterized from the live path I traced but not exhaustively proven — flagged honestly rather than asserted.

## The two stores, and the rule

- **Postgres** is the **system of record** the Documents UI reads: `documents` table (full text + FTS), plus per-source tables (`email_messages`, `whatsapp_messages`, `meeting_transcripts`, …). `GET /api/documents/search` reads `documents`.
- **Qdrant** is the **semantic layer** the chat/Cortex RAG retriever (`SentinelRetriever.search_all_collections`) reads: collections `baker-documents`, `baker-emails`/conversations, `baker-people`, etc.
- A source is **fully covered** only if its content reaches **both** in a form the consumers query. `store_document_full()` writes Postgres `documents` **only** — Qdrant for documents comes from `ingest_file()`. The two-write must be paired.

## Coverage matrix (today)

| Source | Live trigger | → Postgres | → Qdrant | Standalone `documents` row? | Status |
|---|---|---|---|---|---|
| Dropbox files | `dropbox_trigger.py` | `store_document_full` → `documents` | `ingest_file` → `baker-documents` | Yes | ✅ Full (the reference two-write) |
| Dashboard upload `/api/ingest` | `outputs/dashboard.py` | **now** `store_document_full` (PR #285) | `ingest_file` → `baker-documents` | Yes (post-#285) | ✅ Full after #285 merges (was Qdrant-only — the bug) |
| Email body/thread | `email_trigger.py` (+ legacy IMAP `exchange_poller`, `bluewin_poller`) | `store_email_message` → `email_messages` | thread embedded (**VERIFY** collection) | No (email row, not a doc) | 🟡 Searchable as email; not a `documents` row |
| **Email attachments (PDF/docx/img)** | `extract_gmail.extract_attachments_text` | attachment **text inlined into the email thread** | inlined with the thread | **No — live.** Standalone rows only via **batch** `scripts/backfill_email_attachments.py` (`source_path='email:%'`) | 🟡 **Gap:** live attachments are findable only as inlined email text; they become first-class `documents` (with classification/matter tag) **only when the backfill is run manually** |
| WhatsApp media | `waha_webhook.py` | media → Dropbox; text extracted + **inlined into message body** → `store_whatsapp_message` | with the WA message (**VERIFY**) | No | 🟡 Same shape as email attachments — inlined, not standalone docs |
| Meeting transcripts | `plaud_trigger`, `fireflies_trigger`, `youtube_ingest` | `store_meeting_transcript` → `meeting_transcripts` (+ `matter_slug`) | transcript embedded (**VERIFY**) | No | 🟡 Searchable via transcript surface (`/api/transcripts/by-matter`) |
| **M365 mail + attachments** | **none wired** — `kbl/graph_client.py` ships **DORMANT** | — | — | — | ⛔ **Not ingesting** (see gap below) |

Takeaways:
1. **Attachments are never standalone `documents` rows on the live path** (email or WhatsApp). Their **text is inlined** into the parent email/WA record, so it is *searchable* via the email/WA surfaces and (where embedded) via chat RAG — but it does **not** appear in the Documents tab as its own classified, matter-tagged document, and `store_document_full`'s content-hash dedup / extraction pipeline doesn't run on it. The only path that promotes email attachments to first-class docs is the **manual backfill**, which is batch, not live, and (**VERIFY**) writes Postgres `documents` without a Qdrant `baker-documents` upsert.
2. **`store_document_full` ≠ Qdrant.** Any path that calls only `store_document_full` (e.g. the attachment backfill) populates the Documents tab + FTS but **not** `baker-documents` semantic search. Conversely the old `/api/ingest` did the reverse (the bug fixed in #285). Both halves are required; only Dropbox + the now-fixed `/api/ingest` do both.

## M365 gap (Azure-cred gated — Phase 2+ of the M365 program)

- `kbl/graph_client.py` (M365_GRAPH_CLIENT_FOUNDATION_1, Phase 1 of 5) ships **inert**: no token, no HTTP unless `BAKER_USE_GRAPH=true` **and** `M365_*` creds are set. It is auth + a thin REST GET surface only — **no mail/calendar/attachment poll built yet** (Phases 2–4).
- Live mail today is **legacy IMAP** (`exchange.evok.ch` via `exchange_poller` + `bluewin_poller`) — it is **not** Microsoft Graph and does not use `graph_client`.
- So there is **no M365 mail or attachment ingestion** at all yet. When Phase 2+ lands, to reach parity (and not repeat the #285 gap) it must wire, per message:
  1. **Mail body** → `store_email_message` (Postgres) **+** embed to the email Qdrant collection.
  2. **Each attachment** → extract text → **`store_document_full`** (Postgres `documents`, first-class) **+** **`ingest_file`** (Qdrant `baker-documents`) — i.e. the Dropbox two-write, applied to attachments, **on the live path** (not a backfill). This is the single most important lesson from the #285 bug: ingest must write **both** stores, and attachments deserve standalone docs.
  3. Reuse the existing extractors (`tools/ingest/extractors.py`) + `queue_extraction` so M365 attachments get the same classification/matter tagging as Dropbox docs.

## Recommended follow-up briefs (for lead to triage — separate from #285)

1. **Live email/WhatsApp attachment → first-class documents** (close the 🟡 gap): promote the batch `backfill_email_attachments.py` logic into the live email/WA triggers (two-write, not inline-only). Medium.
2. **Audit the attachment backfill's Qdrant half** (**VERIFY**): confirm whether `backfill_email_attachments.py` upserts `baker-documents` or only writes Postgres; if Postgres-only, attachments aren't in semantic search. Small.
3. **M365 Phase 2 ingestion spec** uses the two-write contract above as an explicit acceptance criterion. (Brief, when Azure creds land.)

Bug A from Phase 1 (dead Qdrant branch in `/api/documents/search`) is also still open — separate Tier-B call.
