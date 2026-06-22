# Ship report — AI_HOTEL_LAB_SEARCH_ROUTING_1 (Sprint-0 Step 3)

**Builder:** b2 · **Dispatched_by:** lead · **Date:** 2026-06-22
**Branch:** `b2/ai-hotel-search-routing-1` · **Base:** `main` @ `ca70bf45`
**Source of truth:** codex-arch #3679 (product, 8 ACs) + deputy-codex #3683 (security
rubric, folded into the brief done rubric at `ca70bf45`). Both binding.

## What shipped

A new `policy/search/` subpackage — the controlled intelligence-intake layer — built
as a CONSUMER of Step-1 (`policy.engine`) + Step-2 (`policy.sources`). No second allow
path, no forked registry, no forked taxonomy.

| File | Role |
|---|---|
| `policy/search/models.py` | 5 `SearchMode`, 13 `RouteTarget`, `RoutingMethod`, `RawSignal` (16 fields), result records |
| `policy/search/routing.py` | 11 deterministic rules; LLM assist-only (projection-safe input, schema-validated, capped, cannot override risk); audited human override that never touches policy |
| `policy/search/runner.py` | `search()` over Step-2 sources; external ALWAYS forced through `partner_projection`; bounded+paginated; generic external zero-result |
| `policy/search/signals.py` | amber raw-signal capture (lands `raw_signal`); promotion ONLY via the Step-1 lifecycle gate |
| `policy/search/store.py` | parameterized SQL for 6 tables + bounded/time-limited `load_search_candidates`; every `except` fails closed |
| `migrations/20260622_ai_hotel_search_routing.sql` | 6 tables, additive + idempotent (`IF NOT EXISTS`), enum CHECK constraints, plain indexes |
| `tests/test_search_routing.py` | 71 tests, 1:1 to ACs / threats / done-rubric |

## Done rubric (answered point by point)

1. **Citation table** — below (codex-arch AC1–8 + deputy-codex AC/T threat semantics → named tests).
2. **Partner-safe body from `partner_projection` only** — `_partner_body` copies projection fields only; `test_rubric2_external_body_comes_from_partner_projection` spies the call; `test_rubric2_removing_projection_yields_no_external_body` proves removing the projection yields NO external body.
3. **Direct-API bypass** — `test_ac2_crafted_internal_mode_by_external_still_projection_only` + `test_ac8_permission_bypass_attempt_returns_nothing_raw`: external forced through projection regardless of mode/filter; no raw field reachable.
4. **No second allow path (T3)** — `test_rubric4_external_routes_through_engine_evaluate` / `_internal_routes_through_engine_search_action`: every visible result goes through `policy.engine.evaluate` (+ `partner_projection` for external).
5. **Routing** — all 11 deterministic rules (`test_rubric5_all_eleven_deterministic_rules`); LLM proposes-only/capped/can't-override (`test_rubric5_llm_*`); override audited (`test_ac5_*`); conflict → `source_gap_unassigned_review` (`test_rubric5_conflicting_routes_resolve_to_unassigned_review`).
6. **Raw-signal + promotion** — `test_ac4_save_raw_signal_lands_raw_signal`; `test_ac7_raw_signal_cannot_skip_to_shared_view` (skip refused by the Step-1 lifecycle gate); `test_ac7_promotion_path_via_lifecycle_gate` (legit path works).
7. **Zero-results never leak** — `test_ac6_*`, `test_zero_result_external_is_generic_no_facets` (no facets/counts/deny-reason/gap inventory); internal coverage may log scope (`test_zero_result_internal_may_carry_scope`).
8. **Staleness regression (T9)** — `test_t9_demote_after_index_hides_stale_payload` / `_redact_external_flag_after_index` / `_never_external_after_index`: live re-check at response time; no stale partner-safe payload.
9. **Prompt-injection (T8/AC9)** — `test_t8_llm_router_receives_projection_safe_text_only`, `_llm_non_routetarget_output_is_rejected`, `_injection_text_cannot_widen_external_visibility`, `_llm_output_only_channel_is_a_suggestion`.
10. **Abuse/scale (AC10)** — `test_ac10_results_are_limit_bounded`, `_pagination_offset`, `_limit_hard_capped_to_page_max`, `_candidate_scan_hard_capped`, `_external_search_fails_closed_on_backend_error`, `_load_search_candidates_fails_closed`, `_load_search_candidates_clamps_limit` (bounded SQL: `LIMIT`/`OFFSET`, limit clamped to 500, statement timeout, no unbounded `SELECT`).
11. **Migrations + green** — additive/idempotent, no `CREATE INDEX CONCURRENTLY`; `pytest tests/test_search_routing.py` = **71 passed**; `bash scripts/check_singletons.sh` = green; `tests/test_source_inventory.py` = **38 passed** (no Step-2 regression).
12. **DONE invariant** — information can enter and be routed, but nothing becomes externally visible or trusted evidence except through the Step-1 policy engine + the human-ratified lifecycle gate.

## Citation table

codex-arch product ACs:

| codex-arch AC | Test(s) |
|---|---|
| AC1 internal search across domains | `test_ac1_internal_sees_permitted_results_across_domains`, `test_ac1_internal_domain_filter` |
| AC2 external cannot retrieve raw fields | `test_ac2_external_results_never_carry_raw_fields[0..2]`, `test_ac2_crafted_internal_mode_by_external_still_projection_only`, `test_ac2_external_never_sees_internal_only_or_neverexternal_or_gap` |
| AC3 result carries route_target + reason | `test_ac3_every_result_has_routing` |
| AC4 save as raw amber signal | `test_ac4_save_raw_signal_lands_raw_signal`, `test_ac4_rawsignal_has_all_16_fields` |
| AC5 override audited | `test_ac5_override_is_audited`, `test_ac5_override_on_signal_changes_only_route_not_policy` |
| AC6 zero-results → gap, never blank | `test_ac6_zero_result_is_gap_candidate_not_blank`, `test_ac6_web_live_hook_is_defined_only` |
| AC7 promotion needs confirmation path | `test_ac7_raw_signal_cannot_skip_to_shared_view`, `test_ac7_promotion_path_via_lifecycle_gate`, `test_ac7_ai_cannot_finalize_promotion` |
| AC8 threat-case tests | `test_ac8_*` (bypass / misclassified / never-external / duplicate / conflict) |

deputy-codex AC1–AC10 (exact labels relayed by lead, bus #3699; deputy-codex owns the
authoritative text in #3683 and gates PR #403 against it):

| deputy-codex AC | Test(s) |
|---|---|
| AC1 search entrypoint policy-bound server-side (client can't widen) | `test_rubric4_external_routes_through_engine_evaluate`, `test_rubric4_internal_routes_through_engine_search_action`, `test_ac2_crafted_internal_mode_by_external_still_projection_only` |
| AC2 candidates from Step-2 registry; missing metadata fails closed | `test_dc_ac2_invalid_candidate_fails_closed`, `test_ac10_load_search_candidates_clamps_limit`, `test_fixture_all_four_principals_same_set` |
| AC3 external bodies from `partner_projection` ONLY | `test_rubric2_external_body_comes_from_partner_projection`, `test_rubric2_removing_projection_yields_no_external_body`, `test_ac2_external_results_never_carry_raw_fields[*]` |
| AC4 no duplicate allow path | `test_rubric4_external_routes_through_engine_evaluate`, `test_rubric4_internal_routes_through_engine_search_action` |
| AC5 never-external/sensitive fail closed (search+counts+facets+routing) | `test_ac8_never_external_source_hidden_and_routed_to_risk`, `test_t9_never_external_after_index_hides_payload`, `test_t8_injection_text_cannot_widen_external_visibility`, `test_zero_result_external_is_generic_no_facets` |
| AC6 zero-result non-leaking (generic external; internal gap log) | `test_ac6_zero_result_is_gap_candidate_not_blank`, `test_ac6_zero_result_does_not_leak_hidden_material`, `test_zero_result_external_is_generic_no_facets`, `test_zero_result_internal_may_carry_scope` |
| AC7 search logging auditable but non-leaking by audience | `test_dc_ac7_search_audit_is_non_leaking`, `test_t10_log_search_query_fails_closed`, `test_t10_record_zero_result_gap_fails_closed` |
| AC8 routing suggestions proposals only (no policy/lifecycle/visibility mutation) | `test_ac5_override_on_signal_changes_only_route_not_policy`, `test_t8_llm_output_only_channel_is_a_suggestion`, `test_rubric5_llm_is_assist_only_and_capped` |
| AC9 LLM routing projection-safe inputs + schema-validated outputs | `test_t8_llm_router_receives_projection_safe_text_only`, `test_t8_llm_non_routetarget_output_is_rejected`, `test_rubric5_llm_cannot_override_confident_rule`, `test_rubric5_llm_cannot_override_risk_route`, `test_rubric5_llm_failure_falls_back_to_deterministic` |
| AC10 abuse/failure/scale (bounded/paginated/time-limited; fail closed; no unbounded SQL) | `test_ac10_results_are_limit_bounded`, `test_ac10_pagination_offset`, `test_ac10_limit_hard_capped_to_page_max`, `test_ac10_candidate_scan_hard_capped`, `test_ac10_external_search_fails_closed_on_backend_error`, `test_ac10_load_search_candidates_fails_closed`, `test_ac10_load_search_candidates_clamps_limit` |

deputy-codex T1–T10 (exact labels, bus #3699):

| deputy-codex threat | Test(s) |
|---|---|
| T1 raw snippet leak | `test_ac2_external_results_never_carry_raw_fields[*]`, `test_dc_ac7_search_audit_is_non_leaking` |
| T2 crafted filter bypass | `test_ac2_crafted_internal_mode_by_external_still_projection_only`, `test_ac8_permission_bypass_attempt_returns_nothing_raw[*]` |
| T3 count/facet/zero-result inference | `test_zero_result_external_is_generic_no_facets`, `test_ac6_zero_result_does_not_leak_hidden_material` |
| T4 cross-partner bleed | `test_dc_t4_cross_partner_bleed_blocked_in_search`, `test_fixture_all_four_principals_same_set` |
| T5 misclassification leak | `test_ac8_misclassified_source_without_grant_is_hidden` |
| T6 policy bypass drift | `test_rubric4_external_routes_through_engine_evaluate`, `test_ac2_crafted_internal_mode_by_external_still_projection_only` |
| T7 LLM auto-action | `test_t8_llm_output_only_channel_is_a_suggestion`, `test_ac7_ai_cannot_finalize_promotion`, `test_rubric5_llm_is_assist_only_and_capped` |
| T8 prompt-injection route escalation | `test_t8_injection_text_cannot_widen_external_visibility`, `test_t8_llm_non_routetarget_output_is_rejected`, `test_rubric5_llm_cannot_override_risk_route` |
| T9 search index staleness | `test_t9_demote_after_index_hides_stale_payload`, `test_t9_redact_external_flag_after_index_hides_payload`, `test_t9_never_external_after_index_hides_payload` |
| T10 logging leak | `test_dc_ac7_search_audit_is_non_leaking`, `test_t10_save_raw_signal_row_fails_closed` |

## Reuse (no fork / no second path)

- Visibility: ONLY `policy.engine.evaluate` + `policy.engine.partner_projection` (via `policy.sources.registry.external_projection_for`). `Action.SEARCH` from the Step-1 enum.
- Promotion: ONLY `policy.lifecycle` (`transition` / `propose_promotion` / `approve_promotion`). `signals.raw_signal_to_evidence_item` bridges into the Step-1 object model.
- Source metadata: read via `policy.sources` (`load_search_candidates` reuses Step-2 `_row_to_record`). Taxonomy (`Org` / `Classification` / `LifecycleState` / `Sensitivity` / `SourceDomain` / `SourceObjectType`) reused unchanged.

## Test evidence

```
$ python3 -m pytest tests/test_search_routing.py -q
71 passed, 1 warning in 0.09s

$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -m pytest tests/test_source_inventory.py -q
38 passed, 1 warning in 0.04s
```

(Full-suite run shows pre-existing, environment-only failures — missing `mcp`/grok/
perplexity deps and no `TEST_DATABASE_URL` — verified identical with this branch's new
files removed; not caused by this change.)

## Gate chain (next)

1. ✅ Builder self-test — pytest + singleton green.
2. → **deputy-codex** AC + threat gate vs #3683 (REQUEST_CHANGES blocks merge).
3. → **deputy** augmented chain (architect + codex-verifier).
4. → **lead** `/security-review` (Tier-A partner-leak surface) → merge.
5. → POST_DEPLOY_AC v1 after Render deploy (migration runs clean at startup).
