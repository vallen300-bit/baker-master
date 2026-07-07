---
brief_id: BAKER_OS_V2_C3_GATE_RUNNER_1
attempt: 3
branch: b3/c3-gate-runner-harness
pr: 474
reply_topic: baker-os-v2/c3-gate-runner
dispatched_by: lead
reason_for_checkpoint: context ~52% over the 50% line; lead order #6032 = checkpoint+respawn before starting the round-3 residual fix. NOT a failure loop — rounds 1/2/3 each resolved DISTINCT codex findings; attempt-3 successor should PROCEED with the single residual fix below, not stand down.
---

# C3 GATE-RUNNER R1-R4 harness — checkpoint (attempt 1)

## ROUND-4 STATUS — round-3 residual FIX APPLIED (attempt 3, respawn GO #6036)
Codex #6002 residual HIGH (live email sandbox admits real concurrent arrivals) is
FIXED. `c3_lib.sandbox_email_fetch()`/`restore_email_fetch()` wrap
`bridge.fetch_email_arrivals` on live-target runs to return ONLY `c3-gate-` rows;
wired into `main_scaffold` alongside `_DESK` + watermark sandbox (set before run_fn,
restored in `finally`, guard var `email_fetch_orig = None`). A real matching email
arriving mid-run is now dropped before `run_tick` can ticket it under the stub.
Validated: py_compile ×5 + `--dry` ×4 + run-guard + no-DB fail-loud + `check_singletons`
+ behavioral wrapper test (real rows dropped, c3-gate- kept, restore reinstates
unfiltered fetch). Attempt NOT bumped (GO #6036 is the claim). Next: codex round-4
re-gate on `gate/c3-gate-runner-g3`, then lead G4 /security-review → squash-merge.

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

## ROUND-3 RESIDUAL — codex #6001/#6002 (ONE HIGH, all prior fixes CONFIRMED resolved)
Codex round-3 (#6001) VERIFIED resolved: R3/R4 _DESK sandbox, baker_actions payload,
kbl.db/registry get_conn routing, R2 code-less + continuity pass bar. Merge blocked by
ONE residual HIGH only:

- **HIGH — live email sandbox admits real concurrent arrivals.** Pinning the watermark
  (`_SANDBOX_SINCE`) scopes the SINCE cursor, but production `fetch_email_arrivals`
  (orchestrator/airport_ticketing_bridge.py:1409-1424) has NO message_id/source filter —
  it selects EVERY keyword-matching email with `received_date >= since`. A real matching
  email arriving AFTER `_SANDBOX_SINCE` (mid-run) is processed under stubbed bus I/O and
  `issue_ticket`/`write_terminal_status` COMMIT a real `airport_tickets` row
  (bridge.py:2450-2480, 2563-2574) that fake-sends. Watermark restore does NOT undo it.

### NEXT CONCRETE STEP (attempt 3 — do exactly this, then re-gate)
1. In `scripts/c3_gate/c3_lib.py` add a `sandbox_email_fetch()` / `restore_email_fetch()`
   pair mirroring `sandbox_boarding_desk()`: on `is_live_target()`, monkeypatch
   `bridge.fetch_email_arrivals` with a wrapper that calls the original then returns ONLY
   rows whose `message_id` startswith `PREFIX` (`c3-gate-`). Return the original fn for
   restore. (run_tick calls the module global `fetch_email_arrivals`, so patching
   `bridge.fetch_email_arrivals` intercepts it. EmailArrival has `.message_id`.)
2. Wire into `main_scaffold`'s live sandbox block: `email_fetch_orig = sandbox_email_fetch()`
   set BEFORE run_fn (alongside the watermark + _DESK sandbox); `restore_email_fetch(email_fetch_orig)`
   in the `finally` next to `restore_boarding_desk`. Guard var init `= None` like the others.
3. Re-validate: py_compile ×5 + `--dry` ×4 + run-guard + `check_singletons.sh`.
4. Commit NEW commit (never amend) + push `b3/c3-gate-runner-harness`; post codex re-gate on
   topic `gate/c3-gate-runner-g3` (round 4); status to lead topic `ship/box5-c3-gate-runner-g3`
   with context %. Update this checkpoint / mark done.
Codex full verdict: bus #6002. Lead fix order: #6032.

## STATUS attempt 2 round-2 — codex #5984 (3 HIGH + 1 MED) fixed @80dd1806, re-gated
- Round-1 (#5956) fixes were @81f365cb (below). Codex re-review (#5983/#5984) FAILED
  with 4 NEW findings; all fixed @80dd1806 (pushed, PR #474):
  - HIGH-1 R3/R4 live scope leak — `sandbox_boarding_desk()` repoints `flow._DESK`
    to `c3-gate-desk` on live (restored in finally); R3/R4 seed with `flow._DESK`.
    Boarding scans (run_receipt_writer/run_boarding_ttl_nudge) now hit ONLY harness rows.
  - HIGH-2 baker_actions `details`->`payload` in `nudge_actions()` + `cleanup()`.
  - HIGH-3 registry DB split — `bind_global_store()` now also routes `kbl.db.get_conn`
    AND the bound `kbl.project_registry_store.get_conn` at `db_url()`.
  - MED-1 R2 reply made code-less (keyword-only) so production thread-continuity fires.
- Validated: py_compile ×5, `--dry` ×4, run-guard, singletons clean. Re-gate → codex
  #5998 topic `gate/c3-gate-runner-g3`. Next: codex G3 → lead G4 /security-review → merge.
- NOTE: no live `--run` executed locally (needs C3_HARNESS_LIVE + a DB); fixes are
  static + dry-validated. Live T2 evidence run stays gated on lead go (#5930).

## (superseded) STATUS attempt 2 — round-1 fixes APPLIED @81f365cb
- HIGH-1 `bind_global_store()` in c3_lib repoints `SentinelStoreBack._get_global_instance`
  at `db_url()` (called in `main_scaffold` before run_fn) — run_tick + trigger_state
  now share the harness DB. `_HarnessStore` shim mirrors conftest `_TestStore`.
- HIGH-2 `snapshot_watermark`/`set_watermark`/`restore_watermark` + `_SANDBOX_SINCE`:
  live-target only, pins email cursor to run-start, injects rows AT that instant,
  restores real cursor in `finally`. Test branch behaviour untouched.
- MED-1 `_REGISTERED_CODES` tracked by `register_code`; `cleanup` deletes them from
  `project_registry` ONLY when `not is_live_target()`.
- MED-2 R2 pass bar now `same_desk and replay_inert and continuity`.
- Validated: py_compile ×5, `--dry` ×4, `check_singletons.sh` clean. Re-gate → codex
  topic `gate/c3-gate-runner-g3`. Remaining: codex G3 re-review → lead G4 /security-review → merge.

## (historical) codex GATE FAIL #5956 / lead #5959: 4 fixes, then re-gate
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
