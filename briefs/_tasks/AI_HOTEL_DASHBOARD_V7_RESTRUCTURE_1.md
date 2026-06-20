# BRIEF — AI_HOTEL_DASHBOARD_V7_RESTRUCTURE_1

**dispatched_by:** aihead1-lead
**design source:** codex-arch v7 design brief (bus #3495)
**task class:** feature / restructure (frontend, single file)
**Harness-V2:** applies — Context Contract + done rubric + gate plan
**governance (Director #3495):** B1-B4 build; Codex reviewer + Codex deputy design-verdicts BEFORE autonomous build; then lead implements autonomously within authority.

## Goal
Restructure `outputs/static/ai-hotel.html` from its current 8-section internal
dashboard into a **13-section external presentation / data-room dashboard** — a
third-party-ready spine (NVIDIA / Mandarin Oriental / investor / site-owner /
vendor facing) with internal Field Evidence preserved as the appendix shelf.

## Current state (verified inventory)
- Single file, ~1,420 lines: CSS `<style>` 8–314 (design tokens in `:root`),
  HTML skeleton 316–367, JS 369–1417.
- Nav = static array of **8** sections (lines 494–503); switching is imperative
  `show(id)` (1279–1292) → calls `render*(main)` + `buildNav()` (506–513). NOT hash-routed.
- Content is **~85% hardcoded constants**: `AREAS`(8), `STAKEHOLDERS`(6),
  `RESEARCH`(1), `COMPETITORS`(1), `VENDORS`(9), `COMMS`(2), `PLANNED`(1).
- **Field notes** = the only dynamic section: fetches `/api/ai-hotel/captures?limit=100`,
  cards via `buildNoteCard`/`openNoteDetail`, photo lightbox + rotate, soft-delete,
  research-findings render, PIN/X-Baker-Key auth. **PRESERVE WHOLESALE.**
- Design tokens: warm cream `--bg #f7f6f2` + dark-ink `--accent`; blue/amber/green
  status; Apple system + mono fonts; light/dark via `setTheme`; mobile drawer @860px.

## v7 — the 13-section spine (left sidebar nav, in order)
Each section = a content pane built from a **reusable presentation-section
template**: section title + kicker, then ordered **subsections**; each subsection
either holds slotted content OR renders a **visible empty-state placeholder**
("— to be filled —" styled, not hidden) so gaps are explicit (Director directive).

| # | Section | Slot existing → | Empty placeholders |
|---|---|---|---|
| 1 | Executive Summary | partnership proposition (NVIDIA×MO×Brisen) | thesis, why now, current ask |
| 2 | Why AI Hotel | `AREAS` (8 use-cases) + MO growth (~45→100+), "AI enhances not replaces", existing AI areas | — |
| 3 | Santa Clara Site Thesis | demand drivers; site photos/cards → link §13; **per-site owner/zoning/parcel/price/permits summary sourced from Field-Notes `research_findings` (24/19/17)** | location rationale, competitive set |
| 4 | Guest & Staff Experience | concierge/reservations, pre-arrival, personalization, staff copilots, always-on front desk (`PLANNED`), staff comms/translation (HITEC) | — |
| 5 | Stakeholder Give/Get | `STAKEHOLDERS` (6, ranked give/get) | city/community card; per-party current-ask/status/next-move |
| 6 | Business Case | revenue uplift (partial), cost reduction (partial), platform upside (partial) | capex/dev economics, investor return, valuation |
| 7 | Technology Architecture | NVIDIA compute/GPU/CUDA/SDK lock-in, digital twins, AI front-desk orchestration, PMS/CRM integration | data architecture, privacy/consent, build-vs-buy |
| 8 | Market Proof | `RESEARCH` (NVIDIA give/get), `COMPETITORS` (Rosewood), HITEC signal | luxury AI benchmarks, customer demand evidence |
| 9 | Vendor & Partner Pipeline | `VENDORS` (9 HITEC) + add ranking / next-action / owner / follow-up fields | — |
| 10 | Execution Roadmap | — | 30 days, 90 days, partner outreach seq, diligence seq, pilot plan, build/opening timeline |
| 11 | Risks & Governance | MO brand protection / moat leakage | guest-data consent, hallucination/service failure, labor acceptance, cost overrun, vendor dependency, regulatory/zoning |
| 12 | The Ask | NVIDIA ask, MO ask; `COMMS` drafts | investor ask, site-owner ask, vendor ask |
| 13 | Appendix / Field Evidence | **EXISTING Field Notes section, preserved 100%** (cards, photos, lightbox+rotate, delete, research-findings, audio/video, GPS) | — |

## Hard constraints
- **Preserve** Field Notes (§13), HITEC, Competitors, Stakeholders content + all
  recent Field-Notes work (EXIF, rotate, soft-delete, readable titles, research-findings).
- **Reuse** existing design tokens, `show(id)` router pattern, `setTheme`, mobile
  drawer, search. External register = clean, third-party-ready (no internal jargon
  on the presentation spine; field-capture stays in §13).
- **Visible empty-states** for every missing subsection — never hidden.
- Do NOT turn it into a CRM-only view; it must read as presentation material.
- Auth: presentation sections (§1–§12) public/client-rendered; §13 stays PIN/key-gated.
- Fail-soft: malformed/missing data renders the empty-state, never throws.

## Open design questions for the Codex review (answer before build)
1. **Decomposition** — single coherent author for a one-file refactor vs B1-B4
   split? A 1,420-line single file is collision-prone for parallel editors.
   Recommend a split that avoids merge hell (e.g. b1 = shell/router/template/CSS +
   §13 preserve; others author per-section **data constants** the shell renders,
   integrated by b1) OR justify single-author. **Codex: recommend the decomposition.**
2. **Nav grouping** — 13 items flat, or grouped headers (e.g. "Narrative" §1–8 /
   "Operating" §9–12 / "Evidence" §13)? Mobile drawer impact.
3. **Section content as data** — extend the existing constants pattern to a single
   `SECTIONS` model so empty-states + subsections are declarative + uniform?
4. **§3 research surfacing** — pull the §13 `research_findings` (24/19/17) into a
   §3 site summary, or just link to §13? Avoid data duplication.

## Gate plan
1. **Design review (THIS step, Director-required):** codex reviewer (codex terminal)
   + deputy-codex verdict on approach + decomposition + the 4 questions. PASS → build.
2. Build per agreed decomposition (B-codes).
3. Integration → codex G3 (independent) → lead merge → deploy → live-verify all 13
   sections render, empty-states visible, Field Notes §13 fully intact + functional.

## Sequencing
Lands AFTER AI_HOTEL_RESEARCH_FINDINGS_1 merges (same file — research-findings
render must be in §13 first). Branch off the post-research-fill main.

---

## LOCKED BUILD SHAPE — codex design verdict #3504 (APPROVE w/ required shape)
Design pattern = **Pattern B** (design-v2): serious operational dashboard; first
screen = thesis + current status + next action + evidence freshness, NOT a
marketing hero.

**Decomposition (REQUIRED — no parallel edits to ai-hotel.html):**
- **B1 = sole file integrator** of `ai-hotel.html`: shell/router/section-template/
  CSS, grouped nav, the `SECTIONS` renderer, first-screen status strip, search
  compatibility, **§13 Field Notes preserved 100%**. B1 integrates B2–B4 packages.
- **B2** authors the data/content package for **sections 1–4** only.
- **B3** authors the data/content package for **sections 5–8** only.
- **B4** authors the data/content package for **sections 9–12** only.
- B2–B4 produce **declarative section data** (no ai-hotel.html edits) → B1 folds in.

**Nav grouping (REQUIRED):** grouped headers, not flat 13 —
Narrative (01–04) · Case (05–08) · Execution (09–12) · Evidence (13).
Keep section numbers visible in labels.

**SECTIONS data model (REQUIRED):** one declarative array; per section fields:
`id, order, group, title, kicker, summary, status, source, evidence, subsections[],
emptyText, render?(hook)`. Sections 1–12 render through ONE reusable
presentation-section renderer; **missing/malformed subsection → visible empty
state, never hidden, never throws**. Keep `renderNotes` as the §13 special hook —
do NOT rewrite it.

**§3 research surfacing (REQUIRED):** inline a SHORT derived site-thesis summary
in §3 with source chips/links back to §13 note IDs (cap 24/19/17). One helper
normalizes `research_findings` → owner / zoning-or-parcel / price-or-permits /
evidence-status. Absent/malformed → visible empty state + link to §13. No full-detail
duplication.

**Build guardrails (REQUIRED):**
1. First screen shows thesis + status + next action + evidence freshness before grids.
2. §13 stays private/gated; preserve cards, photos, lightbox/rotate, delete,
   research-findings, audio/video, GPS.
3. Search includes new presentation cards; must not break current card filtering.
4. No internal jargon on §1–12; field-capture language stays in §13.
5. Final gate = desktop + mobile screenshot/interaction QA + Field Notes regression probes.

**Second design verdict:** deputy-codex concurrence pending (Director required both
reviewers). Build dispatch holds until deputy concurs.
