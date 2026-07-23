# B1 Ship Report — CORTEX_RETIRE_PHASE1_1

- **Brief:** `briefs/BRIEF_CORTEX_RETIRE_PHASE1_1.md` (Director-ratified Cortex retirement 2026-07-23)
- **Memo:** `briefs/_plans/CORTEX_RETIREMENT_MEMO_2026-07-23.md`
- **Dispatched by:** lead (file-drop, bus #15401)
- **Repo:** `vallen300-bit/baker-master`
- **Branch:** `b1/cortex-retire-phase1-1`
- **SHA:** `37af3760b52fb7b7463c63384e182e6aca640bcb` (ls-remote confirmed)
- **Task class:** production backend, reversible env-flag guard, one repo
- **Done rubric:** gated-merge — builder verifies AC 1-5 → codex gate PASS → lead merges → Render deploys → lead runs live 410 probe. Builder-verified alone ≠ done.

## What shipped

1. **`_cortex_retired()` helper** (`outputs/dashboard.py`) — `os.getenv("CORTEX_RETIRED", "true")`, **DEFAULT TRUE**. Env flag is a rollback lever only. Read at call time (survives Render restart with no env var). Fails **CLOSED** on any env-read exception (treats as retired).

2. **Three cycle-starting surfaces guarded:**
   - `POST /api/cortex/trigger` (`trigger_cortex_cycle`) → `HTTPException(410, "cortex_retired")` at top of handler.
   - `POST /api/cortex/run` (`cortex_run_stream`) → same 410 at top of handler.
   - `_cortex_gate_fire_cycle` (FastAPI **background continuation**) → logs + `return` (never raises, per background-task safety).

3. **Stuck-cycle sentinel registration gated off** (`triggers/embedded_scheduler.py`) — `if _cortex_retired:` skips `add_job` **and** `register_expected_job` for `cortex_stuck_cycle_sentinel`, so the expected-job watchdog won't flag a missing job. Skip logged. Env read locally (not imported from dashboard) to avoid a startup circular import. Mirrors `_cortex_retired()` semantics.

4. **Migration** `migrations/20260723a_close_stuck_cortex_cycles.sql` — data-only sweep: `UPDATE cortex_cycles SET status='rejected' WHERE status='tier_b_pending'`. Expected rowcount **2** (verified 2026-07-23). Idempotent (re-run matches 0 rows). No schema change; tables kept for read-only history.

## Acceptance criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | 410 on all three cycle-starting surfaces, default env (no var set) | PASS — live TestClient smoke: trigger 410, run 410, gate-fire no-op |
| 2 | `CORTEX_RETIRED=false` restores old behavior (rollback proven by test) | PASS — flag-off variants + `test_gate_fire_cycle_runs_when_flag_off` |
| 3 | Sentinel not registered when retired | PASS — AST-walk test proves `add_job`/`register_expected_job` absent from retired branch, present in not-retired branch |
| 4 | Dashboard Cortex history panels still render (no 500s) | PASS — GET routes (events/stats/lint) untouched; guard is on POST + bg fire only |
| 5 | Receipt cites repo+branch+sha, ls-remote confirmed, migration rowcount stated | PASS — this report + bus #15404 |

## Verification (literal)

- `pytest tests/ -k cortex --continue-on-collection-errors` → **384 passed, 11 skipped**. 6 collection errors are **pre-existing, unrelated** modules (substack / brisen_lab_consumer_mcp / brisen_lab_gate4 / dropbox_search / email_attachment / mcp_baker_extension — missing optional deps; none touched by this brief).
- Focused set (`test_cortex_retire_phase1` + trigger/run/stream/gate/sentinel endpoint tests) → **68 passed**.
- Scheduler gate tests (`test_scheduler_liveness_sentinel`, `test_fireflies_scan_gate`, `test_cortex_stuck_cycle_sentinel`) → **60 passed**.
- Live 410 smoke via `TestClient` with **no `CORTEX_RETIRED` env var**: `_cortex_retired()`=True; `/api/cortex/trigger`→410 `{"detail":"cortex_retired"}`; `/api/cortex/run`→410; `_cortex_gate_fire_cycle` returned without awaiting `maybe_run_cycle` (await_count=0), no exception.
- `py_compile` clean on all edited modules.
- `scripts/check_applied_migrations.sh` → exit 0 (new migration not in lock, no drift).

## Not applied by builder / owed downstream

- **Migration** validated for syntax + idempotency but **NOT applied** (no prod DB from builder seat). Lead applies to prod and refreshes `migrations/applied_migrations.lock`. Verification SQL after apply: `SELECT status, count(*) FROM cortex_cycles GROUP BY status` → expect `tier_b_pending = 0`, totals otherwise unchanged (38).
- **POST_DEPLOY_AC_VERDICT** owed after Render deploy (lead runs live 410 probe on prod).

## Untouched (per brief scope)

`orchestrator/cortex_*` (Phase 2), GET cortex routes, applied migration files, `cortex_cycles`/`cortex_phase_outputs` schema, `baker-vault/`.

## Next

Codex seat gate (repo+branch+sha above; reviewer curls guarded routes for 410 body + runs touched tests). Lead merges on PASS.
