# Ship report — AI_HOTEL_LAB_PARTNER_PROJECTION_1 (Sprint-0 Step 4)

**Builder:** b2 · **Dispatched_by:** lead · **Date:** 2026-06-22
**Branch:** `b2/ai-hotel-partner-projection-1` · **Base:** `main` @ `a174edb3`
**Source of truth:** codex-arch #3733 (product, 7 ACs + 10 threat cases) + deputy-codex
#3738 (security rubric, folded into the brief done rubric at `a174edb3`). Both binding.

## What shipped

A new `policy/projection/` subpackage — the partner-safe projection surface (the
highest-leak-surface step). A CONSUMER of Steps 1-3: no second permission engine, no
raw-table joins in external responses, no new promotion path.

| File | Role |
|---|---|
| `policy/projection/models.py` | 4 `AudienceRole`, 8 `ProjectionState`, `ProjectionItem` (19 fields), `ViewPacket`, `EXTERNAL_ITEM_ALLOWLIST` (AC4) + forbidden-substring guard |
| `policy/projection/projector.py` | per-audience `ProjectionItem`; cross-role isolation (absent, not hidden); external bodies built ONLY by `partner_projection`; deterministic fail-closed state machine |
| `policy/projection/packets.py` | SEPARATE external/internal/admin serializers (T9); `view_as` byte-identical parity; server-side spoof guard (T10); cache revalidation (T11); audience-scoped `{item}/audit` |
| `policy/projection/admin.py` | evidence-admin approve (via the Step-1 lifecycle gate) / revoke / refresh, each audited; human-Brisen-admin only |
| `policy/projection/store.py` | parameterized SQL for 5 tables; non-mutating reads; fail-closed |
| `migrations/20260622b_ai_hotel_projection.sql` | 5 tables, additive + idempotent (`IF NOT EXISTS`), enum CHECK, plain indexes |
| `tests/test_partner_projection.py` | 31 tests, 1:1 to ACs / threats / done-rubric |

## Done rubric (answered point by point)

1. **Citation table** — below.
2. **Derived-only** — `test_rubric2_external_fields_from_partner_projection` (spy), `test_rubric2_removing_projection_yields_no_external_body` (removing the engine call → 0 visible), `test_ac2_no_raw_text_leaks`.
3. **Cross-role isolation** — `test_rubric3_cross_role_isolation_packet_and_counts` (absent, not hidden, across packet + counts), `test_rubric3_cross_role_isolation_item_audit` (across `{item}/audit`).
4. **Direct-API bypass** — `test_rubric4_direct_api_bypass_crafted_role`, `test_rubric4_crafted_candidates_other_audience_absent`.
5. **No second engine (T3)** — `test_rubric5_external_routes_through_engine`; removing `partner_projection` → no body (rubric2).
6. **raw_signal/research no-project** — `test_rubric6_raw_and_research_never_project[raw_signal|research_artifact]`.
7. **never_external block** — `test_rubric7_never_external_blocked` → `blocked_by_policy`, no payload.
8. **Revoke + stale** — `test_rubric8_revoke_and_stale` (revoked gone from external, audit retained; stale → `stale_projection`).
9. **view-as parity** — `test_rubric9_view_as_byte_identical`.
10. **Empty-state** — `test_rubric10_empty_state_has_reason` (never blank).
11. **Field-allowlist (AC4)** — `test_rubric11_field_allowlist` (keys ⊆ allowlist; forbidden substrings absent).
12. **Action-link no-leak + non-mutating (T8/AC9)** — `test_rubric12_action_link_no_urls`, `test_rubric12_view_is_non_mutating`.
13. **Serializer boundary (T9/AC10)** — `test_rubric13_serializer_boundary` (internal carries source id+owner; external never does).
14. **Spoof (T10)** — `test_rubric14_spoof_org_role_denied` (server-side principal fixture).
15. **Cache staleness (T11)** — `test_rubric15_cache_revalidated_on_change`, `test_rubric15_cache_served_when_unchanged`.
16. **Migrations + green** — additive/idempotent, no `CREATE INDEX CONCURRENTLY`; `pytest tests/test_partner_projection.py` = **31 passed**; Steps 1-3 suites green (`test_policy_core` 113, `test_source_inventory` 38, `test_search_routing` 80); `check_singletons.sh` green.
17. **DONE invariant** — no external audience can see another audience's items or any raw internal field; projection exists only through the Step-1 engine + human-approved lifecycle; revoke/stale honored.

## Citation table

codex-arch product ACs + threat cases:

| codex-arch | Test(s) |
|---|---|
| AC1 role-specific partner packets | `test_ac1_role_specific_packets` |
| AC2 derived, no raw leak | `test_ac2_no_raw_text_leaks`, `test_rubric2_*` |
| AC3 confidence/visibility/redaction/provenance | `test_ac3_item_has_confidence_visibility_provenance` |
| AC4 internal view-as each partner | `test_ac4_view_as_each_partner`, `test_ac4_external_cannot_view_as` |
| AC5 admin approve/revoke/refresh audited | `test_ac5_admin_approve_via_lifecycle_gate`, `test_ac5_admin_actions_reject_non_human_admin`, `test_ac5_revoke_audited_and_removes_from_external` |
| AC6 Step-5 renders from packets | packet `as_dict()` contract used by all packet tests (no policy re-impl) |
| AC7 security tests (all 5 classes) | `test_rubric3/4/6/7/8` |
| Threat: cross-role | `test_rubric3_*` |
| Threat: direct source_id / bypass | `test_rubric4_*` |
| Threat: raw_signal no-project | `test_rubric6_*` |
| Threat: never_external block | `test_rubric7_never_external_blocked` |
| Threat: misclassified / revoke / stale | `test_rubric7`, `test_rubric8_revoke_and_stale` |
| Threat: view-as parity | `test_rubric9_view_as_byte_identical` |

deputy-codex #3738 threats (5 named in lead #3739; **deputy-codex owns the
authoritative AC1-12/T1-12 text in #3738 and gates against it — exact AC#/T# numbering
to be confirmed at gate**, b2 not a party to #3738):

| deputy-codex threat | Test(s) |
|---|---|
| AC4 field-allowlist | `test_rubric11_field_allowlist` |
| T8/AC9 action-link no internal URLs + non-mutating | `test_rubric12_action_link_no_urls`, `test_rubric12_view_is_non_mutating` |
| T9/AC10 serializer boundary | `test_rubric13_serializer_boundary` |
| T10 spoof (server-side principal) | `test_rubric14_spoof_org_role_denied`, `test_rubric4_direct_api_bypass_crafted_role` |
| T11 cache staleness | `test_rubric15_cache_revalidated_on_change`, `test_rubric15_cache_served_when_unchanged` |
| fail-closed store (T10) | `test_store_save_item_fails_closed`, `test_store_load_items_fails_closed` |
| 6-principal fixture incl never_external | `test_all_six_principals_same_fixture_set` |

## Reuse (no fork / no second engine)

- Visibility + safe-body: ONLY `policy.engine.evaluate` + `policy.engine.partner_projection`.
- Promotion: ONLY `policy.lifecycle` (`propose_promotion` / `approve_promotion`) via `admin.approve_projection`.
- Source metadata + amber/research: `policy.sources` / `policy.search` (raw_signal/research_artifact never project externally).
- Taxonomy (`Org`/`Classification`/`LifecycleState`/`Sensitivity`/`RouteTarget`) reused unchanged.

## Test evidence

```
$ python3 -m pytest tests/test_partner_projection.py -q
31 passed, 1 warning in 0.06s

$ python3 -m pytest tests/test_policy_core.py tests/test_source_inventory.py tests/test_search_routing.py -q
231 passed

$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

(Full-suite run shows pre-existing, environment-only failures — missing `mcp`/grok/
perplexity deps, no `TEST_DATABASE_URL` — not caused by this change.)

## Gate chain (next)

1. ✅ Builder self-test — pytest + singleton green; Steps 1-3 green.
2. → **deputy-codex** AC + threat gate vs #3738 (REQUEST_CHANGES blocks merge).
3. → **deputy** augmented chain (architect + codex-verifier).
4. → **lead** `/security-review` (Tier-A — highest partner-leak surface of the sprint) → merge.
5. → POST_DEPLOY_AC v1 after Render deploy (migration runs clean at startup).
