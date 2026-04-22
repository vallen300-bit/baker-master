# B3 Review — PR #42 STEP5_EMPTY_DRAFT_INVESTIGATION_1

**Reviewer:** Code Brisen #3
**Date:** 2026-04-22
**PR:** https://github.com/vallen300-bit/baker-master/pull/42
**Branch:** `step5-empty-draft-investigation-1`
**Head SHA:** `de380449`
**Author:** B2
**Ship report:** `briefs/_reports/B2_step5_empty_draft_investigation_20260422.md`

---

## §verdict

**APPROVE PR #42.** All 8 focus items green. Full-suite regression delta reproduced locally with cmp-confirmed identical 16-failure set. Observability-only PR ships clean (zero logic change); Part B diagnostic reframes the problem correctly (the 13 stuck rows are **not** empty-draft — they're pre-PR-#40 deadline-YAML-coercion victims with real drafts already stored); Part C Option C recommendation holds independently. Tier A auto-merge greenlit; AI Head can execute the 13-row recovery UPDATE under standing Tier A.

---

## §focus-verdict

1. ✅ **emit_log call sites at all 8 bisection points.**
2. ✅ **Smoking-gun WARN branch is a regression tripwire, not dead code.**
3. ✅ **ADD-ONLY diff — zero logic change.**
4. ✅ **Part B diagnostic claims hold.**
5. ✅ **Part C Option C recommendation sound.**
6. ✅ **3 tests — exact tuple assertions via `call_args_list`.**
7. ✅ **Regression delta — +3 passed vs merge-base, 0 regressions.**
8. ✅ **Ship report full pytest with literal counts; "by inspection" absent.**

---

## §1 emit_log call sites

`grep -nE "^\s*emit_log\(" kbl/steps/step5_opus.py` → **12 call sites** (ship report said 10; discrepancy is in the direction of MORE observability, not less — the [6] and [8b] bisection points each have two sub-branches for empty-vs-non-empty and they ship separate emit_log calls for each).

Bisection-point markers `[1]`-`[8b]` (comments inline in source):

| Marker | Level | file:line | Condition |
|--------|-------|-----------|-----------|
| [1] | INFO | step5_opus.py:987 | `synthesize()` entry — anchor per-signal trace |
| [2] | INFO | step5_opus.py:1065 | Cost-gate denial (`paused_cost_cap`) |
| [3] | ERROR | step5_opus.py:1026 | Invalid `step_5_decision` from Step 4 |
| [4] | WARN | step5_opus.py:889 | R3 reflip (AnthropicUnavailableError) |
| [5] | INFO | step5_opus.py:852 | Opus call start — attempt / max_tokens / user_len |
| [6] | WARN / INFO | step5_opus.py:913, 923 | Opus call return — WARN on empty `response.text`, INFO on non-empty |
| [7] | ERROR | step5_opus.py:866 | Opus 4xx (`OpusRequestError`, no retry) |
| [8] | ERROR | step5_opus.py:1107 | R3 exhausted → `opus_failed` terminal |
| [8a] | INFO | step5_opus.py:1007 | Stub draft written |
| [8b] | WARN / INFO | step5_opus.py:1133, 1142 | Full draft written — **WARN on empty draft** (smoking gun), INFO otherwise |

- **`_LOG_COMPONENT = "step5_opus"`** at step5_opus.py:130 — module constant, no drift risk. Matches PR #40 Part B SQL expectation (`WHERE component='step5_opus'`). ✓
- **Signature compliance:** `emit_log(level, component, signal_id, message)` positional — verified against `kbl/logging.py:59-62`. Identical usage to `step6_finalize.py:573, 652, 782`. ✓

## §2 Smoking-gun WARN branch

`step5_opus.py:1122-1143`:

```python
record_opus_success(conn)
_write_draft_and_advance(conn, signal_id, response.text, _STATE_NEXT)
draft_len = len(response.text or "")
if draft_len == 0:
    emit_log(
        "WARN",
        _LOG_COMPONENT,
        signal_id,
        f"wrote empty draft (draft_len=0): Step 6 will reject; ..."
    )
else:
    emit_log(...)
```

**Branch is reachable** — `_write_draft_and_advance` unconditionally writes `response.text` to the column (no `if text: ...` guard in the UPDATE). If Opus returns 200 OK with empty `content[0].text` (content-filter / thinking-only block — PR #40 Part B hypothesis #2), this WARN fires AFTER the empty draft is already persisted. Exactly the regression tripwire the brief asked for.

**Not dead code:** the 3rd test (`test_emit_log_full_synthesis_empty_response_warns_with_bisection_signal`) exercises this branch with a mock returning `text=""`, confirming both the [6] empty-response WARN and the [8b] smoking-gun WARN fire (`warn_prefixes` includes both `empty draft from Opus 200` and `wrote empty draft (draft_len=0)`). ✓

## §3 ADD-ONLY diff

`git diff --stat $(merge-base)..pr42` → `136 ++++++++++++++++` on step5_opus.py, zero deletions (no `--` column). Test file similarly pure-add (+144). Ship report pure-add (+251). ✓

**Line-by-line diff audit** for step5_opus.py:
- 1 new import line: `from kbl.logging import emit_log` (line 105)
- 1 new module constant: `_LOG_COMPONENT = "step5_opus"` (line 130)
- 12 new `emit_log(...)` calls across `_fire_opus_with_r3` and `synthesize`
- 3 new local vars supporting the logs (`resp_len`, `draft_len`, `last_err_summary`)

**Zero changes to:**
- `call_opus` (not touched)
- `_R3_MAX_ATTEMPTS` constant (unchanged at 3)
- `_fire_opus_with_r3` control flow (loop structure, break/continue semantics)
- `_write_draft_and_advance` (pre-existing unconditional UPDATE)
- `_write_cost_ledger` (only the new emit_logs surround it; the call-site unchanged)
- Cost-gate / `record_opus_success` / `record_opus_failure` logic
- `_mark_running` / `_mark_terminal` (unchanged)

Pure observability layer addition. ✓

## §4 Part B diagnostic quality

Reviewed the 3 load-bearing claims:

**4a. `api_cost_log` key = `opus_step5` (corrected from brief).**

Verified independently at `kbl/steps/step5_opus.py:383`:
```sql
INSERT INTO kbl_cost_ledger ... VALUES (%s, 'opus_step5', ...)
```

The literal `'opus_step5'` is hard-coded in the single Step-5 cost-ledger writer. B2's correction of the brief's `step LIKE 'step5%'` hypothesis is correct — only `'opus_step5'` ever matches. ✓

**4b. 100% `deadline` hit on the 13.**

Part B table shows `deadline` appears on 13 of 13 failed-field columns. Load-bearing for Part C Option C: PR #40's `_deadline_coerce_to_str` validator directly addresses this class. If all 13 fail on `deadline`, all 13 unblock on the PR #40 redeploy. ✓

**4c. 3 of 13 also hit `source_id`.**

Part B table shows `source_id` on rows 25, 22, 17. Consistent with PR #40's defense-in-depth `_source_id_coerce_to_str`. ✓

**Bonus findings acknowledged as out-of-scope:**
- hagenauer-rg7 over-routing bias (9 of 13, 69%) — flagged for Cortex Design §4 Director territory.
- Body-too-short tail (9 of 13 with `body` field in WARN) — noted as legitimate-short-body distribution issue; out of scope per brief.

Both correctly surfaced without scope creep. ✓

## §5 Part C Option C validation

Walked the reasoning:

- **Option A** (re-queue from Step 1): burns ~$5-8 in new Opus calls across 13 rows. Drafts already exist and are correct. Same deadline failure will recur unless PR #40 has shipped — in which case Opus re-runs are pure waste. ✗ Wasteful.
- **Option B** (abandon terminal): loses 1524-2570 chars of legitimate Opus analysis per row, 9 of which are on the hottest active matter (hagenauer-rg7). ✗ Content cost.
- **Option C** (wait + reset retry counter): PR #40 is live post-deploy; drafts already populated; `UPDATE signal_queue SET finalize_retry_count=0, status='awaiting_finalize' WHERE id IN (...)` → PR #39's `claim_one_awaiting_finalize` picks up → `_process_signal_finalize_remote` runs Step 6 with the coerced-deadline validator → existing drafts validate and advance to `awaiting_commit` → Mac Mini poller pushes to vault.

**Cost of Option C: $0 new Opus.** Routing through PR #39's chain is already instrumented and recovery-tested (PRs #38/#39/#41 validated). PR #40's coercion already in production. Option C is the right call. ✓

**Caveat I verified:** the 9 rows that ALSO hit `body` in their WARN column. For those, Option C may still fail Step 6 on the body-floor check (legitimate short-body tail). B2 notes this as a follow-up — "a further follow-up may be needed to investigate whether these specific drafts are legitimately under-300 chars of body." Correct handling: approve Option C, accept that 0-9 of 13 may need a second pass or manual review depending on the body-too-short subset. 4 of 13 (those with `deadline` ONLY, no `body` in their failed fields) are guaranteed clean.

## §6 3 new tests

`tests/test_step5_opus.py:948-1091`. Read each body:

| # | Test | Locks |
|---|------|-------|
| 1 | `test_emit_log_skip_inbox_logs_entry_and_stub_written` | SKIP_INBOX path emits `step5 entry` + `stub draft written` INFO pair with `component='step5_opus'` + `signal_id=101` + `decision='skip_inbox'` substring. Zero WARN/ERROR. |
| 2 | `test_emit_log_full_synthesis_happy_path_logs_trace_points` | FULL_SYNTHESIS emits 4 INFO anchors (entry / opus call start / opus call return / draft written). `opus call return` carries `stop_reason='end_turn'` + `output_tokens=42` (exact). All 4 carry `signal_id=202` + `component='step5_opus'`. Zero WARN. |
| 3 | `test_emit_log_full_synthesis_empty_response_warns_with_bisection_signal` | Opus 200 with `text=""` → **BOTH** `empty draft from Opus 200` WARN AND `wrote empty draft (draft_len=0)` WARN emitted. Pipeline still advances to `awaiting_finalize` (documented as "bug out of scope to fix here"). Smoking-gun log carries `stop_reason` + `output_tokens=0`. |

All 3 use a helper `_emit_log_messages_at_level(m_emit, level)` that flattens `call_args_list` to `(component, sid, message)` tuples, then assert specific substrings + counts. Not presence-only. ✓

**Focused run:** `tests/test_step5_opus.py` → `39 passed in 0.41s` (36 pre-existing + 3 new). Matches ship report claim.

## §7 Full-suite regression delta

Reproduced locally in `/tmp/b3-venv` (Python 3.12). **Note:** main advanced to 812 passed after PR #41 merged. PR #42 branched from pre-PR-#41 main (`805 + 3 = 808` baseline), so I compared against BOTH the merge-base (correct scientific comparison) AND current main (sanity check the failure set is still identical).

**Merge-base comparison (the scientifically correct one):**
```
merge-base (pre-PR-41): 16 failed / 805 passed / 21 skipped / 19 warnings  (12.48s)
pr42 head (de380449):    16 failed / 808 passed / 21 skipped / 18 warnings  (12.57s)
Delta:                    +3 passed, 0 regressions, 0 new errors, 0 new skips
```

**Failure-set identity:** `cmp -s /tmp/b3-mergebase42-failures.txt /tmp/b3-pr42-failures.txt` → exit 0 (IDENTICAL).

**Current-main sanity check** (post-PR-#41, 812 passed):
```
current main:  16 failed / 812 passed / 21 skipped
pr42 head:     16 failed / 808 passed / 21 skipped
Delta in passed counts: -4 passed
```

The -4 pass delta vs current main is a FALSE NEGATIVE caused by PR #41's 7 new tests not yet being on the pr42 branch (squash merge will bring them together). Failure set still `cmp -s` IDENTICAL on both comparisons. Zero true regressions.

B2's `805 + 3 = 808` math matches my merge-base measurement EXACTLY. ✓

## §8 Ship report — no "by inspection"

Ship report §Full pytest section carries:
- Literal counts: `16 failed, 808 passed, 21 skipped, 19 warnings in 11.50s`.
- Full head + tail capture (session start banner, ~3 test progress lines, 16 FAILED rows enumerated, final summary).
- Per-failure triage paragraph tracing each failure to env state (voyageai key, scan 401, storeback fixtures) rather than code.

`grep -i "by inspection"` in ship report → zero matches. Phrase absent. `memory/feedback_no_ship_by_inspection.md` honored. ✓

---

## §non-gating

- **N1 — emit_log call-count discrepancy in ship report.** Ship report claims "10 emit_log call sites at 8 bisection points"; actual count is 12 emit_log calls (bisection points [6] and [8b] each have 2 sub-branches emitting separate logs). Informational only — more observability is fine; the table in Part A correctly enumerates all 12 via the "INFO / WARN" sub-entries. Not a code issue.

- **N2 — logger.warning kept at cost-gate.** Ship report notes the pre-existing stdout `logger.warning` at the cost-gate branch is KEPT alongside the new `emit_log INFO`. Dual logging is defensible (stdout for ops pager, kbl_log for joinability) but risks future drift if one is updated without the other. Informational.

- **N3 — Option C body-too-short tail.** 9 of 13 rows that also hit `body` in their WARN set. Option C as-is will unblock 4 of 13 cleanly; the other 9 need a follow-up (either Step 5 prompt tuning or Director decision to accept short bodies / mark Gold). B2 flags this explicitly in Part C. Worth explicit AI Head acknowledgment when executing the recovery UPDATE: the first few re-runs through Step 6 may still fail on body if the draft's post-frontmatter body is legitimately <300 chars. Not gating the approval; AI Head should budget a second-pass review.

---

## §regression-delta

```
$ wc -l /tmp/b3-mergebase42-failures.txt /tmp/b3-pr42-failures.txt
      16 /tmp/b3-mergebase42-failures.txt
      16 /tmp/b3-pr42-failures.txt

$ cmp -s /tmp/b3-mergebase42-failures.txt /tmp/b3-pr42-failures.txt && echo IDENTICAL
IDENTICAL

$ cmp -s /tmp/b3-main6-failures.txt /tmp/b3-pr42-failures.txt && echo IDENTICAL
IDENTICAL
```

Raw logs: `/tmp/b3-mergebase42-pytest-full.log`, `/tmp/b3-pr42-pytest-full.log`, `/tmp/b3-main6-pytest-full.log` (local).

---

## §post-merge

- Tier A auto-merge (squash) proceeds.
- Render redeploys. Step 5 becomes observationally lit on next tick — first `component='step5_opus'` rows land in `kbl_log` per signal processed.
- AI Head executes the 13-row recovery UPDATE under standing Tier A:
  ```sql
  UPDATE signal_queue
     SET finalize_retry_count = 0, status = 'awaiting_finalize'
   WHERE id IN (10, 17, 22, 24, 25, 50, 51, 52, 53, 54, 59, 61, 73);
  ```
- PR #39's `claim_one_awaiting_finalize` picks up on next tick; Step 6 validates existing drafts with PR #40's coercion; vault push via Mac Mini poller. Expected clean pass on the 4-of-13 `deadline`-only subset; possible second-pass needed on the 9-of-13 `body+deadline` subset.

**Cortex-launch surface post-merge:** full crash-recovery coverage (PRs #38/#39/#41), YAML-coercion fix live (PR #40), Step 5 observable (PR #42), 13 stuck signals flow to vault (post-recovery UPDATE). Clean.

**APPROVE PR #42.**

— B3
