# Baker AI Dev — Agent Memory

## Architecture Reviews Completed

### SPECIALIST-UPGRADE-1 (Mar 10, 2026)
- Reviewed original brief, split into Package A (full doc storage) + Package B (intelligence pipeline)
- **Key finding:** Cost estimates in original brief were 5-7x too low
- **Key finding:** Specialist memory table conflicts with existing feedback loop (baker_tasks → _get_capability_feedback)
- **Decision:** Shared baker_insights table instead of per-specialist memory. validated_by field distinguishes Director-confirmed from auto-stored.
- **Must-fix:** ContextBudgetManager needed (can't just remove 2000-char cap). 12K cap for enriched results.
- **Must-fix:** All new Claude calls must wire into api_cost_log + check_circuit_breaker
- **Director decisions:** Contracts/invoices/Nachträge are priority doc types. Shared memory (Baker is one team). Cost is negligible — use Haiku for all extraction.
- **Email attachments:** Must be treated same as Dropbox docs (Director decision #7934)
- Briefs written: BRIEF_SPECIALIST_UPGRADE_1A.md (Package A), BRIEF_SPECIALIST_UPGRADE_1B.md (Package B)

## Codebase Patterns

- Column name mismatches are the #1 recurring bug (started_at vs created_at, received_at vs received_date). Always verify with information_schema.
- Full-text enrichment pattern: Qdrant chunk match → swap with full text from PostgreSQL (already works for emails, meetings, WhatsApp). Package A extends this to documents.
- All migrations use ALTER TABLE ADD COLUMN IF NOT EXISTS (idempotent).
- file_hash uses compute_file_hash() in ingest pipeline — must share, not duplicate.

## Key Tables

- 3,188 existing documents in ingestion_log (need backfill to new documents table)
- capability_sets: 11 domain + 2 meta, 6 have use_thinking=TRUE
- sentinel_health: 9 sentinels tracked (Whoop retired 2026-04-20, Feedly retired 2026-04-20)
