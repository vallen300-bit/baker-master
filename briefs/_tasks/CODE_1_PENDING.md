# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** LAYER0-IMPL shipped as PR #7 at `7342617`. Idle since.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## Task: STEP1-TRIAGE-IMPL — Step 1 Gemma Triage Evaluator

**Why now:** All inputs ratified. Layer 0 PASS emits `awaiting_triage` signals (PR #7). Step 1 consumes them, runs Gemma triage, writes results + routes. Production-moving, unblocks Step 2/3 impl.

### Scope

**IN**

1. **`kbl/prompts/step1_triage.txt`** — extract the template text from `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` §1.1. Plain-text file with `{signal}`, `{slug_glossary}`, `{hot_md_block}`, `{feedback_ledger_recent}` placeholders. Source of truth for the prompt text going forward.

2. **`kbl/steps/step1_triage.py`** — the evaluator module:
   - `build_prompt(signal_text: str, conn) -> str` — assembles the prompt per the template draft §1.1 builder (calls `slug_registry`, `load_hot_md`, `load_recent_feedback`, `render_ledger` from `kbl/loop.py`). Caller owns `conn`.
   - `parse_gemma_response(raw: str) -> TriageResult` — parses Gemma's structured JSON output. Returns dataclass with: `primary_matter`, `related_matters`, `vedana`, `triage_score`, `triage_confidence`, `summary`. Raises `TriageParseError` on malformed.
   - `normalize_matter(raw: str | None) -> str | None` — delegates to `slug_registry.normalize()` (handles aliases, returns None for "null"/"none").
   - `call_ollama(prompt: str, model="gemma2:8b", timeout=30) -> str` — HTTP POST to Ollama `/api/generate`, seed=42, temperature=0, format=json. Returns raw response text.
   - `triage(signal_id: int, conn) -> TriageResult` — full pipeline: load signal from `signal_queue.id`, build prompt, call Ollama, parse, write results to `signal_queue` columns (`primary_matter`, `related_matters`, `vedana`, `triage_score`, `triage_confidence`, `triage_summary`), write `kbl_cost_ledger` row (`step='triage'`, `model='gemma2:8b'`, tokens from Ollama response if available), advance state.
   - State transitions: `awaiting_triage` → `triage_running` → `awaiting_resolve` OR `awaiting_inbox_route` (if triage_score < `KBL_PIPELINE_TRIAGE_THRESHOLD`, default 40)

3. **`kbl/exceptions.py`** (if not exists) — `TriageParseError`, `OllamaUnavailableError`

4. **Tests** — `tests/test_step1_triage.py`:
   - `build_prompt` integration: mock signal + mock DB with seeded hot.md + ledger rows → prompt contains expected blocks
   - `parse_gemma_response` happy path
   - `parse_gemma_response` malformed → raises
   - `normalize_matter` alias resolution (e.g., "hagenauer" → "hagenauer-rg7", "lilienmat" → "lilienmatt")
   - `call_ollama` mocked (don't require live Ollama in CI)
   - `triage` end-to-end with mocked Ollama: verifies DB writes (columns + cost ledger row + state transition)
   - Triage-threshold gating: score < 40 → state `awaiting_inbox_route`; score >= 40 → `awaiting_resolve`

**OUT**
- Ollama service management (systemd/launchd config) — KBL-A territory
- Qwen fallback (availability-only per D1; separate ticket when Phase 1 runs into actual availability issue)
- Step 2 resolver — next ticket
- Anthropic cost ledger mapping — this step uses Gemma (local, free), ledger row has `cost_usd=0.0`, `input_tokens` + `output_tokens` from Ollama response if exposed

### CHANDA pre-push

- **Q1 Loop Test:** This step READS hot.md + feedback_ledger on every call — core Leg 3 behavior. **Loop-compliant by construction.** Cite in PR body. Must not short-circuit the reads (no "if-hot-md-empty-skip"). Zero reads = Inv 1 violation.
- **Q2 Wish Test:** pure wish-service. Pass.
- **Inv 1:** gold_context_by_matter is Step 5's concern, not Step 1's. Step 1 reads hot.md + ledger; Inv 1 compliance.
- **Inv 3:** explicit — `triage()` calls `load_hot_md()` + `load_recent_feedback(conn)` before `call_ollama()`. Test this in the `build_prompt` integration test.
- **Inv 10:** template is loaded from `kbl/prompts/step1_triage.txt` once per process. No self-modification.

### Dependencies

- `kbl/slug_registry.py` ✓ (PR #2)
- `kbl/loop.py` ✓ (PR #6)
- `kbl/layer0.py` emits `awaiting_triage` ✓ (PR #7)
- `feedback_ledger` schema ✓ (PR #5)
- `signal_queue` columns: `primary_matter TEXT`, `related_matters TEXT[]`, `vedana TEXT`, `triage_score NUMERIC`, `triage_confidence NUMERIC`, `triage_summary TEXT` — if not all exist in current schema, include ALTER TABLE ADD COLUMN in the migration sub-step; verify against current schema first
- Triage prompt text @ `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` commit `d7db987`

### Branch + PR

- Branch: `step1-triage-impl`
- Base: `main`
- PR title: `STEP1-TRIAGE-IMPL: kbl/steps/step1_triage.py + kbl/prompts/step1_triage.txt`
- Target PR: #8

### Reviewer

B2 (reviewer-separation).

### Timeline

~60-90 min.

### Dispatch back

> B1 STEP1-TRIAGE-IMPL shipped — PR #8 open, branch `step1-triage-impl`, head `<SHA>`, <N>/<N> tests green. Ready for B2 review.

---

*Posted 2026-04-18 by AI Head. B2 reviewing PR #7 in parallel. B3 authoring STEP5-OPUS-PROMPT in parallel. Director: Fireflies labeling in separate session.*
