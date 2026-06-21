# BRIEF — AI_HOTEL_LAB_POLICY_CORE_1

**Sprint:** AI Hotel Lab — Sprint-0, Build Step 1 of 5 (policy/evidence core).
**Dispatched_by:** lead (AH1). **Gate owner:** deputy-codex (AC + threat-model), deputy (augmented chain), lead (merge).
**Source of truth:** codex-arch scoping brief (bus #3545) + deputy-codex Step-1 rubric (bus #3621).
**Harness-V2:** in scope — Context Contract + task class + done rubric + gate plan below.

---

## CONTEXT CONTRACT

**What this is.** The foundational permission + evidence-lifecycle engine for the AI Hotel Lab — a
permissioned cooperation cockpit for Brisen + NVIDIA + Mandarin Oriental (MOHG) + the Santa Clara venue
owner. This is **backend policy core only**. NO UI, NO partner view rendering, NO search endpoint, NO
export path in this step — but every one of those future surfaces MUST call this engine and none may
bypass it.

**Why now / why first.** codex-arch + deputy-codex ratified: lock the permission/evidence model BEFORE
any UI is treated as real. UI-before-policy is a mock only. The risk being defended against: builders
implement dashboard-first because dashboard requirements are concrete and the policy model is abstract.
This brief makes the policy model concrete so it gets built first.

**First-dashboard primitive (codex-arch #3618):** EVIDENCE CONFIDENCE — "which claims are verified
enough to show which partner now." Every visible evidence object must carry confidence + source_refs +
freshness + owner + last_reviewed.

**Ownership invariant:** Brisen owns the evidence core, ontology, promotion rules, citations, and the
partner-safe object model. Vendors may later host backbone/projection/UI but never own this engine.

**Where it lives.** baker-master repo. New module — recommend `policy/` package:
`policy/engine.py` (decision function), `policy/models.py` (object model), `policy/lifecycle.py`
(state machine), plus migrations under `migrations/`. Builder may propose an alternative layout if it
better fits existing patterns (e.g. `orchestrator/` or `models/`) — flag the choice in the ship report.
Stack unchanged: Python 3.11+, FastAPI, PostgreSQL (Neon), parameterized SQL only.

**Out of scope (do NOT build):** UI, partner dashboards, search endpoints, export/PDF/data-room,
SSO/identity provider (Sprint-0 simulates principals with test users), Bodhi/BMS/PMS/digital-twin,
real partner data ingestion. These are later steps or later sprints.

---

## TASK CLASS

New-module backend build with security-critical invariants + DB migrations + comprehensive test gate.
Class: **foundational / high-assurance** (this is the highest-value safety surface in the Lab — a leak
here exposes Brisen strategy to external partners). Treat default-deny + fail-closed as load-bearing.

---

## ACCEPTANCE CRITERIA

**Authoritative AC + threat-model rubric = deputy-codex bus #3621 — reproduced as the binding spec.**
Build to AC1–AC10 and defend against T1–T10 exactly as written there. Summary (full text in #3621):

- **AC1** Object-level policy primitive: principal_org, role, object_type, object_id, action,
  lifecycle_state, classification, allowed_view. Actions ≥ {read, search, export, promote, demote,
  annotate, assign_action, view_audit}. Decision returns allow/deny + reason_code + evaluated inputs.
- **AC2** Default-deny external, enforced **server-side before response construction**. Search / read /
  digest / audit / export / partner projection all call the **same** policy function. UI/client filters
  are NOT accepted as the control.
- **AC3** Classifications first-class + test-covered: Brisen-raw, Brisen-confidential, partner-safe-NVIDIA,
  partner-safe-MOHG, public-source, exportable.
- **AC4** Never-external classes are HARD-DENY (beats any allow): email/WA raw, strategy notes,
  vendor-negotiation, financial, legal. Tests prove NVIDIA/MOHG/venue-owner cannot read/search/export them.
- **AC5** Evidence lifecycle state machine: raw_signal → research_artifact → verified_evidence →
  shared_view → action. Invalid back/skip transitions denied unless explicit admin override records reason.
  Each transition records actor, timestamp, source_refs, confidence, freshness/last_reviewed, prior/new state.
- **AC6** Human ratifies partner-safe promotion. AI may propose, cannot finalize. Audit row: proposer,
  approver, approval_timestamp, rationale, source evidence.
- **AC7** Partner-safe projection is a DERIVED view, not raw-table exposure. No raw body/snippet/title/
  audit-note leakage via metadata. Partner audit is redacted (claim, source_type, freshness, confidence,
  owner only).
- **AC8** Evidence confidence is the first-dashboard primitive (see Context Contract). partner-safe states
  require non-null confidence; only raw_signal may have empty/unknown confidence.
- **AC9** Logging + fail-loud: every deny/promotion/export/projection writes audit or structured log.
  Policy-engine failures fail **closed**. No broad `except` returns unfiltered objects.
- **AC10** Test gate: allow/deny matrix by role×classification×action; state-machine valid/invalid;
  regression (external search can't return never-external; export can't include Brisen-raw/confidential;
  no partner-safe promote without human approval); negative test — malicious client category/view param
  cannot widen access.

**Threats to defend (full text #3621):** T1 confused-deputy/UI-bypass · T2 search leakage · T3
misclassification leakage · T4 AI over-promotion · T5 audit leakage · T6 cross-partner bleed (NVIDIA≠MOHG)
· T7 stale-evidence-as-trusted · T8 export widening · T9 privilege creep · T10 fallback-open failure.

---

## DONE RUBRIC (answer these in the ship report — not "tests pass")

1. A builder can create representative Brisen / NVIDIA / MOHG / venue-owner objects and prove via tests
   that **each role sees exactly the permitted evidence-confidence objects** — no raw/private leakage,
   no partner-safe promotion without human approval. (deputy-codex DoD, #3621.)
2. Every AC1–AC10 mapped to a passing test (cite test name per AC).
3. Every threat T1–T10 mapped to a control + a test that would fail if the control were removed.
4. Migrations are additive, idempotent (`IF NOT EXISTS`), and runner-safe (no `CREATE INDEX CONCURRENTLY`
   inside the per-file transaction — see migrations/20260621_alerts_uq_pending_quiet.sql note).
5. `pytest` green; cite count. No singleton-pattern violation (`bash scripts/check_singletons.sh`).
6. Fail-closed proven: a test that simulates policy DB/config missing returns a visible error with **no
   object payload** (T10).

---

## GATE PLAN

1. Builder self-test → `pytest` + singleton guard green.
2. **deputy-codex** runs the AC + threat-model gate against #3621 (its owned scope).
3. **deputy** runs the augmented chain (architect + codex-verifier cross-vendor) on the PR.
4. **lead** runs /security-review (Tier-A, mandatory — this is the highest-value safety surface) → merge.
5. POST_DEPLOY_AC v1 after Render deploy (migrations run clean at startup).

---

## ONTOLOGY AMENDMENTS (codex-arch #3625 — BINDING, fold into schema + tests)

1. **Naming:** schema enums in `snake_case` (partner-facing UI labels come later). Use **`evidence_item`**,
   not "evidence object".
2. **Lifecycle terminal state:** `raw_signal → research_artifact → verified_evidence → shared_view →
   action_linked` (NOT "action"). Keep `action` as an **object_type**; evidence does not literally become
   an action — it links to one.
3. **Classifications (7):** `brisen_raw`, `brisen_confidential`, `partner_safe_nvidia`, `partner_safe_mohg`,
   **`partner_safe_venue_owner`** (ADDED — venue-owner is a confirmed external role), `public_source`,
   `exportable`. AC3/AC4 tests must cover all 7.
4. **Classification ≠ grant:** classification alone never grants access — `allowed_view` / `allowed_org`
   gates still decide. (Defends T3/T6: a partner_safe_* tag is necessary, not sufficient.)
5. **Roles / orgs:** external — `nvidia/ai_hospitality_lighthouse_lead`, `mohg/ops_standards_lead`,
   `venue_owner/site_diligence_lead`. Seed Brisen as **org=`brisen`** with roles `director`,
   `internal_team`, `evidence_admin`. Do NOT create a separate Brisen-Director org.
6. **Object types (add `claim`):** `claim`, `project`, `site`, `partner`, `signal`, `evidence`, `decision`,
   `action`, `risk`, `document`, `source`. Rationale: the first dashboard asks *which claims are verified
   enough to show* — evidence supports claims, so `claim` is the unit confidence attaches to for partner view.

## NOTES FOR BUILDER

- Parameterized SQL ONLY. All DB/API calls wrapped try/except — but `except` must fail **closed**, never
  return unfiltered objects (AC9/T10).
- This step has no UI. If you find yourself building a template/endpoint that renders objects to a user,
  STOP — that's Step 4/5, out of scope.
- Sprint-0 simulates principals with test users; do not wire real SSO.
- codex-arch owns ontology vocabulary — if a field name or object_type is ambiguous, bus codex-arch, don't
  guess the partner-facing vocabulary.
- Branch from latest main. Self-contained brief; you have independent context.
