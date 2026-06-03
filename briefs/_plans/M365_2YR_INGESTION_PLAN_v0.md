---
type: epic-plan
epic: M365_2YR_EMAIL_INGESTION
owner: lead (AH1) — ingestion design; cowork-ah1 owns M365 Graph auth/Dennis track
status: SCOPING v0 (Director-requested 2026-06-03)
depends_on: M365 Graph live (Dennis .pfx password — currently dormant)
---

# M365 Two-Year Email + Attachment Ingestion — Scoping Plan v0

## 1. Goal

Backfill ~2 years of Outlook (M365) email **and attachments** into Baker's knowledge base — Postgres `email_messages` + `documents` (system of record) and Qdrant `baker-documents`/email vectors (concept search) — so Baker can answer by meaning across the full recent correspondence history, not just what trickled in via the legacy pollers.

## 2. Why now

- **Better pipe.** Graph gives one clean, authenticated API over the whole mailbox (all folders, Sent, attachments, metadata, server-side `$filter`/`$search`, delta queries). Legacy IMAP/EWS scraping is partial and fragile.
- **Legacy pollers are degraded.** Prod `/health` shows `exchange` + `exchange_sent` sentinels DOWN. Current email coverage is incomplete; a Graph backfill closes the gap and a Graph poller replaces the dead ones going forward.
- **Foundation is ready.** This session's durability arc (#285/#287/#286/#288/#290) fixed the two-write ingest + semantic search + attachment parity. A bulk backfill is now safe to land on top.

## 3. Hard dependency (blocker)

Graph is **dormant**: `BAKER_USE_GRAPH=false`, and `kbl/graph_client.py` (merged #289) is **auth-only** — generic host-pinned `get()/get_url()`, no mail methods. Live Graph is gated on **Dennis Egorenkov delivering the .pfx import password** (cert filed in 1P, password-protected; Director's request drafted in Outlook — cowork-ah1 track, bus #1732). **No backfill runs until that lands.** Scoping + build can proceed in parallel; the run cannot.

## 4. What must be built (3 layers)

1. **Mail-pull layer on GraphClient** (new — does not exist):
   - Page `/users/{id}/messages` with `$select` (id, subject, from, toRecipients, sentDateTime, receivedDateTime, conversationId, hasAttachments, bodyPreview, body), `$filter` on date window, `$top` paging via `@odata.nextLink`.
   - `$expand=attachments` (or per-message `/messages/{id}/attachments`) for attachment bytes + names.
   - Prefer **delta queries** (`/messages/delta`) for the forward poller so steady-state is incremental, not full re-scan.
2. **Backfill orchestrator** (new):
   - Iterate the 2-year window in bounded batches (e.g. by month or by `$top=50` page), idempotent, resumable via a stored cursor/delta token.
   - Per message: store to `email_messages` (dedup on message-id) → embed body to Qdrant → for each attachment, run the **existing #286 two-write attachment path** (`tools/ingest/pipeline.ingest_text` + `promote_attachment_text_to_document_and_qdrant`) → `documents` + Qdrant.
   - PostgreSQL advisory lock so two Render instances don't double-run (Lesson: concurrent-startup OOM).
   - **Never on startup** — triggered endpoint or a controlled job, bounded, caller-driven (Lesson: backfill-OOM on deploy).
3. **Forward Graph poller** (replaces dead exchange pollers): delta-query poll on a schedule once backfill is current.

## 5. Relevance filter (critical — do NOT blanket-ingest)

Blanket 2-year ingest pulls newsletters, spam, calendar noise, marketing → pollutes retrieval. Filter strategy (Director to weigh in §8):
- **Folder scope:** Inbox + Sent + matter-named folders; exclude Junk, Promotions/Clutter, auto-archive.
- **Sender allowlist/denylist:** drop known newsletter/no-reply senders; keep counterparties + internal + matter contacts.
- **Per-message classify gate:** lightweight Haiku "is this matter-relevant correspondence?" before the expensive embed+extract — or rely on existing classifier. Trade-off: classify-everything cost vs noise.

## 6. Volume + cost model (estimate — finalize once Graph live)

Can't query volume yet (Graph dormant). Use Graph `$count` on the filtered set as Step 0 once live. Rough model:

```
emails_in_scope (E)   = measure via Graph $count   (assume 8,000–20,000 for 2y filtered)
attachments (A)       ≈ 0.3 × E
embed cost            = (E + A) × Voyage embed  ≈ cents/1k → low tens of $ total
classify+extract      = (E + A) × ~$0.03 (Haiku) ≈ $0.03 × (E+A)
```

Worked range: at E=15,000, A=4,500 → classify+extract ≈ 19,500 × $0.03 ≈ **$585**; embeddings ≈ low tens of $. **Total order-of-magnitude: a few hundred dollars**, dominated by classify+extract. Filtering (§5) is the main cost lever — tighter scope cuts this sharply.

## 7. Phasing

- **P0 — unblock:** Dennis password → `BAKER_USE_GRAPH=true` smoke (cowork-ah1 track). Gate: GraphClient.health() green on prod.
- **P1 — mail-pull layer:** b-code brief; methods + paging + delta; unit-tested against recorded Graph fixtures.
- **P2 — orchestrator + filter:** b-code brief; dry-run mode returns counts only (measure volume/cost before spending).
- **P3 — bounded backfill run:** lead-triggered, batched, monitored; reconciliation endpoint confirms PG↔Qdrant parity as it runs.
- **P4 — forward poller:** delta poll replaces dead exchange sentinels.

## 8. Open decisions for Director

1. **Scope window:** exactly 24 months, or matter-life (some matters older than 2y)?
2. **Filter aggressiveness:** matter-relevant only (cheaper, cleaner) vs everything-but-junk (complete, noisier, ~5× cost)?
3. **Mailboxes:** Director's mailbox only, or shared/office mailboxes (office.vienna, etc.) too?

## 9. Risks / lessons applied

- Backfill OOM on startup → never run on deploy; bounded triggered job only.
- Concurrent Render instances → advisory lock.
- DMARC/forwarding gaps → Graph polls source directly (no forwarding).
- Silent partial failure → reconciliation endpoint + per-batch counts + sentinel health on the new poller.
- Over-ingest noise → §5 filter is mandatory, not optional.

## 10. Coordination

cowork-ah1 owns the **Graph auth / Dennis** track (P0). Lead (me) owns **ingestion design + orchestrator briefs** (P1–P4). Sync at P0 green before P3 spends money.
