# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous report:** [`briefs/_reports/B2_kbl_b_skeleton_review_20260418.md`](../_reports/B2_kbl_b_skeleton_review_20260418.md) — REDIRECT (small surface, blockers applied inline)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** KBL-B skeleton review task (shipped)

---

## Task: KBL-B §4-5 Review (I/O contracts + status migration)

AI Head drafted §4 (per-step I/O contracts) and §5 (two-track status migration) post-skeleton ratification. Commits `5ba00c1` + `43d499a` on main. Review before §6-13 builds on top.

### Scope

**IN**
- §4.1-4.9: per-step I/O contracts (reads/writes/ledger/log/invariants per step, plus §4.9 TOAST cleanup)
- §5.1-5.7: two-track status migration design

**OUT**
- §1-3 (already ratified)
- §6-13 (not yet written; forthcoming)
- Code implementation (design review only)

### What to scrutinize

1. **§4 I/O completeness.** Are there reads/writes the steps will need that aren't listed? Specifically: does Step 1 (triage) need to read `source` for the prompt template selection? Does Step 5 (Opus) need `subject` or just `raw_content`?
2. **§4 invariants.** Each step has a one-line invariant. Are any of them wrong, unprovable, or missing (e.g., is there a termination invariant for the whole pipeline)?
3. **§4.9 TOAST cleanup.** Is the same-transaction approach right, or should nulling be a post-commit trigger/deferred task?
4. **§5 compatibility mirror.** Table at §5.3 maps `(stage, state)` → `status` for legacy compat. Does it cover all cases? Do existing KBL-A queries on `status` keep working?
5. **§5 worker claim query.** §5.4 SQL uses `ORDER BY started_at NULLS FIRST, id`. Does this handle fair scheduling correctly, or create starvation risk for signals stuck in retry loops?
6. **§5.6 no-backfill stance.** Is leaving existing pre-KBL-B rows with `status` populated and `stage`+`state` NULL the right call, or does it create dual-read complexity downstream?

### Output format

File: `briefs/_reports/B2_kbl_b_phase2_review_20260418.md`

- **Verdict:** READY / REDIRECT / BLOCK
- **Blockers** / **Should-fix** / **Nice-to-have** / **Questions** (same pattern as prior reviews)

### Time budget

~30 min. If >45 min, ship partial.

### Dispatch back

> B2 KBL-B §4-5 review done — see `briefs/_reports/B2_kbl_b_phase2_review_20260418.md`, commit `<SHA>`. Verdict: <READY | REDIRECT | BLOCK>.

---

*Dispatched 2026-04-18 by AI Head.*
