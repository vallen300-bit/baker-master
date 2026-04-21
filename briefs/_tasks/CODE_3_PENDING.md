# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-21 evening
**Status:** OPEN — review PR #33 `BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1`

---

## Target

- **PR:** https://github.com/vallen300-bit/baker-master/pull/33
- **Branch:** `bridge-hot-md-match-type-repair-1`
- **Head commits:** `cb37867` + `1d650b1`
- **Author:** B2
- **Author's ship report:** `briefs/_reports/B2_bridge_hot_md_match_type_repair_20260421.md`
- **Upstream substrate:** `briefs/_reports/B2_bridge_hot_md_match_drift_20260421.md` (earlier diagnostic, ratified direction)

## Context (one paragraph)

Bridge has been dead ~4h with `invalid input syntax for type boolean: "Lilienmatt"` — hot_md_match column is BOOLEAN in live DB (pre-existing bootstrap from KBL-19 era) while PR #29's `ADD COLUMN IF NOT EXISTS hot_md_match TEXT` silently no-op'd. This PR flips live column BOOLEAN → TEXT, fixes bootstrap DDL to match, adds self-healing reconciliation for deployed instances, and tests three layers. Today's 4-bug drift cluster closes with this PR (#30 + #31 + #32 already merged).

## Focus items for review

1. **Idempotency of the `ALTER COLUMN ... TYPE TEXT` migration.** DO-block guarded by `data_type='boolean'` check — confirm re-apply on an already-TEXT DB is a no-op (not just an error-swallow). Ordering (`_b` suffix sorts after original migration) — verify runner applies in intended order.
2. **Bootstrap edit at `memory/store_back.py:6213`.** Confirm `hot_md_match TEXT` in `_ensure_signal_queue_base` matches what the migration produces. Verify no other reference in `store_back.py` still declares BOOLEAN (drift rule: grep mandatory).
3. **`_ensure_signal_queue_additions` reconciliation helper.** Idempotency: repeated boots must be no-ops. Advisory-lock / `pg_typeof` guard structured correctly. Mirrors the existing status-CHECK re-assertion pattern cited in the ship report — verify symmetry is real, not prose-only.
4. **Migration-vs-bootstrap DDL drift rule compliance** (`memory/feedback_migration_bootstrap_drift.md`). Two sites for `hot_md_match` in `store_back.py` — both must land on TEXT. Fifteen minutes of grep for any other column affected adjacent to this change.
5. **Tests (`tests/test_hot_md_match_type_repair.py`).** 7 parse-level + 4 live-PG. Live-PG tests should cover: (a) fresh DB path ends TEXT, (b) legacy BOOLEAN DB path self-heals to TEXT, (c) `pg_typeof` post-ensure-chain assertion, (d) bridge INSERT of TEXT value succeeds. Confirm each is present and exercises what it claims.
6. **Data-loss surface.** Pre-fix audit: 16/16 rows `hot_md_match IS NULL` — `::text` cast is effectively a rename. Confirm assertion holds in ship report + in migration comments.
7. **No scope creep.** Only files touched: the new migration, `store_back.py` (two targeted edits), the new test file. No bridge code changes. No step-consumer changes.

## Deliverable

- Verdict: `APPROVE` / `APPROVE_WITH_NITS` / `REQUEST_CHANGES` on PR #33.
- Report: `briefs/_reports/B3_pr33_bridge_hot_md_match_type_repair_review_20260421.md`.
- Include: per-focus-item verdict, any nits inline on PR (non-blocking) vs. blocking in report, grep evidence for drift-rule compliance.

## Gate

- **Tier A auto-merge on APPROVE (clean mergeable, no blockers).**
- APPROVE_WITH_NITS: AI Head reviews nits before merge; merge if all are non-blocking.
- REQUEST_CHANGES: back to B2 with your delta.

## Working dir

`~/bm-b3`. `git pull -q` before starting.

— AI Head
