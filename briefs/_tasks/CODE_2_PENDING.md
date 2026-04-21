# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2
**Task posted:** 2026-04-21 evening (post PR #32 merge — critical path to Gate 1)
**Status:** OPEN — BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1

---

## Context

PR #32 merged. Step consumers 1-6 healthy + deployed. Bridge still broken: `alerts_to_signal_bridge` failing every tick with `invalid input syntax for type boolean: "Lilienmatt"`. 15+ alerts backed up waiting to land in signal_queue. Bridge-fix is the one remaining blocker on Gate 1 — existing 16 signals are all destined for `routed_inbox` (Opus out-of-scope), so Gate 1 needs fresh in-scope signals to flow.

Full diagnostic by you earlier today — no re-investigation needed.

## Substrate (YOURS — read first)

`briefs/_reports/B2_bridge_hot_md_match_drift_20260421.md` (commit e3a4ad8).

Everything required to ship is in §"Fix direction — TEXT" and §"Proposed next brief". No decisions left — direction ratified.

## Scope — ship the fix

Ratified direction: live column BOOLEAN → TEXT; match bootstrap DDL; add type-reconciliation helper so already-booted instances self-heal where `ADD COLUMN IF NOT EXISTS` silently no-op'd.

Sequence (from your report §"Proposed next brief"):

1. Write migration `migrations/NNN_alter_hot_md_match_to_text.sql` — `ALTER COLUMN ... TYPE TEXT USING hot_md_match::text`. Wire into the migration runner.
2. Add a boot-time type-reconciliation helper in `_ensure_signal_queue_additions` (or equivalent) so existing deployments self-heal even when the migration ledger says "already applied". Idempotent — `pg_typeof` guard or advisory-lock'd DO block.
3. Fix `memory/store_back.py:6213` — change `hot_md_match BOOLEAN` to `hot_md_match TEXT` in `_ensure_signal_queue_base` so fresh-DB boots are correct from minute zero.
4. Regression test: boot a fresh DB + boot an old DB (legacy BOOLEAN), assert both end TEXT. Assert `pg_typeof(hot_md_match) = 'text'` after full ensure-chain.
5. Follow migration-vs-bootstrap DDL drift rule (`memory/feedback_migration_bootstrap_drift.md`) — grep `store_back.py` for any bootstrap DDL touching columns this migration references, verify type alignment before landing.

## Deliverable

- PR on baker-master, branch `bridge-hot-md-match-type-repair-1`, reviewer B3.
- Ship report at `briefs/_reports/B2_bridge_hot_md_match_type_repair_20260421.md`.
- Include: migration + bootstrap edits summary, regression test output, type-conformance check.

## Recovery (AI Head handles post-merge)

- No rows to reset — 15 stalled alerts drain automatically on first successful bridge tick post-deploy.
- Watch `kbl_log` for bridge errors clearing.
- Fresh signals → in-scope ones reach Step 6 → Mac Mini Step 7 commits → Gate 1 closes.

## Constraints

- **XS effort (<1h)** per your own estimate.
- No touch to bridge code (`kbl/bridge/alerts_to_signal.py`) — already correct.
- No touch to step consumers.
- Migration-vs-bootstrap DDL drift check is mandatory (rule ratified today).
- **Timebox: 60 min.**

## Working dir

`~/bm-b2`. `git pull -q` before starting.

— AI Head
