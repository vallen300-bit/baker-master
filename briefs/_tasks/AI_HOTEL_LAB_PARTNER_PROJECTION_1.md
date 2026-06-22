# BRIEF — AI_HOTEL_LAB_PARTNER_PROJECTION_1

**Sprint:** AI Hotel Lab — Sprint-0, Build Step 4 of 5 (partner-safe projection surface).
**Dispatched_by:** lead (AH1). **Gate owner:** deputy-codex (AC + threat-model), deputy (augmented chain), lead (security-review + merge).
**Source of truth:** codex-arch product framing (bus #3733, Director-confirmed GO) + deputy-codex Step-4 security rubric (bus #3738 — both binding).
**Builds on:** Step 1 LIVE policy engine `policy/` (66411ba) + Step 2 LIVE source registry `policy/sources/` (9f83b31) + Step 3 LIVE search/routing `policy/search/` (35e9c0f). This step CONSUMES all three; it must NOT add a second permission engine or join raw tables directly.
**Harness-V2:** in scope — Context Contract + task class + done rubric + gate plan below.

---

## CONTEXT CONTRACT

**What this is.** The AI Hotel Lab **partner-safe projection surface**: a backend / API / view-model layer
that turns `verified_evidence` + `action_linked` items into role-specific, redacted, partner-safe **view
packets** for NVIDIA (AI-hospitality lighthouse), MOHG (ops/brand standards), and the venue owner (site
diligence) — plus a Brisen-internal preview role and an evidence-admin role. It is the safety gate between
internal intelligence and partner-facing cooperation: it defines what each external audience can actually
see, with confidence + provenance, **without ever touching raw Brisen sources**.

**What this is NOT.** NOT the final UI — Step 5 consumes these packets (this step is the backend contract).
NOT a second permission engine — external visibility is decided ONLY by the Step-1 policy engine. NOT
filters over raw tables — projection is **derived + redacted**, built through policy projection helpers.
NOT a static export/data-room — the Sprint-0 direction is a live gated view (export deferred). NOT real
external users — Sprint-0 uses simulated/test principals.

**Default principle (codex-arch #3733).** External audiences see only promoted/verified or action-linked
items the Step-1 engine permits for that audience; projection is derived + redacted; **classification
alone is never a grant**. `raw_signal` + `research_artifact` do NOT project externally (only as safe
status/gap metadata if at all).

**Where it lives.** baker-master repo. Recommend a `policy/projection/` subpackage (sibling to
`policy/search/`) + a migration for the projection tables. Stack unchanged: Python 3.11+, FastAPI,
PostgreSQL, parameterized SQL only.

---

## SUBSTRATE TO REUSE (do not reimplement)

- `policy.engine.evaluate(principal, item, action)` + `policy.engine.partner_projection(...)` — the ONLY
  external-visibility control AND the ONLY path that builds an external-safe body. Every projection_item's
  display fields come from `partner_projection`, never from raw source text (carries T3 from Steps 1-3).
- `policy.lifecycle` — only `verified_evidence`, `shared_view`, `action_linked` are projection-eligible
  states. Entering `shared_view` stays human-ratified via the existing `propose_promotion` /
  `approve_promotion` gate — do NOT add a new promotion path.
- `policy.sources.registry` — source metadata + safe source labels (never raw paths/ids externally).
- `policy.search` (Step 3) — raw_signal / research_artifact live here; they are NOT projectable externally.
- Canonical taxonomy: Step-1 `Classification` + `Org` (brisen/nvidia/mohg/venue_owner). Do NOT fork.
  `never_external` stays the hard-deny flag.

---

## AUDIENCE MODEL (codex-arch #3733 — exactly these `audience_role` values)

`brisen_internal` (full preview + raw where Step-1 policy allows; **view-as-partner mode required**) ·
`nvidia_lighthouse` · `mohg_ops_standards` · `venue_owner_site_diligence` · plus an **evidence-admin**
capability (approve / revoke / refresh projection, view-as-partner, inspect policy decision, export
internal audit). External audiences are partner-safe-projection ONLY.

**Audience-specific show/hide (codex-arch #3733):** each external role sees only its own thesis-relevant
verified items + approved asks; each HIDES the other partners' confidential thinking, financing strategy,
raw Brisen strategy, private email/WA, vendor negotiations. NVIDIA↔MOHG↔venue-owner are mutually isolated.

---

## DATA MODEL (codex-arch #3733)

**Objects:** `projection_view`, `projection_item`, `projection_audit_log`, `projection_redaction`,
`projection_snapshot`/`view_packet`.

**`projection_item` minimum fields (all 19, codex-arch #3733):** `projection_item_id`, `audience_role`,
`source_evidence_item_id`, `lifecycle_state` (verified_evidence|shared_view|action_linked), `route_target`/
`dashboard_section`, `display_title`, `display_summary`, `evidence_confidence`, `confidence_reason`,
`source_label_safe`, `citation_or_provenance_safe`, `freshness`/`last_verified_at`, `owner`/`reviewer`,
`visibility_reason`, `redaction_applied` (bool), `redaction_reason`, `action_linked_id`, `revoked_at`/
`revoked_by`/`revoke_reason`, `audit_trace_id`. **All external display fields are projection-derived;
never raw.**

**Projection states (codex-arch #3733):** `not_projectable`, `projectable_candidate`,
`projected_shared_view`, `action_linked_visible`, `revoked`, `stale_projection`, `blocked_by_policy`,
`blocked_by_missing_confirmation`.

**Projection flow (codex-arch #3733):** raw_signal (Step 3) → human/research confirms → `verified_evidence`
→ evidence-admin selects audience(s) (or accepts AI suggestion) → **Step-1 policy evaluates audience +
classification + allowed_view + allowed_org** → projection builder creates safe title/summary/label/
citation + redacts → evidence-admin approves → item enters that audience's view packet → any later
revoke/stale/update is audited.

---

## VIEW PACKETS (Step-5 consumes; codex-arch #3733)

Expose backend/API responses (route names illustrative — adapt to repo style): internal, nvidia, mohg,
venue-owner, `view-as/{role}`, `{item}/audit`. **`view-as/{role}` MUST return byte-identical content to
the real external role's packet** (test case 10). Each packet includes: audience label, allowed sections,
projection_items grouped by `route_target`, evidence-confidence summary, stale/blocked/gap counts,
action-linked items, `last_generated_at`, `policy_version`/`projection_version`, and **explicit empty
states with reason** (never blank → `blocked_by_missing_confirmation` / `blocked_by_policy` / stale).

---

## ACCEPTANCE CRITERIA

**Authoritative AC + threat rubric = deputy-codex bus #3738 (security) + codex-arch #3733 7 ACs
(product) — both binding.** codex-arch ACs (build to all 7):

1. Backend returns role-specific partner-safe packets for NVIDIA, MOHG, venue-owner test users.
2. Projection responses are DERIVED — no raw internal text leaks.
3. Each item includes evidence_confidence, visibility_reason, redaction_reason (if applied), safe provenance.
4. Brisen internal can preview each partner view (`view-as/{role}`).
5. Evidence admin can approve / revoke / refresh projection, each audited.
6. Step-5 UI can render from Step-4 packets without re-implementing policy.
7. Security tests cover cross-role leakage, raw-source leakage, never-external leakage, stale/revoked
   projection, and direct-API bypass.

**Governance invariants (codex-arch #3733):** AI may propose a partner-safe summary, but human approval is
required before external `shared_view`; every projection cites its verified evidence item + policy
decision; a projection cannot outlive revoked/stale underlying evidence (must mark stale/blocked);
never-external hard-deny survives mis-registration; external direct API calls fail closed. deputy-codex
#3738 threats are binding on top. The 10 codex-arch test/threat cases (cross-role, direct source_id,
raw_signal-no-project, never_external-block, misclassified-email, revoke, stale, view-as parity) are all
mandatory test coverage.

---

## DONE RUBRIC (answer in the ship report — not "tests pass")

1. Citation table mapping codex-arch AC1–AC7 + the 10 threat cases + deputy-codex #3738 AC1-12 + T1-12 to named tests (1:1).
2. **Derived-only test:** every external projection_item display field is proven to come from
   `partner_projection`, NOT raw source text (spy/mock; removing the projection call fails the test).
3. **Cross-role isolation test:** NVIDIA principal cannot retrieve any MOHG/venue item (absent, not just
   hidden); same for each pair — across packet, counts, facets, and `{item}/audit`.
4. **Direct-API bypass test:** external principal hitting any projection endpoint with crafted
   role/item_id/source_id cannot retrieve raw fields or another audience's items; fails closed.
5. **No-second-engine test (T3):** every external-visible projection_item routes through
   `policy.engine.evaluate` + `partner_projection`; removing the engine call fails tests.
6. **raw_signal/research_artifact no-project test:** neither projects externally (only safe status/gap).
7. **never_external block test:** a verified item flagged never_external → `blocked_by_policy`, no external payload.
8. **Revoke + stale test:** revoked projection gone from external view but audit retained; stale underlying
   evidence marks the projection `stale_projection` and routes internally to Execution Roadmap.
9. **view-as parity test:** `view-as/{role}` byte-identical to the real external role's packet.
10. **Empty-state test:** no blank — missing/blocked yields `blocked_by_missing_confirmation` /
    `blocked_by_policy` with reason.
11. **Field-allowlist test (deputy-codex AC4):** external packets carry ONLY allowlisted fields (opaque
    id, safe title/summary, safe source label, evidence/action status, safe state, partner-safe action
    text); assert raw ids/source_ids/provenance refs/file paths/participant lists/raw titles/internal
    notes/denial reasons/raw task URLs are absent.
12. **Action-link no-leak + non-mutating test (deputy-codex T8/AC9):** external action_linked packets
    expose NO internal ClickUp/GitHub/Dropbox/admin URLs — safe action text only; viewing/listing a packet
    mutates nothing (routing/registry/policy/lifecycle/evidence unchanged).
13. **Serializer-boundary test (deputy-codex T9/AC10):** internal-preview + evidence-admin serializers are
    SEPARATE from the external serializer; prove internal denial reasons/audit/source refs/raw fields/
    hidden counts cannot appear in any external response.
14. **Simulated-user spoof test (deputy-codex T10):** a test user tampering with org/role headers or query
    params to impersonate another partner or Brisen is denied by the server-side principal fixture.
15. **Cache/staleness revalidation test (deputy-codex T11):** a cached projection after a policy/source/
    lifecycle change is revalidated/invalidated at response time — no stale external payload survives.
16. Migrations additive + idempotent (`IF NOT EXISTS`), runner-safe (no `CREATE INDEX CONCURRENTLY` in the
    per-file transaction). `pytest` green (cite count) + `bash scripts/check_singletons.sh` green; Steps 1-3
    test suites still green (no regression).
17. **DONE means:** no external audience can see another audience's items or any raw internal field;
    projection exists only through the Step-1 engine + human-approved lifecycle; revoke/stale are honored.

---

## GATE PLAN

1. Builder self-test → `pytest` + singleton guard green; Steps 1-3 suites green.
2. **deputy-codex** AC + threat-model gate vs #3738 (its owned scope) — REQUEST_CHANGES blocks merge until fixed + re-gated.
3. **deputy** augmented chain (architect + codex-verifier cross-vendor).
4. **lead** /security-review (Tier-A — partner-leak surface, the highest of the sprint) → merge.
5. POST_DEPLOY_AC v1 after Render deploy (migration runs clean at startup).

---

## NOTES FOR BUILDER

- Parameterized SQL ONLY. Every DB/API in try/except — `except` fails **closed**, never returns raw rows
  or another audience's items or default-public.
- **Backend only** (Step 5 owns UI). A minimal internal/debug surface is OK, labelled as such.
- Reuse `policy.engine` + `partner_projection` + `policy.lifecycle` + `policy.sources` + `policy.search`
  for ALL visibility, body-building, promotion, and source metadata — do NOT add a second engine or join
  raw tables in an external response.
- `raw_signal` + `research_artifact` (Step 3) NEVER project externally.
- Ontology / partner-facing vocab ambiguous? Bus codex-arch — don't guess.
- Branch from latest main (must include 66411ba + 9f83b31 + 35e9c0f). Self-contained brief.
