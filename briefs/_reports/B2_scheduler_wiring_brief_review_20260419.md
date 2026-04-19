# B2 — KBL_PIPELINE_SCHEDULER_WIRING brief review — REDIRECT

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (late afternoon)
**Brief:** `briefs/_drafts/KBL_PIPELINE_SCHEDULER_WIRING_BRIEF.md` @ `16e89e0`
**Target PR:** #18 (`kbl-pipeline-scheduler-wiring`)
**Implementer:** B1 (pending this brief approval)
**Verdict:** **REDIRECT** — one S1 premise-verification issue + one S2 test-coverage gap; everything else is sound.

---

## Bottom line

The architectural split is correct, the env gate is default-closed, the
APScheduler params are right, and the tx-boundary contract is preserved.
But the brief rests on a factual claim about Mac Mini infrastructure that
**cannot be verified from the repo** — and if the claim is wrong, PR #18
ships a pipeline with no Step 7 driver anywhere. One concrete addition to
Scope fixes it.

---

## S1 — Scope gap: "Mac Mini poller already calls step7_commit directly" is unverified

The brief's core architectural premise (§Design, line 36):

> Mac Mini poller already calls `step7_commit.commit` directly — no change to the poller.

And §Scope.2 line 52:

> Step 7 runs on Mac Mini via poller.py. Do not call from Mac Mini.

**Problem:** `poller.py` does not exist in the repo. `grep -rn "poller" kbl/ scripts/ launchd/`
returns zero matches for a Step-7-only driver. The only Mac Mini entry
in the repo is `scripts/kbl-pipeline-tick.sh` → `python3 -m kbl.pipeline_tick`,
which invokes **`main()`** — the very function this PR rewrites to call
`_process_signal_remote` (Steps 1-6 only).

The AI Head handover says `com.brisen.baker.poller.plist` is loaded on
Mac Mini (deployed by B3 in `MAC_MINI_LAUNCHD_PROVISION`), but:

- No `.plist` file by that name exists in `launchd/` in the repo.
- No `poller.py` Python entry point exists.
- No `scripts/kbl-baker-poller.sh` wrapper exists.
- No report in `briefs/_reports/` documents what the plist's `ProgramArguments` actually is.

Three possible ground-truths, **only one of which is safe** for this PR:

| Ground truth | Consequence if this PR merges + `KBL_FLAGS_PIPELINE_ENABLED=true` flips |
|---|---|
| **(a)** Mac Mini's `com.brisen.baker.poller.plist` invokes a real Step-7-only driver (in `~` on Mac Mini, not in the repo) | Safe. But untracked infra = bad hygiene; future redeploy from fresh clone silently breaks Step 7. |
| **(b)** Mac Mini's `com.brisen.baker.poller.plist` invokes `python3 -m kbl.pipeline_tick` (i.e., Mac Mini is still running the full pipeline via the same entrypoint this PR rewrites) | **Broken.** After rewrite, Mac Mini runs Steps 1-6 only. No host runs Step 7. Signals pile at `awaiting_commit` forever. |
| **(c)** Mac Mini's `com.brisen.baker.poller.plist` is loaded but does nothing useful / misconfigured | Same as (b). |

I don't have `ssh macmini` from B2's worktree to verify. B1 can't verify
without Mac Mini access either.

### Concrete fix — add to Scope

Add a new §Scope.6 **Pre-merge verification** item:

> 6. **Verify Mac Mini Step-7 driver.** Before merging PR #18, B1 OR AI
>    Head must run `ssh macmini 'cat ~/Library/LaunchAgents/com.brisen.baker.poller.plist'`
>    (or wherever the plist lives) and confirm `<ProgramArguments>`
>    points to a wrapper script that invokes a function which calls
>    `kbl.steps.step7_commit.commit` **and only that** — NOT
>    `python3 -m kbl.pipeline_tick`. Paste the plist contents + wrapper
>    script into the PR description. If the driver does not exist or
>    invokes `kbl.pipeline_tick`, block merge and dispatch a separate
>    `MAC_MINI_STEP7_POLLER_IMPL` brief to create it (either as `poller.py`
>    in the repo + new wrapper + new plist, committed so it's tracked).

This single add-on catches both ground-truths (b) and (c) before shadow
mode flips. If (a) turns out to be the actual state, at minimum we end
up with the plist contents documented in the PR — which is itself an
improvement over the current untracked state.

### Why I'm not classifying this as "implementation bug" (it's the brief's premise)

This isn't B1's fault-to-be. The brief tells B1 "no change to the poller"
as a hard IN/OUT boundary. Without the verification step, B1 would
correctly skip poller work, land PR #18 clean, tests green — and the
pipeline would still be dead post-flip. The fix belongs in the brief,
not in B1's execution.

---

## S2 — Test plan: three branches missing

The 4 enumerated tests cover the happy paths: disabled/enabled gate +
remote-stops-at-awaiting_commit + remote-routed-inbox. Good foundation.
Missing three branches that materially exercise the tx-boundary in the
new `_process_signal_remote`:

1. **Circuit breaker + env-enabled interaction.**
   - Set `KBL_FLAGS_PIPELINE_ENABLED="true"` AND `anthropic_circuit_open="true"`.
   - Assert: `main()` returns 0 via the circuit check (not the env gate),
     and `_process_signal_remote` is NOT called.
   - Why: the brief puts the env gate AFTER the two circuit checks. If a
     future refactor accidentally hoists the env gate above the circuit
     checks, an open circuit would spend a tick doing nothing useful but
     the log line would be wrong. One test kills that refactor.

2. **Step 5 `paused_cost_cap` clean exit in remote variant.**
   - Fixture signal at `awaiting_opus`. Step 5 mock internally commits
     `paused_cost_cap` and returns (no raise — cost gate hit).
   - Assert: `_process_signal_remote` returns cleanly; Step 6 mock NOT
     called; final status = `paused_cost_cap`.
   - Why: existing `_process_signal` test for this branch relies on the
     status recheck at original lines 156-166, which `_process_signal_remote`
     inherits. But since the brief's "copy of lines 104-173" is ambiguous
     about whether the check is preserved verbatim, explicit coverage
     forces it.

3. **Step 6 `finalize_failed` clean exit in remote variant.**
   - Fixture signal at `awaiting_finalize`. Step 6 mock internally commits
     `finalize_failed` and returns (no raise — 3 retries exhausted per PR #15).
   - Assert: `_process_signal_remote` returns cleanly; final status =
     `finalize_failed`; no post-Step-6 Step-7-gate code runs (there shouldn't
     be any).
   - Why: this is the "Step 6 exits without raising" branch. Brief lists
     `finalize_failed` in "Terminal states it can produce" but doesn't
     test the exit path.

Each test is ~15 lines using the existing mock harness in
`tests/test_pipeline_tick.py`. Total additional surface: ~45 lines.

---

## N-level nits (minor, B1 may or may not fold)

- **N1. Drop dead `step7_commit` import from `_process_signal_remote`.**
  Brief says "Copy of `_process_signal` lines 104-173". Line 108 imports
  `step7_commit`. In the remote variant, step7 is never called — drop
  the import. Avoids loading `kbl/_flock.py` and the git subprocess
  scaffolding on Render, where they do nothing.

- **N2. Module docstring update must be in-scope.** Current
  `kbl/pipeline_tick.py` docstring (lines 1-6) still says "runs it through
  Steps 1-5... Steps 6-7 are not wired yet" — stale since PR #16, and
  about to get staler. Add to Scope.2: "Rewrite module docstring to
  describe both variants: full 1-7 in `_process_signal` (local/tests),
  1-6 in `_process_signal_remote` (Render), Step 7 owned by Mac Mini
  poller." Three sentences, prevents future B2 flagging it again.

- **N3. Specify `misfire_grace_time`** on the new `add_job` call.
  APScheduler default is 1s; if the scheduler is even briefly late
  (GC pause, event loop contention), the tick drops. With
  `coalesce=True` this is mostly covered, but a 30-60s grace is
  conservative and matches existing cadence discipline. Existing
  jobs in `triggers/embedded_scheduler.py` don't set it either — so
  at least document "default grace acceptable because coalesce=True"
  if B1 chooses to skip.

- **N4. Consistency with existing scheduler pattern.** Brief uses
  `trigger="interval", seconds=...`. Every existing job in
  `triggers/embedded_scheduler.py` uses `IntervalTrigger(seconds=...)`
  as a positional arg. Both work; consistency wins. B1 will likely
  match existing pattern on sight — just worth calling out so the
  brief-vs-code diff isn't confusing.

- **N5. Env-gate parsing robustness.** `os.environ.get("KBL_FLAGS_PIPELINE_ENABLED", "false").lower() != "true"`
  will treat `"True"`, `"true"`, `"TRUE"` as enabled (good) but
  `"1"`, `"yes"`, `" true "` (with whitespace) as disabled. YAML emits
  mixed case sometimes; the Mac Mini shell gate is a string compare
  against exactly `"true"`. Consistency = fine. Just document in the
  env-var docs: "must be the literal string `true` (case-insensitive);
  `1` / `yes` / `on` are NOT accepted."

- **N6. Env var `KBL_PIPELINE_TICK_INTERVAL_SECONDS` unparseable value.**
  `int(os.environ.get("KBL_PIPELINE_TICK_INTERVAL_SECONDS", "120"))`
  crashes `ValueError` if someone sets `"2m"` or `"120s"`. On Render's
  dashboard where env vars are typed in, this is a realistic typo.
  Wrap in try/except → fall back to 120 with a WARN emit. 3 lines.

---

## What's right (for the record)

- **Option B is the correct split.** Alternatives A (env-gated skip) and
  C (duplicate `step7_tick`) both have real costs. B's function-level
  separation leaves tests untouched and keeps `_process_signal` as an
  asset for local dev.
- **Env-gate default-closed** is correct: `"false"` fallback + case-insensitive
  "true" comparison. No accidentally-live path.
- **APScheduler params** — `max_instances=1` + `coalesce=True` +
  `replace_existing=True` — are exactly right and consistent with the 20+
  existing jobs in `triggers/embedded_scheduler.py`.
- **120s cadence** is justified: Voyage + Opus calls 20-30s each; 120s
  gives single-tick headroom with `max_instances=1` as belt-and-suspenders.
- **Tx-boundary contract preserved.** Per-step `conn.commit()` on success
  + `conn.rollback()` on raise stays identical in `_process_signal_remote`
  as a copy of lines 104-173 (assuming N1 is applied — else the dead
  import is cosmetic, not functional).
- **Inv 9 explicitly honored.** §CHANDA pre-push calls it out; Render
  never calls Step 7 under this design.
- **"Do NOT touch `_process_signal`"** is the right call for test asset
  preservation.
- **"Do NOT add KBL_HOST/KBL_ROLE"** is the right call for avoiding
  runtime env branching when function-dispatch is cleaner.

---

## Dispatch

**REDIRECT.** One S1 scope add (pre-merge Mac Mini poller verification)
and one S2 test plan expansion (3 missing branches). All other concerns
are N-level and foldable at B1's discretion.

**Lift the REDIRECT when:**
1. Brief §Scope adds item 6 (pre-merge Mac Mini poller plist verification).
2. Brief §Scope.5 enumerates 7 tests (the current 4 + the 3 I flagged in S2).

Nothing else blocks. The architectural design itself is sound — if you
want to APPROVE on those two changes and let B1 fold N1-N6 at discretion,
the PR #18 surface stays at ~60-90 min.

**Recommendation:** AI Head applies the two S-level changes to the brief
in-place (2 min edit), re-commits, re-dispatches to B1. I re-review the
diff at that point (~5 min flip to APPROVE).
