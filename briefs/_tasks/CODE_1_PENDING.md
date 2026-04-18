# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR8-S2-FIX shipped at `067e29c`. B2 review delta pending. Director ratified path (b) on PR #12 S1.
**Task posted:** 2026-04-18 (late evening)
**Status:** OPEN — tiny rename amend on existing PR #8 branch

---

## Task: PR8-S1-RENAME — `awaiting_inbox_route` → `routed_inbox` canonical

**Source:** B2's PR #12 review @ `1feebf7` (S1) + Director ratification of option (b).

### Why

Your PR8-S2-FIX advances low-score triage signals to `'awaiting_inbox_route'`, but the KBL-B brief §4.2 canonical terminal state is `'routed_inbox'`. PR #12 (now MERGED at `68db3568`) includes `routed_inbox` in the CHECK set but NOT `awaiting_inbox_route`. Your choice was a silent spec drift from the brief.

Director ratified option (b): rename PR #8's writes to `'routed_inbox'` instead of adding a 35th CHECK value. Bundles cleanly with B2's pending S2 delta review — single B1 commit closes both S1 (rename) + S2 (already fixed in your PR8-S2-FIX).

### Scope

**IN**

1. **`kbl/steps/step1_triage.py`** — rename every occurrence of `'awaiting_inbox_route'` (string literal + any constant like `_STATE_INBOX_ROUTE` if you defined one) → `'routed_inbox'`. Semantic note: `routed_inbox` is **terminal** (not `awaiting_*`), so clarify the docstring / comments around the state transition to reflect "signal reaches terminal inbox state" rather than "signal awaits inbox routing."

2. **Tests** — `tests/test_step1_triage.py` — update every assertion that expects `'awaiting_inbox_route'` → `'routed_inbox'`. This should include the new tests you added in PR8-S2-FIX (`test_triage_parse_error_retries_exhausted_writes_stub` + low-score routing tests).

3. **Any docstrings / comments referencing "awaiting inbox route"** — update wording to reflect terminal-state semantic.

4. **No migration changes.** PR #12 is merged; `routed_inbox` is already in the CHECK set.

### CHANDA pre-push

- **Q1 Loop Test:** rename + semantic clarification; no Leg touched. Pass.
- **Q2 Wish Test:** aligns implementation with brief §4.2 (ratified wish). Pass.

### Branch + PR

- **Branch:** `step1-triage-impl` (same PR #8 branch).
- **Amend as an additional commit** on top of `067e29c`. Do NOT open a new PR.
- **PR #8 head advances to `<new_SHA>`** — B2 will re-review S1 rename + S2 fix together as single APPROVE cycle.

### Reviewer

B2 — combined delta re-review covering both S1 (rename) + S2 (state-leak fix).

### Timeline

~10-15 min (mechanical rename + test-assertion updates + commit).

### Dispatch back

> B1 PR8-S1-RENAME shipped — PR #8 head advanced to `<SHA>`, `awaiting_inbox_route` → `routed_inbox` across code + tests + docstrings, `<N>`/`<N>` tests green. Ready for B2 combined S1+S2 delta re-review.

---

## After this task (for context)

1. B2 re-reviews PR #8 combined S1+S2 delta → APPROVE → I auto-merge PR #8.
2. PR #7 (LAYER0), PR #10 (STEP2-RESOLVE), PR #11 (STEP3-EXTRACT) — I verify each against new main (post PR #12 merge), auto-merge on clean CI. You are not needed for these.
3. Your next dispatch: **STEP4-CLASSIFY-IMPL** (deterministic classifier, ~30 min) OR **OLLAMA-CLIENT-REFACTOR-1** (lift `call_ollama` into shared `kbl/ollama.py` — PR #11 N1).

---

*Posted 2026-04-18 (late evening) by AI Head. PR #12 merged at `68db3568`. Tiny fold.*
