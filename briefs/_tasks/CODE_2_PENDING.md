# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Task posted:** 2026-04-18 (late evening)
**Status:** OPEN — one combined delta review on PR #8

---

## Completed since last dispatch

- Task A — PR #7 review (REDIRECT → phone-delta APPROVE @ `6fb6c89`) ✓ **MERGED `be21dc70`**
- Task B — STEP5-OPUS-PROMPT review (APPROVE @ `b7c0b0c`) ✓
- Task C-delta-phone — PR #7 S1 fix re-verify ✓
- Task C-new — PR #9 LOOP-GOLD-READER-1 (APPROVE) ✓ (already merged pre-handover)
- Task C-delta — STEP5-OPUS S1 APPROVE ✓
- Task D — REDIRECT fold (APPROVE @ `f712647`) ✓
- Task E — PR #10 STEP2-RESOLVE-IMPL (REDIRECT @ `7059ce3`) ✓ **MERGED `6a607a3a`** (S1 resolved by PR #12)
- Task F — PR #11 STEP3-EXTRACT-IMPL (REDIRECT @ `8f2fdac`) ✓ **MERGED `312279a8`** (S1 resolved by PR #12, exceptions.py additive conflict resolved by AI Head)
- Task C — PR #8 STEP1-TRIAGE-IMPL (REDIRECT @ `85a759f`) ✓ — awaiting delta re-review
- Task G — PR #12 STATUS-CHECK-EXPAND-1 (REDIRECT @ `1feebf7`, Director ratified option b) ✓ **MERGED `68db3568`**

PR #12 merged. Canonical CHECK set active on main. 4 pipeline PRs merged to main.

---

## Task H (NOW, final open item): PR #8 combined S1+S2 delta re-review

**PR:** https://github.com/vallen300-bit/baker-master/pull/8
**Branch:** `step1-triage-impl`
**Previous head:** `067e29c` (PR8-S2-FIX by B1 — parse-failure state-leak → retry budget + stub + inbox route)
**New head:** `<after B1 pushes PR8-S1-RENAME>` — check `gh pr view 8 --json headRefOid`
**Purpose:** verify both S1 (rename `awaiting_inbox_route` → `routed_inbox`) AND S2 (state-leak fix) land cleanly in one review cycle.

### Scope

**IN — S1 rename (Director ratification of option b from your PR #12 review):**

1. **`kbl/steps/step1_triage.py`** — every `'awaiting_inbox_route'` replaced by `'routed_inbox'` (string literals + constants + docstrings). Semantic: `routed_inbox` is **terminal**, not `awaiting_*`. Verify docstring + comment wording reflects terminal-state semantic.

2. **`tests/test_step1_triage.py`** — every assertion expecting `'awaiting_inbox_route'` now expects `'routed_inbox'`. Includes new tests from PR8-S2-FIX (`test_triage_parse_error_retries_exhausted_writes_stub` + low-score routing tests).

3. **Alignment with brief §4.2** — "Routing: triage_score < threshold → state='routed_inbox' terminal" — verify PR #8's final head matches exactly.

**IN — S2 delta (state-leak fix):**

1. **Retry budget `_RETRY_BUDGET = 1`** — 2 Ollama calls max per triage invocation.
2. **Pared prompt on retry** — second attempt drops ledger block (substitute `[LEDGER OMITTED — R3 retry]`), keeps glossary + hot.md + signal. `_build_pared_prompt` helper takes pre-computed blocks (reuses fresh reads from attempt 1).
3. **Retries-exhausted path** — stub `TriageResult(primary_matter=None, vedana=None, summary='parse_failed')` + advance to `'routed_inbox'` (was `'awaiting_inbox_route'` pre-rename). No raise. Pipeline flows.
4. **Happy-retry path** — first call fails, second succeeds: TWO cost rows (false + true), ONE result UPDATE, state routed by score.
5. **Inv 3 preservation** — `_read_prompt_inputs` centralizes fresh hot.md + ledger reads ONCE per triage() invocation. Explicit test (`test_triage_invocation_reads_hot_md_and_ledger_once`) asserts single read on both happy + retries-exhausted paths. **This is Leg 3 critical — verify with extra rigor.**
6. **`OllamaUnavailableError`** propagates unchanged (transport failures not budgeted against parse retries).
7. **`TriageResult.vedana: Optional[str]`** — widened to allow None in stub. Happy path still enforces 3-value enum via parser.

### Specific scrutiny

1. **Every `awaiting_inbox_route` literal string gone?** `grep -r 'awaiting_inbox_route' kbl/ tests/` must return zero. Flag any survivor as BLOCK.
2. **`routed_inbox` in new CHECK set?** Confirm (it's one of the 34 — you verified in PR #12 review, re-cite). Bogus status writes would have crashed tests against new main.
3. **Stub + retry + Inv 3 test coherence** — the three tests cover: (a) happy retry, (b) retries exhausted, (c) fresh-read counter. All three must pass against the renamed state.
4. **Test count delta vs pre-fix** — B1 report: 44 → 51 tests. Verify 7 new tests landed + any existing tests updated for new state name.
5. **PR #8 now mergeable against new main** — PR #12 + PR #7 + PR #10 + PR #11 merged. Check for conflicts; if none, APPROVE clears the merge gate.

### CHANDA audit

- **Q1 Loop Test:** Leg 3 surface — verify `_read_prompt_inputs` reads hot.md + ledger on EVERY `triage()` call, including retry path (retry pares the prompt, does NOT re-read — same source-of-truth data for both attempts).
- **Q2 Wish Test:** rename honors the brief; stub-and-route keeps pipeline flowing (no silent stalls on parse failure); wish-aligned.
- Inv 3 re-certified — explicit test asserts single read per invocation.

### Format

`briefs/_reports/B2_pr8_delta_review_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline

~20-30 min (combined S1 + S2 review on unchanged surface area, post-PR #12 CHECK re-verify).

### Dispatch back

> B2 PR #8 combined delta review done — `briefs/_reports/B2_pr8_delta_review_20260418.md`, commit `<SHA>`. Verdict: <...>.

On APPROVE: I auto-merge PR #8 (final pipeline PR to land).

---

## Working-tree reminder

**Work only inside `/tmp/bm-b2`** (or another `/tmp/*` clone). **Never operate on files inside Dropbox paths** (`~/Vallen Dropbox/`, `~/Dropbox/`). Director confirmed seeing a Dropbox prompt for `CHANDA.md` earlier — cancelled. Fresh clone: `rm -rf /tmp/bm-b2 && git clone git@github.com:vallen300-bit/baker-master.git /tmp/bm-b2 && cd /tmp/bm-b2`.

---

*Posted 2026-04-18 (late evening) by AI Head. Final pipeline PR. After merge, Director's reviewable baseline = full Step 0 → Step 3 impl + migration on main.*
