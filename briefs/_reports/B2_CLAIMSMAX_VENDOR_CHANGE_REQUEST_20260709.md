# ClaimsMax — Search Index Change Request

**To:** Ellie Technologies — ClaimsMax product / support
**From:** Brisen Group
**Date:** 9 July 2026
**Priority:** Normal — we have a workaround in place; this is a data-quality / durability fix, not an outage.

---

## In one line
When we search the ClaimsMax archive, some results come back without a usable document reference —
the filename shows an internal placeholder (e.g. `worker_9391_<long hash>`) and the document ID is
blank — even though the document itself is fully processed and available in your system. We'd like
those search results to point to the real document.

## What we see
Certain search results come back with:
- **Document ID:** empty
- **Filename:** `worker_<number>_<64-character hash>.pdf` (or `.docx`)
- **Text snippet:** empty
- (Date, category, and relevance score ARE filled in.)

The same documents, on other searches, come back correctly — with a real document ID, the real
filename, and a snippet. So the archive effectively holds two versions of the same document in
search: one usable, one placeholder. Which one appears at the top varies from search to search,
so the same query sometimes works and sometimes returns only placeholders.

## What we found (root cause, verified)
The placeholder results are **search-index entries left over from the ingestion ("worker") stage**.
Classification, date, and relevance were computed, but the row was never updated with the
document's real ID, filename, and snippet once processing finished.

The documents themselves **are fully processed and retrievable**: the 64-character hash in the
placeholder filename is the document's SHA-256, and fetching by that hash via
`GET /documents/{sha256}` returns the complete record — real document ID, extracted text, summary,
and metadata. These are **not** in-flight items; they trace back to batch runs from **March 2026**.

## Evidence (two verified examples)

| Placeholder filename in search | Real document ID (fetched by SHA-256) | Ingestion batch | Processed |
|---|---|---|---|
| `worker_9391_49d2e99f…ede.pdf` | `d9cd7d20-8f9c-4293-b6b2-bf23348a1baf` | `_batch_020_output` | 2026-03-02 |
| `worker_17427_d276745…df0.pdf` | `6110a945-f728-4065-a731-1207f328daa5` | `_batch_006_output` | 2026-03-02 |

Both fetches returned full extracted text (34,505 and 8,341 characters) and correct metadata —
confirming the documents are complete and only the **search projection** is stale.

## Requested fix (whichever approach fits your architecture)
1. **Back-fill at finalization** — when a document finishes processing, update its search-index
   row(s) with the real document ID, original filename, and snippet. *(Preferred — prevents
   recurrence on future ingests.)*
2. **One-off reindex** — for existing search rows where the document ID is empty and the filename
   matches `worker_<number>_<64-hex>`, join to the finalized document by SHA-256 and back-fill the
   ID / filename / snippet (or delete and re-emit from the finalized record).
3. **De-duplicate** — ensure a finalized row supersedes / removes its worker-stage predecessor so
   the same document isn't indexed twice.

## Acceptance criteria
- Search results for finalized documents show a non-empty document ID, the real filename (not
  `worker_*`), and a snippet.
- No search rows remain with an empty document ID **and** a `worker_*` filename (or such rows are
  excluded from search results entirely).
- No duplicate search entries for the same document.

## Our offer
We can re-run two specific queries that today return the placeholder rows and confirm they return
proper document IDs after your fix — happy to verify on your timeline.

## Note on urgency
We have a client-side workaround live (we recover the document via the SHA-256 in the placeholder
filename), so this is **not blocking us**. We're raising it as a durability / quality fix so the
issue doesn't recur on future batch ingests.
