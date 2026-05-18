---
brief_id: GROK_API_HARDENING_1
pr: 217
branch: b3/grok-api-hardening-1
amendment_commit: b2c3c23
prior_commit: 41e2c6e
trigger: bus #384 (request-changes/grok-pr-217 from lead, 2026-05-18T08:19Z)
director_auth: 2026-05-18 ~08:15Z chat ("ratified" post-gate-chain summary)
posted_to_bus: 2026-05-18T08:31Z (msg #386, topic amendments/grok-pr-217)
status: amendments_pushed_awaiting_gates_3_and_4_rerun
---

# B3 amendment report — GROK_API_HARDENING_1 / PR #217

REQUEST_CHANGES from lead (bus #384) carried 3 folds. All 3 closed in a single
new commit `b2c3c23` on top of `41e2c6e` (no amend, per repo hard rule).

## FOLD #1 — citation merge order (gate-3 MEDIUM + gate-4 LOW converge)

**Problem.** `kbl/grok_client.py:_shape_search_response` called
`_merge_citations_by_url(top_level_citations, inline_citations)`. When the same
URL appears in both — common per xAI Agent Tools API — the bare top-level
string wins first-seen and the rich inline dict `{url, title, snippet, …}` is
dropped. `_shape_web_citation` then emits an empty title/snippet downstream.
Real data loss observed in prod smoke #5.

**Fix.**
- `kbl/grok_client.py` — swap args to `_merge_citations_by_url(inline_citations,
  top_level_citations)`. Inline call-site comment explains the order constraint.
- `kbl/grok_client.py:_merge_citations_by_url` docstring — now states
  "first-source-wins" explicitly so the call-site contract is enforceable.
- `tests/test_grok_client.py` — extended
  `test_web_search_merges_top_level_and_inline_dedup` to assert the rich title
  survives + added
  `test_web_search_rich_inline_beats_bare_top_level_string_on_url_tie` as a
  dedicated regression-guard for the prod-smoke-#5 scenario.

## FOLD #2 — drift detector predicate equivalence (gate-4 MEDIUM)

**Problem.** `tests/test_capability_sets_constraints.py::test_store_back_bootstrap_in_sync_with_migration`
asserted only that the constraint **name** and the `UPDATE capability_sets`
statement appeared in the bootstrap block. A future predicate-text edit in one
file but not the other (the exact Lesson #50 failure mode this M4 fix is
supposed to defend against) would pass silently.

**Fix.** New helpers `_extract_check_predicate` (balanced-paren walker, handles
nested `jsonb_array_length(trigger_patterns)` correctly) and
`_check_predicate_clauses` (split on `OR`, normalize whitespace). The detector
now extracts the CHECK predicate body from the migration SQL, splits into
OR-clauses, and asserts each clause appears verbatim in the bootstrap block's
own predicate. Asserts `≥2 OR-clauses` on the migration side so the detector
itself fails loudly if the constraint shape changes upstream.

## FOLD #3 — retry wall-clock vs per-call timeout (gate-3 MEDIUM)

**Problem.** `_request` accepted `timeout` as a per-HTTP-attempt override, but
the docstring + MCP descriptions read "Per-call HTTP timeout". With
`_max_retries=3` + `Retry-After: 30s`, a caller passing `timeout=10` could still
see ~120s total wall-clock before failing. Contract mismatch with caller
expectation.

**Fix — Option A picked per AH1 recommendation (lowest-risk, docstring-only).**
- `kbl/grok_client.py:_request` — docstring now documents per-attempt semantics
  + the explicit worst-case wall-clock formula
  (`timeout × max_retries + Retry-After × max_retries`) + the "wrap in your own
  deadline" guidance.
- `kbl/grok_client.py:ask + x_search + web_search` — short references back to
  the `_request` docstring on each public method.
- `tools/grok.py` — all 3 inputSchema `timeout_seconds` descriptions updated
  to mirror the per-attempt contract, including the worst-case formula and the
  hard-bound guidance for MCP callers.
- `tests/test_grok_client.py` — new
  `test_timeout_is_per_attempt_not_total_wall_clock` exercises 3 attempts with
  `timeout=10`, asserts every attempt receives the full per-call timeout (not
  a budgeted remaining value) and that `Retry-After=30` sleeps are honoured at
  face value (not capped against the per-call timeout).

## Non-folds (left untouched per dispatch)

- Gate-3 L1 / AH2 N1 schema-vs-validator `minimum:1` mismatch — schema is the
  first gate; harmless.
- Gate-3 L2 missing `applied_migrations.lock` doc line — cosmetic.
- Gate-3 L3 bootstrap CHECK-runs-before-seed ordering — safe today, defer.
- AH2 N2 default-model duplication (`'grok-4.3'` in `tools/grok.py` +
  `_DEFAULT_MODEL` in `kbl/grok_client.py`) — cosmetic.

## Verification

`python3.12 -m pytest tests/test_grok_client.py tests/test_capability_sets_constraints.py -v`
— full literal output:

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 52 items

tests/test_grok_client.py::test_missing_api_key_raises PASSED            [  1%]
tests/test_grok_client.py::test_default_base_url PASSED                  [  3%]
tests/test_grok_client.py::test_base_url_trailing_slash_stripped PASSED  [  5%]
tests/test_grok_client.py::test_auth_header_uses_bearer PASSED           [  7%]
tests/test_grok_client.py::test_ask_parses_response_and_returns_text PASSED [  9%]
tests/test_grok_client.py::test_ask_body_uses_default_model_and_passes_overrides PASSED [ 11%]
tests/test_grok_client.py::test_x_search_returns_summary_and_tweets PASSED [ 13%]
tests/test_grok_client.py::test_x_search_passes_date_and_handle_filters PASSED [ 15%]
tests/test_grok_client.py::test_web_search_uses_tools_array PASSED       [ 17%]
tests/test_grok_client.py::test_web_search_passes_domain_filters PASSED  [ 19%]
tests/test_grok_client.py::test_web_search_citations_are_shaped PASSED   [ 21%]
tests/test_grok_client.py::test_401_raises_auth_error PASSED             [ 23%]
tests/test_grok_client.py::test_403_raises_forbidden PASSED              [ 25%]
tests/test_grok_client.py::test_422_raises_validation_error PASSED       [ 26%]
tests/test_grok_client.py::test_5xx_raises_server_error_no_retry PASSED  [ 28%]
tests/test_grok_client.py::test_non_json_2xx_raises_server_error PASSED  [ 30%]
tests/test_grok_client.py::test_429_retries_then_succeeds PASSED         [ 32%]
tests/test_grok_client.py::test_429_budget_exhaustion_raises PASSED      [ 34%]
tests/test_grok_client.py::test_parse_retry_after_fallback PASSED        [ 36%]
tests/test_grok_client.py::test_timeout_raises_transport_error PASSED    [ 38%]
tests/test_grok_client.py::test_http_error_raises_transport_error PASSED [ 40%]
tests/test_grok_client.py::test_flatten_output_text_handles_mixed_blocks PASSED [ 42%]
tests/test_grok_client.py::test_shape_tweet_citation_handles_string_and_dict PASSED [ 44%]
tests/test_grok_client.py::test_shape_web_citation_handles_string_and_dict PASSED [ 46%]
tests/test_grok_client.py::test_cost_usd_prefers_ticks_when_provided PASSED [ 48%]
tests/test_grok_client.py::test_cost_usd_falls_back_to_token_rates PASSED [ 50%]
tests/test_grok_client.py::test_cost_usd_zero_when_empty PASSED          [ 51%]
tests/test_grok_client.py::test_http_client_reused_across_requests PASSED [ 53%]
tests/test_grok_client.py::test_close_releases_underlying_client PASSED  [ 55%]
tests/test_grok_client.py::test_dispatch_grok_logs_cost_after_call PASSED [ 57%]
tests/test_grok_client.py::test_dispatch_grok_blocks_when_circuit_breaker_tripped PASSED [ 59%]
tests/test_grok_client.py::test_dispatch_grok_cost_monitor_import_failure_fails_open PASSED [ 61%]
tests/test_grok_client.py::test_reset_client_cache_picks_up_rotated_key PASSED [ 63%]
tests/test_grok_client.py::test_reset_client_cache_alias_is_identity_preserving PASSED [ 65%]
tests/test_grok_client.py::test_grok_client_request_passes_timeout_to_httpx PASSED [ 67%]
tests/test_grok_client.py::test_grok_client_default_timeout_when_omitted PASSED [ 69%]
tests/test_grok_client.py::test_timeout_is_per_attempt_not_total_wall_clock PASSED [ 71%]
tests/test_grok_client.py::test_dispatch_grok_passes_timeout_seconds_to_client PASSED [ 73%]
tests/test_grok_client.py::test_dispatch_grok_rejects_invalid_timeout PASSED [ 75%]
tests/test_grok_client.py::test_web_search_extracts_inline_annotations PASSED [ 76%]
tests/test_grok_client.py::test_web_search_merges_top_level_and_inline_dedup PASSED [ 78%]
tests/test_grok_client.py::test_web_search_rich_inline_beats_bare_top_level_string_on_url_tie PASSED [ 80%]
tests/test_grok_client.py::test_x_search_extracts_inline_annotations PASSED [ 82%]
tests/test_grok_client.py::test_extract_inline_annotations_helper_filters_non_url_types PASSED [ 84%]
tests/test_grok_client.py::test_merge_citations_keeps_non_url_entries PASSED [ 86%]
tests/test_grok_client.py::test_live_grok_ask_smoke SKIPPED               [ 88%]
tests/test_grok_client.py::test_live_grok_web_search_smoke SKIPPED        [ 90%]
tests/test_capability_sets_constraints.py::test_migration_file_exists PASSED [ 92%]
tests/test_capability_sets_constraints.py::test_migration_orders_update_before_constraint PASSED [ 94%]
tests/test_capability_sets_constraints.py::test_store_back_bootstrap_in_sync_with_migration PASSED [ 96%]
tests/test_capability_sets_constraints.py::test_capability_sets_archive_no_trigger_patterns_constraint_blocks_insert SKIPPED [ 98%]
tests/test_capability_sets_constraints.py::test_capability_sets_domain_can_still_have_trigger_patterns SKIPPED [100%]

======================== 48 passed, 4 skipped in 0.28s =========================
```

The 4 skips are the same env-gated suites as on the original ship report:
2 live xAI smoke tests (`TEST_XAI_API_KEY` not set) + 2 live-PG round-trips
(`needs_live_pg` fixture).

Compile-clean confirmed via `py_compile` on all 4 edited files.

## Files touched (this commit only)

- `kbl/grok_client.py` (FOLD #1 + FOLD #3 docstrings)
- `tools/grok.py` (FOLD #3 inputSchema descriptions)
- `tests/test_grok_client.py` (FOLD #1 test + FOLD #3 test + extended dedup test)
- `tests/test_capability_sets_constraints.py` (FOLD #2 drift detector strength)

## Gate chain next

Per AH1 dispatch #384: gate-3 (`code-architecture-reviewer`) + gate-4
(`feature-dev:code-reviewer` 2nd-pass MANDATORY) re-fire on `b2c3c23`. Gate-1
(AH2 static, PASS-W-NITS already accepted as noise) and gate-2 (AH2
`/security-review`, NO_FINDINGS) stay clean.

## Bus

- Posted `amendments/grok-pr-217` to `lead` 2026-05-18T08:31Z (msg #386,
  thread `978b19a5-59e2-4323-ba8e-fa62019e5780`).
- Acked #378 (original dispatch) + #384 (request-changes).
