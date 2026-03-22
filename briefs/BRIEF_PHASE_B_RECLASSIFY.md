# BRIEF: Phase B Reclassify — Haiku re-classification of "other" documents

**Priority:** HIGH — run before B6 backfill (better labels → better extraction)
**Cost:** ~EUR 20 (Haiku calls on ~1,000 docs)
**Effort:** 10 min (run existing script)
**Approved by:** Director (2026-03-22)

## What

Phase A triage (just completed) filtered 1,674 non-documents (media, empty, corrupted) using free heuristics. But many real documents are still classified as `"other"` — meaning the original classifier couldn't determine their type.

Phase B re-runs Haiku classification on these "other" docs with the improved 16-type taxonomy and path-based hints.

## Execute

### Step 1: Diagnose first (free, no cost)

```bash
python3 scripts/reextract_documents.py --diagnose
```

This shows how many docs are classified but not extracted, broken down by type. Note the numbers.

### Step 2: Run reclassification (Haiku cost)

```bash
python3 scripts/reclassify_docs.py --limit 5
```

Test on 5 docs first. Verify output looks sane (docs getting reclassified from "other" to contract/invoice/report/etc.).

Then run the full batch:

```bash
python3 scripts/reclassify_docs.py
```

This will:
- Query all docs with `document_type = 'other'` and `LENGTH(full_text) > 100`
- Call Haiku to classify each one
- If reclassified to a type with an extraction schema, also runs extraction
- Respects circuit breaker (stops if daily cost limit hit)
- Sleeps 2s between calls to avoid rate limits

### Step 3: Report results

After completion, run diagnose again to see the improvement:

```bash
python3 scripts/reextract_documents.py --diagnose
```

Post the before/after numbers.

## Important

- This runs against **production DB** (Neon PostgreSQL via env vars)
- Circuit breaker will auto-stop if daily cost exceeds limit
- If the script errors on a specific doc, it continues to the next one
- No code changes needed — just run the existing script
