# BRIEF: BACKFILL-RERUN-PDF-1 — Re-run backfill for failed PDFs

**Priority:** HIGH
**Effort:** 15 min
**Author:** Code Brisen (Session 21)
**Date:** 2026-03-11

---

## Context

The overnight backfill (BRIEF_BACKFILL_COMPLETION_1) completed at 05:13 UTC.
- **1,606 new documents** stored successfully
- **2,174 errors** — almost all caused by missing `pdfplumber` dependency
- A few oversized images (>5MB) also failed (Claude API limit — not fixable without resize)

The DB now has **3,132 documents** but is missing ~2,000 PDFs that could not be extracted.

## Task

### Step 1: Install pdfplumber

```bash
cd ~/Desktop/baker-code
pip install pdfplumber
```

Verify:
```bash
python3 -c "import pdfplumber; print('OK', pdfplumber.__version__)"
```

### Step 2: Re-run the backfill

The existing script already skips files whose hash is already in the DB (hash dedup), so re-running it will only process the previously failed files.

```bash
cd ~/Desktop/baker-code
caffeinate -i python3 scripts/backfill_dropbox_full.py 2>&1 | tee /tmp/backfill_rerun_log.txt
```

This should:
- Skip the ~2,376 files already stored (770 + 1,606)
- Process the ~2,174 that failed last time
- PDFs will now succeed; oversized images will still fail (expected, ~5-10 files)

### Step 3: Verify

```bash
# Check results
tail -30 /tmp/backfill_rerun_log.txt

# Check DB count (should be ~5,000+)
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM documents"
```

### Step 4: Also add pdfplumber to requirements

Make sure it persists across deploys:

```bash
grep -q pdfplumber requirements.txt || echo "pdfplumber>=0.10.0" >> requirements.txt
```

## Expected Outcome

- DB grows from ~3,132 to ~5,000+ documents
- All PDFs (contracts, Schlussrechnungen, Nachträge, correspondence) become searchable
- Remaining errors should be <50 (oversized images only)

## Cost Estimate

~2,000 files × Haiku classification = ~€60-80 (within daily budget)

## Dependencies

- None — backfill script already exists and handles dedup
