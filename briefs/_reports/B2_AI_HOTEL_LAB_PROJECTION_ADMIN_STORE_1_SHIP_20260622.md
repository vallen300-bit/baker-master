# B2 Ship Report — AI_HOTEL_LAB_PROJECTION_ADMIN_STORE_1 (Step 5.1)

- **Brief:** AI_HOTEL_LAB_PROJECTION_ADMIN_STORE_1 (Sprint-0 Step 5.1, projection admin control plane)
- **Spec:** codex-arch #3943 (AC1-12 / T1-12) — built to the headlines + 6 core-wiring deltas carried in the brief (could not read #3943 directly: `not_party_to_message`)
- **PR:** https://github.com/vallen300-bit/baker-master/pull/412
- **Branch:** `b2/ai-hotel-projection-admin-store` · commit `a0a6b66c`
- **Dispatched by:** lead · **reply target:** lead (bus)
- **Tier:** B-adjacent — gate-chain mandatory, no merge until G4

## Done rubric

The endpoint revoke/refresh is no longer a 501 stub. It runs against a **persisted, audited** projection-admin store, so partner-live sharing is governable: durable revoke kill switch, freshness control, revoked absent from every partner surface generically, fail-closed on store outage.

## Delta (wiring, not greenfield)

| File | Change |
|---|---|
| `policy/projection/admin_store.py` (new) | Persisted admin overlay keyed by `source_evidence_item_id`. Matter-level decision persisted once under the `brisen_internal` record via deterministic opaque id (idempotent upsert). Reuses Step-4 `store.py`. `load_admin_overlay()` fails closed (raises). Injectable backend for DB-free tests. |
| `outputs/ai_hotel_lab.py` | `_candidates()` overlays persisted state (internal-tolerant); `_external_candidates()` strict/fail-closed. revoke→`admin.revoke_projection`; refresh→`admin.refresh_projection` (never resurrects revoked); approve→409 on revoked. All partner surfaces read the overlay → revoked absent generically; outage→generic empty packet. UI enables Revoke/Refresh. |
| `policy/projection/store.py` | Upsert also refreshes `freshness`/`last_verified_at` (AC9). Additive. |
| `tests/test_ai_hotel_cockpit.py` | 13 Step-5.1 tests + updated AC7/page-marker tests. |

## Migration
**No new migration.** The Step-4 migration `20260622b_ai_hotel_projection.sql` already carries `revoked_at`/`revoked_by`/`revoke_reason`/`projection_state`/`updated_at`/`freshness`/`last_verified_at`. T12 (migration breaks Step-5 cockpit) satisfied trivially — schema unchanged.

## AC / threat mapping (named tests)
- AC1 restart persistence → `test_s51_revoke_survives_process_restart`
- AC3 / T1-T3 revoked absent from packet+evidence+audit, no count/reason/source leak → `test_s51_revoke_persists_and_item_vanishes_from_partner_packet`, `test_s51_revoked_absent_from_every_partner_surface`
- AC5 revoked visible to Brisen audit view → `test_s51_internal_view_shows_revoked_for_audit`
- AC7 / T7 AI + external principals rejected at policy layer → `test_s51_ai_and_external_principals_cannot_admin`
- AC8 / T8 idempotent revoke + approve-blocked-on-revoked → `test_s51_revoke_is_idempotent`, `test_s51_approve_blocked_on_revoked_item`
- AC9 refresh recomputes freshness → `test_s51_refresh_recomputes_freshness_on_live_item`
- T5 / T11 refresh never resurrects revoked → `test_s51_refresh_never_resurrects_revoked`
- T9 audit records actor + reason + transition → `test_s51_audit_records_actor_reason_and_transition`
- T11 fail-closed read + write → `test_s51_external_fails_closed_on_store_outage`, `test_s51_revoke_not_applied_on_store_outage`

## G1 — pytest (literal)
```
tests/test_ai_hotel_cockpit.py ......................................... 60 passed
tests/test_partner_projection.py + test_policy_core.py + test_ai_hotel_cockpit.py  211 passed
```
4 unrelated collection errors (substack / mcp_baker_extension / brisen_lab) are **pre-existing** — confirmed present with this branch stashed (ImportError, not touched by this brief). Singleton CI guard: `OK: No singleton violations found.`

## Note for the gate (scope honesty)
`/api/search` operates on connector `SourceRecord`s, not projection items — a revoked **evidence** item has no search row to surface, so revoke legitimately has no search-result to hide there. Confirmed no leak via the external token scan (`test_s51_revoked_absent_from_every_partner_surface` includes `_external_blob`). There is no separate `/api/export` endpoint; the packet/evidence JSON *is* the export surface and reads the overlay. Flagging in case #3943 intends a distinct export path.

## Gate plan / next
G1 ✅ → G2 deputy-codex (T1-12) → G3 deputy AC → G4 lead `/security-review` → lead merge → Render deploy → b2 `POST_DEPLOY_AC_VERDICT v1` (live revoke+refresh on a seeded non-sensitive item, AC12).
