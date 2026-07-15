# B1 ship report — RECEIPT_WRITE_DURABILITY_1

- **Brief:** `briefs/BRIEF_RECEIPT_WRITE_DURABILITY_1.md` (baker-master @origin/main), authored deputy, lead-PASSed.
- **Dispatch:** bus #11253 from `lead`, topic `case-one/delivery-backlog-triage` (acked).
- **Target repo:** brisen-lab. **PR:** https://github.com/vallen300-bit/brisen-lab/pull/144
- **Branch:** `b1/receipt-write-durability-1` @ commit `04a27d6` (off origin/main `3cd2aa1`).
- **Files:** `db.py`, `semantic_delivery_evaluator.py`, `tests/test_case_one_p5_delivery_confirmation.py`.

## Done rubric (brief §Quality Checkpoints)

1. **R1 durable write** ✅ — `record_delivery_receipts_sync` retries the recycled-conn/transient class (`OperationalError`/`InterfaceError`/`PoolError`/`BusPoolExhausted`) bounded (default 3, env `BRISEN_LAB_RECEIPT_WRITE_ATTEMPTS` override, clamped [1,10]) + idempotent (ON CONFLICT preserved). Rollback+putconn per failed attempt handled by `get_conn`'s context manager (we hold no conn between attempts). Fail-loud structured `[delivery_receipt] receipt_write_dropped msg_ids=… recipients=… attempts=… reason=…` on exhaustion, then re-raise. No signature change (callers + tests unaffected). Non-transient errors re-raise immediately (not masked).
2. **R2 epoch anchor** ✅ — all three `gather_db_evidence` filters (:379/:403/:434) anchor on `m.created_at` (join already present in each). Closes finding-3 backfill leak for all rows.
3. **resolve_receipt_epoch fallback decision** ✅ — left on `MIN(posted_at)`, documented **inert** (env override `BRISEN_LAB_RECEIPT_EPOCH` authoritative in prod; fallback only fires when env unset, currently never). Chose document-as-inert over switching to `MIN(m.created_at)`: the leak lives in the consuming queries (now fixed), not epoch resolution; the floor needs no join. (Mnilax: surfaced the choice, not averaged.)
4. **R1 + R2 regression tests** ✅ — each fails pre-fix / passes post-fix; existing suites green.
5. **live AC + POST_DEPLOY_AC_VERDICT v1** — deputy (bus-health owner), post-deploy, per gate plan. Not builder scope.

## Verification (literal pytest, local throwaway PG, python3.12 venv from requirements.txt)

- `tests/test_case_one_p5_delivery_confirmation.py` — **30 passed** (includes 4 new).
- `tests_unit/test_semantic_delivery_evaluator.py` — **36 passed**.
- **R2 honest vertical proof:** the backfill-exclusion test **fails on pre-fix evaluator** (`assert 2 == 1` — the backfill leg leaked), **passes post-fix** (count == 1). Verified by reverting the evaluator to origin/main and rerunning.
- **Broader suite:** 713 passed, 1 skipped, **6 pre-existing failures** (`test_a10_a14_lifecycle::…hermes`, `test_agent_identity_generated::…card_slugs`/`…cowork_bb_desk`, `test_bus_autowake::…cowork_bb_desk`, `test_review_fixes_2026_05_05::fix2`/`fix3`). Confirmed **identical on pristine origin/main** (reverted both my files, rerun the 6 → same failures) — unrelated to this change, local-env artifacts.

## Caller-change consideration (brief R1 note)

No change to `bus.py`. The drain caller (bus.py:2455) already wraps the receipt write best-effort (try/except + swallow+log), so an exhausted write never crashes the drain, and the ON CONFLICT upsert makes the next unacked re-drain self-heal the pin. A caller-side "soft signal" is unnecessary — proven by the `test_r1_drain_survives_receipt_write_failure` integration test (GET /msg/b3 → 200 with the message despite the receipt write raising).

## Deviation from brief (test placement)

Brief filed the R2 regression under `tests_unit/test_semantic_delivery_evaluator.py`. That suite is **pure by contract** (module docstring: "runs WITHOUT a Neon branch — no TEST_DATABASE_URL required") and has no live-PG fixture. The finding-3 proof is inherently a live-seed test (it runs the real `gather_db_evidence` SQL against seeded rows), so it lives in the live-PG suite (`tests/…p5_delivery_confirmation.py`) alongside the R1 tests. Placement change only; the honest vertical proof is unchanged and stronger (real SQL, not a mocked count).

## Gate plan (next)

builder ✅ → **independent verdict BEFORE merge** (codex correctness cross-vendor, seats lifted #9711; or B-code line-review; #9255 holds) → lead merges → deploy (a db.py/evaluator code change DOES trigger a Render build — confirm deployed, item-A ~25-min stall lesson) → deputy live AC + `POST_DEPLOY_AC_VERDICT v1`.
