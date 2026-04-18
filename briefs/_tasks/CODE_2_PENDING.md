# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous:** PR #5 review APPROVE-with-amend-pending filed at earlier commit. Reviewed at pre-amend SHA `51adc44`.
**Task posted:** 2026-04-18
**Status:** OPEN — five deliverables in sequence

---

## Task A-delta (now, 5 min): PR #5 BIGSERIAL delta re-verify

**PR:** https://github.com/vallen300-bit/baker-master/pull/5
**Head:** `c8c7a35` (BIGSERIAL-amended)
**Delta from your last review:** B1's `signal_queue.id → BIGINT` amend landed.

### Scope (5-min focused delta)
- ALTER ordering (must precede CREATE TABLE blocks)
- Sequence rename (`signal_queue_id_seq` → AS BIGINT)
- DOWN section reverse (drop tables first, then BIGINT→INTEGER, then sequence reset)
- Optional: assess whether REFERENCES clauses now safe to add (type mismatch removed); recommend but do not block

### Format
Append verdict section to existing `briefs/_reports/B2_pr5_review_20260418.md` OR short separate report `briefs/_reports/B2_pr5_delta_review_20260418.md` — your choice.
Verdict: APPROVE / REDIRECT / BLOCK on the delta.

---

## Task A-new: Review PR #6 — LOOP-HELPERS-1

**PR:** https://github.com/vallen300-bit/baker-master/pull/6
**Branch:** `loop-helpers-1` (based on `loop-schema-1` because PR #5 still open at push time — noted in PR body)
**Head:** `6c23d36`
**Tests:** 25/25 green

### Scope of review

**IN**
- `kbl/loop.py` — three helpers: `load_hot_md()`, `load_recent_feedback()`, `render_ledger()`
- `LoopReadError` exception class
- Env var: `KBL_STEP1_LEDGER_LIMIT` default 20
- Tests in `tests/test_loop_helpers.py`:
  - `load_hot_md`: happy path, missing file returns None, permission error raises LoopReadError
  - `load_recent_feedback`: happy path, empty table returns [], limit override, env-var default
  - `render_ledger`: empty list placeholder, N rows render, special-char escape
- Fixture hot.md files in `tests/fixtures/`
- CHANDA compliance: Inv 1 (missing file = valid zero-Gold), Inv 10 (helpers read, don't rewrite)

**Specific scrutiny**
1. `load_hot_md` missing-file returns None (not raise) — Inv 1 compliance
2. `load_recent_feedback` empty-table returns [] (not raise) — Inv 1 compliance
3. Env-var default: 20 matches CHANDA §2 Leg 3 spec + OQ2 resolution
4. `render_ledger` format is Director-scannable (`[YYYY-MM-DD] action target: note` shape)

**OUT**
- Writer-side (KBL-C)
- Prompt wiring (KBL-B impl separate)

### Format
`briefs/_reports/B2_pr6_review_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline
~20-30 min.

---

## Task B (batched review): B3's CHANDA-Compliance Fold Package

Both drafts land as a coherent loop-compliance package — batch the review to save context-load time. Treat as ONE review with two parts.

### Part 1: Step 1 Triage Prompt Inv-3 Amendment

**File:** `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md`
**Commit:** `773f8c5`
**Author:** B3

### Part 2: §10 Test Fixtures Loop Compliance Amendment

**File:** `briefs/_drafts/KBL_B_TEST_FIXTURES.md`
**Commit:** `f47e9a5`
**Author:** B3

### Scope of review

**IN**
- **Inv 3 compliance:** Step 1 builder loads hot.md + feedback_ledger on every call; template body explains USAGE (not just availability)
- **Post-REDIRECT cross-link weight:** `related_matters[]` is now authoritative — Step 6 finalize() does NOT re-evaluate. Verify Step 1 carries that weight explicitly.
- **Cross-matter elevation (AI Head OQ3 answer to B3):** hot.md watch-list matters should elevate triage_score even when they are NOT primary_matter but appear in extracted entities. Verify Step 1 amendment handles this — if not, flag as should-fix.
- **Ledger limit configurability (AI Head OQ2 answer to B3):** 20 is Phase 1 default; should be env-var parameterized (`KBL_STEP1_LEDGER_LIMIT`). Verify helper signature permits override.
- **Loop compliance assertions (§10):** hard-assert pattern per B3 spec. Verify fixtures #11-#13 actually EXERCISE each leg (elevation, correction propagation, zero-Gold). Not just assert the read occurred — assert the read INFLUENCED the output.
- **Leg 2 out-of-scope decision (§10):** B3 explicitly parked Leg 2 atomicity tests to `test_feedback_ledger_atomicity.py`. Confirm that's the right boundary — §10 is pipeline integration, not ledger unit tests. Agree or push back.
- **Worked examples (Step 1 §1.5):** do the 3 examples correctly demonstrate hot.md + ledger behavior, or are they tautological?
- **Token/latency cost estimate:** ~+900 tokens worst-case, +1-3s latency. Validate against prior Gemma perf numbers. Flag if unrealistic.
- **CHANDA compliance:** does amended Step 1 prompt pass Q1 Loop Test explicitly? Cite in review.

**OUT**
- Re-opening D1 Gemma ratification (88v/76m stays)
- Implementing the Python helpers (B1's KBL-B ticket)
- New fixtures beyond #11-#13
- hot.md schema for Phase 3 (B3 OQ1 — deferred to KBL-C)

### AI Head answers to B3's 3 OQs (pass to B2 for context)

1. **OQ1 hot.md schema for Phase 3** — DEFER. Phase 1 is Director-curated manual file; Phase 3 auto-write lives in KBL-C. Out of scope for KBL-B.
2. **OQ2 ledger sampling beyond 20** — env-var configurable (`KBL_STEP1_LEDGER_LIMIT`, default 20). Revisit with Phase 1 data.
3. **OQ3 cross-matter elevation** — YES. Hot.md watch-list matters elevate triage_score if ANY extracted entity matches, not only primary_matter. This is a content-review item — if B3's draft doesn't handle this, flag as should-fix for Task B redirect.

### Format

`briefs/_reports/B2_chanda_compliance_fold_review_20260418.md`
Verdict: APPROVE / REDIRECT (list fix items, inline-appliable) / BLOCK
Structure the report with separate Part 1 + Part 2 verdicts (can be split — e.g., Step 1 REDIRECT + §10 APPROVE).

### Timeline
~30-45 min for both parts combined.

---

## Task C (queued, fires when AI Head commits REDIRECT fold)

AI Head is folding Step 6 REDIRECT into KBL-B brief §2, §3.2, §4.7, §6, §8, §9, §10, §11. Expected commit shortly. When you see `fold(KBL-B): Step 6 REDIRECT` in git log:

### Scope of review

- All 8 sections updated consistently (no residual Sonnet references)
- §4.7 rewrite matches your concrete `step6_finalize()` spec
- §8 retry ladder: Sonnet paths removed, Opus R3 carries frontmatter-validation-failure
- §9 cost-control: no `sonnet_step6` ledger rows written; enum value preserved per your note
- §3.2 state enum cleanup
- §10 fixture path coverage updated for deterministic Step 6 (cross-reference Task B Part 2 §10 amendment)
- §11 observability: no Sonnet metrics; finalize latency metric added

### Format

`briefs/_reports/B2_kbl_b_redirect_fold_review_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline
~20-30 min.

---

## Task D (final): CHANDA.md Onboarding + Prior-Review Audit

Same pattern as B1 + B3's acks. Read CHANDA, internalize §2 loop + §3 invariants + §5 test, file ack at `briefs/_reports/B2_chanda_ack_20260418.md`. ~15-20 min.

### Additionally audit your prior reviews

Compliance audit of: KBL-A PR #1 reverify, SLUGS-1 PR #2, PR #3 TCC, KBL-B §4-5 phase-2, KBL-B Step 1/3 prompts, Step 0 Layer 0 rules, Step 6 scope challenge, PR #4, PR #5 (Task A above), CHANDA-compliance fold (Task B above), REDIRECT fold (Task C above). Any prior verdict conflict with CHANDA invariants in hindsight? Flag, don't silently absorb.

---

## Parallel state

- B1: idle post-double-amend (PR #5 at `c8c7a35`, PR #4 at `7cccb61` ready for Director merge)
- B3: idle post-three-task-delivery
- AI Head: REDIRECT fold in-progress
- Director: possibly running hot.md debrief in a separate session

### Dispatch back (after each task)

> B2 PR #5 review done — `<report>`, commit `<SHA>`. Verdict: <...>.
> B2 CHANDA-compliance fold review done — `<report>`, commit `<SHA>`. Part 1: <...>, Part 2: <...>.
> B2 REDIRECT fold review done — `<report>`, commit `<SHA>`. Verdict: <...>.
> B2 CHANDA ack + prior-review audit done — `<report>`, commit `<SHA>`. <flags>.

---

*Posted 2026-04-18 by AI Head. Four sequential reviews ≈ ~85-120 min total. Reviewer-separation held; you are reviewer-of-record for all active architectural decisions.*
