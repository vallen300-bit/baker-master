# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22 (post-B2 ship of PR #42)
**Status:** OPEN — review PR #42 `STEP5_EMPTY_DRAFT_INVESTIGATION_1`

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
