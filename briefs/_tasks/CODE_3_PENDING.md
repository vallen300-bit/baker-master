# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** SLUGS-V9-FOLD landed at `50167a1` (mo-vie-am + m365 + hot.md v9 sync). Idle since.
**Task posted:** 2026-04-19 (morning)
**Status:** OPEN

---

## Task: STEP5-WORKED-EXAMPLES-EXPAND — Grow §3 from 3 → 6-8 examples

**File:** `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` §3.

### Why

Step 5 Opus synthesis is the highest-stakes step in the pipeline — real Opus cost per call, and output quality determines whether Director promotes Silver → Gold or rejects. The current 3 worked examples cover zero-Gold / continuation / cross-matter. **Ship-day accuracy is bottlenecked by few-shot diversity** — more worked examples = better synthesis on edge cases = fewer rejected Silver entries = Director trusts the pipeline sooner.

Director ratified expansion to **6-8 worked examples** (not 3, not 20 — target range).

### Scope

**IN**

Add **3-5 new worked examples** to §3, bringing total to 6-8. Each new example should cover a scenario the current 3 don't. Select from the gap list below based on which have the strongest grounding in labeled data.

**Priority gaps (pick 3-5):**

1. **Threat-vedana signal** — e.g., Hagenauer administrator-claim deadline letter, AO capital-call slippage, Aukera release refusal. Demonstrates `vedana: threat` frontmatter + arc continuation on a threat thread + Director's ledger-capture pattern on threat signals. **High priority** — threat signals are the highest-volume class per the Fireflies index (hagenauer-rg7 concentration 27.5%).

2. **Opportunity-vedana signal** — e.g., NVIDIA+Corinthia partnership overture, Kitzbüchel-Kempinski asset lead, MO Vienna residence buyer at full ask. Demonstrates `vedana: opportunity` reservation for NEW strategic gains (per `memory/vedana_schema.md`) vs. defensive wins. **High priority** — tests vedana discipline.

3. **Contradiction handling** — signal contradicts prior Gold (e.g., counterparty repudiates an earlier commitment). Demonstrates `⚠ CONTRADICTION:` body marker per §1.2 rules. Critical test of Director's trust in the loop — Opus must flag, not silently overwrite.

4. **Stub-only boundary case** — `triage_score` in the 40-45 noise band (e.g., 42) where Step 4 classifies as `STUB_ONLY`. Demonstrates deterministic stub output: frontmatter + 2-3 sentence body + `status: stub_auto` marker, NO Opus call (per §4.6 brief). Shows Opus what NOT to generate on stubs.

5. **Long-signal truncation** — signal exceeding 50K chars (e.g., long email thread, Fireflies transcript). Demonstrates `[SIGNAL TRUNCATED @ 50000 chars — see source for full text]` marker + how Opus handles partial context. Preserves audit trail.

6. **Director-self-reference strip** — signal where Director is one of the orgs/people. Demonstrates that Step 3 stripped him (per PR #11 pattern) and Opus doesn't re-introduce him as a counterparty.

7. **Multi-source consolidation** — e.g., email + follow-up WhatsApp on same arc, both resolved to same thread. Demonstrates `resolved_thread_paths` with 2+ entries and how Opus weaves them.

8. **Zero-Gold with hot.md elevation** — new matter not yet in Gold but ACTIVE in hot.md. Demonstrates hot.md-driven triage elevation propagating into synthesis framing.

### Source material

- **Labeled corpus:** `outputs/kbl_eval_set_20260417_labeled.jsonl` — 50-entry email/WhatsApp eval set with Director labels. Use for grounding inputs (not direct copies; mask/paraphrase sensitive details).
- **Fireflies index:** `briefs/_drafts/FIREFLIES_MATTER_INDEX_20260418.md` — 107-transcript directory with matter concentration (hagenauer-rg7, mo-vie-am, claimsmax, nvidia). Pull meeting-scenario inputs from here.
- **hot.md source of truth:** `/Users/dimitry/baker-vault/wiki/hot.md` — v9 state; every `primary_matter` in your inputs must resolve to a canonical v9 slug.
- **slugs.yml:** `/Users/dimitry/baker-vault/slugs.yml` v9 — reference for what matters exist.

### Format requirements (must match existing §3 shape)

Each new example must include:
1. **Header:** `### Example N — <scenario label> (<source type>)`
2. **Input block** — mirror existing Ex 1-3 structure:
   - `## Signal raw text (truncated at 50K chars)` — source-shaped content
   - `## Extracted entities` — JSON object with 6 keys (people/orgs/money/dates/references/action_items)
   - `## Resolved thread paths` — JSONB array (can be `[]` for zero-Gold)
   - `## Prior Gold for this matter` — paths + content OR `(none — zero Gold)`
   - `## Director's current-priorities cache` — v9 hot.md excerpt (accurate for the matter)
   - `## Recent Director actions` — ledger rows (format: `YYYY-MM-DD HH:MM | <action> | <matter> | sig:<id> | "<one-line>"`)
3. **Expected output** — full frontmatter + body as Opus should generate it
4. **Rationale** — 2-4 sentences explaining WHY this output is correct (what rules it demonstrates, what could go wrong, what the self-check catches)

### Hard constraints

- **v9 slugs only** — no `mo-vie` (use `mo-vie-am`), no `theailogy` (retired), no drift
- **`author: pipeline`** + **`voice: silver`** always — no `author: tier2`, no `voice: gold`
- **No fictional people** — use Director's real contacts from `memory/people/` or mask as `[Counterparty]`, `[Advisor]`, etc. Do not invent names.
- **Realistic money amounts** — draw from actual matter scales (MO Vienna residence €9-11M, Hagenauer claims ~€600K-€1.5M, AO calls €7M, Aukera €3M, Franck-Muller €6M)
- **Timestamps within last 90 days** — keep in 2026-01 to 2026-04 range

### CHANDA pre-push

- **Q1 Loop Test:** worked examples are prompt data, not loop mechanics. No Leg touched. Pass.
- **Q2 Wish Test:** serves wish — better few-shot grounding = Opus produces Silver Director trusts = faster Silver→Gold velocity = loop closes tighter. Pass.
- **Inv 10 (pipeline prompts don't self-modify):** draft-time authoring, not runtime. Pass.
- **Inv 4 (author-director files untouched):** you read hot.md + slugs.yml + labeled corpus, you write only to `KBL_B_STEP5_OPUS_PROMPT.md` (pipeline-author file). Pass.

### Branch + PR

- **Option A: direct to main** (this is a draft prompt, same pattern as SLUGS-V9-FOLD at `50167a1`). B2 delta review as follow-up if substantive.
- **Option B: branch + PR #14** if you want structured B2 review.

**Lean (A).** Prompt draft editing has no CI risk, no live-code dependency. Commit message lists the N new example headers for legibility.

### Reviewer

B2 delta (optional post-commit pass) — flag if any example breaches v9 slug discipline, invariant citations, or frontmatter spec.

### Timeline

~45-60 min for 3 new examples, ~60-90 min for 5. **Target 4 new** (7 total) as the sweet spot unless one of the scenarios is obviously thin — in which case stop at 6 total.

### Dispatch back

> B3 STEP5-WORKED-EXAMPLES-EXPAND landed — §3 now has <N> examples (was 3), commit `<SHA>`. New examples: <Ex#> <scenario>, <Ex#> <scenario>, ... Sourced from <labeled corpus / Fireflies / mix>. No CHANDA flags.

---

## After this task

- B2 optional delta review (if any surface is structurally novel)
- Next dispatch to you (after Step 4 merges + Step 5 impl starts): likely **STEP6-FINALIZE-PROMPT** is NOT applicable (§4.7 REDIRECT made Step 6 deterministic, no prompt). Your next substantive work is either (a) D2 empirical eval once Step 5 is deployed, or (b) Fireflies 15-pending-transcript resumption in the baker-research session.

---

*Posted 2026-04-19 by AI Head. Director ratified (B). Step 5 accuracy leverage — every new worked example compounds downstream.*
