# BRIEF — AI_HOTEL_LAB_SOURCE_INVENTORY_1

**Sprint:** AI Hotel Lab — Sprint-0, Build Step 2 of 5 (source inventory / evidence supply chain).
**Dispatched_by:** lead (AH1). **Gate owner:** deputy-codex (AC + threat-model), deputy (augmented chain), lead (security-review + merge).
**Source of truth:** codex-arch product framing (bus #3651, Director-confirmed) + deputy-codex Step-2 security rubric (bus #3653).
**Builds on:** Step 1 — the LIVE policy engine `policy/` (merged 66411ba). This step FEEDS that engine; it must NOT duplicate its allow semantics.
**Harness-V2:** in scope — Context Contract + task class + done rubric + gate plan below.

---

## CONTEXT CONTRACT

**What this is.** A machine-usable **source registry** + a human-readable **source map** for the AI Hotel
Lab — a controlled evidence supply chain. It inventories what the Lab may search, ingest, monitor, and
route, and classifies every source/object so the later search/routing layer (Step 3) can operate without
risking leakage to NVIDIA, MOHG, banks, investors, site owners, PR, residence buyers, or vendors.

**What this is NOT.** NOT search (that's Step 3) — no content search, no snippets, no generated summaries
in the source map. NOT a new permission system — external visibility is decided ONLY by the live Step-1
policy engine. This step supplies classification METADATA to that engine; it never decides external
visibility itself.

**Default principle (codex-arch #3651, Director-confirmed):** internal Brisen collection may be broad;
external visibility must be narrow, derived, approved, and redacted. **Classification is not a grant** —
Step-1 policy still gates allowed_view / allowed_org / role / lifecycle_state / classification.

**Where it lives.** baker-master repo. Recommend a `policy/sources/` subpackage or `sources/` package +
a migration for the registry table(s). Reuse the Step-1 `policy/` engine + `partner_projection` path —
do NOT reimplement filtering. Stack unchanged: Python 3.11+, FastAPI, PostgreSQL, parameterized SQL only.

---

## SOURCE DOMAINS (exactly these 8 — codex-arch #3651, AC2; no `misc`/catch-all)

1. **Baker internal memory** — conversation memory, deep analyses, decisions, deadlines, action logs,
   ClickUp/Todoist where relevant.
2. **Vault / project rooms / curated files** — baker-vault AI Hotel / NVIDIA / origination material,
   curated research, gold/proposed-gold, design/spec spine.
3. **Dropbox / project files** — AI Hotel, Santa Clara, NVIDIA/MOHG, site, financing, design, residence,
   PR folders when available.
4. **Email / WhatsApp / Slack (if later added)** — internal Brisen + partner correspondence, AI-Hotel-relevant
   only. **Raw bodies NEVER external** — only derived, approved evidence projects outward.
5. **Field evidence** — site photos, GPS notes, videos, voice-to-form captures, field observations.
6. **Open web** — general/US/local/hospitality/AI press, NVIDIA/MOHG public material.
7. **Santa Clara / site-search public data** — city planning/zoning/permits, GIS/parcel/assessor/recorder,
   council/planning materials, airport/transport, utilities, traffic, broker/listing/ownership signals.
8. **Market / capital / residence** — hotel comps, branded-residence demand, bank/financing signals,
   investor data, sales/PR intelligence.

**Hard-gate / exclude (codex-arch #3651 + deputy-codex AC5):** credentials/secrets; raw email/WA/Slack
bodies in external views; NDA material unless explicit partner-safe projection; personal material
unrelated to AI Hotel; off-AI-Hotel legal/financial; raw partner negotiations.

---

## ACCEPTANCE CRITERIA

**Authoritative AC + threat rubric = deputy-codex bus #3653 (security side) + codex-arch #3651 6 ACs
(product side) — both binding. Build to AC1–AC10, defend T1–T10, satisfy the 6 builder gate requirements.**
Summary (full text in #3653):

- **AC1** Registry schema mandatory + machine-readable: stable opaque `source_id` + domain, source_type/
  object_type, owner_org, provenance, classification, allowed_view, allowed_org/allowed_roles,
  lifecycle_state, `raw_body_available_internal`, `external_projection_available`, redaction_reason,
  freshness/last_seen, `policy_object_id`/object_id, collection_status/gap_status. **Missing required
  fields fail closed, not default-public.**
- **AC2** Exactly the 8 domains; no `misc`/catch-all; unwired sources = explicit gap rows, no payload.
- **AC3** Classification is NOT a grant — a source mis-registered partner-safe still passes live policy/
  engine evaluation. Step 2 supplies metadata; it must not decide external visibility.
- **AC4** Integrates with the LIVE Step-1 policy engine (66411ba), not a duplicate allow-list. External
  registry reads / source-map generation call the policy engine + projection per source/object. Local
  filtering is pre-filter ONLY; final visibility = policy evaluation.
- **AC5** Never-external hard-deny survives registry errors (credentials, raw email/WA, NDA, off-matter
  legal/financial, vendor negotiation, strategy notes, capital-sensitive) — denied externally even if
  accidentally classified partner-safe.
- **AC6** Raw-body flags are non-leaking: `raw_body_available_internal=true` is internal inventory metadata
  only; never surfaces raw body/title/snippet/attachment text/email-id/WA-id/Dropbox-path/vault-path/
  credential locator in any external projection.
- **AC7** External projection state explicit: hidden/partial rows carry `external_projection_available=false`
  + redaction_reason. Missing redaction_reason on a hidden row → fail closed, surface registry-invalid.
- **AC8** Gap sources first-class: explicit gap rows with owner, reason, next_action. No silent blank in
  the human-readable source map.
- **AC9** Provenance mandatory + audience-scoped: internal keeps full provenance; external gets
  provenance_class/source_count/freshness where safe, never raw refs. `source_id` opaque + non-enumerable;
  no URL/path/message-id leakage unless source is public + explicitly safe.
- **AC10** Registry changes auditable: every classification/allowed_view/allowed_org/lifecycle/raw-flag/
  projection-flag/redaction_reason change records actor, timestamp, prior/new, rationale, decision source.
  AI may propose registry metadata; **human ratification required for any change making a source externally
  visible.**

**Threats to defend (full text #3653):** T1 mis-registration leak · T2 raw-flag confused-deputy · T3
policy-bypass drift (independent allow logic) · T4 never-external override · T5 cross-partner bleed
(NVIDIA↔MOHG) · T6 search-before-search leak (no snippets/summaries) · T7 silent blank · T8 public-source
fallacy (public ≠ grant) · T9 identifier leakage (paths/ids/refs) · T10 tamper/audit gap.

---

## DONE RUBRIC (answer in the ship report — not "tests pass") — deputy-codex 6 gate requirements

1. Citation table mapping AC1–AC10 + T1–T10 to named tests (1:1).
2. ≥1 fixture row per 8 source domains + ≥3 explicit gap rows.
3. Negative tests: misclassification, cross-partner bleed, raw email/WA, credentials/NDA/off-matter
   legal/financial, missing required fields.
4. Live-policy integration test proving Step 2 USES the Step-1 policy engine and does NOT duplicate allow
   semantics (spy/mock `policy.evaluate`/projection per external visible item; removing the call fails tests — T3).
5. Human-readable source map sample from the same fixtures, external vs internal projections compared.
6. **DONE means: no source can become externally visible through registry metadata alone — policy engine +
   projection remain the final control.**
7. Migrations additive + idempotent (`IF NOT EXISTS`), runner-safe (no `CREATE INDEX CONCURRENTLY` in the
   per-file transaction). `pytest` green (cite count) + `bash scripts/check_singletons.sh` green.

---

## GATE PLAN

1. Builder self-test → `pytest` + singleton guard green.
2. **deputy-codex** AC + threat-model gate vs #3653 (its owned scope).
3. **deputy** augmented chain (architect + codex-verifier cross-vendor).
4. **lead** /security-review (Tier-A — partner-leak surface) → merge.
5. POST_DEPLOY_AC v1 after Render deploy (migration runs clean at startup).

---

## NOTES FOR BUILDER

- Parameterized SQL ONLY. All DB/API in try/except — `except` fails **closed**, never returns unfiltered
  rows or default-public (AC1/T10).
- This step has NO content search + NO UI. If you find yourself indexing bodies or rendering snippets,
  STOP — that's Step 3/5, out of scope (T6).
- Reuse `policy/` (engine.evaluate + partner_projection) for ALL external visibility — do not write a
  second allow path (T3).
- For domains not yet wired (e.g. Slack, partner data room), create gap rows — do NOT fabricate coverage (T7).
- Ontology vocab ambiguous? Bus codex-arch — don't guess partner-facing names.
- Branch from latest main (must include 66411ba). Self-contained brief.
