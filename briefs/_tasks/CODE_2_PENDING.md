# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-19 (evening)
**Status:** OPEN — post-B1-migration schema sanity-check

---

## Task: KBL_MIGRATIONS_SANITY_CHECK — verify production Neon schema matches KBL-B expectations

### Context

B1 applied 9 migration files + 3 ad-hoc PR #16 ALTERs to production Neon (`briefs/_tasks/CODE_1_PENDING.md` → report at `briefs/_reports/B1_kbl_migrations_apply_20260419.md`). Before we let signals actually flow through the pipeline, AI Head wants independent schema verification against the KBL-B code expectations.

### Scope

Run the following against production Neon (pull `DATABASE_URL` from Mac Mini `~/.kbl.env` via ssh, or from Render API via 1Password):

1. **Per-step write column coverage audit.** For each step's `.py` source file, identify every `UPDATE signal_queue SET <col>` + `INSERT INTO signal_queue (<cols>)` + `ALTER TABLE signal_queue` statement. Confirm each referenced column exists in the applied-schema's `signal_queue`. Flag any mismatch.
   - Steps to audit: `kbl/layer0.py`, `kbl/steps/step1_triage.py`, `step2_resolve.py`, `step3_extract.py`, `step4_classify.py`, `step5_opus.py`, `step6_finalize.py`, `step7_commit.py`.

2. **kbl_cost_ledger shape vs `kbl/cost_gate.py` writes.** Inspect `INSERT INTO kbl_cost_ledger (...)` calls in `kbl/cost_gate.py`; confirm every column referenced exists in applied schema. Flag mismatch.

3. **kbl_cross_link_queue shape vs `kbl/steps/step6_finalize.py` UPSERTs.** Same audit — `INSERT INTO kbl_cross_link_queue` + any UPSERT ON CONFLICT columns must exist in applied schema.

4. **kbl_log and kbl_feedback_ledger presence.** Confirm these tables exist post-migration (they should be in `20260418_loop_infrastructure.sql`). If EITHER is missing, that's a CHANDA §2 Leg 2 blocker — flag loudly, do NOT approve.

5. **CHECK constraint on signal_queue.status.** Must list 34 values per PR #12. Paste `pg_get_constraintdef` output in report.

6. **Index coverage on hot paths.**
   - `signal_queue.committed_at` (silver-landed endpoint query)
   - `signal_queue.status` (claim_one_signal FOR UPDATE SKIP LOCKED)
   - `kbl_cost_ledger.created_at` (cost-rollup 24h window)
   - Flag any missing-but-expected index as N-level (not blocking).

7. **Cross-check against B1's self-report.** B1's report has its own verification queries; compare outputs for drift (e.g., B1 reported column X present, your query shows column X present → match; else flag).

### Deliverable

Verdict at `briefs/_reports/B2_kbl_migrations_sanity_20260419.md`:
- APPROVE (schema matches code expectations) OR REDIRECT (one or more concrete mismatches).
- Full query outputs inline.
- Any N-level observations (missing indexes, naming inconsistencies).

### Timeline

~20-30 min.

### On APPROVE

AI Head flags to Director: shadow mode truly live + functional. First real signal will complete cleanly when it arrives. Standing down until the first signal lands or Director asks.

### On REDIRECT

AI Head takes the mismatch list back to Director for next action (likely another B1 migration/ALTER task).

---

## Working-tree reminder

Work in `~/bm-b2`. Quit tab after verdict ships — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Parallel to B1's apply — start ~20 min after B1 fires, or read B1's report first if it's already landed.*
