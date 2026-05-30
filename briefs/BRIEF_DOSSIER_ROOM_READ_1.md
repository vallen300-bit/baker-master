# BRIEF_DOSSIER_ROOM_READ_1 — Slug-resolved curated-room pre-read for Baker dossier engine

- **Matter:** baker-infra (Baker Research Engine / ART-1)
- **Author:** AH1 (cowork-ah1)
- **Date:** 2026-05-30 · **Rev 3** (folded Architect D1–D5 + Codex FAIL-LIGHT C1–C3, both reviewers converged on the resolution-safety hole)
- **Dispatch target:** b-code **b2/b3/b4 — NOT b1 (busy)**, after both verdicts cleared
- **Reviewers:** Codex (code — FAIL-LIGHT C1–C3 folded) · Architect (design — SOUND-WITH-NITS, D1+D2 folded)
- **Estimated time:** ~2–3h (D1 reuse nets time positive) · **Complexity:** Medium

### Surface contract: N/A — backend-only. Touches `orchestrator/research_executor.py` (slug resolution + call-site) and `kbl/curated_wiki_reader.py` (reader extension). No dashboard panel, button, route, modal, or clickable surface.

---

## CONTEXT

Director directive 2026-05-30: dossiers must consult the curated project room before drafting. On 2026-05-30 both Baker dashboard + CoWork Researcher produced a Bick/MOHG dossier and **both falsely flagged the 22-May Bick concept paper as "missing."** It was filed at `wiki/matters/nvidia-mohg/00_originals/2026-05-22-mohg-bick-ai-opportunities-in-hospitality-concept.pdf`. Architecture review folded (D1 reuse existing KBL reader; D2 fail-closed on fuzzy resolution).

---

## Fix 1: Slug-resolved curated-room pre-read (PUSH into dossier context)

### PROBLEM
`execute_research_dossier` → `_run_specialists` pulls Baker memory + web + email but never reads the matter's curated room — the desk-maintained truth layer. Dossiers re-derive and mis-report filed facts.

### CURRENT STATE (verified against origin/main)
- `orchestrator/research_executor.py`: `execute_research_dossier(proposal_id)` (line 345); `_run_specialists(subject_name, subject_type, context, source_text, specialist_slugs)` (line 150) — builds the specialist prompt; **`context` is injected un-truncated** (only `source_text[:3000]` is capped), so an injected digest flows in full to every specialist; `ThreadPoolExecutor(max_workers=4)`.
- **[Codex C1 — verified] `_get_proposal` SELECT (lines 50–53) OMITS `matter_slug`.** It selects only `id, subject_name, subject_type, context, specialists, trigger_source, trigger_ref`; `execute_research_dossier` never extracts a slug. Prod schema HAS `research_proposals.matter_slug` (Codex-verified). The "explicit matter_slug" path is dead until the column is added to the SELECT + threaded through.
- **[Codex C2 — verified, worse than reported] Generic-alias slug collision.** `slugs.yml:38` gives `mo-vie-am` (MO Vienna hotel ASSET-MANAGEMENT — a different matter) the aliases `mohg`, `mandarin`, `mandarin oriental`. `normalize("MOHG") => mo-vie-am`; `normalize("Raphael Bick") => None`; only the specific composite `mohg-nvidia` / `nvidia-mandarin` → `nvidia-mohg`. **A substring scan of a Bick/MOHG dossier's context resolves to `mo-vie-am` and would inject the WRONG room as authoritative** — the motivating case itself breaks. Generic single-token aliases are unsafe for authoritative resolution.
- **`kbl/curated_wiki_reader.py` ALREADY EXISTS** (8.6KB, wired at `capability_runner.py:1750-1756` via `format_for_prompt(matter_slug)`): `read_curated()` (line 111), `format_for_prompt()` (line 197), `_resolve_vault_root()` (line 76, uses `BAKER_VAULT_PATH`, `.resolve()`). **Path-escape + symlink containment already implemented** (lines 138–166: leading-alphanumeric slug guard, resolved-prefix containment, per-file symlink re-check). **Do NOT re-implement any of this.**
- `kbl/slug_registry.py`: `normalize(raw)`, `is_canonical(slug)`, `aliases_for(slug)`, `canonical_slugs()`.
- Room layout: `00_originals/`, `03_source_summaries/`, `curated/`, optional `02_inventory/*room-structure-overview.md`. **Only `nvidia` has an overview today** — degrade gracefully. **Slug-family boundary (marquee case):** the Bick PDF lives under `nvidia-mohg/00_originals/` while the overview + `touches_siblings` live under `nvidia/` — resolution + sibling-read MUST span the family or it reads the wrong/empty room.

### IMPLEMENTATION — two parts, single call-site seam

**Part A [D1] — extend the existing KBL reader (READING belongs in KBL).**
Add `read_room(slug) -> str` to `kbl/curated_wiki_reader.py`, building on `read_curated`:
- overview-first: `02_inventory/*room-structure-overview.md` if present;
- else enumerate `00_originals/` filenames (names only) + read `03_source_summaries/` bodies + `read_curated(slug)`;
- expand `touches_siblings:` frontmatter → include named siblings' curated + summaries (slug-family-gated);
- reuse the file's existing containment + char-cap helpers — **all new path construction goes through them; flag `/security-review` on any new path join.**
- Caps: ≤8 files / ≤40KB raw / **digest ≤~8K tokens** (Codex nit — lowered from 12K because `source_text[:3000]` + un-truncated `context` already share the specialist prompt; a test must assert the FINAL assembled prompt stays within char/token budget); on truncation append `[room digest truncated: N files omitted]`.
- **Fold the ground-truth instruction INTO the returned string** (so the seam stays single-call-site): the returned block leads with the header + instruction, body follows.

**Part B — slug RESOLUTION in the dossier engine (the genuinely new part). Resolution safety is the load-bearing fix — both reviewers converged here.**
First add `matter_slug` to the `_get_proposal` SELECT (Codex C1) and extract it in `execute_research_dossier`. Then resolve, in strict precedence (first hit wins), and call `read_room`:

1. **Explicit (authoritative):** proposal `matter_slug` column → `slug_registry.normalize()` → `is_canonical()`. **Explicit DOMINATES — if present and canonical, stop here; never override it with a context guess.**
2. **Exact slug / specific composite alias (authoritative):** match `subject_name`+`context` ONLY against (a) an exact canonical slug string, or (b) a *matter-specific composite* alias (e.g. `nvidia-mohg`'s `mohg-nvidia` / `nvidia-mandarin`). **[Codex C2] REJECT generic single-token aliases from freeform context** (`mohg`, `mandarin`, `movie`, etc.) — they collide across matters (`mohg → mo-vie-am`). A bare token never resolves authoritatively.
3. **[Codex C3 + D2] Metadata-only lookup (NON-authoritative):** if 1–2 miss, ONE pass over `wiki/matters/*/` **frontmatter + `_people.md` only — never room bodies** — to suggest a candidate. If it matches → inject under the WEAKER header `=== POSSIBLY-RELATED ROOM (unconfirmed — verify) ===`. This is the only global lookup; it reads metadata, not content, and is explicitly not a body scan.
4. No resolution OR 2+ equal-confidence candidates → return `""` (no-op). Never guess across matters; **high-stakes binding fails CLOSED.**
5. Prepend `read_room` output to `context`.

**[D2/C2] Authoritative header gating:** the `=== CURATED PROJECT ROOM (authoritative — desk-maintained; surface conflicts, do not average; do NOT report a listed document as missing) ===` header is used **only for steps 1–2 (explicit column or exact/specific-composite match).** Step 3 metadata-only → weak header. This prevents a `mohg → mo-vie-am` mis-resolution from ever being labelled authoritative.

**[D3] Observability:** one structured log line per attempt — `path=explicit|alias|grep|none room_found=<bool> slug=<X> files=<N>`. A silent resolver miss re-creates the original silent failure.

**[D4] Cost metering:** log injected digest size (chars + est-tokens). Cost = N specialists × digest input-tokens per dossier; the cap is load-bearing because `context` is not truncated downstream.

**[runtime kill-flag] [D3-stretch]** Read a kill flag **at the call-site at runtime** (e.g. `get_preference('dossier_room_read_enabled')` / DB flag — **NOT a module-level env var, which needs a restart**) so a bad injection is disabled without a deploy.

### KEY CONSTRAINTS
- Read-only on vault. Fault-tolerant: any error → log → return `""` → dossier proceeds unchanged.
- Slug-gated to one family. No bulk `wiki/matters/*` scan.
- Reuse `curated_wiki_reader` containment for ALL path work — no new vault-layout knowledge in the research engine.

### VERIFICATION
- `nvidia-mohg`-resolving subject injects the Bick concept-paper filename; output does NOT say "missing."
- No-room subject → byte-identical flow (mock `read_room` returns "").
- Slug-family span: resolving `nvidia-mohg` still reaches the `nvidia/` overview + siblings.
- Grep-only resolution does NOT get the authoritative header.
- Assert no read of unrelated matter dirs.

---

## Files Modified
- `orchestrator/research_executor.py` — **add `matter_slug` to `_get_proposal` SELECT (Codex C1) + extract in `execute_research_dossier`**; slug resolution (strict precedence, generic-alias reject); single call-site prepend; runtime kill-flag; observability/cost logs.
- `kbl/curated_wiki_reader.py` — add `read_room(slug)` (extends `read_curated`); reuse existing containment.

## Do NOT Touch
- `kbl/curated_wiki_reader.py` existing containment/cap logic — reuse, don't rewrite.
- `kbl/slug_registry.py` — public API only.
- `_format_dossier_markdown` / `_generate_and_save_docx` — output path unchanged (D5-stretch provenance line deferred — currently under Do-Not-Touch).
- Any `wiki/matters/**` content; CoWork Researcher lane (separate brief).

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('orchestrator/research_executor.py', doraise=True)"` + same for `kbl/curated_wiki_reader.py`.
2. `read_room` reuses containment; `/security-review` run on any new path join (D1).
3. **[Codex C2 — must-pass regression] a Bick/MOHG dossier (context contains "MOHG"/"Mandarin") with NO explicit `matter_slug` does NOT resolve to `mo-vie-am` and does NOT get the authoritative header.** Assert generic single-token aliases are rejected.
4. **[Codex C1] `_get_proposal` SELECT includes `matter_slug`; explicit column dominates context guesses.** Test explicit `nvidia-mohg` wins over any context token.
5. **[Codex C3] metadata-only lookup reads frontmatter + `_people.md` ONLY, never room bodies; no bulk body scan.** Assert.
6. Authoritative header ONLY on steps 1–2; metadata-only → weak header; unresolved fails closed (D2).
7. Final-prompt budget assert: `source_text[:3000]` + `context` + digest within char/token cap (digest ≤8K).
8. Structured resolution log per path + `room_found` (D3); digest-size log (D4); runtime kill-flag at call-site, not module env.
9. Integration (Bick reaches `nvidia-mohg` via explicit slug) + no-room regression + slug-family span + error-injection.
10. **Test nit:** assert the ground-truth INSTRUCTION STRING is present in the prompt (deterministic) — do NOT unit-assert the LLM's surface-conflict behavior (flaky; belongs in eval set).
11. Lessons applied: #17/#34/#42/#44/#51 (signature/schema/contract verified in-brief before dispatch — Codex note).

## FAST-FOLLOW (post-merge)
- D5: confirm prod `BAKER_VAULT_PATH` points at a LIVE desk copy, not a deploy-time snapshot (else "authoritative" room can be stale). `curated_wiki_reader` is already live in prod via `capability_runner`, so likely already-solved — confirm + note.
- D5-stretch: one-line provenance note in the dossier ("Curated room consulted: <slug>") — literally what the Director directive asks; needs a formatter touch (currently Do-Not-Touch).

## OUT OF SCOPE
- CoWork Researcher lane (same `read_room` util via `BRIEF_RESEARCHER_FANOUT_1` — Architect D4: one shared function for dossier + fan-out + Cortex).
- Authoring room overviews for matters lacking one (desk task). UI changes. Vault writes.
