# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** Step 1 env-var typo fixed at `d7db987`. Step 1 prompt is prompt-clean; awaits B2 final-pass APPROVE.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## Task: STEP5-OPUS-PROMPT — Author Opus Synthesis Prompt Draft

**Why you:** You authored Step 1 + Step 3 prompts with empirical D1 eval grounding. Step 5 Opus synthesis is the last remaining prompt authoring item before KBL-B §6 is prompts-complete. AI Head is mid-REDIRECT-fold; delegating this to you in parallel saves the critical path ~45-60 min.

### Deliverable

File: `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md`

Structure (mirror your Step 1 + Step 3 prompt-file convention):
- §1 Purpose + model
- §1.1 Prompt template (the actual text)
- §1.2 Usage rules (what the model should do with each input block)
- §1.3 Output format specification (frontmatter + body shape)
- §1.4 Helper signatures (what assembler code calls)
- §2 Changes-against-main table if supersedes prior sketches in KBL-B brief (none expected — this is first authoring)
- §3 Worked examples — 2-3, drawn from the labeled corpus
- §4 CHANDA pre-push self-check
- §5 Open questions for AI Head

### Scope of prompt content

**Model:** `claude-opus-4-7` (1M context).

**When Step 5 fires:** only when Step 4 classify decision = `full_synthesis`. Decision is made upstream on other branches:
- `stub_only` → deterministic stub written by Step 4 itself, Step 5 NOT called
- `cross_link_only` → deterministic cross-link stub, Step 5 NOT called
- `skip_inbox` → inbox stub, Step 5 NOT called
- Cost-cap paused (D14 circuit breaker) → Step 5 call deferred, signal parks in `paused_cost_cap`

Assume Step 5 input is already filtered.

**Input blocks the prompt must accept:**

1. **`{signal_raw_text}`** — the signal content (email thread / WhatsApp thread / meeting transcript / scan query). Max ~50K chars; longer signals are summarized upstream in Step 2.
2. **`{extracted_entities}`** — Step 3 output: people, orgs, money, dates, deadlines, action_items as structured JSON.
3. **`{primary_matter}`** + **`{related_matters}`** — Step 1 triage output.
4. **`{vedana}`** — Step 1 triage output (opportunity / threat / routine / null).
5. **`{triage_summary}`** — one-sentence Step 1 rationale including any hot.md / ledger citations.
6. **`{resolved_thread_paths}`** — Step 2 output: existing vault entries matched as continuation context. May be empty (new arc).
7. **`{gold_context_by_matter}`** — ALL existing Gold wiki entries for `primary_matter`, concatenated with page-breaks. May be empty (zero-Gold matter) — MUST STILL BE PASSED per CHANDA Inv 1 ("zero Gold is read AS zero Gold"). This is the Leg 1 compounding input.
8. **`{hot_md_block}`** — current-priorities cache (same input as Step 1).
9. **`{feedback_ledger_recent}`** — last-N Director actions (same input as Step 1, limit via `KBL_STEP1_LEDGER_LIMIT` or a new `KBL_STEP5_LEDGER_LIMIT` — propose which).

**The prompt's job:**
- Write a wiki-entry Markdown draft that extends / updates / starts the vault page for `primary_matter`
- Frontmatter MUST include: `title`, `voice: silver`, `author: tier2`, `created: <iso8601>`, `source_id`, `primary_matter`, `related_matters`, `vedana`
- Body is Director-readable prose, NOT a raw dump. Structure: one-paragraph summary → key facts → decisions/actions pending → cross-references
- If `resolved_thread_paths` is non-empty, the body MUST explicitly continue / amend / correct the prior entries — don't write a parallel narrative
- If `gold_context_by_matter` is non-empty, the body MUST respect prior Gold judgments — no contradiction without flagging it explicitly
- Zero-Gold case: produce the FIRST wiki entry for this matter; tone should signal "first record"

**Hard constraints (must cite in §1.2 Usage rules):**
- NO speculation beyond the signal content + entities + prior Gold
- NO hallucinated participant names, amounts, dates
- NO direct quotes from raw signal longer than 30 chars without explicit source-line citation
- Frontmatter `voice: silver` ALWAYS — Director's promotion to `gold` is downstream action, not Step 5's
- If Step 5 detects contradiction between signal + prior Gold, flag in body with `⚠ CONTRADICTION:` line — don't silently overwrite

**CHANDA-binding input handling:**
- `hot_md_block` → Opus should cite hot.md if the triage score was elevated because of it ("Director's current focus on hagenauer-rg7 elevated triage.")
- `feedback_ledger_recent` → Opus should respect recent corrections: if Director recently reclassified similar-shape signals, let that inform framing
- `gold_context_by_matter` → Opus MUST read and honor; if ignored, the learning loop breaks (Leg 1 violation)

**Output contract:**
- One response, pure Markdown (frontmatter + body)
- No preamble ("Here's the draft:") or postamble ("Let me know if...")
- Target length: 300-800 tokens body; longer only if signal genuinely warrants it

### Worked examples (§3)

Pick 2-3 from the labeled corpus. Suggested:
1. **Clean email signal, Hagenauer, first Gold entry (zero-Gold case)** — exercises Leg 1 zero-read behavior
2. **Meeting transcript, MO Vienna, continuing prior Gold** — exercises continuation / amendment behavior
3. **WhatsApp thread, cross-matter (primary + 1 related)** — exercises cross-link reasoning (since Step 6 is now deterministic, related_matters expansion happens at Step 1 and the prompt just honors it)

Each example: input blocks filled in briefly, expected Opus output as draft Markdown, 2-sentence rationale.

### Out of scope

- Step 6 finalize / frontmatter validation (deterministic per REDIRECT)
- Step 7 commit (D5 flock mutex, separate impl)
- Pydantic frontmatter model (impl detail, KBL-B §4.7)
- Cost ledger integration (automatic via Anthropic billing response)
- Retry ladder (§8, AI Head authoring)

### CHANDA pre-push self-check

- **Q1 Loop Test:** prompt DESIGN is the Leg 1 compounding mechanism. You MUST cite how `gold_context_by_matter` is read + honored. Flag any design choice that weakens Leg 1 for a clear Director review. Pass expected, but state explicitly.
- **Q2 Wish Test:** prompt serves wish (synthesis of loop inputs into reviewable Silver). Pass.
- **Inv 1 compliance:** zero-Gold case MUST produce a valid first entry, not an error. Explicitly tested in worked example #1.
- **Inv 8 compliance:** output frontmatter `voice: silver` — Step 5 never self-promotes. Cite.
- **Inv 10 compliance:** prompt is a stable template. Data inputs vary per signal. No self-modification.

### Reviewer

B2 (reviewer-separation).

### Timeline

~60-90 min. Larger than Step 1 or Step 3 because Opus synthesis is the highest-stakes prompt in the pipeline.

### Dispatch back

> B3 Step 5 Opus prompt drafted — `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md`, commit `<SHA>`. Ready for B2 review. <any flags>.

---

*Posted 2026-04-18 by AI Head. B1 parallel on LAYER0-IMPL PR #7 (~90-120 min). B2 standing down post-CHANDA-ack, awaits REDIRECT fold. AI Head folding REDIRECT in parallel.*
