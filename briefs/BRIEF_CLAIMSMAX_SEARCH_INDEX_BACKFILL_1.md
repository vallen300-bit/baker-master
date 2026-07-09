# BRIEF — ClaimsMax search-index back-fill (worker-stage placeholder rows)

Target repo: **ClaimsMax** (service behind `https://brisen.claimsmax.co.uk/api/v1/`) — NOT baker-master.
Authored by: b2 · Filed to: lead (lead dispatches to the ClaimsMax repo owner) · 2026-07-09
Source diagnosis: `briefs/_reports/B2_CLAIMSMAX_NULL_DOCID_DIAGNOSIS_20260709.md`
Baker-side interim mitigation already shipped: baker-master PR #499 (recover sha256 from worker
filename). That is a **stopgap for consumers, not a fix for this defect** — this brief is the durable fix.

**Harness-V2: N/A — external ClaimsMax-repo brief, not a baker-master production build.** Harness V2
(Context Contract / task class / done rubric / gate plan) governs baker-master implementation work;
this brief hands the durable fix to the ClaimsMax repo, which runs its own process. The baker-master
side of this issue already shipped Harness-compliant via PR #499. Acceptance criteria + verification
for the ClaimsMax work are specified below.

## Problem
`POST /search` returns result rows for finalized documents that still carry their **worker-stage
placeholder identity**: `doc_id: null`, `filename: "worker_<pid>_<sha256>.<ext>"`, `snippet: null`
— while `doc_date`, `l1`, `l2`, and `score` ARE populated. Consumers cannot fetch content because
`doc_id` is null. Intermittent per query/time: some pages are all-placeholder, others surface the
finalized copy with a real `doc_id`.

## Root cause (confirmed)
The document IS fully finalized in the documents store — real UUID, sha256, extracted text,
summary, classification — but its **search-index projection was never back-filled** from the
worker-stage row after finalization. Confirmed by `GET /documents/{sha256}` on the sha256 embedded
in the worker filename:

| search-row filename (doc_id=null) | real doc UUID | pipeline_run | store state |
|---|---|---|---|
| `worker_9391_49d2e99f…ede.pdf` | `d9cd7d20-8f9c-4293-b6b2-bf23348a1baf` | `_batch_020_output` | text_length 34505, summary, ISIN LU1574669849, EUR 7,000,000 |
| `worker_17427_d276745…df0.pdf` | `6110a945-f728-4065-a731-1207f328daa5` | `_batch_006_output` | text_length 8341, EPI SCA 56 Series A notes EUR 7,000,000 |

So the search index writes a row at the worker ingestion stage (classification + embedding done,
so it's searchable and scored) but the finalization step that mints the canonical `doc_id` and
attaches the real filename + snippet never updates that search row. These are persistent (March
2026 batches), not transient. Duplicate ingestions of the same instrument compound it: the same
Serie A term sheet exists as a finalized `.pst`-sourced row (`ac5d9768`, real doc_id) AND as
orphaned worker rows (`d9cd7d20`, `6110a945`); they compete on ranking, which is the intermittency.

## Scope
ClaimsMax indexing / finalization pipeline + the search index. NOT the documents store (documents
are correct). NOT baker-master (already passes through faithfully + has the interim recovery).

## Proposed fix (pick per ClaimsMax architecture — repo owner decides)
1. **Finalization back-fill:** when a document is finalized (doc_id minted, text extracted), UPDATE
   its search-index row(s) to carry the canonical `doc_id`, `original_filename`, and `snippet`,
   keyed by sha256. Preferred — fixes future ingests and is idempotent.
2. **One-off reindex:** sweep existing search rows where `doc_id IS NULL` and `filename ~
   '^worker_\d+_[0-9a-f]{64}\.'`, join to the documents store by sha256, and back-fill
   doc_id/filename/snippet (or delete + re-emit from the finalized record).
3. **Orphan dedup:** ensure a finalized row supersedes/removes its worker-stage predecessor so the
   same document isn't indexed twice (once fetchable, once not).

## Acceptance criteria
- `POST /search` for a finalized document returns rows with a non-null `doc_id`, the real
  `original_filename` (not `worker_*`), and a `snippet` — for the two probe docs above and broadly.
- Count of search rows with `doc_id IS NULL` AND `worker_*` filename → **0** (or only genuinely
  in-flight, un-finalized ingests, which should be excluded from search results entirely).
- No duplicate search rows (worker + finalized) for the same sha256.
- Regression: existing real-doc_id search behavior unchanged.

## Verification
- Re-run the two hunt queries that failed: "EPI Serie A nominative notes … EUR 7,000,000" (H7) and
  "BREC2 / Brisen Real Estate Capital 2 aggregate nominal Series amount" (H2). Expect real doc_ids
  at the top, fetchable via `get_document(doc_id)`.
- SQL/index count: `worker_*`-filename + null-doc_id rows in the search index = 0 post-migration.
- Cross-check: the recovered UUIDs `d9cd7d20…` and `6110a945…` now appear as the search `doc_id`
  for their rows (no longer only reachable by sha256).

## Notes
- Once this lands, the baker-master PR #499 recovery mapping becomes a harmless no-op (no rows will
  match the worker pattern). **Lead ruling (#7739): KEEP PR #499 post-backfill** as defense-in-depth
  against any future batch-ingest recurrence — do NOT revert.
- Build ownership: lead assigned the reindex implementation to b2 after the rung-1 tally close
  (#7739); independent gates cover the self-authored-brief risk.
