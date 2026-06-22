# BRIEF — AI_HOTEL_LAB_SEARCH_ROUTING_1

**Sprint:** AI Hotel Lab — Sprint-0, Build Step 3 of 5 (search / routing — controlled intelligence intake).
**Dispatched_by:** lead (AH1). **Gate owner:** deputy-codex (AC + threat-model), deputy (augmented chain), lead (security-review + merge).
**Source of truth:** codex-arch product framing (bus #3679, Director-confirmed GO) + deputy-codex Step-3 security rubric (bus #<RUBRIC_ID> — both binding).
**Builds on:** Step 1 LIVE policy engine `policy/` (66411ba) + Step 2 LIVE source registry `policy/sources/` (9f83b31). This step CONSUMES both; it must NOT duplicate the allow path or fork the source registry.
**Harness-V2:** in scope — Context Contract + task class + done rubric + gate plan below.

---

## CONTEXT CONTRACT

**What this is.** The AI Hotel Lab **search + routing layer**: a controlled intelligence-intake
system. It (1) searches across the Step-2 registered sources, (2) returns results gated through the
Step-1 policy engine, (3) proposes a routing target (which dashboard section a result belongs to),
(4) captures useful unconfirmed material as an **amber raw signal** (never trusted evidence), and (5)
prepares promotion to verified evidence through an audited human-confirmation path. Information enters,
gets routed to the right section, stays amber until confirmed, and becomes partner-safe only through
policy projection.

**What this is NOT.** NOT the final dashboard UI — Step 5 owns the interface (a minimal internal/debug
test surface is allowed, labelled as such, not final UI). NOT a general Baker search replacement. NOT
a new permission system — external visibility is decided ONLY by the Step-1 policy engine. NOT
auto-promotion — raw search results cannot skip to `shared_view`. NOT an LLM-as-source-of-truth —
routing is deterministic-rules-first, LLM-assisted second, human-overridable always.

**Default principle (codex-arch #3679).** Internal Brisen search may be broad; external search returns
ONLY projected/approved material built through the policy projection path — never raw source text. The
engine is the single control point; search is a consumer of it (T3 carries forward from Steps 1+2).

**Where it lives.** baker-master repo. Recommend a `policy/search/` subpackage (sibling to
`policy/sources/`) + a migration for the search/routing tables. Stack unchanged: Python 3.11+, FastAPI,
PostgreSQL, parameterized SQL only.

---

## SUBSTRATE TO REUSE (do not reimplement)

- `policy.engine.evaluate(principal, item, action)` + `policy.engine.partner_projection(...)` — the ONLY
  external-visibility control. `Action.SEARCH` already exists in the enum — use it. Every external result
  body is built via `partner_projection`, never from raw source text (T-leak).
- `policy.lifecycle` state machine: `raw_signal → research_artifact → verified_evidence → shared_view →
  action_linked`. Search produces/attaches **raw_signal** only. Promotion to `shared_view` stays
  human-ratified via the existing `propose_promotion` / `approve_promotion` gate — do NOT add a new path.
- `policy.sources.registry` / `store` / `sourcemap` — read source metadata (domain, classification,
  `raw_body_available_internal`, `external_projection_available`, lifecycle, freshness). Do NOT fork the
  registry; search reads it, never duplicates it.
- Canonical taxonomy: the Step-1 7-value `Classification` enum + `Org` (brisen/nvidia/mohg/venue_owner).
  Do NOT fork the taxonomy unless AH1 explicitly briefs a later split (codex-arch open note 1).
  Keep `never_external` as the existing hard-deny flag (open note 2).

---

## SEARCH MODES (codex-arch #3679)

1. **Internal global search** — all AI-Hotel registered sources permitted to the Brisen role; raw
   pointers + internal snippets ONLY when policy allows. Each result shows classification, lifecycle
   state, source domain, freshness, confidence, route suggestion.
2. **Partner-safe search** — only projected/shared/approved material for the current external role
   (NVIDIA / MOHG / venue_owner). NEVER raw bodies from email/WA/Slack/private docs. **Result body MUST be
   generated from the projection/redaction path, not from raw source text.**
3. **Source-domain search** — filter by the Step-2 domains (field evidence, Santa Clara/site, web/press,
   Baker/vault, email/WA, competitor, financing, residence, PR, vendor).
4. **Section search** — search within a routing target / audience view (exact section matches drive Step-5
   navigation later).
5. **Web/live-source hook** — DEFINE the hook only; any future web result enters `raw_signal` first.
   Do not build live web crawling in Step 3.

---

## ROUTING (codex-arch #3679)

**Stable `route_target` enum (13 values, exact):** `executive_summary`, `field_evidence`,
`santa_clara_site_thesis`, `nvidia_lighthouse`, `mandarin_oriental_operator_logic`,
`market_proof_competitive_set`, `business_case_financing`, `residence_buyers`, `marketing_pr`,
`vendors_future_operating_layer`, `execution_roadmap`, `source_gap_unassigned_review`,
`risk_permissions_review`.

**Routing rules — deterministic first (codex-arch #3679, implement all 11):**
1. parcel/permit/zoning/GIS/assessor/site-ownership/access/traffic → `santa_clara_site_thesis`
2. field photo/GPS/video/voice note → `field_evidence` (+ secondary `santa_clara_site_thesis` if site-relevant)
3. competitor/comparable/local hotel/AI-hospitality benchmark → `market_proof_competitive_set`
4. NVIDIA article/GPU/AI-infra/lighthouse/partner signal → `nvidia_lighthouse`
5. MOHG/operator/brand/guest-experience/service-standard → `mandarin_oriental_operator_logic`
6. bank/debt/financing/cap-stack/investor-economics → `business_case_financing`
7. branded residence/buyer demand/luxury-residential comps → `residence_buyers`
8. press/narrative/public-perception/campaign/media → `marketing_pr`
9. vendor/BMS/PMS/locks/HVAC/digital-twin → `vendors_future_operating_layer`
10. missing data/zero results/unresolved empty state/blocked next action → `execution_roadmap`
11. unclear/conflicting/sensitive/permission-risk → `risk_permissions_review` or `source_gap_unassigned_review`

LLM routing is **assist-only** after deterministic rules; it proposes a target + `route_reason`, never
finalizes, never mutates policy. Human override always wins and is audited (overrides may inform future
rule tuning later — no silent policy mutation in Step 3).

---

## DATA MODEL (codex-arch #3679 — tables or equivalent registry)

- `search_query_log` — query, principal/role, mode, filters, result_count, timestamp.
- `search_result_projection` / audit — what was returned to whom, projected vs raw, policy decision ref.
- `raw_signal_inbox` (routed_signal) — the amber raw-signal record, min fields below.
- `routing_suggestions` — proposed `route_target` + `route_reason` + method (rule|llm) + confidence.
- `routing_overrides` — actor, prior target, new target, rationale, timestamp (audited).
- `zero_result_gaps` — zero-result queries logged as `source_gap` candidates.

**Raw signal minimum fields (all 16, codex-arch #3679):** `signal_id`, `source_id`, `source_domain`,
`object_type`, `raw_summary_internal`, `projected_summary_external` (if any), `proposed_route_target`,
`route_reason`, `confidence`, `lifecycle_state=raw_signal`, classification/allowed_view/allowed_org,
owner/reviewer, freshness/observed_at, `evidence_needed_to_confirm`, `duplicate_of`/`related_signal_ids`,
audit trail.

**Promotion flow (codex-arch #3679):** search finds candidate → AI proposes route + raw summary →
internal user accepts/overrides/discards/requests-confirmation → confirmation produces a
`research_artifact` with citations/provenance → evidence-admin/human approval promotes to
`verified_evidence` → policy projection creates `shared_view` only if allowed for that audience → if
action needed, route to `execution_roadmap`, lifecycle may become `action_linked`. **Reuse the Step-1
lifecycle gate — no new promotion path.**

---

## ACCEPTANCE CRITERIA

**Authoritative AC + threat rubric = deputy-codex bus #<RUBRIC_ID> (security side) + codex-arch #3679 8
ACs (product side) — both binding.** codex-arch ACs (build to all 8):

1. Internal role can search across Step-2 registered source domains and see permitted internal results.
2. **External role cannot retrieve raw internal fields even by direct API call** (crafted query, crafted
   filters, direct endpoint — all fail closed).
3. Each result carries a `proposed_route_target` + `route_reason`.
4. User can save a result as a raw amber signal (`lifecycle_state=raw_signal`).
5. User can override routing and the override is audited (actor/prior/new/rationale/timestamp).
6. Zero-results create a `source_gap` / `execution_roadmap` candidate — never a blank result.
7. Promotion to `verified_evidence` requires the confirmation path; a raw search result cannot skip to
   `shared_view`.
8. Tests include permission-bypass attempts, misclassified source, `never_external` source, zero-results,
   duplicate signals, and conflicting routes.

**Governance invariants (codex-arch #3679):** AI proposes search/routing, human approves promotion;
external users see only `shared_view`/`action_linked` objects permitted by policy; every
route/projection/promotion is audited; route overrides never silently mutate policy; sensitive /
never-external source classes fail closed. deputy-codex #<RUBRIC_ID> threats are binding on top of these.

---

## DONE RUBRIC (answer in the ship report — not "tests pass")

1. Citation table mapping codex-arch AC1–AC8 + deputy-codex T-rubric to named tests (1:1).
2. **Partner-safe-body test:** an external partner-safe search result body is proven to come from
   `partner_projection`, NOT raw source text (spy/mock; removing the projection call fails the test).
3. **Direct-API bypass test:** external principal hitting the search endpoint/function with a crafted
   query or filter cannot retrieve any raw internal field, raw body, path, message-id, or source pointer.
4. **No-second-allow-path test (T3):** every externally visible search result routes through
   `policy.engine.evaluate` + `partner_projection`; removing the engine call fails tests.
5. **Routing tests:** all 11 deterministic rules covered; LLM-assist proposes-only (cannot finalize or
   promote); override audited; conflicting-route case resolved to `risk_permissions_review`/`source_gap`.
6. **Raw-signal + promotion test:** save_raw_signal lands `lifecycle_state=raw_signal`; promotion to
   `shared_view` is human-ratified via the existing lifecycle gate (cannot skip).
7. **Zero-results test:** zero-result query logs a `source_gap` candidate and never leaks the existence of
   hidden material.
8. Migrations additive + idempotent (`IF NOT EXISTS`), runner-safe (no `CREATE INDEX CONCURRENTLY` in the
   per-file transaction). `pytest` green (cite count) + `bash scripts/check_singletons.sh` green.
9. **DONE means:** information can enter and be routed, but nothing becomes externally visible or trusted
   evidence except through the Step-1 policy engine + the human-ratified lifecycle gate.

---

## GATE PLAN

1. Builder self-test → `pytest` + singleton guard green.
2. **deputy-codex** AC + threat-model gate vs #<RUBRIC_ID> (its owned scope) — REQUEST_CHANGES blocks merge until fixed + re-gated.
3. **deputy** augmented chain (architect + codex-verifier cross-vendor).
4. **lead** /security-review (Tier-A — partner-leak surface) → merge.
5. POST_DEPLOY_AC v1 after Render deploy (migration runs clean at startup).

---

## NOTES FOR BUILDER

- Parameterized SQL ONLY. All DB/API in try/except — `except` fails **closed**, never returns unfiltered
  rows / raw bodies / default-public.
- **Backend only is acceptable** for Step 3 if it exposes enough API/contracts for the Step-5 UI. If you
  need a test surface, label it internal/debug — NOT final dashboard UI.
- Reuse `policy.engine` + `partner_projection` + `policy.lifecycle` + `policy.sources` for ALL visibility,
  promotion, and source metadata — do NOT write a second allow path or fork the registry.
- Web/live-source = HOOK ONLY in Step 3; any future web result enters `raw_signal` first.
- Ontology vocab ambiguous (partner-facing names, route_target labels)? Bus codex-arch — don't guess.
- Branch from latest main (must include 66411ba + 9f83b31). Self-contained brief.
