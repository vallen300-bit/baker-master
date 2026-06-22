---
status: PENDING
brief_id: AI_HOTEL_LAB_PROJECTION_ADMIN_STORE_1
to: b4
from: lead
dispatched_by: lead
dispatched_at: 2026-06-22
reply_target: lead (bus)
task_class: backend control-plane + UI wiring (baker-master: outputs/ai_hotel_lab.py + policy/projection/* + migration + tests)
arc: AI Hotel Lab Sprint-0 — Step 5.1 (follow-on to Step 5 cockpit, PR #408/#410)
gate_plan: G1 pytest -> G2 deputy-codex security/threat gate (T1-T12) -> G3 deputy AC -> G4 lead /security-review -> merge -> Render deploy -> POST_DEPLOY_AC_VERDICT
harness_v2: applies
product_framing: codex-arch bus #3943 (full SCQA + AC1-12 + T1-12 + DONE def — authoritative spec)
tier: B-adjacent (partner-live governance) — gate-chain mandatory, no merge until G4
---

# AI_HOTEL_LAB_PROJECTION_ADMIN_STORE_1 — Step 5.1: Projection Admin Control Plane

## Problem
Step 5 cockpit shipped (PR #408/#410) with APPROVE live but REVOKE/REFRESH **honestly disabled** —
`outputs/ai_hotel_lab.py:589-597` raises `501 "Step 5.1 pending persisted projection-admin store"`
and operates on the in-memory `_seed_candidates()`. Without a persisted, audited admin store there is
no real kill switch or freshness control, so partner-live sharing is unsafe. Step 5.1 makes sharing
**governable**: persisted revoke, persisted refresh, immutable audit, stale/revoked handling, and
export/view consistency.

## Authoritative spec
codex-arch bus **#3943** is the product spec — SCQA, ADMIN ACTIONS, SOURCE-OF-TRUTH / PERMISSION /
REVOKE / REFRESH / AUDIT / UI requirements, API shape, **AC1-AC12**, **threat cases T1-T12**, DONE
definition. Build to it verbatim. This brief adds repo anchors + gate plan only; do not re-derive scope.

## Good news — scaffolding exists (this is WIRING, not greenfield)
- `policy/projection/store.py` — `save_projection_item`, `record_projection_audit`, `record_redaction`,
  `save_snapshot`, `load_projection_items` (persistence layer, Step 4, fails-closed on error).
- `policy/projection/admin.py` — `approve_projection`, `revoke_projection`, `refresh_projection`,
  `_require_human_admin` (admin logic + AC7 human-only enforcement) already present.
- `migrations/20260622b_ai_hotel_projection.sql` — projection store schema (extend additively if
  revoke/refresh-state columns are missing; **never edit applied migrations** — new file).
- `outputs/ai_hotel_lab.py:578` `post_admin_action` — the endpoint to convert from 501-stub to live.
- `tests/test_ai_hotel_cockpit.py` — Step-5 test bed to extend.

## Core wiring (the delta)
1. `post_admin_action` revoke/refresh: stop raising 501; route through `admin.revoke_projection` /
   `admin.refresh_projection` against the **persisted** store (`load_projection_items` /
   `save_projection_item` / `record_projection_audit`), not `_seed_candidates()`.
2. Make `_candidates()` + `/api/packet` + `/api/search` + `/api/evidence` + any export read the
   **persisted admin state** so a revoked item is absent from every partner surface (DOM, network,
   search, export) generically — no hidden count/reason/source (AC3, AC4, T1-T3, T10).
3. Revoke: durable, idempotent, audit-logged (actor/role/scope/reason/ts), defeats stale cache
   (block/stale if uninvalidatable), applies to post-revoke exports (AC1, AC5, AC8, T4, T8).
4. Refresh: recompute from current policy/evidence; never resurrect revoked unless a separate
   Brisen-human un-revoke exists (out of scope → revoked is a hard stop); record status enum;
   failure preserves last safe packet / generic unavailable, never raw fallback (AC2, T5, T11).
5. UI: enable REVOKE/REFRESH only when backend live; server is source of final state; revoked shows
   in Brisen audit view, vanishes generically from partner views; freshness label updates (AC9, T6).
6. Migration additive + reuses Step-4 model (AC10, T12). All DB calls try/except + `conn.rollback()`
   in except (repo python-backend rule).

## Acceptance criteria — AC1-AC12 per #3943 (verbatim, do not relax)
Headlines: AC1 revoke persists across restart · AC3 revoked absent from NVIDIA/MOHG/Venue packets+DOM+
network+search+export · AC6 direct-API cannot bypass perm · AC7 AI/external cannot execute admin ·
AC11 unit+endpoint+browser no-leak probes all 4 roles · AC12 post-deploy live revoke+refresh on
**seeded non-sensitive test item only**, no prod partner-data mutation without safe-candidate auth.

## Threat cases for the gate — T1-T12 per #3943
T1 revoked visible in partner packet · T2 via search/export/detail · T3 reason/count leak · T4 stale
resurrect · T5 refresh bypasses policy · T6 UI shadow-permission · T7 AI/external executes admin ·
T8 concurrent approve/revoke unsafe · T9 audit omits actor/reason/transition · T10 export from raw ·
T11 failed refresh → raw fallback · T12 migration breaks Step-5 cockpit.

## Verify (Lesson #8 — compile-clean ≠ done)
- `python3 -c "import py_compile; py_compile.compile('outputs/ai_hotel_lab.py', doraise=True)"`
- `pytest tests/test_ai_hotel_cockpit.py -v` (extend with revoke/refresh persistence + no-leak)
- Live exercise: seed item → revoke → confirm gone from all 4 role packets + search + export +
  after process restart; refresh → confirm recompute + freshness update + revoked stays dead.

## Gate plan
G1 pytest green → G2 **deputy-codex** security/threat gate against T1-T12 → G3 **deputy** AC sweep →
G4 **lead** `/security-review` (Tier-A discipline, Lesson #52) → lead merge → Render auto-deploy →
b4 `POST_DEPLOY_AC_VERDICT v1` to bus (live revoke+refresh on seeded item, AC12).

## Reporting
Heartbeat on substrate-lock + on each gate transition (bus, topic `ship|gate-rework|post-deploy-ac/
ai-hotel-lab-projection-admin-store-1`). Ship report → `briefs/_reports/`. Reply target: lead (bus).
