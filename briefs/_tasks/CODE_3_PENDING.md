# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** STEP5-WORKED-EXAMPLES-EXPAND landed at `fceb22f` (§3 now 7 examples). Idle since.
**Task posted:** 2026-04-19 (morning)
**Status:** OPEN — design-doc authoring (no code)

---

## Task: STEP6-FINALIZE-SCHEMA-SPEC — Author Pydantic schema + validation spec

**Target file:** `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md` (new file).

### Why

Step 6 is **deterministic** (no prompt, no model call) per the post-REDIRECT ratification on 2026-04-18. But it's the last quality gate before the vault commit — it Pydantic-validates Opus's draft output, builds `final_markdown`, writes cross-link stubs. If the schema spec is ambiguous, B1 will have to make judgment calls mid-impl and re-ask Director. Front-loading the exact Pydantic shape + validation rules lets B1 ship Step 6 in one pass after Step 5 lands.

**KBL-B §4.7 brief text is the starting point; your job is to expand it into a concrete implementation-ready spec.**

### Scope

**IN — Author `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md` with these sections:**

1. **§1. Purpose & §4.7 anchor** — 3-4 sentences. Reference KBL-B §4.7 (lines 414-422 of pipeline brief). State Step 6 is deterministic, no model call, no ledger row.

2. **§2. Pydantic models (exact):**
   - `SilverFrontmatter` model: all required keys from STEP5-OPUS-PROMPT §1 frontmatter spec (title, voice, author, created, sources, primary_matter, related_matters, vedana, triage_score, triage_confidence, money_mentioned, status, thread_continues). Include optional keys + defaults. Specify exact types (`Literal['silver']`, `Literal['pipeline']`, `datetime | str` with ISO 8601 validator, `list[MatterSlug]` where `MatterSlug` is a constrained str, `Literal['threat', 'opportunity', 'routine']`, etc.).
   - `SilverDocument` model: `frontmatter: SilverFrontmatter` + `body: str` (length bounds: ~300-800 tokens per §Output format; express as char bound e.g. 1500-4000 chars).
   - `MatterSlug` constrained str: must match regex for canonical v9 slug (lowercase, dash-separated, 2-30 chars). Cite slugs.yml v9 as authority.
   - `CrossLinkStub` model: what gets appended to `wiki/<m>/_links.md` per related_matter. Fields: `source_signal_id`, `source_path`, `created`, `vedana`, optional 1-line excerpt.

3. **§3. Validation rules (enumerate precisely):**
   - `target_vault_path` regex: `^wiki/[a-z0-9-]+/\d{4}-\d{2}-\d{2}_[\w-]+\.md$` (cite §3.5 of Step 5 prompt if it's different, reconcile).
   - `author` must be `pipeline` (Silver produced). Director promotion flips to `director` later; Step 6 never writes `director`.
   - `voice` must be `silver`.
   - `primary_matter` must be in v9 slugs.yml ACTIVE set — validator reads `slugs.yml` once at Step 6 module import (cached OK, slug set is static during a process lifetime).
   - `related_matters`: each entry also validated against slugs.yml, MUST NOT equal `primary_matter`, deduplicated.
   - `vedana`: strict 3-value enum per `memory/vedana_schema.md` — no `neutral`, no `other`.
   - `triage_score`: int 0-100.
   - `triage_confidence`: float 0.0-1.0.
   - `created`: ISO 8601 timestamp, timezone-aware, UTC.
   - `money_mentioned`: string or null. If string, must match a currency-amount pattern (€X, £X, $X, CHF X with optional M/K suffix). No implicit-currency numbers.
   - `body`: must not contain `author: director` or `voice: gold` (anti-self-promotion — no accidental Gold frontmatter in body).
   - `body`: must not contain bare Director name without citation (anti-hallucination — full-text contains "Dimitry Vallen" only inside quoted source material).

4. **§4. Cross-link stub file format (`wiki/<m>/_links.md`):**
   - Exact Markdown structure: one row per stub, sorted by `created` DESC.
   - Idempotency rule: identified by `source_signal_id` — if a stub with that ID already exists in the file, REPLACE in place (not append duplicate). Specify the grep/regex used to detect.
   - Atomic write pattern: temp file + rename (filesystem-level atomicity).

5. **§5. Error matrix (Pydantic failure → state transition):**
   - Missing required frontmatter key → `FinalizationError`, state flips to `opus_failed`, Opus R3 retry
   - Invalid enum value (vedana, voice, author) → `FinalizationError`, same path
   - Unknown slug in primary_matter / related_matters → `FinalizationError`, same path
   - Body too short (<300 chars) or too long (>8000 chars) → `FinalizationError`, same path
   - `target_vault_path` doesn't match regex → `FinalizationError`, same path
   - Cross-link write failure (IO error) → `FinalizationError` but state stays at `finalize_running` + retry once, then `finalize_failed` (cross-link is idempotent, safe to retry)
   - After 3 total Opus retries produce invalid drafts → `finalize_failed` terminal + route to inbox per §4.7 brief

6. **§6. Logging spec:**
   - Pydantic validation failure: `level='WARN'`, `component='finalize'`, `message=f'<field>: <reason>'`. One log row per failed field.
   - Cross-link write failure: `level='ERROR'`, `component='finalize'`, `message=f'cross-link write failed: {path}: {reason}'`. One row per failed path.
   - Success: no log.

7. **§7. Open questions for AI Head:** any ambiguities you hit while writing. Number them `OQ1`, `OQ2`, etc. so AI Head can resolve before B1 impl.

8. **§8. CHANDA pre-push self-check** — cite §5 Q1 + Q2 by name.

### Hard constraints

- **No code.** This is a spec document for B1 to implement against. Pydantic model bodies can be shown as code fences for clarity, but no `.py` file is produced.
- **Reference the canonical v9 slug set** at `/Users/dimitry/baker-vault/slugs.yml`. Don't invent slugs.
- **All `author: pipeline` + `voice: silver`** enforced at validation. Spec MUST make self-promotion to Gold impossible at Step 6.
- **Spec must be reviewable by B2** — so write it in the exact shape a brief like `KBL_B_PIPELINE_CODE_BRIEF.md` uses (numbered sections, tables, inline code fences, explicit invariant citations).

### CHANDA pre-push

- **Q1 Loop Test:** spec authoring, no Leg touched. Pass.
- **Q2 Wish Test:** serves wish — tighter Step 6 schema = fewer rejected Silver drafts = faster Silver→Gold velocity. Pass.
- **Inv 8** (Silver→Gold only by Director edit) — spec must structurally enforce (no auto-promote).
- **Inv 10** (prompts don't self-modify) — Step 6 has no prompt, spec is stable.

### Branch + PR

- **Option A: direct to main.** Same pattern as SLUGS-V9-FOLD. Commit message lists sections.
- **Option B: branch + PR for B2 review.** Worth it if the spec is architecturally novel.

**Lean (A).** Spec docs follow the existing draft pattern. B2 can review inline post-commit as part of Task K or separately.

### Timeline

~60-90 min (~8 sections, each tight but precise).

### Dispatch back

> B3 STEP6-FINALIZE-SCHEMA-SPEC landed — `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md` at commit `<SHA>`. N sections, M open questions for AI Head. <GREEN/amber/red> CHANDA self-check.

---

## After this task

Next: Step 7 harness design spec (git-commit path, push-under-mutex, `claude -p` optional) — similar shape, ~45 min. Or if Step 5 Opus has shipped, D2 empirical eval corpus for Step 5 output quality.

---

*Posted 2026-04-19 by AI Head. Front-loads Step 6 so B1's post-Step-5 ramp is zero-wait.*
