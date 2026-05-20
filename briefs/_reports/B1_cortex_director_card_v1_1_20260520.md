---
brief_id: CORTEX_DIRECTOR_CARD_V1_1
agent: b1
date: 2026-05-20
status: SHIPPED
branch: b1/cortex-director-card-v1-1
base: main
brief: briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1_1.md
mailbox: briefs/_tasks/CODE_1_PENDING.md
amends: briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1.md (PR #226, merged 5db210a)
---

# B1 ship report — CORTEX_DIRECTOR_CARD_V1_1

## Summary

Two bundled amendments to v1.0 (Phase 4.5 Director Card):

1. **Model swap** — Phase 4.5 translator now calls Gemini 2.5 Pro as primary
   and falls back to Anthropic Sonnet 4.6 on ANY Gemini call/parse/schema
   failure. Fail-open contract preserved — `translate_to_director_card`
   never raises; double-failure returns `FAIL_OPEN_SENTINEL` (None).
   `_meta.fallback_used` stamped on every card so audit can attribute spend.
2. **Smoke-cycle filter** — `/api/cortex/cycles/pending` gains
   `include_smoke: bool = False`. Default-hide; "Show all" toggle inside
   the Pending tab body re-fetches with the param flipped. Per-cycle
   `is_smoke` derived in SQL from `triggered_by` ILIKE patterns +
   `LEFT(proposal_text, 200)` ILIKE patterns.

## Brief-defect note (surfaced to AH1 via bus #581 pre-implementation)

Brief specified `cortex_cycles.signal_text` as a smoke-detection input,
but that column does not exist on the table. Verified against:
- `memory/store_back.py:658-677` (table bootstrap)
- All migrations under `migrations/2026*cortex_cycles*` (last is
  `20260518_cortex_cycles_add_last_nudge_at.sql`)

`signal_text` exists only as an in-memory variable in
`cycle.phase2_load_context` (`orchestrator/cortex_runner.py:312`). It is
plumbed into Phase 3 synthesis where it generally surfaces in the
`proposal_text` output — so the brief's intent is preserved by the
`LEFT(proposal_text, 200) ILIKE '%smoke #%'` branch.

Brief forbids touching migrations (`Do NOT touch` §); adding a new column
would have been out-of-scope. The triggered_by + proposal_text branches
cover the actual prod smoke cycles (Oskolkov uses
`triggered_by='self_wake_smoke'` and writes `Smoke #N …` into the
proposal). Documented in the route docstring.

## Files changed

- `orchestrator/cortex_phase4_5_director_card.py` — Gemini primary +
  Sonnet fallback + cost helpers + `_meta.fallback_used`. Sanitization,
  schema validation, persistence helpers unchanged.
- `outputs/dashboard.py` — `list_cortex_cycles_pending` gains
  `include_smoke` query param, returns `is_smoke` per cycle +
  `smoke_hidden_count` + `include_smoke` echo.
- `outputs/static/app.js` — `_cortexPendingFilterRowHtml` helper,
  smoke-toggle state + handler `_cortexPendingToggleSmoke`, per-cycle
  smoke chip rendering. Toggle button lives inside the Pending tab body
  (NOT the tab strip — PR #224 hitbox lesson).
- `outputs/static/style.css` — `.pending-filter-row`,
  `.pending-smoke-toggle`, `.cycle-smoke-tag`.
- `outputs/static/index.html` — cache-bust `style.css?v=76 → ?v=77`,
  `app.js?v=117 → ?v=118`.
- `tests/test_cortex_phase4_5_director_card.py` — 15 tests (existing 9
  re-aimed at Gemini primary + new V1.1 contract path; 6 new V1.1 tests).
- `tests/test_dashboard_cortex_ratify.py` — 5 new tests (4 smoke-filter
  paths + 1 source-level guard).

## Files NOT touched (per brief)

- `scripts/backfill_director_cards.py` — Director ratified NO backfill.
- `orchestrator/cortex_runner.py` — Phase 4.5 invocation unchanged.
- `orchestrator/gemini_client.py` — used as-is.
- Migrations + `cortex_cycles` schema — no schema change.

## Quality checkpoints

### 1. pytest (literal output)

```
$ python3.12 -m pytest tests/test_cortex_phase4_5_director_card.py tests/test_dashboard_cortex_ratify.py -v

tests/test_cortex_phase4_5_director_card.py::test_a_happy_path_returns_valid_9_field_card PASSED
tests/test_cortex_phase4_5_director_card.py::test_b_empty_proposal_text_returns_none_without_calling_api PASSED
tests/test_cortex_phase4_5_director_card.py::test_c_primary_api_error_triggers_sonnet_fallback PASSED
tests/test_cortex_phase4_5_director_card.py::test_d_missing_field_in_primary_falls_through_to_sonnet PASSED
tests/test_cortex_phase4_5_director_card.py::test_d_schema_validator_direct PASSED
tests/test_cortex_phase4_5_director_card.py::test_e_prompt_injection_in_card_fields_is_stripped PASSED
tests/test_cortex_phase4_5_director_card.py::test_e_sanitize_string_unit PASSED
tests/test_cortex_phase4_5_director_card.py::test_f_deterministic_at_temperature_zero_on_fallback PASSED
tests/test_cortex_phase4_5_director_card.py::test_gemini_primary_success_path PASSED
tests/test_cortex_phase4_5_director_card.py::test_sonnet_fallback_on_gemini_exception PASSED
tests/test_cortex_phase4_5_director_card.py::test_sonnet_fallback_on_gemini_invalid_json PASSED
tests/test_cortex_phase4_5_director_card.py::test_sonnet_fallback_on_gemini_schema_invalid PASSED
tests/test_cortex_phase4_5_director_card.py::test_double_failure_returns_sentinel PASSED
tests/test_cortex_phase4_5_director_card.py::test_gemini_no_api_key_falls_back PASSED
tests/test_cortex_phase4_5_director_card.py::test_persist_director_card_writes_correct_artifact PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_route_is_registered_in_dashboard_source PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_route_is_registered_in_dashboard_source PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_tab_button_in_static_index_html PASSED
tests/test_dashboard_cortex_ratify.py::test_cortex_ratify_js_helpers_exist PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_returns_200_with_cycles PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_returns_empty_when_no_cycles PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_rejects_missing_api_key PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_marks_has_proposal_false_when_no_synthesis PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_returns_director_card_when_present PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_director_card_null_when_absent PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_filters_smoke_by_default PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_include_smoke_true_returns_all PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_signal_text_smoke_marker_via_proposal_text PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_heartbeat_triggered_by_is_smoke PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_route_source_contains_smoke_detection_clauses PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_returns_200_with_phase_outputs PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_returns_400_on_bad_cycle_id PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_returns_404_when_cycle_missing PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_requires_api_key PASSED
tests/test_dashboard_cortex_ratify.py::test_action_endpoint_dispatches_each_canonical_action PASSED

======================== 35 passed, 7 warnings in 0.42s ========================
```

35 passed, 0 failed. No "by inspection" claims.

### 2. py_compile

```
$ python3.12 -c "import py_compile; py_compile.compile('orchestrator/cortex_phase4_5_director_card.py', doraise=True); py_compile.compile('outputs/dashboard.py', doraise=True); print('compile OK')"
compile OK
```

(Pre-existing SyntaxWarning at dashboard.py:2754 is on a regex literal
unrelated to this brief.)

### 3. Singletons CI guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### 4. Render env pre-flight

```
GEMINI_API_KEY: True
ANTHROPIC_API_KEY: True
```

(Checked via authenticated GET `/v1/services/srv-d6dgsbctgctc73f55730/env-vars`
using `op` 1Password "API Render" key; 61 env vars total.)

### 5. Baseline tests BEFORE edits

Same suite ran clean except a stale `app.js?v=116` cache-bust assertion
from V1.0 (now updated to `?v=118`). 24/25 passed pre-edit; 35/35 post-edit.

## Verification post-merge (AH1 to execute)

Per brief §Verification — manual smoke after Render deploy:

```sql
SELECT cycle_id::text,
       payload->'_meta'->>'model'          AS model_used,
       payload->'_meta'->>'fallback_used'  AS fallback_used,
       (payload->'_meta'->>'card_gen_cost_eur')::float AS cost_eur,
       created_at
FROM cortex_phase_outputs
WHERE artifact_type = 'director_card'
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC LIMIT 10;
```

Expect `model_used = 'gemini-2.5-pro'`, `fallback_used = false` on
healthy first-five cycles. Render logs should show ZERO `[phase4_5]`
fallback warnings on the healthy path. Frontend smoke: open dashboard
→ Cortex tab → Pending sub-tab; default view hides Oskolkov smoke
("Show all (incl. N smoke)" button visible); click toggles; smoke chip
visible only in "Show all" mode.

## Bus thread

- #580 — ack/claim
- #581 — heartbeat / brief-defect note (signal_text column missing)
- #582+ — ship report to lead on PR open

## Reply target

`lead` (per `dispatched_by:` in mailbox) — bus topic `ship/cortex-director-card-v1-1`.
