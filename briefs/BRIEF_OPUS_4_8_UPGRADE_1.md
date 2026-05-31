# BRIEF: OPUS_4_8_UPGRADE_1 — Bump Baker to Claude Opus 4.8 + fix Opus cost table

## Context
Anthropic shipped **Claude Opus 4.8** (`claude-opus-4-8`) on 2026-05-28: ~4× less likely to miss flaws in generated code, 1M context, 128k output, **same price as 4.7 ($5/M in, $25/M out)**. Drop-in replacement. Director ratified scoping this upgrade 2026-05-31.

Codebase audit (2026-05-31) found two problems this brief fixes:
1. **Fragmented + stale model config:** 28 hardcoded `claude-opus-4-6` + 15 `claude-opus-4-7` sites, zero on 4-8, across 14 prod files. No single source of truth.
2. **Mis-calibrated cost table:** `kbl/cost.py` prices the `claude-opus-4` family at **$15/$75** (old 4-6 price). Real 4.7/4.8 = **$5/$25** → Baker overstates Opus spend ~3×, can trip the daily cost cap prematurely.

### Surface contract: N/A — backend model-config + cost-table change, no user-clickable surface.

## Estimated time: ~2.5h
## Complexity: Medium (many sites, but mechanical; cost table is the only logic change)
## Prerequisites: confirm exact `claude-opus-4-8` model string against platform.claude.com release notes before commit.

---

## Fix 1: Centralize + bump model to Opus 4.8

### Problem
43 hardcoded Opus version strings across 14 files; 28 still on 4-6 (two generations behind). No single switch to change model.

### Current State
- `kbl/anthropic_client.py:51` — `_DEFAULT_MODEL = "claude-opus-4-7"`; env override via `_MODEL_ENV` (line ~234 reads `os.environ.get(_MODEL_ENV, _DEFAULT_MODEL)`).
- 4-6 sites: `orchestrator/cortex_phase3_synthesizer.py:31` (`PHASE3C_MODEL`), `cortex_phase3_invoker.py:36`, `cortex_phase3_reasoner.py`, `capability_runner.py:328`, `extraction_engine.py:316`, `memory_consolidator.py:49` (`TIER2_MODEL`), `tools/ingest/classifier.py:92`, `tools/ingest/extractors.py:309`, `tools/document_pipeline.py:32` (`_OPUS_MODEL`), `config/settings.py:47` + `:340`.
- 4-7 sites: `kbl/steps/step5_opus.py:876,899` (env `KBL_STEP5_MODEL`), `claimsmax/recharge_report/generator.py:24` (`MODEL_HIGH`).

### Implementation
1. In `kbl/anthropic_client.py`: set `_DEFAULT_MODEL = os.environ.get("KBL_ANTHROPIC_MODEL", "claude-opus-4-8")` (single source of truth). Update the module docstring (line ~25) to document `KBL_ANTHROPIC_MODEL` default.
2. For each hardcoded Opus constant above, replace the literal with `claude-opus-4-8` **and** add `os.environ.get("KBL_ANTHROPIC_MODEL", "claude-opus-4-8")` where the file already imports `os`. Where a module-level constant is cleaner (e.g. `PHASE3C_MODEL`, `TIER2_MODEL`, `_OPUS_MODEL`, `MODEL_HIGH`), set that constant to the env-resolved value.
3. **Do NOT change intentional non-Opus routes:** `claimsmax MODEL_ROUTINE = "claude-sonnet-4-6"`, the gemma/gemini/haiku routes in `step1_triage`, `step3_extract`, `document_pipeline._HAIKU_MODEL`, `retry.py` health model. Those are deliberate cheaper-tier picks.
4. **LLM three-way match:** changing only the model string keeps the client + response-access pattern identical (all are `claude-opus-*` on the same Anthropic client). No call-signature change. Verify each edited call still reads the same response field.

### Key Constraints
- ONE model family only (Opus → Opus). Do not touch Sonnet/Haiku/Gemma routes.
- Every change env-overridable; no un-overridable hardcoded `4-8`.
- Migrate + syntax-check **one file at a time** (Lesson: batch LLM migration = 19 bugs). `python3 -c "import py_compile; py_compile.compile('<file>', doraise=True)"` after each.

### Verification
- `grep -rn "claude-opus-4-6\|claude-opus-4-7" --include=*.py .` returns only test fixtures + this is reduced to intended overrides.
- `KBL_ANTHROPIC_MODEL=claude-opus-4-7 python3 -c "import kbl.anthropic_client as a; print(a._DEFAULT_MODEL)"` prints `claude-opus-4-7` (rollback works).

---

## Fix 2: Correct Opus pricing in cost tables

### Problem
`kbl/cost.py` PRICING `claude-opus-4` = $15/$75; real 4.7/4.8 = $5/$25. Internal cost monitor overstates Opus spend ~3×.

### Current State
- `kbl/cost.py:35-38` — `claude-opus-4: input PRICE_OPUS4_IN default "15.00", output PRICE_OPUS4_OUT default "75.00"`.
- `orchestrator/cost_monitor.py:27` — `"claude-opus-4-6": {"input": 15.00, "output": 75.00}`.

### Implementation
1. `kbl/cost.py`: change defaults to `PRICE_OPUS4_IN` `"5.00"` / `PRICE_OPUS4_OUT` `"25.00"` (keep env overrides). Add comment: `# Opus 4.7/4.8 pricing, 2026-05-28`.
2. `orchestrator/cost_monitor.py:27`: add `"claude-opus-4-8": {"input": 5.00, "output": 25.00}` and update the 4-6 entry comment to mark it legacy. Keep family normalization working.

### Key Constraints
- Keep env overrides (`PRICE_OPUS4_IN/OUT`) — Director can flex without redeploy.
- `_model_key()` already normalizes `opus` → `claude-opus-4`; do not break that path.

### Verification
- `python3 -c "from kbl.cost import estimate_cost_usd" ` (or the actual fn) on a known token count returns the new $5/$25 rate.

---

## Out of scope — Phase 2 (separate brief, do NOT implement here)
- **Fast mode + effort control** (Opus 4.8: ~2.5× faster, ~3× cheaper). Requires Anthropic SDK param verification before wiring. Target hot-path: ingest classifier/extractor, WhatsApp `_wa_reply`, triage. Deferred.

## Files Modified
- `kbl/anthropic_client.py` — central default → 4-8 via env.
- `orchestrator/cortex_phase3_synthesizer.py`, `cortex_phase3_invoker.py`, `cortex_phase3_reasoner.py`, `capability_runner.py`, `extraction_engine.py`, `memory_consolidator.py` — 4-6 → 4-8.
- `tools/ingest/classifier.py`, `tools/ingest/extractors.py`, `tools/document_pipeline.py` — 4-6 → 4-8 (Opus route only).
- `config/settings.py` — defaults 4-6 → 4-8.
- `kbl/steps/step5_opus.py`, `claimsmax/recharge_report/generator.py` — 4-7 → 4-8.
- `kbl/cost.py`, `orchestrator/cost_monitor.py` — Opus pricing $15/$75 → $5/$25.
- Tests: `tests/test_anthropic_client.py`, `test_step5_opus.py`, `test_prompt_cache_audit.py`, `test_prompt_caching_1.py`, `test_claimsmax_client.py`, `test_dashboard_kbl_endpoints.py` — assert new default + pricing.

## Do NOT Touch
- `claimsmax MODEL_ROUTINE` (sonnet), `step1_triage`/`step3_extract` gemma, `document_pipeline._HAIKU_MODEL` (gemini), `retry.py` health model — intentional cheaper tiers.
- Any non-model logic in the edited files.

## Quality Checkpoints
1. `pytest` literal-green (no "by inspection") — paste output in ship report.
2. One live Opus 4.8 call via `kbl/anthropic_client.py` returns 200 + non-empty completion.
3. Rollback verified: `KBL_ANTHROPIC_MODEL=claude-opus-4-7` reverts model with no redeploy.
4. `grep` confirms no stray 4-6/4-7 outside intended overrides + test fixtures.
5. Cost calc returns $5/$25 for an Opus call.

## Verification SQL
```sql
-- After a deploy + one Cortex cycle, confirm cost rows use the corrected rate
SELECT model, input_tokens, output_tokens, cost_usd
FROM baker_actions
WHERE model LIKE 'claude-opus-4%' AND created_at > now() - interval '1 hour'
ORDER BY created_at DESC LIMIT 20;
```
