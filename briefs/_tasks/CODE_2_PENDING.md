# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-19 (evening)
**Status:** OPEN — two queued reviews, run in order

---

## Task 1 (first): MIGRATION_RUNNER_1 brief review

B3 authored at `cd0cdfe`. Brief: `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md`. Director ratified **ship-now** path (not park). B2 brief review gates B1 implementation.

### Verdict focus

- **Module location** — `config/migration_runner.py` vs alternatives. Co-located with `settings.py`. Sound?
- **Connection independence** — runner uses own `psycopg2.connect(DATABASE_URL)`, NOT `_get_store()`. Mirrors `kbl/db.py` rationale (avoid Qdrant/Voyage bootstrap drag). Correct choice?
- **Integration point** — `outputs/dashboard.py:329 @app.on_event("startup")`, inserted between store-init and `start_scheduler()` call. Order preserved via AST assertion test #5. Sufficient?
- **Mac Mini excluded by design** — explicit non-goal. Rationale: Render is single schema writer; dual writers could half-apply a file racing on `schema_migrations` inserts. Does the brief state this clearly enough?
- **sha256 mismatch aborts startup** — fail-loud on modified migration file. Is the "reapply by `DELETE FROM schema_migrations WHERE filename='...'`" rollback path clearly documented?
- **Inline DDL in `memory/store_back.py` (people_issues, ideas, generated_documents, AND the kbl_cost_ledger + kbl_log now in today's migration) — flagged as follow-up out-of-scope.** Is the scope boundary defensible or should it be in-scope?
- **Test plan** — 5 tests enumerated. Adequate? Any missing edge case? (e.g., two services starting simultaneously — does the runner handle the race? Brief may need a §5 note.)
- **CHANDA pre-push** — Q1/Q2 + Inv 4/8/9/10. Correctly reasoned?

### Deliverable

APPROVE or REDIRECT with concrete foldable changes. File at `briefs/_reports/B2_migration_runner_brief_review_20260419.md`.

On APPROVE: AI Head dispatches B1 for PR implementation (~90 min).

### ~20-30 min.

---

## Task 2 (second): PR #19 KBL_DASHBOARD_COST_ROLLUP_HOTFIX review (after B1 ships)

B1 amended `outputs/dashboard.py` to rename `created_at` → `ts` in two SQL queries for the `/api/kbl/cost-rollup` endpoint. `kbl_cost_ledger` actual column is `ts` per `memory/store_back.py:6514`. This hotfix is a follow-up to your own sanity-check note.

### Verdict focus

- Both lines renamed correctly (10887 + 10897).
- No drive-by changes outside those two lines + test update.
- No OTHER kbl_cost_ledger / kbl_log column-name drift in the file (B1 was asked to grep).
- Tests cover the fix in a way that would catch future drift.
- CI green (or trust B1's report given local py3.9 blocker).

### Verdict

APPROVE or REDIRECT. File at `briefs/_reports/B2_pr19_cost_rollup_hotfix_review_20260419.md`.

On APPROVE + MERGEABLE: AI Head auto-merges. `/cost-rollup` endpoint live. All 4 KBL Pipeline widgets functional.

### ~10 min.

---

## Working-tree reminder

Work in `~/bm-b2`. **Quit tab after both reviews ship** — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Two reviews chain: brief APPROVE unblocks B1 for MIGRATION_RUNNER_1 impl (~90 min task, next queue); PR #19 review = tiny same-branch-style hotfix (~10 min).*
