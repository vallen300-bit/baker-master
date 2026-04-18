# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** STEP2-RESOLVE-IMPL shipped as PR #10 at `d735136`. Idle since.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## Task: STEP3-EXTRACT-IMPL — Gemma Structured Entity Extraction

**Why now:** Step 2 shipped (PR #10 pending review). Step 3 is the next pipeline unit. Spec ratified in KBL-B §4.4. Prompt ratified (B3-authored, B2-reviewed READY at `briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md`).

### Scope

**IN**

1. **`kbl/prompts/step3_extract.txt`** — extract template text from `briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md`. File-based load pattern per Inv 10.

2. **`kbl/steps/step3_extract.py`** — the evaluator
   - `build_prompt(signal_text, source, primary_matter, resolved_thread_paths) -> str`
   - `parse_gemma_response(raw: str) -> ExtractedEntities` — structured dataclass with keys `people`, `orgs`, `money`, `dates`, `references`, `action_items` (all arrays, possibly empty)
   - `call_ollama(prompt: str, model="gemma2:8b", timeout=30)` — reuse pattern from `step1_triage.py` or lift to shared `kbl/ollama.py` module if not already there
   - `extract(signal_id: int, conn) -> ExtractedEntities` — full pipeline: load signal, build prompt, call Ollama, parse, write to `signal_queue.extracted_entities JSONB`, write `kbl_cost_ledger` row (`step='extract'`, `model='gemma2:8b'`, `cost_usd=0`), advance state
   - State transitions: `awaiting_extract` → `extract_running` → `awaiting_classify` OR `extract_failed`
   - Partial-JSON handling (per §7 error matrix): missing sub-keys → drop from output (not NULL), log WARN, continue

3. **`kbl/exceptions.py`** — add `ExtractParseError` (coexists with existing exceptions per B1's PR #10 pattern)

4. **Tests** — `tests/test_step3_extract.py`:
   - `build_prompt` integration: mock signal + placeholders filled correctly
   - `parse_gemma_response` happy path (all 6 keys populated)
   - `parse_gemma_response` partial JSON (4 of 6 keys) → accepts, missing keys default to `[]`
   - `parse_gemma_response` unparseable → raises `ExtractParseError`
   - `call_ollama` mocked (no live Ollama in CI)
   - `extract` end-to-end: DB writes + cost ledger row + state transition
   - R3 retry path: first call unparseable, second call valid → final result written

### CHANDA pre-push

- **Q1 Loop Test:** Step 3 does not read hot.md / ledger / Gold. Not a Leg touch. Pass.
- **Q2 Wish Test:** serves wish (structured entities feed Step 5 synthesis). Pass.
- **Inv 10:** prompt loaded once from file; no self-modification. Verify.
- **Shared ollama client:** if you lift to `kbl/ollama.py`, verify no duplication-drift between Step 1 and Step 3 client code.

### Dependencies

- PR #8 (Step 1 triage) merged or mergeable — provides signal_queue columns your state machine needs
- Step 3 extract prompt @ `briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md` (B3-authored, READY)
- `signal_queue.extracted_entities JSONB` column — verify exists, add migration if missing

### Branch + PR

- Branch: `step3-extract-impl`
- Base: `main`
- PR title: `STEP3-EXTRACT-IMPL: kbl/steps/step3_extract.py + kbl/prompts/step3_extract.txt`
- Target PR: #11

### Reviewer

B2.

### Timeline

~60-90 min (similar shape to Step 1, smaller because no hot.md/ledger loading).

### Dispatch back

> B1 STEP3-EXTRACT-IMPL shipped — PR #11 open, branch `step3-extract-impl`, head `<SHA>`, <N>/<N> tests green. Ready for B2 review.

---

*Posted 2026-04-18 by AI Head. B2 reviewing PR #8 + PR #10. B3 idle.*
