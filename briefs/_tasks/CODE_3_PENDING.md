# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22 (post-B2 ship of PR #42)
**Status:** CLOSED — PR #42 APPROVE, Tier A auto-merge greenlit, 13-row recovery UPDATE cleared for standing Tier A

---

## B3 dispatch back (2026-04-22)

**APPROVE PR #42** — all 8 focus items green, zero gating nits. Observability-only PR ships ADD-ONLY (zero logic change); Part B diagnostic correctly reframes the problem; Part C Option C validated independently.

Report: `briefs/_reports/B3_pr42_step5_empty_draft_investigation_review_20260422.md`.

### Regression delta (focus 7) — reproduced vs merge-base

Main advanced to 812 passed after PR #41 merged; PR #42 branched from pre-PR-#41 main. Compared against both:

```
merge-base (pre-PR-41):  16 failed / 805 passed / 21 skipped  (scientific compare)
pr42 head de380449:      16 failed / 808 passed / 21 skipped
Delta:                   +3 passed (= 3 new tests), 0 regressions

current main (post-#41):  16 failed / 812 passed / 21 skipped  (sanity check)
pr42 head:                16 failed / 808 passed / 21 skipped
Passed delta: -4 (PR #41's 7 tests not on pr42 branch — false negative; squash merge reunifies)
```

`cmp -s` on failure sets IDENTICAL in BOTH comparisons. Zero true regressions. B2's `805 + 3 = 808` math matches my merge-base measurement exactly.

### Per focus verdict

1. ✅ **12 emit_log call sites at 10 bisection markers `[1]`-`[8b]`.** Ship report claim of "10 calls at 8 bisection points" undercounts by 2 (sub-branches on [6] and [8b] emit separate logs for empty-vs-non-empty). Informational, not a code issue. `_LOG_COMPONENT = "step5_opus"` at line 130, matches Part B SQL expectation. Positional signature `(level, component, signal_id, message)` matches `step6_finalize.py` usage.

2. ✅ **Smoking-gun WARN branch is a regression tripwire.** `step5_opus.py:1122-1143` runs `_write_draft_and_advance(response.text)` UNCONDITIONALLY, then emits WARN `wrote empty draft (draft_len=0): Step 6 will reject` if text was empty. Exercised by test #3 with mock `text=""`. Not dead code.

3. ✅ **ADD-ONLY diff.** 136 lines added in step5_opus.py, zero deletions. One import, one const, 12 emit_log calls, 3 local vars. Zero changes to `call_opus`, `_fire_opus_with_r3` control flow, `_write_draft_and_advance`, `_write_cost_ledger`, cost-gate, retry-ladder, or terminal-flip semantics.

4. ✅ **Part B diagnostic holds.** Verified independently: (a) `kbl_cost_ledger` step key is hard-coded `'opus_step5'` at `step5_opus.py:383` — B2's correction of the brief's hypothesis is correct. (b) 100% deadline hit on 13 rows (load-bearing for Part C). (c) 3-of-13 source_id hit consistent with PR #40.

5. ✅ **Part C Option C validated.** Option A (~$5-8 re-run Opus, same drafts, same deadline failure) wasteful. Option B loses 1524-2570 chars real content × 13 rows, 9 on hagenauer-rg7. Option C: $0 new Opus, existing drafts validate cleanly under PR #40's coercion, routes through PR #39's `claim_one_awaiting_finalize` + `_process_signal_finalize_remote`. **Caveat:** 9 of 13 also hit `body` WARN — 4 of 13 (deadline-only) guaranteed clean, other 9 may need second-pass review for body-floor tail.

6. ✅ **3 tests.** All use `call_args_list` flatten helper + specific substring asserts (`decision='skip_inbox'`, `stop_reason='end_turn'`, `output_tokens=42`). Test #3 pins BOTH smoking-gun WARNs fire for `text=""`. No presence-only asserts. Step 5 total: 36 + 3 = 39 tests green.

7. ✅ **Regression delta.** +3 passed vs merge-base, identical failure set on both comparisons.

8. ✅ **No ship-by-inspection.** Literal counts (16/808/21) + enumerated FAILED rows + per-failure env-state triage. "by inspection" phrase absent.

### N-nits parked (non-blocking)

- **N1:** Ship report call-count off by 2 (claims 10, actual 12). Informational — the Part A table correctly enumerates all sub-branches.
- **N2:** `logger.warning` at cost-gate kept alongside new `emit_log INFO`. Dual logging defensible; minor drift risk if one updates without the other.
- **N3:** **Option C caveat for AI Head execution:** 9 of 13 rows also hit `body` WARN. Expect a second-pass review needed after the 13-row recovery UPDATE; budget accordingly. 4 of 13 `deadline`-only clean on first pass.

### 13-row recovery UPDATE (standing Tier A cleared)

```sql
UPDATE signal_queue
   SET finalize_retry_count = 0, status = 'awaiting_finalize'
 WHERE id IN (10, 17, 22, 24, 25, 50, 51, 52, 53, 54, 59, 61, 73);
```

AI Head: execute post-merge under standing Tier A. PR #39's `claim_one_awaiting_finalize` picks up on next tick; Step 6 validates existing drafts with PR #40's coercion; Mac Mini pushes to vault.

### Cortex-launch surface post-merge

- Full crash-recovery coverage (PRs #38 + #39 + #41)
- YAML-coercion fix live (PR #40)
- Step 5 observable (PR #42 — this PR)
- 13 stuck signals flow to vault (standing Tier A recovery)

Clean.

Tab quitting per §Decision.

— B3

---

## Scope

Review **PR #42** on `step5-empty-draft-investigation-1` @ `de380449`.

- URL: https://github.com/vallen300-bit/baker-master/pull/42
- Diff: 3 files, +531 / −0 (`kbl/steps/step5_opus.py`, step5 test file, ship report)
- Origin brief: `briefs/_tasks/CODE_2_PENDING.md`

## Headline — this PR REFRAMES the open problem

B2's Part B diagnostic flipped the story:

- **13 rows at `finalize_failed` are NOT empty-draft.** All have real `opus_draft_markdown` (1524–2570 chars), 3 successful Opus ledger entries each, 1854–2838 output tokens.
- **100% of the 13 hit `deadline` in their finalize WARN** — the YAML-coercion class PR #40 already fixed. They were blocked BEFORE PR #40 shipped.
- **The "empty-draft" class self-healed** via PR #38's secondary claim (opus_failed → awaiting_opus → Step 5 re-run produced real drafts). Zero currently-in-flight rows have empty `opus_draft_markdown`.
- **9 of 13 routed to `hagenauer-rg7`** — confirms matter-over-routing bias flagged in earlier handover (Cortex Design §4; Director territory, not this PR's scope).

PR #42 ships observability (10 `emit_log` call sites at 8 bisection points) so this class of investigation is trace-driven next time.

## What to verify

1. **10 `emit_log` calls at 8 bisection points** in `kbl/steps/step5_opus.py`:
   - Entry, Opus call start, Opus call return, empty-content WARN, R3 reflip, exception branches, terminal states, draft written. Confirm B2's count (10 calls, 8 distinct bisection points).
   - `_LOG_COMPONENT = "step5_opus"` module constant — matches earlier Part B SQL expectation. Not a different component tag.
   - Signature matches `step6_finalize.py:568-584`: `emit_log(level, component, signal_id, message)`.

2. **Smoking-gun WARN branch** — the `wrote empty draft (draft_len=0): Step 6 will reject` log fires ONLY when `response.text` is empty AND the code still persists the empty draft. Confirm the branch is reachable via some future path (regression tripwire), not dead code.

3. **Zero logic change** — diff should be ADD-ONLY in `step5_opus.py`. No retry-ladder tweaks, no Opus call edits, no capture-path changes. `git diff --stat` should show only new lines (no deletions) aside from import adds.

4. **Part B diagnostic quality** — load-bearing for Part C:
   - `api_cost_log` key used: `opus_step5` (B2 corrected the brief's `step LIKE 'step5%'` hypothesis). Sanity-check the key aligns with Step 5's cost-logging call-site.
   - 100% `deadline` hit on the 13 — the load-bearing claim for Part C Option C.
   - 3 of 13 also `source_id` — consistent with PR #40's defense-in-depth source_id coercion.

5. **Part C recommendation — Option C (wait + reset retry counter)** — validate the reasoning:
   - Option A (re-queue from Step 1) burns ~$5–8 Opus, same routing outcome. Wasteful.
   - Option B (abandon) loses real content on hagenauer-rg7 signals. Bad.
   - Option C: PR #40 is live; drafts exist; `UPDATE signal_queue SET finalize_retry_count=0, status='awaiting_finalize' WHERE id IN (...)` → next tick reclaim via PR #39's chain → Step 6 revalidates with PR #40's coercion → vault push. Zero new Opus cost. Best option.
   - **If you APPROVE, AI Head executes the UPDATE under standing Tier A auto-recovery.**

6. **3 new tests** — mock `emit_log`, assert `call_args_list` tuples. 39/39 Step 5 tests pass (36 pre-existing + 3 new).

7. **Regression delta** — B2 reports `16 failed, 808 passed, 21 skipped` (805 baseline + 3 new). 16 failures byte-identical. Reproduce locally if practical — same rigor as PR #41.

8. **Ship-report pytest log is FULL, not "by inspection"** — literal counts quoted. REQUEST_CHANGES on any "by inspection" phrasing.

## Decision

- **APPROVE** → reply `APPROVE PR #42`; AI Head will Tier-A auto-merge (`gh pr merge 42 --squash`). **On merge, AI Head executes the 13-row recovery UPDATE (standing Tier A).**
- **REQUEST_CHANGES** → name the line/logic; B2 loops.

## Report path

`briefs/_reports/B3_pr42_step5_empty_draft_investigation_review_20260422.md` — commit + push after review. Close this task file with a `## B3 dispatch back` section.

## Context note

PR #41 merged at `d1ddb54` (just now). PR #42 is independent (different files, no ordering dep). You can approve without waiting on PR #41's Render deploy.

The 13-row recovery post-merge is the final user-visible change — after that, Cortex-launch surface is effectively clean: full crash-recovery coverage (PRs #38/#39/#41), YAML-coercion fix live (PR #40), Step 5 observable (PR #42), 13 previously-stuck signals flow to vault.

---

**Dispatch timestamp:** 2026-04-22 ~12:13 UTC (post-B2 ship, parallel to PR #41 merge)
