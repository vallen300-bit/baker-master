# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** Stood down after D1 ratification (`397c391`)
**Task posted:** 2026-04-18
**Status:** OPEN — re-engaged for prompt authoring

---

## Task: Draft KBL-B §6 — Production Prompts for Steps 1 + 3 (Gemma local)

You have the deepest empirical knowledge of Gemma prompt behavior (v1/v2/v3 evals). AI Head is writing §6 for Opus + Sonnet prompts in parallel. You handle the two local-LLM prompts.

### Deliverables — 2 production prompt templates

**Step 1 — `triage` prompt**

Based on your v3 glossary prompt that landed Gemma at 88v/76m. Harden for production:

- Slug enumeration sourced from `kbl.slug_registry.active_slugs()` at prompt-build time (not hardcoded). Per-slug one-line descriptions from `registry.describe(slug)`.
- Vedana rules block verbatim per v3.
- JSON output spec with exact field types (per §4.2 contract: `primary_matter` nullable, `related_matters` array, `vedana` enum, `triage_confidence` 0-1, `triage_score` 0-100).
- D1 sampling config unchanged (temp=0, seed=42, top_p=0.9).
- Prompt preamble explicitly permits `null` for primary_matter + rejects generic category strings ("hospitality", "investment", etc.).

**Step 3 — `extract` prompt**

New prompt (no prior draft). Structured entity extraction per §4.4 schema:

```json
{"people": [...], "orgs": [...], "money": [...], "dates": [...], "references": [...], "action_items": [...]}
```

All 6 keys always present, values always arrays (possibly empty). Non-extractable → omit from sub-object, not null/missing.

Include 2-3 few-shot examples spanning email / WA / transcript source types (use signals from `outputs/kbl_eval_set_20260417_labeled.jsonl` as source material — you know the content shape).

### Where to put them

File: `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` and `briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md`.

Each file:
- The prompt template (copy-paste-ready for a Python `.format()` or similar)
- Rationale notes (why this structure, what empirical result motivated each piece)
- Expected failure modes + recovery (tied to §4 invariants)

These drafts will be imported verbatim into KBL-B §6 when AI Head assembles the full section.

### Scope guardrails

- **Do NOT** run evals. This is authoring, not measurement.
- **Do NOT** modify `scripts/run_kbl_eval.py` or labeled set.
- **Do NOT** speculate on Opus/Sonnet prompts (§6 covers those — AI Head authoring).
- Use Director's slug descriptions (from `baker-vault/slugs.yml` post-SLUGS-1 merge, or the 9 you drafted yourself in v3 report).

### Dispatch back

> B3 §6 prompts drafted — Step 1 at `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md`, Step 3 at `briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md`, commit `<SHA>`.

### Est. time

~45 min total:

- 15 min Step 1 prompt (v3 hardening + registry-dynamic)
- 25 min Step 3 prompt (new, with few-shot examples)
- 5 min rationale notes + commit

---

*Dispatched 2026-04-18 by AI Head. Re-engaged from stand-down per Director speed directive.*
