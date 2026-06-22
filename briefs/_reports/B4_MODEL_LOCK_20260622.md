# B4 ship report — BAKER_DASHBOARD_V2_MODEL_LOCK_1

- **Date:** 2026-06-22
- **Dispatched by:** deputy (bus #3740)
- **Branch:** `b4/baker-dashboard-v2-model-lock-1` off main
- **PR:** #406 — **MERGE HELD** (no lead-merge request; hold per gate plan)
- **Commit:** e5cf0e8
- **Ship report → deputy (bus) + cc codex-arch**

## DONE rubric answers

**Q1 — Which Flash call sites were found?**
Full census `rg "call_flash|_extract_flash|gemini-2.5-flash|Haiku" orchestrator/ outputs/ kbl/`. ~30 LLM call sites across 16 modules. Every `call_flash` / `_llm_call("gemini-2.5-flash")` site was classified trusted vs non-trusted by tracing its downstream write/object.

**Q2 — Which were converted to Gemini Pro? (19 trusted sites)**
- extraction_engine: `_extract_t3_trusted` (was `_extract_flash`, T3 → signal_extractions) + `_extract_visual`
- deadline_manager: `extract_deadlines` (→ deadlines table, AC3) + deadline proposal (→ alert structured_actions)
- pipeline: `_generate_structured_actions` (→ alerts.structured_actions) + low-value trigger routing (AC4 — `_LOW_VALUE_TRIGGER_TYPES` now route to `gemini-2.5-pro`, not Flash)
- research_trigger (→ research_proposal), convergence_detector ×2 (→ convergence alerts), capability_runner ×2 (corrections + insights→tasks/deadlines), initiative_engine (→ proactive initiatives), chain_runner (→ write-step adaptation), action_handler meeting_detect (→ detected_meetings) + critical_detect (→ critical deadline), meeting_pipeline (→ pending follow-up draft), decision_engine vip_auto_draft (→ pending draft), insight_to_task (→ ClickUp tasks/deadlines), obligation_generator (→ obligation alerts)
- dashboard: morning narrative + morning proposals (AC5), quick_add_enrich (→ alerts.structured_actions), add_meeting (→ detected_meetings), contact enrichment (→ vip_contacts / People surface)

**Q3 — Which were left as Flash, and why provably non-trusted housekeeping?**
- action_handler `classify_intent` / `fireflies_params` / `clickup_params` — routing label + tool-param JSON; the downstream write happens in a separate trusted handler, not from this output.
- agent `query_baker_data` — generates a SELECT-only read query; no actionable object written.
- decision_engine `classify_domain` — routing label only.
- sentiment_scorer ×2 — 1–5 tone metadata on contact_interactions; does not gate a card.
- dashboard: trip_reading_filter / trip_message_filter (presentation filtering), scan_image (ephemeral answer), AI-Hotel capture transcription + section classification (intermediate/metadata), followup_suggestions + alert_draft_reply (ephemeral UI text, Director edits/sends manually).
- **Borderline call flagged:** dashboard **contact enrichment** writes `tier`/`contact_type` to `vip_contacts`. That is a categorization label, not an actionable object — but the Director ruling names **People** as a trusted surface, so I converted it to Pro to honor the named-surface rule. Surfacing it here rather than deciding silently; revert to Flash if the coordinator judges it pure metadata.

**Q4 — Which tests prove no trusted extraction uses Flash?**
`tests/test_model_policy.py` (13 tests). Flash-spy on `call_flash`; trusted paths proven not to invoke it: `call_trusted` wrapper, T3 extraction, deadline extraction, pipeline low-value routing (rss/dropbox/clickup/browser → `gemini-2.5-pro`), dashboard `_llm_call` card path. Plus policy units (flash detection, fail-closed, Flash-override refusal) and a check that non-trusted Flash routing still works.

**Q5 — Expected cost impact.**
Per-trusted-call token cost rises ~4× (Flash $0.30/$2.50 → Pro $1.25/$10.00 per M). Volume is dominated by the pipeline low-value triggers (RSS / file / task-status) now on Pro. Per the plan §10 + Director ruling, cost is to be reclaimed by reducing volume / batching / skipping in a later tranche — NOT by reinstating Flash on a trusted path. No volume reduction is in scope for this step.

**Q6 — Model provenance visibility.**
AC6: `model_policy.log_model_provenance()` emits a structured `MODEL_PROVENANCE model=… trusted=… source=… output=… context=… ts=…` line; `call_trusted` calls it on every trusted call, and the dashboard trusted sites call it alongside `log_api_cost`. `log_api_cost` now records the Pro model id + source for every converted site (replacing the hardcoded `"gemini-2.5-flash"`).

## Verification (literal)
- `tests/test_model_policy.py`: **13 passed**
- `tests/test_ai_hotel_capture.py`: **33 passed, 1 skipped** (asserts ≥2 non-trusted Flash `_llm_call` retained — 6 remain)
- bridge/pipeline/proactive/cost/dashboard-noise/cortex suites: **87 passed, 19 skipped** (DB-gated)
- `py_compile` clean on all 16 modified modules.

## Gate plan status
1. Builder self-test ✅
2. deputy-codex G-review — **PENDING (mandatory, Director-directed)**: verify no trusted path still calls Flash.
3. MERGE HELD ✅ (PR open, not requesting merge)
4. Post-deploy AC after eventual merge: sampled trusted extraction rows show `gemini-2.5-pro`+.

## Rework round 1 — codex G-review F1 (commit e577165)

deputy-codex (#3764) REQUEST_CHANGES, one HIGH, valid + runtime-proven:
`call_pro()` asserted the policy **floor** (`trusted_extraction_model()`) but
dispatched `config.gemini.pro_model` **unvalidated** — so `pro_model='gemini-2.5-flash'`
ran trusted paths on Flash via both `call_trusted()` and `_llm_call('gemini-2.5-pro')`.
A config/env bypass straight back to Flash.

Fix: `call_pro()` now asserts `config.gemini.pro_model` is non-Flash before
`generate()` and raises `TrustedModelPolicyError` (fail loud) — never silently
dispatches Flash. +4 regression tests: `call_pro` / `call_trusted` / `_llm_call('gemini-2.5-pro')`
all raise AND `generate()` is not reached when `config.gemini.pro_model` is Flash;
plus a positive control. `test_model_policy.py` now **17 passed**; regression
bridge/ai_hotel/proactive/cost **65 passed / 8 skip**. Re-gate posted (#3775 deputy, #3776 codex-arch).

## Done-state
Harness-done = PR #406 + pytest literal green. Arc/lock-done (= live trusted rows on Pro) is a **separate** post-deploy state, not claimed here.
