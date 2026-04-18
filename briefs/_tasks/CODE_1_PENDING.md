# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #12 STATUS-CHECK-EXPAND-1 shipped at `0d78c0b`. Pending B2 review (Task G queued).
**Task posted:** 2026-04-18 (late afternoon)
**Status:** OPEN — PR #8 S2 fix while PR #12 awaits B2

---

## Task: PR8-S2-FIX — Fix state-leak on triage parse failure

**Source:** B2's PR #8 review @ `85a759f` — `briefs/_reports/B2_pr8_review_20260418.md` §3 S2.

### Why

On Gemma parse failure, PR #8 writes the cost-ledger row (success=False) + re-raises `TriageParseError`. But the signal's `status` stays at `'triage_running'` — never rolled back. Signal is stuck indefinitely unless the caller (pipeline_tick, not yet shipped) explicitly catches and updates. Three peer step impls handle this differently:
- PR #10 Step 2: on failure, writes `status='resolve_failed'` BEFORE re-raise (terminal, operator-visible)
- PR #11 Step 3: retry-budget + stub + advance to `awaiting_classify` (pipeline flows)
- PR #8 Step 1: no status write on failure → **leak**

Brief §7 row 3 says: *"Triage | Gemma JSON unparseable | TriageParseError | WARN | R3 retry (pared prompt); 2 failures → inbox | Y after R3"*. PR #8 implements zero of the retry/inbox-route logic.

### Scope — implement option (b) from B2's review

**Match PR #11's pattern exactly.** Internal retry budget + stub + advance to inbox.

1. **`kbl/steps/step1_triage.py`** — rework `triage()`:
   - Add `_RETRY_BUDGET = 1` (1 retry after initial → 2 total calls max, mirrors PR #11's `R3` policy).
   - On first `TriageParseError`: log WARN, write cost-ledger row (`success=False`), retry with a **pared prompt** (remove the feedback ledger block — B3's STEP1-TRIAGE-PROMPT §7 suggests this as the R3 strategy; keep hot.md + slug glossary + signal).
   - On second `TriageParseError`: log ERROR, write second cost-ledger row (`success=False`), write stub `TriageResult(primary_matter=None, related_matters=[], vedana=None, triage_score=0, triage_confidence=0.0, triage_summary="parse_failed")`, advance status to `'awaiting_inbox_route'` + set triage columns to the stub values. Pipeline keeps flowing. No raise.
   - On success (either call): existing path unchanged.
   - Keep `OllamaUnavailableError` re-raise behavior as-is (transient transport failure, caller decides retry-claim).

2. **Pared prompt helper** — add `_build_pared_prompt(signal_text, slug_glossary, hot_md_block) -> str` that omits the `{feedback_ledger_block}` placeholder substitution (substitute empty string or a fallback marker like `[LEDGER OMITTED — R3 retry]`).

3. **Tests** — `tests/test_step1_triage.py`:
   - Update `test_triage_parse_error_writes_failure_ledger_row_and_raises` → split into two tests:
     - `test_triage_parse_error_first_attempt_triggers_retry` — first call unparseable, second valid → single status update at end, final result written, ONE cost row success=True, no raise
     - `test_triage_parse_error_retries_exhausted_writes_stub` — both calls unparseable → stub written, status = `'awaiting_inbox_route'`, TWO cost rows both success=False, NO raise
   - `test_pared_prompt_omits_ledger` — verify `_build_pared_prompt` output does not contain the `{feedback_ledger_block}` content
   - Update any existing assertions that expect a raise on single-parse-failure

4. **Brief alignment note** — the statement in PR #8's current docstring *"Caller writes a stub + routes to inbox per §3"* should be removed or updated. Step 1 now owns the stub-and-route behavior internally, matching PR #11's self-contained pattern.

### CHANDA pre-push

- **Q1 Loop Test:** this PR touches **Leg 3** (Step 1 reads hot.md + feedback ledger on every run). Rework preserves this: both initial and retry calls invoke `build_prompt` or `_build_pared_prompt`, both READ hot.md AND ledger. Retry pares the ledger from the prompt for model robustness but does NOT skip the read — the helper is still invoked. **Leg 3 preserved.** State this explicitly in the commit message and module docstring.
- **Q2 Wish Test:** serves wish (pipeline keeps flowing on parse failure, no silent stalls; Director still judges stub-routed inbox entries). Wish-aligned, not convenience.

### Dependencies

- PR #12 STATUS-CHECK-EXPAND-1 must merge before PR #8 can merge (adds `'awaiting_inbox_route'` + `'triage_running'` to the CHECK set — your new status write depends on it). No code dependency on PR #12; just a deploy-order constraint.
- Re-use existing `_write_cost_ledger` / `_mark_running` / write helpers; no new schema.

### Branch + PR

- **Branch:** `step1-triage-impl` (amend existing PR #8, do NOT open a new PR).
- **Push as additional commit** on top of `4918b52`. Keeps reviewer cycle tight.
- **PR #8 head will advance to `<new_SHA>`** — B2 will re-review the S2 delta as a fast APPROVE once PR #12 lands.

### Reviewer

B2 (delta review on S2 fix only).

### Timeline

~45-60 min (two code paths + pared-prompt helper + 3 new tests + test split).

### Dispatch back

> B1 PR8-S2-FIX shipped — PR #8 head advanced to `<SHA>`, `_RETRY_BUDGET=1` + stub/inbox route matches PR #11 pattern, 3 new tests green, total `<N>`/`<N>` passing. Ready for B2 S2 delta re-review.

---

## After this task

1. B2 reviews PR #12 (Task G in CODE_2_PENDING) → on APPROVE, I auto-merge PR #12.
2. PR #7 auto-merges (already APPROVE'd, just waiting on #12).
3. B2 re-reviews PR #8 S2 delta → on APPROVE, I auto-merge PR #8.
4. PR #10 auto-merges (S1 resolved by #12 merge; 4 nice-to-haves tracked for follow-up).
5. PR #11 auto-merges (S1 resolved by #12 merge; 5 nice-to-haves tracked).
6. Your next dispatch: **STEP4-CLASSIFY-IMPL** (deterministic classifier, ~30 min) OR **OLLAMA-CLIENT-REFACTOR-1** (lift shared helper per B2's PR #11 N1).

---

*Posted 2026-04-18 (late afternoon) by AI Head. S2 is the only PR-intrinsic bug across the 4 pipeline PRs — worth fixing cleanly now.*
