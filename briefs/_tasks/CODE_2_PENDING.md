# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous:** PR #3 APPROVE + §6 prompts READY shipped (both reviews, AI Head applied S1+S2 inline at `5bac5c5`)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** both prior-turn deliverables (shipped)

---

## Task: Review B3's Step 0 Layer 0 Rules Draft

**File to review:** `briefs/_drafts/KBL_B_STEP0_LAYER0_RULES.md` (commit `6341b94`, 527 lines)
**Author:** B3 (empirical lead, 50-signal eval corpus experience)
**Reviewer-separation:** B3 authored, AI Head didn't touch, you didn't touch — clean.

### Scope

**IN**
- Per-source rule coverage (email, WhatsApp, meeting transcript, scan query)
- Rule ordering + first-match semantics
- Rules-as-data YAML architecture (B3's proposal to lift rules into `kbl/config/layer0_rules.yml`)
- Configurability boundaries (hardcoded vs env-var tunable)
- Empirical basis — does each rule cite specific eval-set signals? Are citations sound?
- Integration with §4.1 I/O contract (writes `state='done'` or `'dropped_layer0'`, log on drop only, zero LLM cost)
- False-positive risk analysis — are legitimate signals at risk of accidental drop?

**OUT**
- Running any eval (B3 stood down from eval loop)
- Rule implementation code (this is rule *spec* review, Python impl lands in KBL-B)
- Proposing new rules not in B3's draft (if you see gaps, flag — don't author)
- Second-guessing D3 §247 "10-30% drop rate" ratification

### Specific scrutiny

1. **Rules-as-data YAML choice** — B3 proposes `kbl/config/layer0_rules.yml`. Is this the right shape vs hardcoded Python constants vs baker-vault config? What's the Director edit path?
2. **Email self-analysis dedupe** — v1 eval had 7 duplicates of Baker's own Ofenheimer-email analysis. What's the signature pattern? Is the rule specific enough to catch them without false-positive on legitimate Baker outputs (e.g., if Baker later emails itself a genuine note)?
3. **WhatsApp automated-number detection** — US-throwaway ranges, verification codes. Is the pattern match too narrow (only matches specific ranges) or too broad (could drop legitimate international contacts)?
4. **Meeting transcript minimum threshold** — B3 spec'd a minimum content check. What's the threshold value? Does it account for signals that are legitimately short (tight decision meeting transcripts)?
5. **Scan-query pass-through** — "Director's own queries NEVER drop." How is a "Director scan query" identified? (source=scan should be enough, but verify.)
6. **Ordering dependencies** — B3 listed some ordering constraints. Are there others? E.g., does Baker-self-analysis dedupe need to run BEFORE the "short content" check because self-analyses are often terse?
7. **Idempotency** — rules are deterministic, same signal produces same outcome every time. Confirm no hidden state.

### Output format

File: `briefs/_reports/B2_step0_layer0_rules_review_20260418.md`

Same pattern as your prior reviews:
1. **Verdict:** READY / REDIRECT / BLOCK
2. **Blockers** / **Should-fix** / **Nice-to-have** / **Gaps flagged** (rules that should exist but don't)
3. **Architectural notes** on the rules-as-data YAML choice

### Time budget

~30-45 min. 527 lines of rule spec is substantial but tight — skim once, then scrutinize the sections where B3 makes concrete claims about drop rates or false-positive risks.

### Dispatch back

> B2 Step 0 Layer 0 review done — see `briefs/_reports/B2_step0_layer0_rules_review_20260418.md`, commit `<SHA>`. Verdict: <...>.

---

## Scope guardrails

- Don't propose Python implementation — you're reviewing the rule spec, not building the filter
- Don't re-open D3 §247 (10-30% drop rate ratified)
- If you flag a gap (rule that should exist), state why in operational terms — don't over-engineer

---

*Dispatched 2026-04-18 by AI Head.*
