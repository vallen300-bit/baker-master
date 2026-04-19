# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Task posted:** 2026-04-19 (morning)
**Status:** OPEN — PR #13 review

---

## Completed since last dispatch

- Task H — PR #8 combined S1+S2 delta (APPROVE @ `fd67ca3`) ✓ **MERGED `6382ee50`**

All 5 Phase 1 PRs on main. Pipeline 5/5 shipped.

---

## Task I (NOW): Review PR #13 — STEP4-CLASSIFY-IMPL

**PR:** https://github.com/vallen300-bit/baker-master/pull/13
**Branch:** `step4-classify-impl`
**Head:** `4d38a44`
**Tests:** 40/40 new parse-level + 1 live-PG skip; full related suite 304/304 + 4 live-PG skips
**Spec:** KBL-B §4.5 (deterministic policy classifier).

### Scope

**IN**

1. **`migrations/20260418_step4_signal_queue_step5_decision.sql`** — adds `step_5_decision TEXT` + `cross_link_hint BOOLEAN NOT NULL DEFAULT FALSE`. No DB CHECK on decision (enum enforced in Python).

2. **`kbl/steps/step4_classify.py`** — full classifier:
   - `ClassifyDecision` str-Enum (Py3.9-compat StrEnum equivalent). Values: `FULL_SYNTHESIS`, `STUB_ONLY`, `CROSS_LINK_ONLY`, `SKIP_INBOX`
   - `CROSS_LINK_ONLY` reserved for Phase 2; runtime guard fails loud if emitted
   - `classify(signal_id, conn) -> ClassifyDecision` — load row → apply table → write → advance state
   - `_load_allowed_scope()` — hot.md + env union, fresh read per classify()
   - `_evaluate_rules()` — pure, first-match-wins
   - State transitions: `awaiting_classify` → `classify_running` → `awaiting_opus` or `classify_failed`
   - `ClassifyError` new in `kbl/exceptions.py` (net-additive)

3. **Decision table (§4.5):**
   - Rule 0 unreachable: `triage_score < THRESHOLD` → raises `ClassifyError` (Step 1 drift guard)
   - Rule 1: `primary_matter not in allowed_scope` → `SKIP_INBOX` + Layer 2 INFO log
   - Rule 2: `triage_score < THRESHOLD + NOISE_BAND` → `STUB_ONLY`
   - Rule 3: `resolved_thread_paths == [] AND related_matters == []` → `FULL_SYNTHESIS` (new arc)
   - Rule 4: `resolved_thread_paths == [] AND related_matters != []` → `FULL_SYNTHESIS` + `cross_link_hint=TRUE`
   - Rule 5: `resolved_thread_paths != []` → `FULL_SYNTHESIS` (continuation)

### Specific scrutiny

1. **Rule ordering correctness** — first-match-wins against §4.5 table. Verify Rule 1 (scope gate) fires BEFORE Rule 2 (threshold gate) — a below-scope signal should `SKIP_INBOX` even if triage_score is high. Verify Rule 2 before Rule 3-5 — a stub-only signal should not advance to full synthesis.

2. **CROSS_LINK_ONLY guard** — B1 says it fails loud if emitted. Verify:
   - The guard exists (raise on emit, not silent fallback)
   - No rule path can reach it
   - Test exists that asserts the guard fires on forced attempt

3. **Inv 3 Leg-3 anchor** — `_load_allowed_scope` reads hot.md on EVERY classify() call. Explicit `@patch` call-count test across 3 successive invocations must pass (mirror Step 1's `test_triage_invocation_reads_hot_md_and_ledger_once`). This is Leg 3 critical — BLOCK default applies if missing.

4. **Hot.md parsing fidelity** — verify parser pulls ONLY from `## Actively pressing` block, NOT `## Watch list` (per Director ratification: ACTIVE matters only). Slugs in `## Watch list` should NOT enter `allowed_scope`.

5. **Env override shape** — `KBL_MATTER_SCOPE_ALLOWED` comma-separated parsing:
   - Empty/unset → hot.md is sole source
   - Leading/trailing whitespace stripped
   - Duplicates collapsed (union semantic)
   - Invalid slugs (not in `slugs.yml` v9) — does parser reject, warn, or pass-through? Flag the chosen behavior.

6. **State-machine CHECK compliance** — `awaiting_classify`, `classify_running`, `awaiting_opus`, `classify_failed` all in the 34-value set from PR #12. No leftover drift.

7. **`cross_link_hint` write semantic** — Rule 4 sets TRUE, Rule 3 sets FALSE. Verify:
   - Migration default FALSE (matches Rule 3 behavior on zero-cross-link signals)
   - Rule 4 explicit TRUE write (not reliance on default)
   - Step 6 read path (future) will consume this — brief §4.7 docstring or comment references the hint.

8. **Failure-path atomicity** — `ClassifyError` → state flips to `classify_failed` BEFORE exception bubbles. Verify order: status UPDATE commits, then raise. Not: raise, then caller handles status (leak-prone per PR #8 S2 precedent).

9. **Test count** — 40 new tests. Verify coverage of: each rule (5), allowed-scope derivation (4+), Inv 3 fresh-read counter (3+), env parsing edge cases, state transitions, ClassifyError paths, `cross_link_hint` write correctness.

### CHANDA audit

- **Q1 Loop Test:** Step 4 reads hot.md — **Leg 3 surface**. Fresh-read per invocation. Pass if Inv 3 test passes.
- **Q2 Wish Test:** deterministic policy gates Opus cost on Director's hot.md ACTIVE set. Wish-aligned.
- **Inv 3** (hot.md + ledger every run) — critical verification point.
- **Inv 6** (never skip Step 6) — Step 4 always advances; never terminates signal.
- **Inv 10** (no prompt self-modification) — no prompt; pure Python.

### Format

`briefs/_reports/B2_pr13_review_20260419.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline

~25-35 min (pure Python, no external calls, focused surface).

### Dispatch back

> B2 PR #13 review done — `briefs/_reports/B2_pr13_review_20260419.md`, commit `<SHA>`. Verdict: <...>.

On APPROVE: I auto-merge PR #13. That's Step 4 done; Step 5 (Opus synthesis) is B1's next big dispatch.

---

## Working-tree reminder

**Work only inside `/tmp/bm-b2`** (or another `/tmp/*` clone). Never operate on files inside Dropbox paths.

---

*Posted 2026-04-19 by AI Head. PR #13 = last deterministic step before Opus boundary.*
