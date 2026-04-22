# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1
**Task posted:** 2026-04-22 ~12:55 UTC (post PR #41 merge + 13-row recovery)
**Status:** OPEN — `OBSERVABILITY_STEP7_PLUS_POLLER_DOC_1` (closes out B2's observability gaps #2 + #3)

---

## Brief-route note (charter §6A)

Freehand continuation-of-work. Closes the final two items from B2's CORTEX_GATE2 report (observability gaps #2 + #3) that Director cleared under "lets do all outstanding." B1 gets this because you just shipped PR #41 in the `pipeline_tick.py` space and have the surrounding code fresh.

Small brief. 60-90 min. One PR.

---

## Context — what B2's CORTEX_GATE2 diagnostic flagged

After finding the `BAKER_VAULT_DISABLE_PUSH=true` shadow-mode root cause, B2 noted three observability gaps that let the issue fester unseen for 3+ days:

1. **Step 5 log-silent** — CLOSED by B2's PR #42 (10 `emit_log` calls added to `step5_opus.py`).
2. **Step 7 happy-path silent** — `step7_commit.py` only logs on failure; successful commits leave no `kbl_log` trace. **OPEN — this brief.**
3. **`kbl/poller.py` off-tree** — `pipeline_tick.py` docstring references a `kbl/poller.py` module that does not exist in the repo. The actual Mac Mini Step 7 runner lives at `/Users/dimitry/baker-pipeline/poller.py` on Mac Mini — outside the baker-master repo. **OPEN — this brief.**

## Scope — 2 parts, ship together as one PR

### Part A — Step 7 happy-path observability in `kbl/steps/step7_commit.py`

Match `step5_opus.py` (PR #42) and `step6_finalize.py` patterns. Minimum log points:

1. **Entry** — `INFO` on Step 7 entry: `emit_log("INFO", "step7_commit", signal_id, f"step7 entry: target={target_vault_path}")`. Use the same module-constant pattern: `_LOG_COMPONENT = "step7_commit"`.
2. **Vault lock acquired** — `INFO` with `lock_path` + wait time.
3. **Pre-commit guard pass** — `INFO` confirming `_inv4_guard_target_path` passed (Gold file protection).
4. **Files written** — `INFO` with count: main + N stub-link files.
5. **Commit created** — `INFO` with `commit_sha` (short 7-char) + commit message.
6. **Push result** — INFO on push success OR `shadow-mode: skipping git push` INFO if `cfg.disable_push=True`. The existing `logger.info("step7 mock-mode: …")` line (around line 622-627) should be MIRRORED as an `emit_log` so the kbl_log table sees it too. Keep both logs; don't replace `logger.info`.
7. **Row advanced to `awaiting_commit`** — `INFO` with the new status.

Don't over-log. Aim 6-8 call sites. Ship report lists each with file:line.

**Signature:** `emit_log(level, component, signal_id, message)` — match `step6_finalize.py:568-584`.

**ADD-ONLY.** Zero logic change. Do NOT touch:
- `_git_add_commit`, `_git_push_with_retry`, `_atomic_write`, `_append_or_replace_stub`
- The `UPDATE signal_queue SET opus_draft_markdown = NULL, final_markdown = NULL, ...` row at line 260-268
- The `disable_push` branch logic
- Any lock / git-pull-rebase / vault-lock semantics

### Part B — Fix the stale `kbl/poller.py` reference in `pipeline_tick.py`

**Scout first:**
```bash
rg "kbl/poller\.py|from kbl\.poller|kbl\.poller" kbl/pipeline_tick.py
```

You'll find a docstring reference claiming `kbl/poller.py` handles Mac Mini Step 7 reclaim. The file doesn't exist in this repo — the actual runner lives off-tree at `/Users/dimitry/baker-pipeline/poller.py` on Mac Mini.

**Fix:** rewrite the docstring to say something like:

```
# Mac Mini Step 7 reclaim runs via the off-tree poller at
# /Users/dimitry/baker-pipeline/poller.py on Mac Mini
# (LaunchAgent com.brisen.baker.poller, 60s StartInterval).
# That runner calls step7_commit.finalize_one() for awaiting_commit rows.
# The poller is intentionally off-tree because it's Mac-Mini-specific
# infra code, not pipeline logic.
```

Use the exact path + LaunchAgent label above — AI Head verified via SSH earlier today:
- Path: `/Users/dimitry/baker-pipeline/poller.py`
- LaunchAgent: `com.brisen.baker.poller`
- Wrapper: `~/baker-pipeline/poller-wrapper.sh`
- Env source: `~/.kbl.env`
- Interval: 60s (`StartInterval` in `com.brisen.baker.poller.plist`)

No code changes for Part B — docstring/comment only.

## Tests

### Part A tests — `tests/test_step7_commit.py` (or nearest existing test)

3 tests minimum. Mock `emit_log`, run a happy-path commit through a fixture, assert `call_args_list` contains the expected tuples:
1. Entry INFO fires with `target_vault_path` in message.
2. Push-success INFO fires when `cfg.disable_push=False`.
3. Shadow-mode INFO fires when `cfg.disable_push=True` AND `emit_log` WARN NOT called (happy path, not failure).

If no Step 7 test scaffold exists, add one minimal fixture. Don't retrofit a full test suite — out of scope.

### Full pytest gate

Run `pytest tests/`. Baseline post PR #42: `16 failed, 812+3=815 passed, 21 skipped` (wait — actually PR #42 added 3 tests on a branch pre-PR-41, and merged post-PR-41; check current main's post-merge test count yourself via `pytest tests/ 2>&1 | tail -3`).

Expected: your additions = +3 → `16 failed, 818 passed, 21 skipped` (or whatever current baseline + 3 is). Zero new failures.

## Out of scope (explicit)

- **No commit / push logic changes.** Observability-only.
- **No schema changes.**
- **No bringing `kbl/poller.py` into the repo.** The off-tree location is intentional and Director-ratified.
- **No Step 7 happy-path logic tweaks.** Only `emit_log` additions.
- **No changes to `disable_push` default.** Director flipped that on Mac Mini's `~/.kbl.env` at 11:33 UTC; code default stays the same.

## Ship shape

- PR title: `OBSERVABILITY_STEP7_PLUS_POLLER_DOC_1: Step 7 happy-path logging + poller docstring fix`
- Branch: `observability-step7-plus-poller-doc-1`
- Files: `kbl/steps/step7_commit.py` + `kbl/pipeline_tick.py` (docstring) + new/existing step7 test file + ship report. 3-4 files.
- Commit style: one clean commit (match PR #38/#39/#40/#41/#42).
- Ship report path: `briefs/_reports/B1_observability_step7_plus_poller_doc_1_20260422.md`. Include:
  - Part A §before/after (line numbers + 6-8 log call-site listing)
  - Part B §before/after (docstring diff excerpt)
  - Full pytest log head+tail (no "by inspection")
- Tier A auto-merge on B3 APPROVE.

**Timebox:** 90 min.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-22 ~12:56 UTC (parallel-safe with any B2 work; independent of PR #42 deploy)
