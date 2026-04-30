# CODE_4 — IN_REVIEW (CORTEX_PHASE6_REFLECTOR_1 — Brief 3, follow-up patch needed)

**Status:** IN_REVIEW — REQUEST_CHANGES (1 IMPORTANT) — 2026-04-30
**PR shipped:** https://github.com/vallen300-bit/baker-master/pull/129 (`b4/cortex-phase6-reflector-1`) — MERGED 2026-04-30T20:59:06Z by Director, before architect-review landed.
**Follow-up PR needed:** new branch off main, 1-line ORDER BY flip + optional regression test.
**Builder:** B4
**Reviewer:** B1 second-pair-of-eyes on the follow-up patch (B4 builder-conflict)

## Verdict

Architect-review pass via `code-architecture-reviewer` subagent → APPROVE WITH NITS. 8 of 8 dispatch concerns verified clean. 1 IMPORTANT bug (separate from the 8) requires follow-up patch.

Full architect comment on PR #129: issuecomment-4356143719.

## Required patch (1 IMPORTANT)

### `_load_proposal_text` chops trailing citations on long proposals

**File:** `orchestrator/cortex_phase6_reflector.py:496-532`

`cortex_phase4_proposal.py:237` truncates `proposal_text[:8000]` before persisting in the `proposal_card` artifact. Phase 3c synthesizer outputs up to `PHASE3C_MAX_TOKENS = 4000` (~12K-16K chars). Citation preamble explicitly tells the model to put `[directive: <id>]` **at the end of the proposal** (`cortex_phase3_synthesizer.py:178`). The Reflector's ORDER BY prefers `proposal_card` over `synthesis`, so for any proposal > 8000 chars the trailing citation gets chopped, parser sees no citation, all proposals get queue-flagged with `no_citation`. Counters never increment.

Worst case: every long proposal looks untraceable → learning loop dark for the most substantive cycles (the very cycles this brief is for).

**Fix (one-line ORDER BY flip):**

```python
ORDER BY CASE artifact_type
             WHEN 'synthesis'     THEN 0
             WHEN 'proposal_card' THEN 1
         END, created_at DESC
```

Prefer `synthesis` artifact (full text, no truncation) over `proposal_card` (Slack-rendered, truncated). Slack rendering still uses `[:8000]`; only the Reflector parsing sees full text.

## Required regression test

Add a test that:
- Creates a `synthesis` artifact >8000 chars with `[directive: <id>]` at the very end (e.g., chars 9000+).
- Creates a `proposal_card` artifact for the same cycle truncated at 8000 chars (citation chopped).
- Calls Reflector parse path.
- Asserts the citation is detected (not flagged `no_citation`).

Without this test, the bug recurs the moment someone re-flips the ORDER BY thinking `proposal_card` is canonical.

## Non-blocking suggestions (deferred — separate brief OK)

- **S1 (RA-23 tracker note):** Trigger A absorbed into the hourly sweep is a defensible V1 scope deviation from brief §3.5. Adds up to 60 min counter-update latency on Triaga-decided cycles. Note in tracker.
- **S2 (follow-up brief):** Vault write happens outside the counter-update transaction. If vault write throws after counter UPDATE + idempotency marker commit, vault file never written; subsequent sweeps skip via `already_reflected=True`. Inherent PG/filesystem-boundary tradeoff. Follow-up: reconciler that reads `reflector_complete` markers and verifies vault-file presence.

## Patch ritual

```
cd ~/bm-b4
git fetch origin
git checkout main
git pull --ff-only origin main
git checkout -b b4/cortex-phase6-reflector-orderby-fix
# 1-line ORDER BY flip in orchestrator/cortex_phase6_reflector.py:496-532
# new regression test in tests/test_phase6_reflector_parse.py (or counters/sweep)
# pre-pytest re-checkout ritual
pytest tests/test_phase6_reflector_*.py -v   # confirm full pass
git add -p
git commit -m "fix(reflector): prefer synthesis artifact over truncated proposal_card (PR #129 IMPORTANT from architect-review)"
git push origin b4/cortex-phase6-reflector-orderby-fix
```

Then comment on the new PR with grep proof of the order flip + new test passing. Architect-review re-runs against the patch; B1 second-pair-of-eyes; AI Head A merges.

## Trigger-class

TIER A — modifies Phase 6 Reflector's core citation-resolution path. AI Head B cross-lane ratify can chain on top after architect-review re-pass + B1 review.

## Companion state

- Brief 4 (CORTEX_CONFIG_DIRECTIVES_SCHEMA_1) shipped in PR #125 + #127.
- Brief 3 (CORTEX_PHASE6_REFLECTOR_1) shipped in PR #129; this follow-up closes the citation-truncation gap.
- Vault PR #37 (`brisen` slug v17) merged.
- Vault PR #40 (Desk memory seeds) merged.
- Briefs 1+2 build (BAKER_VAULT_WRITE_1 + READ_WIKI_SCOPE_1) — next dispatch when Director ratifies.

## Previous task (closed)

Brief 4 dispatch + ship loop closed via PR #125 + #127 + #128 mailbox flip. Brief 3 main shipped via PR #129 (Director-merged before architect-review landed; same race as PR #125 — non-blocking now since sweep is hourly cadence).
