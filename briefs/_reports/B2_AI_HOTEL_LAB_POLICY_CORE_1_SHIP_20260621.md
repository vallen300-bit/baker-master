# B2 SHIP REPORT — AI_HOTEL_LAB_POLICY_CORE_1

**Brief:** `briefs/_tasks/AI_HOTEL_LAB_POLICY_CORE_1.md` (commit a44c936)
**Dispatched_by:** lead (AH1) · bus #3627
**Branch:** `b2/ai-hotel-policy-core-1` (off origin/main d6cab32)
**Builder:** B2
**Class:** foundational / high-assurance — new-module backend, security-critical invariants + DB migration + comprehensive test gate.

---

## What shipped

New `policy/` package — the single server-side permission + evidence-lifecycle engine. No UI, no partner-view rendering, no search endpoint, no export path (all out of scope per Context Contract). Every future surface must call `policy.engine.evaluate`; none may bypass it.

| File | Role |
|---|---|
| `policy/models.py` | Enums (Org, Action, ObjectType, LifecycleState, 7 Classifications, Sensitivity), constant sets, dataclasses (Principal, EvidenceItem, PolicyDecision, AuditEvent), reason codes. Folds ontology #3625. |
| `policy/engine.py` | `evaluate()` — default-deny, layered gates, fail-closed. `partner_projection()` (AC7), `redact_audit_for_partner()` (AC7/T5). |
| `policy/lifecycle.py` | State machine: `transition()` forward-by-one + admin override; `propose_promotion()` (AI) / `approve_promotion()` (human). |
| `policy/audit.py` | Audit sinks (LoggingAuditSink default, ListAuditSink for tests). Decouples AC9 logging from pure logic. |
| `policy/store.py` | Parameterized-SQL persistence; `query_visible_items()` fail-closed (T10); `DbAuditSink`. |
| `migrations/20260621c_ai_hotel_policy_core.sql` | 4 tables: `policy_evidence_items`, `policy_lifecycle_transitions`, `policy_promotions`, `policy_audit_log`. Additive, idempotent, CHECK-constrained enums, plain indexes (no CONCURRENTLY). |
| `tests/test_policy_core.py` | 107 tests; AC1–AC10 + T1–T10 each cited below. |

**Layout choice:** new top-level `policy/` package (brief allowed an alternative). It is a cross-cutting control plane consumed by future search/projection/export surfaces, so it sits beside `orchestrator/` / `kbl/` rather than inside `models/` (which holds passive data models). Flagged per brief.

---

## DONE RUBRIC (answered)

1. **Roles see exactly their permitted evidence.** `test_ac2_query_visible_items_filters_server_side` builds a Brisen-raw + a shared partner item; the NVIDIA principal sees only the shared one. Cross-partner, raw, unpromoted, and no-confidence items are all filtered server-side. Promotion to partner-safe requires human approval (`test_ac6_*`).
2. **Every AC1–AC10 → passing test:**
   - AC1 → `test_ac1_decision_shape_and_evaluated_inputs`, `test_ac1_actions_cover_required_set`
   - AC2 → `test_ac2_default_deny_external_no_grant`, `test_ac2_query_visible_items_filters_server_side`
   - AC3 → `test_ac3_seven_classifications_recognized` (param × all 7), `test_ac3_exact_seven_classifications`
   - AC4 → `test_ac4_never_external_hard_deny_beats_allow` (param ext×sensitivity×action), `test_ac4_internal_can_still_read_never_external`
   - AC5 → `test_ac5_forward_by_one_allowed`, `_skip_denied`, `_backward_denied_without_override`, `_backward_allowed_with_admin_override`, `_override_requires_admin`, `_transition_records_all_fields`
   - AC6 → `test_ac6_ai_cannot_finalize_promotion_via_transition`, `_non_admin_human_cannot_finalize`, `_human_admin_can_finalize`, `_ai_may_propose_without_state_change`, `_external_cannot_propose`, `_approve_records_proposer_approver_rationale_source`
   - AC7 → `test_ac7_projection_excludes_internal_fields`, `_projection_denied_fails_closed`, `_redact_audit_for_partner_keeps_only_safe_fields`
   - AC8 → `test_ac8_partner_safe_requires_non_null_confidence`, `_raw_signal_may_have_null_confidence_internally`, `_promote_to_shared_view_requires_confidence`
   - AC9 → `test_ac9_every_decision_writes_audit`, `_transition_and_promotion_audited`
   - AC10 → `test_ac10_allow_deny_matrix` (10-case role×classification×action), `_external_search_cannot_return_never_external`, `_export_cannot_include_brisen_confidential`, `_malicious_param_cannot_widen_access`
3. **Every threat T1–T10 → control + test that fails if control removed:**
   - T1 confused-deputy → server-side engine; `test_t1_confused_deputy_engine_is_server_side` + `test_ac10_malicious_param_cannot_widen_access`
   - T2 search leakage → external SEARCH gate; `test_t2_search_leakage_blocked`
   - T3 misclassification → never-external sensitivity beats classification; `test_t3_misclassification_blocked_by_sensitivity`
   - T4 AI over-promotion → human-ratify gate; `test_t4_ai_over_promotion_blocked`
   - T5 audit leakage → `redact_audit_for_partner`; `test_t5_audit_leakage_redacted`
   - T6 cross-partner bleed → matching-org classification gate; `test_t6_cross_partner_bleed_blocked`
   - T7 stale-as-trusted → confidence gate; `test_t7_stale_evidence_blocked_by_confidence`
   - T8 export widening → exportable-only gate; `test_t8_export_widening_blocked`
   - T9 privilege creep → external-action allow-list; `test_t9_privilege_creep_external_blocked` (param 4 actions)
   - T10 fallback-open → fail-closed store + engine guard; `test_t10_fallback_open_store_unavailable_fails_closed`, `test_t10_engine_internal_error_denies`
4. **Migrations additive + idempotent + runner-safe.** All `CREATE TABLE/INDEX IF NOT EXISTS`; no `CREATE INDEX CONCURRENTLY` (the runner wraps each file in a transaction — documented inline mirroring `20260621_alerts_uq_pending_quiet.sql`). Down-SQL commented (runner executes files raw).
5. **`pytest` green; no singleton violation.** `107 passed` on `tests/test_policy_core.py`. `bash scripts/check_singletons.sh` → `OK: No singleton violations found.`
6. **Fail-closed proven.** `test_t10_fallback_open_store_unavailable_fails_closed`: `query_visible_items` with a raising conn factory raises `PolicyUnavailableError` and returns **no** payload. `test_t10_engine_internal_error_denies`: an internal exception in the decision pipeline returns `allow=False`, never an allow. No broad `except` returns unfiltered objects.

---

## Test evidence (literal)

```
$ python3 -m pytest tests/test_policy_core.py -q
107 passed, 1 warning in 0.06s
```

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

Syntax: all 6 `policy/*.py` files `py_compile` clean; `import policy` clean.

---

## Pre-existing baseline note (NOT introduced by this PR)

- `tests/test_migration_runner.py::test_migration_file_has_up_marker` is RED on origin/main — 13 pre-existing migrations (20260505…–20260607…) lack the `-- == migrate:up ==` marker. My new migration `20260621c_ai_hotel_policy_core.sql` HAS the marker and is **not** in the failure list. Surfacing as existing tech debt; out of scope for this brief.
- 4 collection errors (`test_baker_substack_search.py`, `test_brisen_lab_consumer_mcp.py`, `test_brisen_lab_gate4_fixes_2026_05_05.py`, `test_mcp_baker_extension_1.py`) — all `ModuleNotFoundError: No module named 'mcp'` (optional dep absent locally). Pre-existing, unrelated.

---

## G2 REQUEST_CHANGES round 1 — deputy-codex (bus #3633) — ADDRESSED

deputy-codex returned REQUEST_CHANGES with 2 blockers + 1 coverage note. All fixed in the follow-up commit:

- **F1 (AC7/T1/T2 leak):** `query_visible_items(project=False)` returned the full `EvidenceItem` (with `raw_body`/`title`) to external callers. Fix: `query_visible_items` now FORCES partner projection for any `principal.is_external` regardless of the `project` flag — an external caller can never receive a raw item. Regression: `test_f1_external_query_never_returns_raw_item_default_path` (+ `test_f1_internal_default_path_returns_full_item` proves internal behaviour unchanged). Probe on fixed head: NVIDIA default read → `dict`, no `raw_body`/`title`/`source_refs`.
- **F2 (AC8 gap):** projection lacked a source count. Fix: `partner_projection` now emits `source_count` (count only — raw `source_refs` may embed internal ids and must not leak). Regression: `test_f2_projection_carries_source_count`.
- **AC6 coverage note:** `save_item` could persist a `shared_view`/`action_linked` item directly, bypassing the human-ratify gate. Fix: `save_item` raises `PromotionBypassError` for partner-visible states unless `via_lifecycle=True` (the post-promotion persistence step). Regressions: `test_ac6_save_item_cannot_bypass_promotion_gate`, `_via_lifecycle_allows_partner_visible`, `_internal_state_allowed_by_default`.

Re-run: `113 passed` (was 107; +6). Singleton guard green.

## Gate plan status

- G1 self-test → `pytest` + singleton guard green ✅
- G2 deputy-codex AC + threat-model gate vs #3621 → round 1 REQUEST_CHANGES **addressed**; re-review requested
- G3 deputy augmented chain (architect + codex-verifier) → after G2
- G4 lead `/security-review` (Tier-A) → merge
- POST_DEPLOY_AC v1 after Render deploy (migration runs clean at startup) → after merge

## Notes / escalations

- No real SSO wired (Sprint-0 simulates principals with test users) per brief.
- `last_reviewed` / `freshness` stored as TEXT to round-trip the freeform model values without timestamp-parse friction; revisit if a later step needs range queries.
- Ontology vocabulary followed exactly as reproduced in the brief (#3625). No field-name ambiguity hit, so no codex-arch consult was needed.
