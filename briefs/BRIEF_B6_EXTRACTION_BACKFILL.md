# BRIEF: B6 — Document Extraction Backfill

**Priority:** HIGH — last item on original 48-item backlog
**Cost:** ~EUR 80 (Haiku extraction calls on ~3,000 docs)
**Effort:** 15 min (run existing script)
**Approved by:** Director (2026-03-22)
**Prerequisite:** Run BRIEF_PHASE_B_RECLASSIFY first (better labels → better extraction)

## What

Baker has ~3,032 real documents stored with full text. Most were classified (have a `document_type`) but never had structured data extracted. Extraction means Haiku reads each document and pulls out:
- Dates, amounts, parties, deadlines, obligations
- Structured JSON stored in `document_extractions` table
- Powers the `search_documents` agent tool for all 5 specialists that use it

Without extraction, specialists can find documents but can't answer structured queries like "all contracts over EUR 1M" or "deadlines in Hagenauer correspondence."

## Execute

### Step 1: Diagnose (free)

```bash
python3 scripts/reextract_documents.py --diagnose
```

This shows:
- Total classified but not extracted
- How many have full_text
- How many have extraction schemas (contract, invoice, correspondence, etc.)
- How many are schema-less (will be stamped as extracted with no structured data)

Note the "Extractable" number — that's how many Haiku calls this will make.

### Step 2: Test on 5 docs first

```bash
python3 scripts/reextract_documents.py --run --limit 5
```

Verify output: should show docs being extracted with structured data. Check for errors.

### Step 3: Run full backfill

```bash
python3 scripts/reextract_documents.py --run
```

This will:
1. **Phase 1 (free):** Mark all schema-less docs (other, proposal, presentation) as `extracted_at = NOW()` — no Haiku call, just a timestamp so they're not re-processed
2. **Phase 2 (Haiku cost):** For each doc with a known schema (contract, invoice, correspondence, protocol, report, nachtrag, schlussrechnung):
   - Read full_text from DB
   - Call Haiku with the type-specific extraction schema
   - Store structured JSON in `document_extractions` table
   - Respects circuit breaker
   - 2s sleep between calls

### Step 4: Verify

```bash
python3 scripts/reextract_documents.py --diagnose
```

"Total classified, not extracted" should now be 0 or near-0.

### Step 5: Report results

Post:
- How many docs were extracted (Phase 2 count)
- How many were stamped schema-less (Phase 1 count)
- Any errors
- Final diagnose output

## Important

- Runs against **production DB** — no code changes needed
- Circuit breaker auto-stops at daily cost limit
- If it stops mid-run due to circuit breaker, just re-run the next day — it picks up where it left off (only processes docs with `extracted_at IS NULL`)
- Expected runtime: ~2-3 hours for 3,000 docs (2s sleep between each)
- No git commit needed — this is a data operation, not a code change
