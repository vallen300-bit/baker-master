# KBL-B §6 Step 1 + Step 3 Prompt Drafts Review (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) — Deliverable 2 (B3-authored prompts review)
**Files reviewed:**
- [`briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md`](../_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md) (`cd8abab` B3, AI Head touched §3 + §6 for Qwen re-scoping)
- [`briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md`](../_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md) (`242a4d3` B3)
**Cross-referenced:** §4.2 + §4.4 contracts in `KBL_B_PIPELINE_CODE_BRIEF.md`
**Date:** 2026-04-18
**Time spent:** ~25 min

---

## 1. Verdict

**READY** — both prompts are mergeable into §6 with two should-fix items (one in each prompt) and a handful of nice-to-have flags. None are structural.

The bones are right. Step 1 is empirically backed (v3 results, ratified D1) and the AI Head Qwen re-scoping landed cleanly. Step 3 is design-forward (no prior eval) but the few-shots are corpus-grounded and the schema rules are tight.

---

## 2. Blockers

**None.**

---

## 3. Should-fix

### S1 — Step 3 few-shot Example 3 violates the date-format rule

**Location:** `KBL_B_STEP3_EXTRACT_PROMPT.md` Example 3 expected output:
```json
"dates":[{"date":"2018","event":"share transfer under dispute"}]
```

**Issue.** The prompt's extraction rule 4 says: *"date MUST be ISO 8601 (YYYY-MM-DD). Partial dates ('end of Q2', 'next week') → skip unless context gives a real date."* `"2018"` is a partial date (year-only), violating the rule. The few-shot is teaching the model the opposite of what the rule states.

Few-shot examples are the highest-fidelity teaching signal — Gemma will pattern-match this and emit year-only dates for legitimate ISO-8601 contexts. Self-contradiction is the worst class of prompt bug.

**Fix.** Three options, pick one:
- **(a)** Drop the date entry entirely from Example 3 (the share-transfer year is contextual, not actionable as a date).
- **(b)** Loosen the rule to allow year-only with explicit format spec: `"date MUST be ISO 8601 (YYYY-MM-DD or YYYY for year-only references)"`. Adds one more format gate Python validator must accept.
- **(c)** Replace with an ISO 8601 date that's actually in the signal (e.g., the 2026-01-12 meeting date itself, with `event: "court hearing"`).

I lean (a) — keeping the rule strict means downstream temporal reasoning in Step 5 doesn't have to handle year-only fuzz.

### S2 — Step 1 retry-on-malformed-JSON is a logical no-op at temp=0

**Location:** `KBL_B_STEP1_TRIAGE_PROMPT.md` §3 failure table row 1:
> "JSON malformed | json.loads() raises | Retry once with same prompt (non-determinism is zero at temp=0, but some Gemma builds show rare malformed output)."

**Issue.** The parenthetical correctly identifies the inconsistency: at `temperature=0, seed=42`, the model output is deterministic. Retrying with the same prompt + same options produces the same bytes. The retry can only succeed if:
- Ollama returned a transient infrastructure error wrapped as malformed-looking output (then retry maybe gets a clean response). Plausible.
- Model weights / GPU state changed mid-run. Implausible at our scale.

The "rare malformed output" claim isn't physically possible with deterministic sampling unless something below the model layer hiccupped. The retry then gates on infrastructure flakiness, not model nondeterminism.

**Fix.** Two options:
- **(a)** Acknowledge in-text: change parenthetical to *"(retry covers transient Ollama / network failures, not model nondeterminism — at temp=0 the same input deterministically produces the same output)"*.
- **(b)** Make the retry useful: bump `temperature=0.3` on the retry (a "rescue temp" pattern). Breaks out of any bad-attractor regions of the output distribution. Costs determinism on the retry path (single signal), but if the first attempt failed, deterministic-replay isn't useful anyway.

I lean (a) — keep determinism the strict default; document the retry's actual purpose. (b) is a real lever to consider in §7 error-matrix design but adding it here mid-prompt-doc is scope creep.

---

## 4. Nice-to-have

### N1 — Both prompts truncate at 3000 chars; meeting transcripts lose ~90%

**Location:** Step 1 line `signal_text.replace('"', "'")[:3000]`; Step 3 same.

A 30-min Fireflies transcript averages 5K-10K tokens (~20K-40K chars). Truncating at 3000 chars (~750 tokens) gives the model the first ~5 minutes only. For Step 1 (triage) this is probably fine — the matter and vedana are usually identifiable from the opening. For Step 3 (extract), entities discussed in the back half (e.g., money figures named in closing) silently disappear.

This isn't fixable in the prompt — it's a §4 contract design decision (cost vs completeness). But it should be **explicitly documented** in §6 as a known limitation. Future improvement: chunked extraction with per-chunk Step 3 calls, then merge — but that's KBL-B v2, not v1.

**Fix.** Add a `### Truncation note` paragraph to each prompt's §2 rationale: "Signals are truncated at 3000 chars before prompt assembly. For meetings >5 min, this loses content. Operating assumption: Step 1 matter+vedana are stable in the opening; Step 3 extraction may miss late entities. Reconsider in v2 with per-chunk extraction."

### N2 — Step 3 Example 1 silently parses ambiguous date "4/2/2026" as European format

Example 1 signal text mentions "your letter 4/2/2026 [EH-AT.FID2087]". Expected output normalizes to `"date":"2026-02-04"` — i.e., 4 February 2026 (DD/MM/YYYY European format). Could equally parse as April 2, 2026 (US MM/DD/YYYY).

For Brisen's Austrian/Swiss correspondence, EU format is the right default. But this is implicit in the few-shot and the rule doesn't pin it down.

**Fix.** Add to extraction rule 4: *"Ambiguous date formats (e.g., 4/2/2026) → assume DD/MM/YYYY (European convention) unless the source explicitly indicates otherwise."* Single sentence, clears the ambiguity.

### N3 — Step 1 confidence threshold (0.5) overlaps "guessing" rubric band

Step 1 §3 routes to inbox at `triage_confidence < 0.5`. The prompt's confidence rubric says `0.3-0.6 = guessing on at least one field`. So a model output of 0.5 confidence (right in the "guessing" zone) is on the edge — could route either way depending on rounding.

This is calibration territory (no eval has measured the score's distribution), so any single threshold pick is defensible. 0.5 is a reasonable default. Worth noting that ~half of "guessing" range routes to inbox, not all of it.

**Fix.** Optional: bump default to 0.6 to capture all of the "guessing" band. Or leave at 0.5 and tune empirically post-Phase-1. Neither blocks merge.

### N4 — Step 3 few-shot Example 2 puts Director ("Dimitry") in `action_items.actor`

Example 2 emits `{"actor":"Dimitry","action":"advise how to introduce RG7 to Wertheimer SFO"}`. The "skip self-references" rule (extraction rule 2) is scoped to `people` extraction. Dimitry-as-actor in action_items is fine — the rule doesn't prohibit it, and Dimitry IS the actor for this incoming WhatsApp request.

But it's worth being explicit. The rule could note: *"Self-references rule applies to `people` and `orgs` only. `action_items.actor` legitimately names the Director when they are the addressee of a request."*

Cosmetic clarification, not a behavior change.

### N5 — `triage_score` type drift: prompt says integer, brief §4.2 says NUMERIC(5,2), base table is INT

Step 1 prompt says `triage_score: <integer 0-100>`. KBL-B brief §4.2 invariant says `triage_score NUMERIC(5,2)`. Actual base table column is `triage_score INT` (KBL-19, can't be ALTERed by `IF NOT EXISTS`).

Three docs, three slightly-different specs. Prompt + base table agree (INT). §4.2 contract is the outlier.

This is the same item I flagged in `B2_kbl_b_phase2_review_20260418.md` S1. Resolution belongs in the §4.2 brief revision, not in this prompt. Flagging here only because the inconsistency now spans 3 documents.

### N6 — Step 1 prompt is silent on triage threshold

The prompt asks the model to score 0-100 but doesn't tell the model that signals scoring `<40` will be inboxed. Implicit. This is correct design (model shouldn't game the threshold), but worth noting that the model has no awareness of the cliff. If post-Phase-1 data shows clustering around the threshold (40, 41, 42 over-represented), might warrant rubric adjustment to give the model more spread.

No fix needed; flag for future tuning.

---

## 5. Confirmations — AI Head fixes landed

### Step 1 — Qwen re-scoping (D1 ratification 2026-04-18)

| Where | Status |
|---|---|
| §1 header — "AVAILABILITY fallback ONLY" | ✓ landed |
| §2.2 changes table — "**NOT used to trigger Qwen fallback**" | ✓ landed |
| §3 failure table — `low_confidence_to_inbox` row "Do NOT retry with Qwen" | ✓ landed |
| §3 failure table — Gemma-unreachable row triggers cold-swap with WARN log | ✓ landed |
| §6 Q1 — "RESOLVED by AI Head 2026-04-18" | ✓ landed |

Pattern is consistent across all 5 references. No accuracy-rescue framing leaks remain. Qwen-swap retry cap of 3 + recovery after 10-on-Qwen-or-1h is appropriate (sufficient for transient Ollama hiccups, doesn't anchor on a stuck-Qwen state).

### Step 3 — schema vs §4.4

| §4.4 invariant | Step 3 prompt enforcement |
|---|---|
| `extracted_entities` is a JSON object | "Output ONLY valid JSON" + "all 6 top-level keys MUST be present" ✓ |
| All 6 keys present | Explicit rule + Python post-parse adds missing keys with `[]` ✓ |
| Values are arrays | Explicit "values MUST be arrays" + Python coerces non-array ✓ |
| Sub-fields not null | "Omit, don't null" rule + Python drops null sub-fields ✓ |

Schema compliance is solid. Belt-and-suspenders: prompt-level rules + Python validator. Right level of defense for an extraction task with a strict JSON schema.

### `related_matters` dedupe (Step 1)

Prompt rule: "MUST NOT include primary_matter itself."
Python post: `related_matters` array stripped of `primary_matter` before write.
Both layers present → defense in depth. ✓

---

## 6. Votes on open §6 questions

### Step 1 — Q1 (Qwen trigger)

**RESOLVED** (per AI Head 2026-04-18). No vote needed.

### Step 1 — Q2 (`triage_score` calibration)

**Defer to Phase-1 close-out.** No eval has measured score calibration directly (v3 measured score-bucket alignment with `triage_pass_expected`, which is a related but different metric). Add a `kbl_pipeline_run.score_distribution_p50_p95` capture in §11 observability so calibration drift is visible at dashboard time. Then re-tune if needed. Out of scope for this prompt.

### Step 1 — Q3 (related-matters-only signals → primary=null?)

**Defer.** B3's instinct is right (current prompt biases toward picking one matter; if operational data shows mis-routing, add a "forwarded reference" rule). No data yet to support the change. Phase-1 burn-in will surface whether this is a real failure mode.

### Step 3 — Q1 (per-matter few-shot rotation)

**Defer per B3's recommendation.** Three static few-shots covering source diversity is the right v1. Per-matter rotation adds prompt-build complexity and benefits depend on per-matter eval data we don't have. Revisit when KBL-B v2 has Phase-1 production extraction quality data.

### Step 3 — Q2 (skip extraction on inbox-routed signals)

**YES, ship in v1.** Verified Step 4 (§4.5) reads `triage_score, primary_matter, related_matters, resolved_thread_paths` — does NOT read `extracted_entities`. So skipping Step 3 when `step_5_decision='skip_inbox'` is decided breaks nothing downstream. Saves ~10-25s/signal × N inbox signals/day. Pure cost win.

Caveat: Step 4's decision needs Step 3's output to NOT be required. Confirm in §4.5 implementation that `extracted_entities` defaults to the empty stub object when Step 3 is skipped, so Step 5 (which DOES read it on `full_synthesis` path) doesn't crash.

### Step 3 — Q3 (emoji handling)

**No special rule.** Ollama JSON mode handles UTF-8 fine, Python `json.loads` accepts. Adding a "strip emoji" rule would lose semantic signal (a 🔥 in WhatsApp is meaningful sentiment). Adding "preserve emoji" is implicit. Skip.

### Step 3 — Q4 (org type taxonomy → registry)

**Defer per B3's recommendation.** 9 hardcoded types is fine for v1. Promoting to `baker-vault/org_types.yml` registry adds a SLUGS-1-shaped ceremony for marginal benefit. Revisit if KBL-C dashboard surfaces real need for org-type-based filtering or Director wants to add types mid-flight.

---

## 7. Summary

- **Verdict:** READY (both prompts).
- **Blockers:** 0.
- **Should-fix:** 2 (Step 3 date-format self-contradiction; Step 1 retry-at-temp=0 wording).
- **Nice-to-have:** 6.
- **Confirmations:** AI Head's Qwen re-scoping landed cleanly (5 touchpoints, all consistent). Step 3 schema compliance with §4.4 verified.
- **§6 Q votes:** Step 3 Q2 = ship in v1 (free latency win); all others = defer per B3's instinct.

Both prompts can be copy-pasted into §6 once S1 and S2 are fixed (~5 min of edits).

---

*Reviewed 2026-04-18 by Code Brisen #2. Cross-checked against §4.2 (Step 1 contract) + §4.4 (Step 3 contract) in `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md`. No code, no evals — pure prompt review.*
