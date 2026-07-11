# B2 SHIP — AI_HOTEL_V7 content package, sections 1–4

- **Brief:** AI_HOTEL_V7_CONTENT_PACKAGE_SPEC.md (§ "B2 — sections 1–4") + AI_HOTEL_DASHBOARD_V7_RESTRUCTURE_1.md (LOCKED BUILD SHAPE)
- **Dispatch:** bus #3510 + nudge #3521 (from lead, 2026-06-20)
- **Branch:** `b2/v7-sections-1-4`
- **File:** `_handoff/v7_sections_1-4.js` (declarative data only — no `ai-hotel.html` edits)
- **Ship bus:** #3522 → lead

## What shipped
A declarative JS array (`V7_SECTIONS_1_4`) of 4 section objects in the SECTIONS
schema (id/order/group/num/title/kicker/summary/status/source/subsections/emptyText):

| # | id | status | subs | render hooks |
|---|----|--------|------|--------------|
| 01 | exec | draft | 4 | — |
| 02 | why | ready | 3 | areasGrid |
| 03 | site | partial | 5 | siteThesis |
| 04 | experience | ready | 6 | plannedFrontDesk |

## Decisions
- **Empty-state discipline:** every subsection carries a visible `empty:` string.
  Where the design brief says EMPTY (thesis, why-now, current ask, location
  rationale, competitive set, owner/zoning/parcel/price/permits), body is `''` and
  the empty-state ships — no invented copy.
- **Constants folded by reference (B1 wires render):** §2 `AREAS` grid via
  `render:'areasGrid'`; §3 `research_findings` (notes 24/19/17) via the agreed
  `render:'siteThesis'` hook; §4 `renderPlanned` always-on front desk via
  `render:'plannedFrontDesk'`. §4 staff-comms references HITEC vendor evidence (§9).
- **Register:** external-presentation (NVIDIA/MO/investor/site-owner/vendor) — no
  internal/field-capture jargon.
- **Discrepancy flagged to lead:** brief says `AREAS` holds 8 use-cases; current
  `ai-hotel.html` holds **7** (flagship, concierge, education, operations, design,
  discovery, robots). Copy reflects the actual 7.

## Gate
- `node --check _handoff/v7_sections_1-4.js` → OK.
- `node -e require(...)` load + schema probe: 4 sections, 0 subsections missing
  `empty:`, render hooks present as expected.

## Scope
- Did NOT edit `outputs/static/ai-hotel.html` (B1's file — parallel-edit collision
  guard per LOCKED BUILD SHAPE). B1 is the sole integrator; this package is input.
- No PR opened — dispatch contract is branch + commit + bus, B1 folds in.
