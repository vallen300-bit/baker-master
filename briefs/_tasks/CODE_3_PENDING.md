# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** CHANDA ack + prior-work compliance audit filed at `e9eb04e`. Two real flags raised (Step 1 violates Inv 3; §10 fixtures pass mechanically only).
**Task posted:** 2026-04-18
**Status:** OPEN — three deliverables, priority order below

---

## AI Head direction on your two flags

**Both pre-ratified by Director (amend-now posture approved):**
- Flag 1 (Step 1 Inv 3 violation) → Task 1 below
- Flag 2 (fixtures pass mechanically only) → Task 2 below

**Context update — Step 6 REDIRECT verdict landed:** B2 ratified REDIRECT — Step 6 becomes deterministic `finalize()`, no LLM call. This shifts semantic weight onto Step 1: **the "should this cross-link to Hagenauer?" reasoning now lives ONLY in Step 1's prompt.** Your Step 1 amendment needs to carry both the Inv 3 fix AND the post-REDIRECT cross-link responsibility.

---

## Task 1 (highest priority): Amend Step 1 Triage Prompt for Inv 3 Compliance + Post-REDIRECT Cross-link Responsibility

### Scope

**IN**
- Amend `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md`
- Add the two template placeholders + loader helpers per your §3 remedy sketch:
  - `{hot_md_block}` → loaded from `$BAKER_VAULT_PATH/wiki/hot.md` (Phase 1: Director-maintained file; if absent, render "(no current-priorities cache available)" — valid zero-Gold read per Inv 1)
  - `{feedback_ledger_recent}` → query `feedback_ledger ORDER BY created_at DESC LIMIT 20` (B1 is creating this table in LOOP-SCHEMA-1 PR #5, parallel-running; if table empty at call time, render "(no recent Director actions)")
- Add two new sections in the template body explaining model usage:
  1. **"How to use `hot.md`":** "The hot.md block describes Director's currently-pressing matters. When a signal's matter appears in hot.md, elevate `triage_score` by 0.15 (capped at 1.0). When a signal touches a matter marked ACTIVELY FROZEN in hot.md, suppress triage by 0.10. Hot.md is a steering signal, not a hard override."
  2. **"How to use the feedback ledger":** "The ledger shows Director's last 20 actions. Patterns to respect: if Director has recently re-classified matter X → null for signals resembling this one, prefer null. If Director has promoted similar signals to Gold for matter Y, prefer matter Y with slight triage boost. The ledger is historical correction data, not a mandate."
- Add a **post-REDIRECT cross-link section**: "The `related_matters[]` output is now authoritative. Step 6 is deterministic finalization and will NOT re-evaluate cross-link choices. If a signal substantively touches a matter beyond primary_matter, include it in related_matters. Conservative default: omit. Empty list is always valid."
- Update the worked examples to demonstrate hot.md + ledger influence on triage_score

**OUT**
- Implementing the `_load_hot_md()` / `_load_recent_feedback()` Python helpers (that's KBL-B impl, B1's ticket)
- Schema changes for feedback_ledger (B1's LOOP-SCHEMA-1 PR #5)
- Re-running D1 eval (D1 ratification stands; new prompt will need re-eval at Phase 1 close per D1's Phase 2 gate)
- Any model downgrade discussion (Gemma 4 8B stays)

### Q1 Loop Test (must be explicit in your amendment PR)

This change DIRECTLY MODIFIES Leg 3 (Step 1's reading pattern). It is the remedy for the detected non-compliance, not a new deviation. Director pre-approved remedy under amend-now posture at the prior turn. Cite CHANDA §5 Q1 in commit message + note amend-now authorization.

### Reviewer

B2. Reviewer-separation: you author, B2 reviews.

### Timeline

~45-60 min.

### Dispatch back

> B3 Step 1 Inv-3 amendment shipped — `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md`, commit `<SHA>`. Covers Inv 3 (hot.md + ledger loads) + post-REDIRECT cross-link weight. Ready for B2 review.

---

## Task 2 (after Task 1): Add Learning Loop Compliance Assertions to §10 Fixtures

### Scope

**IN**
- Amend `briefs/_drafts/KBL_B_TEST_FIXTURES.md`
- Add a new **"Loop Compliance" row per fixture**, asserting at Step 1 pseudo-evaluation time:
  - `hot_md_loaded: bool` (true expected for every fixture once Task 1 ships)
  - `feedback_ledger_queried: bool` (true expected for every fixture)
  - `gold_context_by_matter_loaded: bool` (true per Inv 1 — zero Gold is read AS zero Gold)
- For 2-3 fixtures, add **Leg-specific test scenarios**:
  - Fixture demonstrating hot.md's triage_score influence (create a hot.md-steered test case)
  - Fixture demonstrating feedback_ledger correction propagation (create a Director-recently-corrected-similar-signal test case)
  - Fixture demonstrating zero-Gold-case (matter with no prior Gold — Step 1 should STILL attempt the read, just finds nothing)
- §10 harness section updated: pytest asserts loop compliance rows as hard assertions, not soft checks

**OUT**
- New signals outside the labeled corpus (synthetic scenarios OK if marked as such, per your dual-purpose fixture #6 convention)
- Actual Python harness code (that's KBL-B §10 impl, separate ticket)

### Reviewer

B2.

### Timeline

~30-45 min.

### Dispatch back

> B3 §10 fixtures loop-compliance amendment shipped — commit `<SHA>`. Ready for B2 review.

---

## Task 3 (lowest priority, runs last): Fireflies Hagenauer Transcript Search

**Director approved pursuing (c):** search Fireflies for Hagenauer meeting transcripts to add to the 50-signal labeled corpus. This closes the coverage gap you flagged in §10 (no full-synthesis transcript fixture under Phase 1's hagenauer-rg7-only scope).

### Scope

**IN**
- Search Fireflies via MCP (you have access in App Cowork): query meetings where title or summary contains Hagenauer / Schlussabrechnung / RG7 / Baden / Ofenheimer / Leitner / Moravcik
- Filter: meetings from last 90 days (Fireflies retention window) with transcript available
- Produce candidate list at `briefs/_drafts/HAGENAUER_TRANSCRIPT_CANDIDATES.md`:
  - Each candidate: meeting title, date, participants, word count, 150-char summary, Fireflies ID
  - Rank by likelihood of Phase-1-relevance (recent + core participants > older + tangential)
- Top 3-5 candidates surfaced for Director labeling

**OUT**
- Labeling yourself (Director owns labels per D1)
- Adding to the labeled JSONL (Director+you together, separate ticket after Director labels)
- Summarizing meeting content beyond the 150-char tag (no substantive extraction)

### Fallback

If 0 candidates found: report "no Hagenauer transcripts in Fireflies window" → Director rules option (a) per pre-approval, fixture #6 stays Phase-2-parameterized, §10 final spec accepts the gap.

### Reviewer

None — this is research output for Director consumption. No code review needed.

### Timeline

~20-30 min.

### Dispatch back

> B3 Hagenauer transcript search done — candidates at `briefs/_drafts/HAGENAUER_TRANSCRIPT_CANDIDATES.md`, commit `<SHA>`. <N> candidates surfaced OR zero found → invoke fallback (a).

---

## Global status after all three tasks

You close the Step 1 Inv-3 gap, harden §10 fixtures against mechanical-only test pass, and either fill the Hagenauer transcript coverage gap OR confirm we can't. All three feed directly into AI Head's KBL-B §6-13 writing push with zero residual loop-compliance risk.

---

*Posted 2026-04-18 by AI Head. B1 parallel-running LOOP-SCHEMA-1 (creates `feedback_ledger` table your Step 1 amendment depends on). B2 parallel-running PR #4 review + queued REDIRECT-fold review. Production-moving density across all three agents.*
