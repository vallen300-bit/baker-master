# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous:** Step 0 Layer 0 rules review shipped as READY (6 should-fix, 0 blockers; report `B2_step0_layer0_rules_review_20260418.md`, commit `e0f38ab`)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** prior Step 0 Layer 0 review task (shipped, 6 should-fix queued for fold into brief by AI Head)

---

## Task: Architecture Challenge — Is Step 6 (`sonnet_step6`) Overscoped for an LLM Call?

Director surfaced a devil's-advocate challenge on the §6 prompt queue:
*"Why is Sonnet better than Gemma 4 for Step 6?"*

AI Head's honest reply flagged that Step 6 may be **overscoped** — three of its four jobs look near-deterministic, and only one (tone/style polish on Opus prose) genuinely needs a language model. Before AI Head writes the Sonnet prompt for §6, Director wants B2 as independent reviewer to stress-test the scoping.

### Deliverable

File: `briefs/_reports/B2_step6_scope_challenge_20260418.md`
Verdict: **CONFIRM** (keep all 4 jobs in Sonnet) / **REDIRECT** (re-scope N jobs to deterministic) / **ESCALATE** (deeper issue found)

### Sources to read

- `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md`
  - §2 (8-step flow)
  - §4.7 Step 6 I/O contract (lines 366–373)
  - §4.8 Step 7 + §4.9 TOAST cleanup
  - Lines 190–208 — Step 6 narrative
- `briefs/DECISIONS_PRE_KBL_A_V2.md` — D1 (Gemma thresholds + Phase 1 acceptance), D3 (3-layer matter scoping, ALLOWED_MATTERS gate), D14 (cost ledger + circuit breaker)
- `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` + `..._STEP3_EXTRACT_PROMPT.md` — what Gemma upstream already delivers, so you know what `extracted_entities` + `related_matters` already look like when Step 6 reads them
- `briefs/_drafts/KBL_B_TEST_FIXTURES.md` (B3's 10-signal corpus, commit `742f4a1`) — concrete Step 6 expected outputs per-signal
- baker-vault wiki samples (if you can inspect) — what does vault-canonical frontmatter actually look like in practice?

### The four Step 6 jobs — challenge each

Per §4.7 current scope, Sonnet does:

| # | Job | AI Head's pre-assessment | B2 challenge |
|---|-----|--------------------------|--------------|
| 1 | **Metadata** — source IDs, timestamps, `author: pipeline` | Pure code. No LLM. | Any metadata field judgement-based such that deterministic code would fail? Are there cases where source attribution is ambiguous enough to need reasoning? |
| 2 | **`related_matters[]` cross-links** | Arguably deterministic: match `extracted_entities` → matter registry via `ALLOWED_MATTERS` (Layer 2 gate, D3) | Does semantic-overlap judgement ever need LLM reasoning beyond literal entity match? E.g., a signal about "Cupials defects" should also cross-link to "Hagenauer RG7" — does that need LLM semantic reasoning or is a co-occurrence graph from prior vault entries enough? |
| 3 | **Frontmatter schema validation** | Pure Pydantic validation. No LLM. | Are there cases where Opus draft has *usable-but-malformed* frontmatter that an LLM can repair but deterministic code cannot? Or should malformed frontmatter simply fail → Opus retry (R3)? |
| 4 | **Tone/style polish on prose body** | Only genuine LLM job. Sonnet beats Gemma on voice continuity with Opus. | Is this polish even necessary? Opus 4.7 at 1M is unlikely to produce draft prose structurally deficient enough to warrant a second pass. Do we have evidence Opus drafts need polish, or is this cargo-cult? |

### Specific scrutiny

1. **Gemma-for-Step-6 alternative** — if we keep one LLM call but downgrade to Gemma 4 8B, what breaks? D1 ratified Gemma at 88v/76m *with* Layer 2 safety net for matter classification. Step 6's matter-touching work (job #2) is downstream of Step 1 + Layer 2, so the matter-gate safety is already applied. What's the residual risk of Gemma on Step 6 specifically?

2. **No-LLM-at-all alternative** — can Step 6 become fully deterministic? Decompose:
   - Metadata → deterministic Python
   - Cross-links → deterministic graph lookup (would need `kbl_cross_link_index` built from vault history)
   - Frontmatter → Pydantic validation; malformed → Opus R3 retry rather than Sonnet repair
   - Prose polish → **delete this job entirely** if Opus drafts are already vault-ready
   What's the failure mode if Step 6 becomes pure code?

3. **Cost / latency / availability trade** — current Sonnet posture: cheap per-call, but non-zero Anthropic dependency surface. Collapsing Step 6 to code removes one external dependency. Is that worth the residual quality risk on prose polish?

4. **Circular-scope risk (blast radius)** — if you REDIRECT to "no LLM", the change ripples across §2 (8-step → 7-step), §3 schema (some status enums go away: `awaiting_sonnet`, `sonnet_running`, `sonnet_failed`), §4.7, §6 (no prompt needed), §8 (no Sonnet retry ladder), §9 (no ledger entry for `sonnet_step6`). Flag whether the re-scope is doable inside the draft or demands a DECISIONS-V2 amendment.

5. **Reviewer-separation check** — AI Head wrote §4.7 scope + is authoring §6 Sonnet prompt. You didn't touch either. Clean independent-review posture.

### Report format

```
# B2 Step 6 Scope Challenge — <VERDICT>

**Verdict:** CONFIRM | REDIRECT | ESCALATE
**Recommendation:** <one-paragraph executive summary>

## Per-job analysis
### Job 1 — Metadata
- Deterministic-feasible: yes/no
- LLM-required edge cases: <list or "none">
- Recommendation: <keep in Sonnet | move to code | delete>

### Job 2 — Cross-links
[same structure]

### Job 3 — Frontmatter schema
[same structure]

### Job 4 — Prose polish
[same structure]

## Gemma-for-Step-6 alternative
<risk analysis>

## No-LLM alternative
<risk analysis + blast radius across brief sections>

## Recommended Step 6 shape
<concrete spec — if REDIRECT>
```

### Timeline

~30-45 min. Escalate blockers in chat if anything in the brief contradicts itself.

### Dispatch back

> B2 Step 6 scope challenge done — see `briefs/_reports/B2_step6_scope_challenge_20260418.md`, commit `<SHA>`. Verdict: <...>.

---

## Scope guardrails

- Don't propose the Sonnet prompt content — that's AI Head's authoring task if verdict is CONFIRM
- Don't re-open D1 (Gemma 88v/76m) or D3 (Layer 2 ALLOWED_MATTERS gate)
- If verdict is REDIRECT, give a concrete recommended Step 6 shape — don't leave it open-ended

---

*Dispatched 2026-04-18 by AI Head. B1 + B3 idle this turn; you are the active challenger. Director awaiting your verdict before Sonnet prompt authoring proceeds.*
