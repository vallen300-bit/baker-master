---
title: B2 Step 5 Opus Prompt Review
voice: report
author: code-brisen-2
created: 2026-04-18
---

# Step 5 Opus Prompt Draft Review (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) Task B
**File reviewed:** [`briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md`](../_drafts/KBL_B_STEP5_OPUS_PROMPT.md) @ commit `7ea63c6` (570 lines, B3-authored)
**Cross-referenced:** PR #6 `kbl/loop.py`; my prior Step 6 scope challenge (REDIRECT); my CHANDA ack (§5 citation discipline)
**AI Head resolutions to apply:** OQ1 → `author: pipeline`; OQ5 → deployment blocker, not draft blocker
**Date:** 2026-04-18
**Time:** ~30 min

---

## 1. Verdict

**REDIRECT — 1 should-fix (S1: OQ1 author rename throughout) + 7 nice-to-have items.**

The draft is structurally sound, CHANDA-coherent, and the worked examples are corpus-grounded. B3's §4 self-check is the model citation discipline I committed to in my own ack — Q1 Loop Test + Q2 Wish Test cited by name with reasoning, all 10 invariants enumerated. The only structural item is the AI Head OQ1 ratification (`author: pipeline`, not `tier2`) which lands at ~9 sites across the draft.

**§5 Q1 Loop Test:** This prompt **IS Leg 1.** It is the mechanism by which Gold conditions future Silver. B3 explicitly recognizes this in §4 Q1 row and stages it for Director visibility. **Authorization trail:** task brief dispatch → B3 draft → this review → AI Head fold → Director-implicit (Leg 1 design first surface). Director's pre-approval was implicit in the prior approval of KBL-B brief shape (§4.6 Step 5 contract pre-existed). Authorization clean. ✓

**§5 Q2 Wish Test:** Serves the wish — synthesis of loop inputs into Director-reviewable Silver, with Gold honored. The convenience layer (prompt-caching on stable system block) is co-aligned, not at odds. The cost-vs-Gold-corpus-size tradeoff (B3 §5 OQ3) is the genuine future-Phase concern; for now, both legs of Q2 are satisfied. ✓

---

## 2. Blockers

**None.**

---

## 3. Should-fix

### S1 — Apply AI Head OQ1: `author: tier2` → `author: pipeline` (9 sites)

**AI Head ratified resolution:** Step 5 emits `author: pipeline` (machine-generated Silver). Director promotion flips to `author: gold` / `voice: gold`. Two distinct author values track the lifecycle: `pipeline` (Silver) vs `director` / `gold` (Director-promoted Gold).

B3's draft currently uses `author: tier2` and explicitly raises the divergence in §5 OQ1. The fix is mechanical — replace `tier2` → `pipeline` at 9 sites:

| # | Line | Surface | Current | Fix |
|---|---|---|---|---|
| 1 | 14 | §0 CHANDA binding statement (Inv 4) | `author: tier2` (pipeline-authored) | `author: pipeline` |
| 2 | 110 | §1.2 rule F2 text + body | "Frontmatter `author: tier2` always. … You are the Tier-2 synthesis layer. `author: director` and `author: pipeline` are reserved for other writers. Use `tier2`." | "Frontmatter `author: pipeline` always. … `author: director` / `author: gold` are reserved for Director-promoted Gold. Use `pipeline` for all Step 5 output." |
| 3 | 148 | §1.2 frontmatter required-keys spec | `author: tier2` | `author: pipeline` |
| 4 | 179 | §1.2 invariants summary | "`voice: silver`, `author: tier2`" | "`voice: silver`, `author: pipeline`" |
| 5 | 343 | Worked Example 1 frontmatter | `author: tier2` | `author: pipeline` |
| 6 | 421 | Worked Example 2 frontmatter | `author: tier2` | `author: pipeline` |
| 7 | 501 | Worked Example 3 frontmatter | `author: tier2` | `author: pipeline` |
| 8 | 288 | §2 changes-against-main reconciliation note | "this draft uses `author: tier2` per the dispatch task spec … `author: pipeline`" | "this draft uses `author: pipeline` per AI Head OQ1 resolution 2026-04-18; aligned with `kbl/gold_drain.py` docstring (line 146) and B2's Step 6 scope review" |
| 9 | 540 | §4 Inv 4 compliance row | "Frontmatter `author: tier2`. `author: director` never emitted by this prompt (nor `author: pipeline` — see §5 OQ1 reconciliation)" | "Frontmatter `author: pipeline`. `author: director` and `author: gold` are reserved for Director-promoted Gold and never emitted by this prompt." |
| 10 | 552 | §5 OQ1 status | OPEN — "AI Head decision, please" | RESOLVED — "AI Head ratified `pipeline` 2026-04-18; applied throughout S1 amend." |

**Why must-fix, not nice-to-have:**
- Author lifecycle is load-bearing for Director's promotion mechanic (Inv 8). If Step 5 ships `tier2`, Director's promotion gesture (`author: gold` frontmatter edit) doesn't have the canonical predecessor value. The `tier2` → `pipeline` flip closes this.
- B3 already flagged it as production-blocker in §5 OQ1; AI Head's resolution closes the question definitively. The only remaining work is mechanical apply.
- Once landed, prompt-caching system block hashes will rev (`tier2` is in the cacheable §1.2 system template) — one-time cache miss, no recurring cost.

---

## 4. Nice-to-have

### N1 — No worked example demonstrates the `⚠ CONTRADICTION:` rule (G1)

**Location:** §3 Worked examples; §1.2 G1 rule + Contradiction handling subsection.

The G1 rule is one of the strongest invariant-protecting design choices in the prompt — it forecloses the "model silently overwrites Director judgment" failure mode. But none of the 3 worked examples actually exercise it:

- Ex 1: zero-Gold (no Gold to contradict)
- Ex 2: continuation, "no contradiction with prior Gold"
- Ex 3: zero-Gold primary

Without a worked example, the model has no in-context shot of the ⚠ marker shape, and a future debugger can't trace "what should the body look like when contradiction fires?"

**Fix.** Add a 4th example (Ex 4 — Contradiction case). Suggested signal: a hypothetical Cupial settlement counter-offer that contradicts prior Gold (e.g., a Gold entry stating "Cupials demand €266K + €600K defects total ~€866K" vs a new signal where Hassa proposes settlement at €450K cap — direct contradiction with prior Director judgment of the gap). Show:
- The ⚠ CONTRADICTION line with full Gold path citation
- The body NOT trying to reconcile or paraphrase
- "Director review requested" wording

Alternative: extend Ex 2's MO Vienna case with a parametrized "if the Feb 4 meeting had said 'we're sticking with Data Vision, abandoning the build,'" → ⚠ marker — keeps fixture count at 3 but adds the variant.

Defer-but-track. Not blocking. The G1 rule is correctly stated; an exemplar would harden it.

### N2 — No worked example demonstrates ledger-driven correction propagation

**Location:** §1.2 "How to use the feedback ledger" + §3 worked examples.

§1.2 says: *"If Director recently `correct`-ed a similar-shape signal (same source, similar sender, similar body), frame your draft the way the correction implies — not the way the original errored model did."*

Worked Example 2 has a `promote` ledger event but not a `correct` event. Worked Example 3 has a `promote` event for `wertheimer`, also not a `correct`. So the correction-propagation mechanic — arguably the most consequential ledger-steering pattern — has no in-context demonstration.

**Fix.** Either extend Ex 2 with a hypothetical `correct` event in the ledger (e.g., 2026-02-02 correct on a prior MO Vienna signal where the model misclassified vedana from `routine` to `opportunity`), and show the new draft applying that correction. Or add Ex 5.

This pairs with N1 — both are gaps in worked examples for the most invariant-sensitive rules. A single fixture amend could cover both (one contradiction example + one correction example).

### N3 — `_render_entities()` output shape unspecified

**Location:** §1.1 builder line 78; §5 OQ8.

The builder calls `_render_entities(extracted_entities)`. No definition is given for this function — the §1.2 user template just `{extracted_entities}` formats whatever it returns. The 3 worked examples show entities rendered as a YAML-like bulleted block:

```
extracted_entities:
  people: Alric Ofenheimer (E+H, lawyer), Thomas Leitner (Brisengroup)
  orgs: Hagenauer, Engin+Hanousek
  money: (none)
  ...
```

But §5 OQ8 says "compact JSON dump vs human-readable bulleted block vs mixed form" is undecided.

**Inconsistency:** the worked examples implicitly commit to bulleted-block format, but the open question says it's undecided. Pick one, document in §1.4 helper signatures, and remove from OQ8 → RESOLVED. The bulleted block (matches what examples show) is fine; compact JSON is also fine (terser, machine-friendlier). Either is a 30-char fix.

**Subtle gotcha:** if entities is empty `{}`, the renderer should output a stable sentinel (`(no entities extracted)`), not empty string — otherwise the template has a blank section and the model may infer "section was missing" rather than "section was empty." Same shape-stability principle as the zero-Gold sentinel.

### N4 — `signal_raw_text[:50000]` truncation is silent

**Location:** §1.1 builder line 77.

```python
signal_raw_text = signal_raw_text[:50000],
```

If raw signal exceeds 50K chars (unlikely for email/WhatsApp; possible for a long meeting transcript), truncation happens silently. The model sees the truncated text without any indication that it's incomplete.

**Failure mode.** A 60-min meeting transcript (~50-80K chars) gets truncated mid-discussion. Model summarizes only the first half. Director reads the Silver entry and sees no flag that context was lost.

**Fix.** Either:
- **(a)** Append a marker when truncation occurs: `signal_raw_text[:50000] + "\n\n[TRUNCATED FROM " + str(len(signal_raw_text)) + " CHARS]"` if `len > 50000`. Three lines.
- **(b)** Raise on truncation and let the upstream worker decide (escalate to summarization sub-step, route to inbox for Director, etc.).

Lean (a) for v1 — preserves liveness, surfaces the loss. (b) is the more architectural answer and pairs with the Gold-corpus-summarization pre-step B3 floats in OQ3.

### N5 — Self-check summary (§1.2 line 178-184) omits the ⚠ CONTRADICTION rule

**Location:** §1.2 Invariants summary subsection.

The 6-bullet self-check list before the model emits:
- Frontmatter begins with `---`, 9 required keys, voice/author correct
- Body begins with prose summary, not heading
- No preamble, no postamble
- Gold referenced by path if referenced at all
- `resolved_thread_paths` entries appear in body or in `thread_continues` frontmatter
- No speculation beyond inputs

The contradiction-flag rule (G1's most consequential clause) is **not** in the list. A model self-checking against this enumerated set could fail to apply ⚠ when it should. Add a 7th bullet:

> *"If the body contradicts any line in `gold_context_block`, the body contains an explicit `⚠ CONTRADICTION:` line with the conflicting Gold path. No silent overwrite, no paraphrase-as-correction."*

One bullet. Tighten the prompt's self-check coverage of its strongest invariant.

### N6 — Gold context loaded for `primary_matter` only — not `related_matters`

**Location:** §1.1 builder lines 61-65; §1.4 helper signature.

`load_gold_context_by_matter(primary_matter)` reads Gold for ONE matter — the primary. A signal with non-empty `related_matters` does NOT load related-matter Gold context. This is a defensible scoping choice (primary is where the synthesis lives; related_matters are cross-link bullets, not context for the body) but it isn't documented as an explicit decision.

**Failure mode (Phase 3+):** A signal with primary `wertheimer` (zero-Gold) and related `mo-vie` (rich Gold corpus). The prompt sees no mo-vie Gold; the cross-reference bullet is a plain `- see wiki/mo-vie/` without any actual mo-vie context informing the body. If a Director ever expects the Silver to "weave in" related-matter Gold, the design says no — and they should know it does.

**Fix.** Add a one-line clarification to §1.4 helper signature docstring (between the existing "Path resolution" and "Returns" lines):

> *"Scope: only `primary_matter` Gold is loaded. Related-matters Gold is NOT loaded — it is referenced via cross-link bullets in `## Cross-references`, not as body context. If a future Phase requires loading related-matters Gold, that's a new helper (`load_gold_context_for_matters([slug, ...])`), not a parameter to this one."*

Closes a future "but my related-matter Gold is missing" gotcha.

### N7 — OQ2 (ledger limit env-var) is a small thing AI Head can resolve in this fold

**Location:** §1.4 line 279; §5 OQ2.

B3 proposes `KBL_STEP5_LEDGER_LIMIT` mirroring PR #6's `KBL_STEP1_LEDGER_LIMIT`, with an alternative single `KBL_LEDGER_LIMIT` governing both steps.

**Recommend resolving in this fold.** The ledger is the same table; the recency-window concept is the same. Two env vars is over-flexibility for v1. AI Head: either pick `KBL_LEDGER_LIMIT` (single source of truth) or `KBL_STEP5_LEDGER_LIMIT` (parallel naming). Trivial decision, blocks-nothing — but if not resolved, B1 ships Step 5 impl with one env-var name, then has to refactor when AI Head later picks the other.

Defer to AI Head call. Mark RESOLVED in §5 with the chosen name when the fold lands.

---

## 5. CHANDA compliance audit

### Q1 Loop Test — explicit, escalation-aware

§4 Q1 row (line 536):
> *"This prompt IS Leg 1. It is the mechanism by which Gold conditions future Silver. Design choices in §1.2 rules G1-G3 and the mandatory `gold_context_block` pass in §1.1 encode Leg 1. A reviewer who challenges G1-G3 is flagging a Leg 1 concern and MUST escalate per §5 before a merge. Not a new Leg violation — this prompt CREATES the Leg 1 reading pattern for Step 5, consistent with Inv 1. Flagged for Director visibility regardless."*

This is the citation shape my CHANDA ack committed to. B3 correctly identifies that **creating a new Leg 1 surface** is itself a CHANDA-significant act, not just an implementation detail. The escalation framing ("a reviewer who challenges G1-G3 MUST escalate") prevents future REDIRECTs from quietly weakening G1-G3 without going through Director. Strong.

### Q2 Wish Test — wish + convenience tradeoff named

§4 Q2 row (line 537): both legs satisfied; the cost-vs-Gold-corpus-size tradeoff (will surface at Phase 3 with mature matters) is correctly deferred to Phase-1-close measurement. The mitigation path (Gold-summarization pre-step rather than truncation cap) is the right architectural answer if cost compounds.

### Per-invariant audit

| Inv | B3 §4 row | My audit |
|---|---|---|
| **1** Gold read; zero-Gold safe | "Empty-sentinel block, not absent. Prompt rule G2 enforces first-record behavior." | ✓ Verified in §1.1 (lines 61-65) + §1.2 G2 rule + Worked Ex 1 (zero-Gold body). |
| **3** Step 1 reads hot.md + ledger every run | "Re-read on every call via the same `kbl/loop.py` helpers Step 1 uses. Not cached." | ✓ Verified in §1.1 (lines 68-72). Same helpers, same fail-soft posture. |
| **4** `author: director` files never modified | "Frontmatter `author: tier2`. `author: director` never emitted." | **S1 will rewrite to `author: pipeline`.** Substance correct (this prompt produces NEW files, doesn't modify Director-authored ones); the literal `author` value is the OQ1 fix. |
| **5** Every wiki file has frontmatter | "Every emitted wiki file has full 9-key frontmatter." | ✓ §1.2 frontmatter spec + 3 worked examples all show 9 keys minimum. Step 6 finalize() Pydantic-validates this; Step 5 is the producer. |
| **6** Pipeline never skips Step 6 | "Cross-link section emitted when `related_matters` non-empty. Step 6 finalize() applies structural cross-link handling deterministically." | ✓ Aligns with my Step 6 REDIRECT (Step 6 still fires, deterministic). Cross-link work split between Step 5 (body bullet) + Step 6 (structural `_links.md` write). |
| **7** Ayoniso alerts are prompts, not overrides | "No ayoniso override behavior in this prompt — Step 5 is the synthesis step, not the alerting step." | ✓ §5 OQ7 raises the ⚠-vs-ayoniso channel question — recommend keeping them independent (B3's lean). My recommendation: agree, ⚠ is documentary, ayoniso is runtime. |
| **8** Silver→Gold only by Director frontmatter edit | "`voice: silver` always. No self-promotion." | ✓ §1.2 rule F1 + invariants summary explicit. Hard rule. |
| **9** Mac Mini single writer | "Single-writer Mac Mini constraint is a Step 7 harness concern, not this prompt's." | ✓ Correct boundary. Step 5 produces the markdown; Step 7 commits to vault under flock. |
| **10** Pipeline prompts don't self-modify | "Prompt is a stable template. All variation comes through data blocks." | ✓ System block is immutable string; user block is `format()` substitutions only. No self-rewriting path. |

**Net: CHANDA posture is exemplary.** All 9 applicable invariants enumerated and substantively addressed. Q1 + Q2 cited by name. The escalation clause in §4 Q1 row is the right shape for future review discipline.

---

## 6. Specific scrutiny — task brief items

### Template completeness against §4.6 contract

§1.1 builder reads all 10 listed input blocks ✓:

| Block | Source | Where in builder |
|---|---|---|
| `signal_raw_text` | Step 0+ | line 77 (truncated at 50K — see N4) |
| `extracted_entities` | Step 3 | line 78 (`_render_entities` — see N3) |
| `primary_matter` | Step 1 | line 79 |
| `related_matters` | Step 1 | line 81 |
| `vedana` | Step 1 | line 82 |
| `triage_summary` | Step 1 | line 83 |
| `resolved_thread_paths` | Step 2 | line 84 |
| `gold_context_by_matter` | new helper (OQ5) | lines 61-65 |
| `hot_md_block` | PR #6 helper | line 69 |
| `feedback_ledger_block` | PR #6 helpers | lines 70-72 |

All 10 present, all sentinel-aware on empty.

### Leg 1 compliance (Inv 1)

- `gold_context_by_matter` is **always** loaded — sentinel block on null primary OR empty Gold (lines 61-65). Not omitted, not None — empty-sentinel string. ✓
- Worked Example 1 demonstrates the zero-Gold path produces a valid first entry, not an error or refusal. ✓
- §1.2 G2 rule explicitly mandates first-record tone for zero-Gold. ✓
- See N6 for related-matters Gold scoping clarification (additive, not Inv 1 violation).

### Inv 8 compliance (frontmatter `voice: silver` always)

- §1.2 rule F1: "voice: silver always. You never emit voice: gold." ✓
- §1.2 frontmatter spec: `voice: silver` ✓
- §1.2 invariants summary: `voice: silver` ✓
- All 3 worked examples: `voice: silver` ✓
- §4 Inv 8 row reaffirms ✓

### Contradiction handling (`⚠ CONTRADICTION:` marker)

- §1.2 G1 rule explicit: ⚠ marker required, no silent overwrite, no paraphrase-as-conclusion ✓
- §1.2 Contradiction handling subsection (lines 169-175) repeats with format example ✓
- **Gap:** no worked example demonstrates the marker — see N1.
- **Gap:** invariants summary self-check doesn't include the contradiction rule — see N5.

### Hard constraints

§1.2 lists all 5:
1. No speculation ✓
2. No hallucinated entities ✓
3. No long verbatim quotes (>30 chars requires citation) ✓
4. No preamble/postamble ✓
5. Target 300-800 tokens body ✓

### Output contract

- Frontmatter first, then body, both mandatory ✓
- 9 required keys in spec'd order ✓
- 3 optional keys named (thread_continues, deadline, money_mentioned) ✓
- Body structure: 5 sections (summary / key facts / decisions / context / cross-references) ✓
- 300-800 token target ✓
- No preamble/postamble ✓

### Worked examples (§3)

| Ex | Coverage | Quality |
|---|---|---|
| 1 — Hagenauer zero-Gold | Leg 1 zero-Gold (G2); Inv 1 first-record | ✓ Corpus line 10 cited; expected output is plausible Silver shape |
| 2 — MO Vienna continuation | G3 thread continuation; G1 honor Gold; hot.md acknowledgement; ledger `promote` propagation | ✓ Corpus line 28 cited; demonstrates `## Continues` block + `thread_continues` frontmatter; `money_mentioned` surfaced |
| 3 — Wertheimer cross-matter WhatsApp | Cross-matter handling (Step 1's `related_matters` honored, no second-guessing); zero-Gold primary + ACTIVE hot.md mention; ledger `promote` propagation | ✓ Corpus line 35 cited; demonstrates the post-REDIRECT contract (Step 5 honors Step 1's cross-link choice, doesn't re-derive); single-shot cross-matter elevation referenced in body |

**Coverage gaps:** no contradiction example (N1), no `correct`-event ledger propagation example (N2). Defer-but-track.

### CHANDA §5 Q1 + Q2 cited in §4

✓ Both cited by name. Q1 has explicit escalation clause. Q2 names wish + convenience tradeoff.

---

## 7. AI Head resolution audit

| Resolution | B3 draft state | Action this review |
|---|---|---|
| **OQ1** → `author: pipeline` (not `tier2`) | Draft uses `tier2` at 9 sites; §5 OQ1 explicitly raises divergence | **S1 must-fix** — apply at all 9 sites listed above; mark §5 OQ1 RESOLVED |
| **OQ5** → B1 helper PR coming later, deployment blocker not draft blocker | B3 already framed this way (§1.4 + §5 OQ5) | ✓ No draft change needed; §5 OQ5 stays OPEN with "blocks deployment, not draft" annotation. Pre-flag for B1 dispatch (suggested PR name `LOOP-GOLD-READER-1`). |

---

## 8. Summary

- **Verdict:** REDIRECT.
- **Blockers:** 0.
- **Should-fix:** 1 (S1: `author: tier2` → `author: pipeline` at 9 sites per AI Head OQ1).
- **Nice-to-have:** 7 (N1 contradiction worked example; N2 ledger-correction worked example; N3 entity renderer shape decision; N4 silent truncation marker; N5 contradiction rule in self-check summary; N6 related-matters Gold scoping clarification; N7 OQ2 single-vs-dual env-var resolution).
- **CHANDA compliance:** Q1 + Q2 cited by name with escalation clause; all 9 applicable invariants enumerated and substantively addressed. Exemplary citation discipline.
- **Worked examples:** 3 of 3 corpus-grounded; coverage gaps on contradiction + correction (N1 + N2).
- **Template completeness:** all 10 input blocks loaded; all 5 hard constraints stated; all 9 frontmatter keys spec'd; output contract complete.

**Pre-flag for AI Head:**
- When folding S1, system-block prompt-cache invalidates (one-time miss, no recurring cost). Bump prompt version key per Inv 10 spirit.
- B1 follow-on: `LOOP-GOLD-READER-1` for `load_gold_context_by_matter` helper. Step 5 cannot fire in production until it lands — gate Step 5 dispatch behind it.
- N1 + N2 (worked-example coverage gaps for contradiction + correction) can land in a single fixture amend on the next Step 5 prompt revision; defer to first-cycle close-out.

The draft is mergeable into KBL-B §6.3 after S1 lands. The 7 nice-to-haves are post-fold polish that should land alongside the LOOP-GOLD-READER-1 PR or in a separate prompt-tightening touch — none gate Step 5 implementation start, except S1 which must precede.

This is the strongest CHANDA-aware prompt draft B3 has shipped. The §4 Q1 escalation framing should be the convention for future Leg-1-touching prompts.

---

*Reviewed 2026-04-18 by Code Brisen #2. File @ `7ea63c6`. Cross-referenced against PR #6 `kbl/loop.py` (helpers verbatim ✓), my Step 6 scope challenge (REDIRECT-coherent ✓), and CHANDA §5 framework (citation discipline exemplary). No code changes; design + draft review only.*
