# B2 SHIP REPORT — AI_HOTEL_LAB_SOURCE_INVENTORY_1

**Brief:** `briefs/_tasks/AI_HOTEL_LAB_SOURCE_INVENTORY_1.md` (commit db0a42f)
**Dispatched_by:** lead (AH1) · bus #3657
**Branch:** `b2/ai-hotel-source-inventory-1` (off main, includes Step-1 merge 66411ba)
**Builder:** B2 · **Sprint-0 Step 2 of 5**

---

## What shipped — `policy/sources/` subpackage (feeds the Step-1 engine, no second allow path)

| File | Role |
|---|---|
| `policy/sources/models.py` | 8 `SourceDomain`s, `SourceObjectType` (lead default #1), `CollectionStatus`, `ProvenanceClass`, `SourceRecord` (all AC1 fields), `RegistryChange`. **Reuses Step-1 `Classification` unchanged**; never-external = reused Step-1 `Sensitivity` dimension (lead default #2). |
| `policy/sources/registry.py` | Fail-closed `validate_record` (AC1/AC7); `record_to_evidence_item`; `external_projection_for` → calls **`policy.engine.partner_projection`** (AC4/T3); AC10 `propose`/`apply_registry_change` with human-ratify-on-exposure. |
| `policy/sources/store.py` | Parameterized SQL; `save_source` (validates first); `query_external_visible_sources` (external→projections only, fail-closed T10); change audit. |
| `policy/sources/sourcemap.py` | Markdown source map: internal vs external columns, computed by the live engine. No snippets/summaries (T6). |
| `policy/sources/fixtures.py` | SAMPLE rows: 1 per 8 domains + 3 gap rows. Opaque, non-enumerable `source_id`s (AC9). |
| `migrations/20260621d_ai_hotel_source_registry.sql` | `source_registry` + `source_registry_audit`. Additive/idempotent, CHECK-constrained enums + DB-level AC7 (hidden→reason) + AC8 (gap fields) constraints, no CONCURRENTLY-in-txn. |
| `tests/test_source_inventory.py` | 35 tests; AC1–AC10 + T1–T10 cited below. |

**Layout:** `policy/sources/` subpackage (brief-recommended) — sits beside the engine it feeds; reuses `policy.engine` + `policy.models` directly, zero duplication of allow semantics.

---

## DONE RUBRIC (deputy-codex 6 gate requirements)

1. **AC/T → test citation (1:1):**
   - AC1 → `test_ac1_valid_record_passes_validation`, `_missing_required_field_fails_closed` (param), `_save_validates_before_persist`
   - AC2 → `test_ac2_exactly_eight_domains`, `_fixtures_cover_all_eight_domains`, `_at_least_three_gap_rows`
   - AC3 → `test_ac3_misregistered_partner_safe_still_denied_without_grant`
   - AC4 → `test_ac4_uses_live_policy_engine_spy` (spies `engine.partner_projection`)
   - AC5 → `test_ac5_never_external_hard_deny` (param ×3 externals)
   - AC6 → `test_ac6_projection_has_no_raw_body_title_or_identifiers`
   - AC7 → `test_ac7_hidden_row_without_reason_fails_closed`, `_with_reason_ok`
   - AC8 → `test_ac8_gap_row_requires_owner_reason_next`, `_never_externally_visible`, `_cannot_be_marked_external`
   - AC9 → `test_ac9_external_has_provenance_class_not_raw_refs`, `_source_id_opaque_and_non_enumerable`
   - AC10 → `test_ac10_ai_cannot_make_source_externally_visible`, `_human_can_ratify_external_exposure`, `_propose_does_not_mutate`, `_ai_can_change_internal_metadata`
   - T1 → AC3 test (mis-registration leak) · T2 → `test_ac6_*` (raw-flag confused-deputy) · T3 → `test_t3_removing_engine_call_would_change_result` · T4 → `test_ac5_*` + `test_ac10_ai_cannot_*` · T5 → `test_t5_cross_partner_bleed_blocked` · T6 → `test_t6_no_snippet_or_body_keys_in_projection` · T7 → `test_sourcemap_sample_has_all_domains_and_gaps` · T8 → `test_t8_public_source_still_needs_grant` · T9 → `test_t9_no_identifier_leakage_in_source_map` · T10 → `test_t10_query_external_fails_closed_on_store_error`, `_apply_change_records_audit_via_recorder`
2. **≥1 fixture row per 8 domains + 3 gap rows** — `policy/sources/fixtures.py`; asserted by `test_ac2_*`.
3. **Negative tests:** misclassification (AC3), cross-partner (T5), raw email/WA (AC5 fixture EMAIL_WA_RAW), capital-sensitive financial (AC5), missing required fields (AC1 param). Credentials/NDA covered by the hard-gate exclude list (registered as never-external or kept out as gaps).
4. **Live-policy integration:** `test_ac4_uses_live_policy_engine_spy` proves `external_projection_for` delegates to `engine.partner_projection`; `test_t3_removing_engine_call_would_change_result` proves a forced engine-deny hides the row — there is no independent allow path (T3).
5. **Source-map sample** — internal vs external columns, generated from the same fixtures for an NVIDIA principal (full render below). Gaps explicit (⛔), never-external/cross-partner hidden (🔒), partner-visible rows show claim+confidence+source_count only.
6. **DONE invariant proven:** no source becomes externally visible through registry metadata alone — every external view routes through the Step-1 engine. `test_ac3_*`, `test_t3_*`, `test_t8_*` all confirm registry flags never widen access past the engine.
7. **Migration** additive/idempotent (`IF NOT EXISTS`), runner-safe (no CONCURRENTLY-in-txn). `pytest` green; singleton guard green.

---

## Test evidence (literal)

```
$ python3 -m pytest tests/test_source_inventory.py -q
35 passed, 1 warning in 0.05s

$ python3 -m pytest tests/test_policy_core.py tests/test_source_inventory.py -q
148 passed, 1 warning in 0.10s

$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

---

## Source-map sample (NVIDIA principal — done rubric #5)

The external column is computed by the **live Step-1 policy engine**. Note: NVIDIA
sees only its granted partner-safe row + broadly-granted public rows; the
venue-owner photos resolve to "policy-denied" (NVIDIA not in `allowed_orgs`);
internal/raw/financial rows are hidden with reasons; gaps are explicit.

| Domain | Row | External view (NVIDIA) |
|---|---|---|
| 1 Baker memory | Lab go/no-go decision log | 🔒 hidden — internal Brisen reasoning |
| 2 Vault | NVIDIA lighthouse readiness brief | “…host an NVIDIA lighthouse pilot in Q4.” conf=0.9 sources=2 derived |
| 2 Vault | partner_data_room | ⛔ GAP (origination-desk) |
| 3 Dropbox | Santa Clara site design WIP | 🔒 hidden — internal design WIP |
| 4 Comms | Brisen↔NVIDIA email thread | 🔒 hidden — raw correspondence never external |
| 4 Comms | slack_workspace | ⛔ GAP (AID-T) |
| 5 Field | Venue condition survey photos | 🔒 hidden — policy-denied (venue-owner only) |
| 6 Open web | AI-hospitality market press | “…pilots accelerating in 2026.” conf=0.7 sources=1 public |
| 7 Site public | Santa Clara zoning record | “…zoned for hospitality…” conf=0.6 sources=1 public |
| 8 Market | Construction financing term signal | 🔒 hidden — capital-sensitive never external |
| 8 Market | residence_buyer_crm | ⛔ GAP (sales-desk) |

---

## Vocab notes (lead defaults #3657 — flag per brief)

- Object types built to lead default #1 exactly. No additions needed.
- Classification: reused Step-1's 7-value enum unchanged (single source of truth). `internal_only`/`sensitive_partner` → `brisen_confidential`; never-external modelled as the separate Step-1 `Sensitivity` dimension, not a classification value. Enum-stable — absorbs a later codex-arch refinement cleanly.
- No mid-build vocab ambiguity hit, so no codex-arch consult was needed.

---

## Gate plan status
- G1 self-test → `pytest` + singleton green ✅
- G2 deputy-codex AC + threat-model gate vs #3653 → **requested**
- G3 deputy augmented chain (architect + codex-verifier) → after G2
- G4 lead `/security-review` (Tier-A, partner-leak surface) → merge
- POST_DEPLOY_AC v1 after Render deploy (migration runs clean at startup)

## Pre-existing baseline (not this PR)
- `test_migration_runner.py::test_migration_file_has_up_marker` red on main (13 old migrations lack the marker; mine has it). 4 `mcp`-import collection errors (optional dep absent locally). Both pre-existing, unrelated.
