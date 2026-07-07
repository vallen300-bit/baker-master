---
brief_id: BAKER_OS_V2_C3_GATE_RUNNER_1
attempt: 2
branch: b3/c3-gate-runner-harness
pr: 474
reply_topic: baker-os-v2/c3-gate-runner
dispatched_by: lead
reason_for_checkpoint: context ~45%, 50%-refresh rule (#5918) + lead order #5959; attempt-2 claimed 2026-07-07 per respawn #5966
---

# C3 GATE-RUNNER R1-R4 harness — checkpoint (attempt 1)

## What's done
- Full harness shipped: `scripts/c3_gate/` = `c3_lib.py` + `r1_fast_lane.py` +
  `r2_coded_reply_dedup.py` + `r3_receipt_writeback.py` + `r4_nudge_stop_on_landing.py`
  + `README.md`. `.gitignore` ignores `scripts/c3_gate/_runs/`.
- Committed @12f5e10e, pushed, **PR #474** open against main.
- Validated locally: py_compile ×5, `--dry` ×4 (no DB), `--run` guard (needs
  `C3_HARNESS_LIVE=1`), no-DB-env fail-loud, `check_singletons.sh` clean.
- Lead rulings already wired: Q1a receipt-row evidence (R3), Q2 BOTH-sequenced
  DB, Q3 direct `email_messages` INSERT (cleared by b2 #5935 + b4 #5937).
- DONE posted #5946.

## What's left — codex GATE FAIL #5956 / lead #5959: 4 fixes, then re-gate
- **HIGH-1 unify DB contract.** `bridge.run_tick()` uses the global
  `SentinelStoreBack` pool (reads `POSTGRES_*` config), NOT the harness admin
  conn (`TEST_DATABASE_URL`/`DATABASE_URL`). They can point at DIFFERENT DBs →
  run_tick writes one, harness reads another. Fix: before run_tick, point the
  global store at the SAME `db_url()` (mirror the `tier_b_test_store` fixture in
  `tests/conftest.py` / `tests/test_box5_ticketing_runner.py` — it repoints
  `SentinelStoreBack._get_global_instance` at the test DB) OR pass the conn
  through. R1/R2 (which call run_tick) are affected; R3/R4 call flow fns with the
  passed conn so they're fine — but align the whole lib on one explicit DSN.
- **HIGH-2 scope the live path.** `fetch_email_arrivals` sweeps ALL matching rows
  since the real `airport_ticketing:email` cursor AND advances it. On live that
  (a) processes real un-ticketed emails, (b) moves the real cursor. Fix: in the
  harness, snapshot `trigger_watermarks` (source = `bridge._WATERMARK_SOURCE`)
  before the run and RESTORE it in `cleanup`, and constrain the run to
  `c3-gate-` rows (codex flags 1 real matching row at risk right now).
- **MED-1 registry seed unmarked/unremoved.** `register_code` writes a
  `project_registry` row that `cleanup` never deletes. Mark + delete it in
  cleanup — but ONLY on the test branch (`not is_live_target()`); NEVER delete
  the real BB-AUK-001 registry row on live.
- **MED-2 R2 pass bar.** `r2_coded_reply_dedup.run()` computes `continuity` then
  omits it from the pass condition. Add thread-continuity to the R2 PASS bar.

## Key paths / commits
- Work branch `b3/c3-gate-runner-harness` @12f5e10e (PR #474).
- Harness dir `scripts/c3_gate/`. Fix targets: `c3_lib.py` (HIGH-1 global-store
  repoint helper + HIGH-2 watermark snapshot/restore in cleanup + MED-1 registry
  cleanup), `r2_coded_reply_dedup.py` (MED-2 pass bar).
- Reference for the DB-repoint pattern: `tests/test_box5_ticketing_runner.py`
  `runner`/`hard_lane` fixtures + `tier_b_test_store` in `tests/conftest.py`.
- Codex full verdict: bus #5956. Lead directive: bus #5959.

## Next concrete step (start here in the fresh seat)
1. Read `tests/conftest.py` `tier_b_test_store` to learn the exact global-store
   repoint call; add a `c3_lib.bind_global_store()` that repoints the global
   `SentinelStoreBack` at `db_url()` and call it in `main_scaffold` before
   `run_fn` (HIGH-1).
2. Add watermark snapshot/restore around the run in `main_scaffold`/`cleanup`
   (HIGH-2).
3. Add test-branch-only registry cleanup (MED-1). Fix R2 pass bar (MED-2).
4. Re-validate `--dry` ×4 + compile + singletons; commit NEW commit (never
   amend); push; post re-gate request to codex on topic
   `gate/c3-gate-runner-g3` (medium); update this checkpoint or mark done.

## Claim discipline
Successor claims by bumping `attempt:` in this file with a commit. If `attempt`
is already >1 from another session, stand down. At `attempt >= 3`, stop and
escalate to lead with checkpoint path + last error.
