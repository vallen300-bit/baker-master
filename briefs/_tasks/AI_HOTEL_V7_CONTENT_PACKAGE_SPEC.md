# AI_HOTEL_V7 — Shared CONTENT-PACKAGE SPEC (for B2/B3/B4)

**Parent brief:** `AI_HOTEL_DASHBOARD_V7_RESTRUCTURE_1.md` (read its LOCKED BUILD SHAPE).
**Your job (B2/B3/B4):** author a **declarative data package** for your assigned
sections. You do **NOT** edit `outputs/static/ai-hotel.html`. You produce a JS
snippet file that B1 (sole integrator) folds into the `SECTIONS` model. Zero file
collision — each B-code writes its own handoff file.

## Output contract
Write your package to `_handoff/v7_sections_<range>.js` on your branch
(B2 → `v7_sections_1-4.js`, B3 → `v7_sections_5-8.js`, B4 → `v7_sections_9-12.js`),
commit + push your branch, and bus lead the branch + commit. The file exports a
plain JS array fragment of section objects (see schema). No DOM, no fetch, no
side effects — pure data + optional pure-function render hooks.

## SECTIONS object schema (each section)
```js
{
  id: 'exec',              // short stable slug, kebab
  order: 1,                // 1..12
  group: 'narrative',      // narrative(1-4) | case(5-8) | execution(9-12)
  num: '01',               // visible 2-digit label
  title: 'Executive Summary',
  kicker: 'The one-screen case',          // short eyebrow line
  summary: '',             // 1-2 sentence section lede; '' → renders empty-state
  status: 'draft',         // draft | partial | ready  (drives a status chip)
  source: '',              // provenance line if any (e.g. 'Brisen + MO concept note')
  subsections: [
    {
      label: 'Project thesis',
      body: '',            // string OR array of strings (bullets); '' → empty-state
      empty: 'Thesis to be written.',     // visible placeholder when body is empty
      chips: []            // optional [{label, href}] source chips/links
    },
    // ...
  ],
  emptyText: 'This section is not yet filled.'   // section-level fallback
}
```
**Rules:** every missing subsection MUST carry an `empty:` string (visible
placeholder — Director directive). No `null`/`undefined` bodies. Keep copy
**external-presentation register** (NVIDIA/MO/investor/site-owner/vendor audience)
— no internal jargon, no field-capture language. Concise, precise, operational
(Pattern B). Where a subsection is genuinely empty per the v7 design brief, ship
the empty-state — do NOT invent content.

## Existing constants to FOLD IN (read from current ai-hotel.html, lines noted)
- `AREAS` (397–426, 8 AI use-cases) → §2.
- `STAKEHOLDERS` (1332–1408, 6 give/get) → §5.
- `RESEARCH` (429–433) + `COMPETITORS` (441–445) → §8.
- `VENDORS` (451–492, 9 HITEC) → §9 (+ add ranking/next-action/owner/follow-up fields).
- `PLANNED` (1249–1277, front-desk concept) → §4.
- `COMMS` (434–438, NVIDIA/MO draft letters) → §12.
When folding a constant in, reference it by name + keep its data; B1 wires the
render. You may reshape it into the subsection schema.

## Per-section content (from codex-arch v7 design brief #3495)
### B2 — sections 1–4 (group: narrative)
- **§1 Executive Summary:** thesis (EMPTY), why now (EMPTY), partnership proposition
  (NVIDIA × Mandarin Oriental × Brisen — write a tight factual line), current ask (EMPTY).
- **§2 Why AI Hotel:** MO growth challenge (~45 → 100+ hotels); "AI enhances luxury
  service, does not replace human touch"; existing AI areas (fold `AREAS`: flagship,
  concierge/reservations, training, operations/personalization, digital twins,
  AI search/GEO, robotics).
- **§3 Santa Clara Site Thesis:** location rationale (EMPTY); demand drivers (Silicon
  Valley / business meetings / airport / convention / tech ecosystem); competitive set
  (EMPTY); **site summary placeholder** — B1 injects the derived `research_findings`
  (24/19/17) summary + chips→§13 here, so leave a subsection `{label:'Scouted sites',
  body:'', empty:'Site research summary loads from Field Evidence.', render:'siteThesis'}`;
  owner/zoning/parcel/price/permits (EMPTY).
- **§4 Guest & Staff Experience:** guest concierge + reservations; pre-arrival planning;
  personalization (room/dining/spa/loyalty); staff training copilots; always-on AI
  front desk (fold `PLANNED`); staff communication/translation (from HITEC vendor evidence).

### B3 — sections 5–8 (group: case)
- **§5 Stakeholder Give/Get:** fold `STAKEHOLDERS` (NVIDIA, MO, Brisen, AI
  startups, investor/owner/lender, guests); ADD a city/community card (EMPTY give/get);
  ADD per-party current-ask / status / next-move (EMPTY where unknown).
- **§6 Business Case:** revenue uplift (PARTIAL — describe, not quantified); cost
  reduction (PARTIAL — describe, not quantified); capex/dev economics (EMPTY);
  investor return (EMPTY); platform upside (PARTIAL); valuation case (EMPTY).
- **§7 Technology Architecture:** NVIDIA compute/GPU/CUDA/SDK lock-in; digital
  twins/simulation; AI front-desk orchestration layer; PMS/CRM/legacy integration;
  data architecture (EMPTY); privacy/consent model (EMPTY); build-vs-buy map (EMPTY).
- **§8 Market Proof:** NVIDIA give/get precedents (fold `RESEARCH`); Rosewood AI
  hackathon competitor signal (fold `COMPETITORS`); HITEC 2026 vendor evidence
  (reference §9); luxury hospitality AI benchmarks (EMPTY); customer demand evidence (EMPTY).

### B4 — sections 9–12 (group: execution)
- **§9 Vendor & Partner Pipeline:** fold `VENDORS` (Hudini, Data Plus, RoomPriceGenie,
  Hercules, Relay, aiOla, American Sentinel, Optacy); ADD vendor ranking / next-action /
  owner / follow-up-status fields per vendor.
- **§10 Execution Roadmap:** first 30 days (EMPTY); first 90 days (EMPTY); partner
  outreach sequence (EMPTY); site diligence sequence (EMPTY); pilot plan (EMPTY);
  build/opening timeline (EMPTY).
- **§11 Risks & Governance:** MO brand protection / moat leakage (write from the
  known thesis); guest data consent (EMPTY); AI hallucination/service failure (EMPTY);
  labor/staff acceptance (EMPTY); cost overrun (EMPTY); vendor dependency (EMPTY);
  regulatory/zoning (EMPTY).
- **§12 The Ask:** NVIDIA ask (co-marketing, engineering support, GPU priority,
  Inception/startup access); Mandarin Oriental ask (brand, operating venue, service
  standards, guest/data access); investor ask (EMPTY); site-owner ask (EMPTY); vendor
  ask (EMPTY); fold `COMMS` draft letters as linked artifacts.

## DO NOT
- Do not edit `ai-hotel.html` (B1's file).
- Do not invent figures, names, or claims beyond the design brief + existing constants.
- Do not write persuasive marketing copy where the brief says EMPTY — ship the empty-state.
