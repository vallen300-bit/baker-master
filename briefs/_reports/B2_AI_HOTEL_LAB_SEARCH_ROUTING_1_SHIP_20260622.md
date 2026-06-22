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
| `tests/test_search_routing.py` | 68 tests, 1:1 to ACs / threats / done-rubric |

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
11. **Migrations + green** — additive/idempotent, no `CREATE INDEX CONCURRENTLY`; `pytest tests/test_search_routing.py` = **68 passed**; `bash scripts/check_singletons.sh` = green; `tests/test_source_inventory.py` = **38 passed** (no Step-2 regression).
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

deputy-codex threat semantics (#3683 — labels mapped to the Step-2 taxonomy carried
forward + the 3 Step-3 redefinitions lead named in #3684; **deputy-codex to confirm
exact AC#/T# numbering at gate**, since b2 is not a party to #3683):

| Threat (semantics) | Test(s) |
|---|---|
| T1 confused-deputy (crafted mode/filter) | `test_ac2_crafted_internal_mode_by_external_still_projection_only` |
| T2 field/identifier leakage | `test_ac2_external_results_never_carry_raw_fields[*]` |
| T3 no second allow path | `test_rubric4_external_routes_through_engine_evaluate`, `_internal_routes_through_engine_search_action` |
| T4 promote-bypass (AI can't finalize) | `test_ac7_ai_cannot_finalize_promotion`, `test_ac7_raw_signal_cannot_skip_to_shared_view` |
| T5 cross-partner bleed | `test_ac8_misclassified_source_without_grant_is_hidden`, `test_fixture_all_four_principals_same_set` |
| T6 no snippets/summaries leak | `test_ac2_external_results_never_carry_raw_fields[*]` |
| T7 stale-as-trusted (raw not trusted) | `test_ac4_save_raw_signal_lands_raw_signal`, `test_ac7_*` |
| **T8 prompt-injection** | `test_t8_llm_router_receives_projection_safe_text_only`, `_llm_non_routetarget_output_is_rejected`, `_injection_text_cannot_widen_external_visibility`, `_llm_output_only_channel_is_a_suggestion` |
| **T9 index-staleness** | `test_t9_demote_after_index_hides_stale_payload`, `_redact_external_flag_after_index`, `_never_external_after_index`, `test_zero_result_external_is_generic_no_facets` |
| T10 fail-closed | `test_t10_*`, `test_ac10_external_search_fails_closed_on_backend_error`, `test_ac10_load_search_candidates_fails_closed` |
| **AC10 abuse/scale** | `test_ac10_results_are_limit_bounded`, `_pagination_offset`, `_limit_hard_capped_to_page_max`, `_candidate_scan_hard_capped`, `_load_search_candidates_clamps_limit` |

## Reuse (no fork / no second path)

- Visibility: ONLY `policy.engine.evaluate` + `policy.engine.partner_projection` (via `policy.sources.registry.external_projection_for`). `Action.SEARCH` from the Step-1 enum.
- Promotion: ONLY `policy.lifecycle` (`transition` / `propose_promotion` / `approve_promotion`). `signals.raw_signal_to_evidence_item` bridges into the Step-1 object model.
- Source metadata: read via `policy.sources` (`load_search_candidates` reuses Step-2 `_row_to_record`). Taxonomy (`Org` / `Classification` / `LifecycleState` / `Sensitivity` / `SourceDomain` / `SourceObjectType`) reused unchanged.

## Test evidence

```
$ python3 -m pytest tests/test_search_routing.py -q
68 passed, 1 warning in 0.08s

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
