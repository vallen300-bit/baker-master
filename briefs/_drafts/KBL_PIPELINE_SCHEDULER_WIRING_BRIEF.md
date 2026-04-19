# KBL_PIPELINE_SCHEDULER_WIRING — Brief for Code Brisen #1

**Author:** AI Head
**Reviewer (brief):** B2
**Implementer:** B1 (after B2 approves this brief)
**Target PR:** #18 (base: `main`; branch: `kbl-pipeline-scheduler-wiring`)
**Prev:** PR #16 STEP7-COMMIT-IMPL merged at `20370e7e`. All 7 pipeline steps on main.

---

## Why — the blocker I found during AI Head refresh (2026-04-19 late afternoon)

Prior handover said shadow-mode go-live = "flip `KBL_FLAGS_PIPELINE_ENABLED=true` on Render + `BAKER_VAULT_DISABLE_PUSH=true` on Mac Mini." Verification result:

1. **`KBL_FLAGS_PIPELINE_ENABLED` does not exist in the codebase.** `grep -rn KBL_FLAGS_PIPELINE_ENABLED --include="*.py"` returns zero hits. There is nothing to flip.
2. **`kbl.pipeline_tick.main()` is still the KBL-A stub** — at `kbl/pipeline_tick.py:197-end` it claims one signal and marks it `classified-deferred` without running Steps 1-6. The real orchestrator is `_process_signal` at `kbl/pipeline_tick.py:78` which correctly chains Steps 1-7 — but **nothing calls it from `main()`**.
3. **No scheduler registers `kbl.pipeline_tick.main` on Render.** Render has 42 scheduled jobs (via existing APScheduler); none are the KBL pipeline.
4. **Mac Mini's `com.brisen.baker.poller` only runs Step 7** (via `poller.py` which imports `kbl.steps.step7_commit.commit` directly and iterates on `awaiting_commit` rows). Steps 1-6 have no driver.

Net: the pipeline is not actually runnable end-to-end today. Going "live" without this PR means signals sit at `pending` forever.

---

## Architectural boundary — Render vs. Mac Mini

Inv 9: Mac Mini is single writer to `~/baker-vault`. Step 7 writes files there. **Step 7 cannot run on Render** (no vault clone, no flock target).

Split:
- **Render** — runs Steps 1-6 per tick. Stops at `awaiting_commit`.
- **Mac Mini** — `poller.py` claims `awaiting_commit` rows and runs Step 7. Already deployed by B3.

Existing `_process_signal` (lines 78-191) chains 1-7 — correct for tests + local dev but wrong for Render. We need a variant that stops after Step 6.

### Design — Option B (chosen)

Extract a new `_process_signal_remote(signal_id, conn)` that runs Steps 1-6 only. Keep `_process_signal` as-is (still covers 1-7 for tests + any future same-host run). Render's `main()` calls `_process_signal_remote`; Mac Mini poller already calls `step7_commit.commit` directly — no change to the poller.

Rationale vs. alternatives:
- **A (env-gated Step 7 skip inside `_process_signal`)** — conditional branching inside orchestrator; harder to reason about at test time.
- **C (separate Step-7-only entrypoint `step7_tick`)** — duplicates what `poller.py` already does.
- **B** — cleanest separation, minimal surface, leaves tests + existing poller untouched.

---

## Scope

### IN

1. **`kbl/pipeline_tick.py` — new function `_process_signal_remote(signal_id, conn)`:**
   - Copy of `_process_signal` lines 104-173 (Steps 1-6 block). Drops Step 7 call + the pre-Step-7 status-gate check (lines 175-191).
   - Terminal states it can produce: `routed_inbox` (Step 1 low score), `paused_cost_cap` (Step 5 cost gate), `finalize_failed` (Step 6 exhausted retries), or `awaiting_commit` (success — Mac Mini takes over).
   - Docstring: "Steps 1-6 only. Step 7 runs on Mac Mini via poller.py. Do not call from Mac Mini."

2. **`kbl/pipeline_tick.py` — rewrite `main()`:**
   - Remove the KBL-A stub (lines 220-241: the `emit_log("WARN", ..., "KBL-A stub...")` + `UPDATE status = 'classified-deferred'` block).
   - Add env gate at top of `main()` (after the two circuit checks):
     ```python
     if os.environ.get("KBL_FLAGS_PIPELINE_ENABLED", "false").lower() != "true":
         _local.info("pipeline disabled via KBL_FLAGS_PIPELINE_ENABLED; skipping tick")
         return 0
     ```
   - After `claim_one_signal`, call `_process_signal_remote(signal_id, conn)` inside a try/except that routes unexpected exceptions to `emit_log("ERROR", ...)` and re-raises. The tx-boundary contract stays inside `_process_signal_remote`.
   - `import os` at top if not already present.

3. **Register in Render's APScheduler:**
   - Find the existing scheduler bootstrap (likely `app.py` lifespan / startup — grep `add_job\|APScheduler` in `app.py` + `sentinels/`). Add one job:
     ```python
     scheduler.add_job(
         func=kbl_pipeline_tick_job,
         trigger="interval",
         seconds=int(os.environ.get("KBL_PIPELINE_TICK_INTERVAL_SECONDS", "120")),
         id="kbl_pipeline_tick",
         max_instances=1,
         coalesce=True,
         replace_existing=True,
     )
     ```
   - `kbl_pipeline_tick_job` is a thin wrapper that calls `kbl.pipeline_tick.main()` and logs any non-zero return. Lives alongside the other job wrappers in whatever module they use.
   - Default tick = **120 s** (not 60 s) — each tick claims at most one signal, and Voyage + Opus calls can take 20-30 s, so 120 s gives headroom for a single full pipeline run without overlap (`max_instances=1` already prevents overlap but 120 s reduces backpressure on long Step 5 calls).
   - Include in `/health` scheduled_jobs count (no explicit code — APScheduler already exposes the count).

4. **Env var documentation:**
   - Add `KBL_FLAGS_PIPELINE_ENABLED` + `KBL_PIPELINE_TICK_INTERVAL_SECONDS` to whatever env-docs exist (e.g. `README.md` env section, `.env.example`, or `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md` §9.x — whichever is canonical; B1 pick based on where other KBL envs live).
   - `KBL_FLAGS_PIPELINE_ENABLED` must default to `"false"` for ALL environments. Opt-in only.

5. **Tests** — `tests/test_pipeline_tick.py` (7 total, per B2 S2):
   - `test_main_disabled_returns_zero_without_claim` — with `KBL_FLAGS_PIPELINE_ENABLED` unset OR `"false"`, `main()` returns 0 and does NOT call `claim_one_signal`. Mock `claim_one_signal` and assert `call_count == 0`.
   - `test_main_enabled_claims_and_processes` — with `KBL_FLAGS_PIPELINE_ENABLED="true"`, `main()` calls `_process_signal_remote` with the claimed id. Mock `_process_signal_remote`.
   - `test_remote_variant_stops_at_awaiting_commit` — fixture signal at `awaiting_extract`; run `_process_signal_remote`; assert final status is `awaiting_commit` (not `completed`) and Step 7 mock was NOT called.
   - `test_remote_variant_handles_routed_inbox` — Step 1 low score → `routed_inbox` terminal; `_process_signal_remote` returns without calling Steps 2-6.
   - `test_main_circuit_breaker_precedes_env_gate` — when `anthropic_circuit_open == "true"` OR `cost_circuit_open == "true"`, `main()` returns 0 even with `KBL_FLAGS_PIPELINE_ENABLED="true"`, AND does NOT call `claim_one_signal`. Asserts circuit checks run before the env-gate (existing order in `main()` lines 197-206) is preserved.
   - `test_remote_variant_stops_at_paused_cost_cap` — fixture signal routed through Step 5 with cost gate denied; `_process_signal_remote` returns cleanly; final signal status is `paused_cost_cap`; Step 6 mock NOT called; no exception raised.
   - `test_remote_variant_stops_at_finalize_failed` — fixture signal routed through Step 6 with 3 retries exhausted (terminal `finalize_failed` flip committed by Step 6 internally per its docstring); `_process_signal_remote` returns cleanly (Step 6 re-raise propagates, but caller-owned rollback leaves the Step-6-internal commit intact); final status stays `finalize_failed`; Step 7 driver (not-in-this-variant) never invoked.

6. **Pre-merge Mac Mini verification** — mandatory gate before B2 APPROVES or AI Head merges PR #18 (per B2 S1):

   The brief's architectural premise is that Mac Mini's `com.brisen.baker.poller` invokes a Step-7-only loop (`/Users/dimitry/baker-pipeline/poller.py` importing `kbl.steps.step7_commit.commit` directly), NOT `python3 -m kbl.pipeline_tick`. That script lives on Mac Mini disk only and is not tracked in the repo, so the claim must be verified against live state before merge.

   Run (AI Head or B1, paste output into PR #18 comments):

   ```bash
   ssh macmini 'cat ~/Library/LaunchAgents/com.brisen.baker.poller.plist | grep -A3 ProgramArguments'
   ssh macmini 'cat /Users/dimitry/baker-pipeline/poller-wrapper.sh'
   ssh macmini 'grep -nE "from kbl|import kbl" /Users/dimitry/baker-pipeline/poller.py'
   ```

   **Required outputs:**
   - plist `ProgramArguments` → `poller-wrapper.sh` (not `python3 -m kbl.pipeline_tick`).
   - `poller-wrapper.sh` → `exec /usr/bin/python3 ${HOME}/baker-pipeline/poller.py` (not pipeline_tick module).
   - `poller.py` imports → `from kbl.steps.step7_commit import commit` AND `from kbl.exceptions import CommitError, VaultLockTimeoutError` (NOT `from kbl.pipeline_tick import ...`).

   **If any check fails:** BLOCK merge immediately. Cut a new prerequisite brief `MAC_MINI_STEP7_POLLER_IMPL` (install a dedicated Step-7-only poller on Mac Mini; <10 lines of Python) and land it BEFORE PR #18 can merge. Signals would otherwise pile at `awaiting_commit` with no driver post-shadow-flip.

### OUT (explicit non-goals)

- **Do NOT touch `_process_signal` (lines 78-194).** The full 1-7 variant stays for tests + local dev. Tests against the full path are assets.
- **Do NOT modify `poller.py` on Mac Mini.** It already processes `awaiting_commit` correctly. Zero change there.
- **Do NOT flip `KBL_FLAGS_PIPELINE_ENABLED=true` on Render in this PR.** That flip is a separate Director action after PR merges + dashboard MVP (PR #17) lands. Keep the gate default-closed.
- **Do NOT add a `KBL_HOST` / `KBL_ROLE` env var.** Design uses function-dispatch boundary (different `main()` vs `poller.py` imports), not runtime env branching.
- **Do NOT add metrics endpoints.** Dashboard MVP (PR #17, in-flight B1 rail #1) handles observability.

---

## Hard constraints

- **Tx-boundary contract preserved.** `_process_signal_remote` follows the same per-step `conn.commit()` on success + `conn.rollback()` on raise pattern as `_process_signal`. Do not collapse commits.
- **No change to step function signatures.** Each step still takes `(signal_id, conn)` and writes state + ledger within its own cursor.
- **`main()` return code 0 on success OR on disabled.** Non-zero only on unexpected crash. (APScheduler logs non-zero but treats any return value as success for its purposes — we reserve non-zero for ops visibility.)
- **Idempotent re-runs.** If a tick fires twice on the same signal (APScheduler race), the `claim_one_signal` `FOR UPDATE SKIP LOCKED` guarantees only one wins. Do not add duplicate guards.

---

## CHANDA pre-push

- **Q1 Loop Test:** does not touch Leg 1 (Gold reading — Step 1's problem), Leg 2 (ledger writes — steps' problem), or Leg 3 (hot.md + ledger reading — Step 1 again). Pure wiring change. **Pass.**
- **Q2 Wish Test:** without this PR, the compounding loop cannot run at all (no driver). With it, shadow mode becomes flippable. Serves the wish directly. **Pass.**
- **Inv 4:** no agent touches `author: director` files. N/A.
- **Inv 9:** **explicitly honored** — Render never calls Step 7. Mac Mini stays single writer.
- **Inv 10:** no prompt self-modification. Code-only change to orchestration. **Pass.**

---

## Branch + PR

- Branch: `kbl-pipeline-scheduler-wiring`
- Base: `main`
- PR title: `KBL_PIPELINE_SCHEDULER_WIRING: wire Steps 1-6 into APScheduler; env-gated`
- Target PR: #18

## Reviewer (PR)

B2 — full review incl. CHANDA invariants, tx-boundary audit, scheduler-job max_instances correctness, env-default-closed audit.

## Timeline

~60-90 min B1. Focused surface: one new function (~40 lines), `main()` rewrite (~15 lines), one APScheduler registration (~10 lines), 4 tests (~80 lines).

## Dispatch back (template for B1)

> B1 KBL_PIPELINE_SCHEDULER_WIRING shipped — PR #18 open, branch `kbl-pipeline-scheduler-wiring`, head `<SHA>`, <N>/<N> tests green. Steps 1-6 wired via `_process_signal_remote`; `main()` env-gated on `KBL_FLAGS_PIPELINE_ENABLED` (default closed); APScheduler job `kbl_pipeline_tick` registered at 120 s. Step 7 unchanged — Mac Mini poller still owns it. Ready for B2 review.

## After this task

- B2 reviews PR #18 → auto-merge on APPROVE
- Director flips `KBL_FLAGS_PIPELINE_ENABLED=true` on Render
- Dashboard (PR #17) shows first signals moving through the state table
- After ~24 h stable burn-in with `BAKER_VAULT_DISABLE_PUSH=true` on Mac Mini: Director flips disable-push off → production

---

*Authored 2026-04-19 (late afternoon) by AI Head. Routed to B2 for brief review before B1 dispatch.*
