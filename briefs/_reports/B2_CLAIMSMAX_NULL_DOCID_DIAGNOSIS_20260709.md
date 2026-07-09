# B2 — ClaimsMax null-doc_id diagnosis (2026-07-09)

Owner: b2 (dispatched by lead #7707). Scope: root-cause the intermittent ClaimsMax
`baker_claimsmax_search` "results with null doc_ids" that blocked CM-3 H7 (#7694) and
CM-1 wave-1 H2, while CM-2/CM-4 got real doc_ids on the same query.

## Symptom
`baker_claimsmax_search` returns pages where every result has `doc_id: null`,
`snippet: null`, and `filename: worker_<pid>_<64-hex>.{pdf,docx}` — while `doc_date`,
`l1`, `l2`, and `score` ARE populated. Content is then un-fetchable via the normal
`get_document(doc_id)` path because doc_id is null. Intermittent: same query, different
seats/times → sometimes real doc_ids, sometimes an all-worker/all-null page.

Observed instances (evidence base):
- CM-1 wave-1 H2 (#7626): "219+ indexed references but null doc_ids".
- CM-3 H7 (#7694): 238 results, all doc_ids null → fail-loud MISS.
- CM-2 H8 (#7718): "ClaimsMax 251 results, all null doc_ids".
- CM-1 prior H7 (findings/7506, 2026-07-08): "only obfuscated worker_* filenames with null doc_ids".
- **b2 live repro 2026-07-09 ~08:40Z**: query "EPI Serie A nominative notes … EUR 7,000,000"
  → total 232, **top 25 ALL `doc_id: null` + `worker_<pid>_<sha256>` + `snippet: null`**.
- Contrast — CM-4 H7 (#7690) + CM-2 H7 (#7693): SAME instrument, got real doc_id
  `ac5d9768-67aa-4775-b7da-922331b32bb6` + real filename + verbatim text.

## Baker side is a faithful passthrough — RULED OUT
- `kbl/claimsmax_client.py::search` → `POST /search`, returns the raw server JSON. No mapping.
- `tools/claimsmax.py::_format_search_result` → slims each row via `r.get("doc_id")` /
  `r.get("filename")` / `r.get("snippet")` — straight passthrough, no stripping/obfuscation.
- `grep -niE "worker_|obfusc|redact|scrub"` across `kbl/claimsmax_client.py` + `tools/claimsmax.py` → 0 hits.
Conclusion: the null doc_id + `worker_` filename originate in the **ClaimsMax `/search` response**
(`https://brisen.claimsmax.co.uk/api/v1/`), not in Baker.

## Root cause (ClaimsMax-side) — CONFIRMED by document probe
The documents ARE fully finalized in the ClaimsMax documents store; only their **search-index
projection is stale**. Proof — `get_document(<sha256-from-worker-filename>)` returns the full
finalized record:

| worker filename (search row) | recovered doc UUID | pipeline_run | proof of finalization |
|---|---|---|---|
| `worker_9391_49d2e99f…ede.pdf` (doc_id=null in search) | `d9cd7d20-8f9c-4293-b6b2-bf23348a1baf` | `_batch_020_output` | text_length 34505, summary, ISIN LU1574669849, EUR 7,000,000, processed 2026-03-02 |
| `worker_17427_d276745…df0.pdf` (doc_id=null in search) | `6110a945-f728-4065-a731-1207f328daa5` | `_batch_006_output` | text_length 8341, EPI SCA 56 Series A notes EUR 7,000,000, processed 2026-03-02 |

So each "null doc_id" search row DOES correspond to a fully-processed document with a real UUID,
extracted text, and metadata. The search row simply still carries the **worker-stage placeholder
identity** — `doc_id: null`, `filename: worker_<pid>_<sha256>.ext`, `snippet: null` — that was
never back-filled with the canonical doc_id / original filename / snippet after finalization.
These are persistent (March 2026 batches), not in-flight.

Intermittency mechanism (LEADING HYPOTHESIS, evidence-supported):
duplicate ingestions of the same instrument coexist in the index — e.g. the Estates SA / EPI
Serie A term sheet exists BOTH as a finalized `.pst`-sourced row (`ac5d9768`, real doc_id) AND as
orphaned worker-stage rows (`d9cd7d20` batch_020, `6110a945` batch_006, doc_id=null in search).
They compete for the top result slots; ranking variance decides whether a seat's page is
dominated by finalized rows (real doc_ids) or worker rows (nulls). CONFIRMED facts: (a) stale
search projection, (b) duplicate copies with distinct UUIDs for the same instrument, (c) the
result set varies over time. INFERENCE: ranking variance between the two is the intermittency knob.

## Recovery path — the null doc_id is NOT data loss
The 64-hex token in `worker_<pid>_<sha256>.ext` IS the document sha256, and
`get_document(sha256)` accepts it. So any "null doc_id" worker row is fully recoverable:
extract the sha256 from the filename → `get_document(sha256)` → real UUID + text. Verified 2/2
across two batches. This is the basis of the interim mitigation.

## Fix options
1. **ClaimsMax-repo (proper fix)** — reindex/back-fill so finalized documents' search rows carry
   the canonical `doc_id` + `original_filename` + `snippet`, and orphaned worker-stage rows are
   dropped or superseded. This is a ClaimsMax search-index projection job; needs ClaimsMax-repo
   code work (not baker-master). → tight brief to the ClaimsMax repo owner.
2. **Baker-repo (interim mitigation, ~5 lines, no ClaimsMax dependency)** — in
   `tools/claimsmax.py::_format_search_result`, when `doc_id is None` and `filename` matches
   `^worker_\d+_([0-9a-f]{64})\.`, extract the sha256 and emit it as a `sha256` field (and/or set
   `doc_id` to the sha256, which `get_document` already accepts). Every CM seat then gets a
   fetchable handle transparently while the ClaimsMax index stays stale. Add a `recovered_from:
   worker_filename` flag for honesty. Low blast radius, reversible, unit-testable off a captured
   payload. b2 can build on a follow-on dispatch.
3. **Seat-level (zero code, weakest)** — CM contract note: on a `worker_<id>_<sha256>` + null
   doc_id result, fetch by the sha256. Immediate but relies on every seat remembering; option 2
   centralizes it.

Recommendation: option 2 now (unblocks seats today, Baker-side, I can implement) + option 1 brief
to the ClaimsMax repo for the durable index back-fill. Do NOT grade CM-3 H7 / CM-1 H2 as seat
capability fails — they hit a real ClaimsMax index defect and were correctly fail-loud.

## Secondary (diagnose-only, per #7707) — per-wake cap=3 split
Wave 2 drain: CM-2 + CM-4 each drained exactly 3 (H5/H6/H7), with CM-2's H8/H9 arriving on a later
wake — cap=3 held. CM-1 + CM-3 each drained 6 in one pass (H5–H9 + H2-rerun). Leading explanation:
the cap is enforced per drain-cycle, and CM-1/CM-3 ran two back-to-back drain cycles (or the
H2-rerun, seeded on a fresh thread after their initial queue snapshot, counted as a separate
batch), letting wall-clock throughput exceed 3; CM-2/CM-4 ran a single cycle. Cannot fully confirm
without the seat-side drain logs. If the cap must be a hard per-seat-per-wake throttle, the seat
drainer needs a persistent per-wake counter rather than a per-cycle one. No fix proposed (per lead).
