---
brief_id: CORTEX_DIRECTOR_CARD_V1_1_HOTFIX_GEMINI_JSON_1
agent: b1
date: 2026-05-20
status: SHIPPED
branch: b1/cortex-director-card-v1-1-hotfix-gemini-json-1
base: main
brief: briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1_1_HOTFIX_GEMINI_JSON_1.md
mailbox: briefs/_tasks/CODE_1_PENDING.md
fixes: PR #229 (CORTEX_DIRECTOR_CARD_V1_1) live smoke 100% Sonnet fallback rate
---

# B1 ship report — CORTEX_DIRECTOR_CARD_V1_1_HOTFIX_GEMINI_JSON_1

## Summary

Three-part hot-fix for the Phase 4.5 Gemini primary path. Live smoke
30 min after the V1.1 deploy showed 100% Sonnet fallback rate
(`[phase4_5] cycle dceaf71b…: gemini returned non-JSON; trying Sonnet
fallback`) — Gemini returned HTTP 200 with a body the parser could not
extract JSON from. Root cause = three combined weaknesses; this PR
closes all three.

### 1. `orchestrator/gemini_client.py` — `response_format` param

`generate(...)` gains optional `response_format: str = None`. When set
to `"json"`, the SDK config builder adds
`response_mime_type="application/json"` so Gemini emits strict JSON
(no markdown fences, no leading or trailing prose).

Used the kwargs-construction pattern recommended in the brief
(`types.GenerateContentConfig(**config_kwargs)`) — safer than
post-construction field assignment against frozen pydantic-v2 model
configs in newer google-genai versions.

Backward compatible — every existing caller (`capability_runner`,
auto-insight, `call_flash` / `call_pro` convenience wrappers) omits the
new kwarg and gets identical behavior.

### 2. `orchestrator/cortex_phase4_5_director_card.py` — token headroom + JSON-mode

- New constant `_MAX_TOKENS_GEMINI = 2000` next to existing
  `_MAX_TOKENS = 600`. Sonnet fallback path untouched (still 600 —
  works fine without thinking-mode overhead).
- Gemini call site now passes `max_tokens=_MAX_TOKENS_GEMINI` +
  `response_format="json"`.

### 3. `_parse_json_response` — brace-balanced extraction

Replaced the strict `json.loads` after leading-prose / fence stripping
with a brace-balanced, string-aware walk: find first `{`, scan forward
respecting `"…"` strings + `\\` escapes, return the slice up to the
matching `}`. Strips trailing prose in addition to existing leading
prose + fence handling.

## Files changed

- `orchestrator/gemini_client.py` — `generate()` signature + config build.
- `orchestrator/cortex_phase4_5_director_card.py` — `_MAX_TOKENS_GEMINI` constant, Gemini call params, parser rewrite.
- `tests/test_cortex_phase4_5_director_card.py` — 3 new tests + existing happy-path test updated to assert the new Gemini token budget + `response_format="json"` kwarg.

## Files NOT touched (per brief)

- `SYSTEM_PROMPT` — prompt already says "Output ONLY a JSON object…"; the issue is API-level enforcement.
- `_sanitize_card` / `_validate_card_schema` — schema/sanitization paths unrelated to parsing failure.
- Sonnet fallback block (`_MAX_TOKENS = 600` + `client.messages.create`).
- `gemini_client.call_flash` / `call_pro` defaults — `response_format` defaults to `None`.
- No `/env-vars` PUT, no migration, no UI surface.

## Quality checkpoints

### 1. pytest literal output

```
$ /opt/homebrew/bin/python3.12 -m pytest tests/test_cortex_phase4_5_director_card.py -v

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
tests/test_cortex_phase4_5_director_card.py::test_gemini_response_with_trailing_prose_parses PASSED
tests/test_cortex_phase4_5_director_card.py::test_gemini_response_with_fences_and_trailing_prose_parses PASSED
tests/test_cortex_phase4_5_director_card.py::test_parse_json_response_strips_trailing_prose_unit PASSED
tests/test_cortex_phase4_5_director_card.py::test_persist_director_card_writes_correct_artifact PASSED

============================== 18 passed in 0.04s ==============================
```

18/18 passed (15 carried forward from PR #229 + 3 new).

### 2. py_compile

```
$ python3.12 -c "import py_compile; py_compile.compile('orchestrator/gemini_client.py', doraise=True); py_compile.compile('orchestrator/cortex_phase4_5_director_card.py', doraise=True); print('compile OK')"
compile OK
```

### 3. Singletons

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### 4. Diff inspection

- `response_format` param on `generate()` defaults to `None` — backward compatible.
- Sonnet fallback path's `max_tokens=_MAX_TOKENS` (600) unchanged.
- No `/env-vars` PUT in diff (no relevance to pre-commit hook Part 4).

## Bus thread

- #598 — dispatch from lead (acked)
- #599 — heartbeat / claim
- TBD on PR open — ship report bus-post

## Post-merge verification (AH1 to execute)

Per brief §Verification:
- Fire `POST /api/cortex/trigger` with matter `oskolkov`, smoke trigger.
- Assert `payload->'_meta'->>'model' = 'gemini-2.5-pro'` AND
  `payload->'_meta'->>'fallback_used' = 'false'` on the resulting card.
- Render logs in the cycle window must have ZERO `[phase4_5]` warnings.

## Reply target

`lead` (per `dispatched_by:` in mailbox) — bus topic
`ship/cortex-director-card-v1-1-hotfix-gemini-json-1`.
