# B2 — AI Hotel Transcript Retag (AI-HTL-001 fast-follow)

- **Dispatch:** `AI_HOTEL_TRANSCRIPT_RETAG_1` (bus #8305, topic `flight/ai-htl-001`, from lead) — fast-follow to preflight HIGH #1.
- **Date:** 2026-07-10
- **Scope:** DATA-ONLY prod write to `meeting_transcripts.matter_slug`. No code change (classifier fix proposed below as a separate brief).
- **Result:** `by-matter/nvidia` **3 → 7**. 5 transcripts retagged in, 1 mis-tag retagged out, 6 audit rows written. 30 candidates SKIPPED + listed with reasons.

---

## What changed (before → after)

`GET /api/transcripts/by-matter/{slug}` (live, verified post-write):

| Slug | Before | After |
|---|---|---|
| nvidia | 3 (2 real Fireflies + 1 mis-tagged YouTube) | **7** (2 Fireflies + 5 AI-Hotel project meetings; YouTube removed) |
| nvidia-ai-hotel | 0 | 0 |
| nvidia-mohg | 0 | 0 |
| nvidia-corinthia | 0 | 0 |

The `nvidia` parent now carries the AI-Hotel project spine: 05-12 (concept/mid-June alignment) → 06-02 (Storer call) → 06-06 (critical pivot) → 06-06 (NVIDIA partnership + California concept) → 06-17 (flagship "AI Hotel Project with Nvidia and Mandarin Oriental").

## Rows written (6) — each logged to `baker_actions` (id 17829–17834, `trigger_source=AI_HOTEL_TRANSCRIPT_RETAG_1`)

| id | date | old_slug | new_slug | evidence |
|---|---|---|---|---|
| plaud_186506fe… | 2026-05-12 | baker-internal | nvidia | "AI Hotel Concept, Mid-June Stakeholder Alignment + Pilot Use Cases" |
| plaud_92700a47… | 2026-06-02 | baker-internal | nvidia | "AI-Powered Mandarin Luxury Hotel" — Peter Storer present (the 2-June call) |
| plaud_acfff484… | 2026-06-06 | baker-internal | nvidia | (RU) "Critical pivot in NVIDIA hotel project — urgent land search" |
| plaud_6873bd0d… | 2026-06-06 | **mo-vie-exit** | nvidia | (RU) "NVIDIA partnership + California AI-hotel concept" — misfiled (no Vienna-exit content) |
| plaud_a167dc25… | 2026-06-17 | baker-internal | nvidia | "AI Hotel Project with Nvidia and Mandarin Oriental" — flagship, 8 speakers |
| youtube_erV_8yrGMA8 | 2026-04-12 | nvidia | **NULL** | "TurboQuant" LLM-memory explainer — generic AI, not AI Hotel; retagged OUT |

**Reversal:** every row's `old_slug` is in its `baker_actions` payload. To revert: `UPDATE meeting_transcripts SET matter_slug=<old_slug> WHERE id=<id>` per audit row.

## Assignment rule (why parent `nvidia`, not the siblings)

All 5 are cross-sibling AI-Hotel *project* meetings (NVIDIA tech + MOHG operator + concept together), so they go to the **parent** `nvidia` room — matching the room's own model ("parent room = cross-sibling NVIDIA-channel touchpoints"). None was confidently isolable as MOHG-operator-only (`nvidia-mohg`) or pure-vision (`nvidia-ai-hotel`), so the siblings were left at 0 this pass. Finer sibling assignment can be a follow-up if the fold needs it.

## Conservative scope — why only 5 of the ~31-37 candidate pool

`matter_slug` is **single-valued**. Re-tagging a transcript that primarily belongs to a *real active matter* (Hagenauer, AO, ClaimsMax, MO-Vienna) would **strip it from that matter**. So this pass retagged only transcripts that are **dominantly AI-Hotel by both title AND summary AND sat in a catch-all bucket** (`baker-internal`/`personal`) or were **clearly misfiled with no coverage loss** (the one `mo-vie-exit` row = a California AI-hotel meeting with zero Vienna-exit content). The "~31-37" figure was the keyword **candidate pool** from the preflight, not 37 dominant-AI-Hotel meetings — triage removes incidental mentions, out-of-scope MO ops, and active-matter sub-threads.

## SKIPPED (30) — with reasons

**A. On-topic but in an ACTIVE matter — recommend retag pending lead/Director confirm** (single-slug retag strips the current matter, or content is mixed):

| id | date | current slug | note |
|---|---|---|---|
| plaud_6ba597b0… | 05-07 | hagenauer-rg7 | "AI Partnerships, Hospitality Platform, Asset Monetisation" — recorded the DECISION to pursue NVIDIA; but "Asset Monetisation" may be Hagenauer/portfolio |
| plaud_03b65926… | 05-10 | claimsmax | "ClaimsMax projects + strategic NVIDIA partnership" — ClaimsMax named primary |
| 01KKT38S… | 03-15/16 | claimsmax | "GPU Credit Strategy / NVIDIA" — NVIDIA-dominant but filed under claimsmax |
| 01KKW11J… | 03-16 | baker-internal | "AI Infrastructure (Nvidia GPUs)" + ClaimsMax billing structure — genuinely mixed |
| 01KM66NC… | 03-20 | baker-internal | 167-min RU: NVIDIA×MO action items, but construction-AI heavy |
| 01KKSMM0… | 03-15 | baker-internal | Hospitality-vertical AI strategy (digital twin, acquire tech cos) — no explicit NVIDIA |

**B. Out-of-scope MO ops / adjacent AI-hospitality (NVIDIA incidental):** plaud_45a9d485 (06-02 personal, **MO Prague + CITIC — out of scope**), plaud_49bb6864 (05-20 mo-vie-exit, MO Vienna mgmt), plaud_10504c4c (04-28 personal, Vienna hotel sale), plaud_e0a9578c (05-20 kitzbuhel, Vienna restaurant), plaud_4d6c0095 (06-16 mo-vie-exit, **Duetto/Rosie** — adjacent AI-hospitality tech, not the NVIDIA AI Hotel).

**C. Other active matters, NVIDIA keyword incidental:** plaud_5ff5b488 (07-06 ao), plaud_8709887b (06-25 ao/Istanbul), plaud_cb9883c4 (06-25 hagenauer), plaud_97e71e08 (06-22 hagenauer), plaud_2a9f08b9 (06-10 kitzbuhel court valuation), plaud_456554a7 (06-16 personal API), plaud_0e1d1cad + plaud_38a7dbf2 (04-27 austrian-tax), plaud_673080aa (05-21 baker-internal, 876-min disputes+tech), plaud_ac97b7a9 (05-14 mo-vie-am, dual venture pitches — half AI Hotel).

**D. Fireflies auto-titled, mixed/incidental:** 01KMT8MS (03-28 insolvency+NVIDIA), 01KMQT27 (03-27 construction digital twin), 01KMMQTFEC (03-26 media), 01KM83CE (03-21 restaurants+NVIDIA), 01KM1E9076 (03-18, 15-min), 01KKYTW7 (03-17 hotel-robotics vendor session), 01KJZ6NZ (03-05 refinancing), 01KGMW7Q (02-04 data systems).

No ambiguous row was silently dropped — all 30 are listed above.

## Proposed follow-up brief — `AI_HOTEL_CLASSIFIER_FIX_1` (per dispatch: "classifier fix = separate brief tomorrow")

Root cause the retag exposed:
1. **Single-slug `matter_slug` column.** A transcript can genuinely belong to >1 matter (e.g. a call that is both a Hagenauer strategy session AND the NVIDIA-partnership decision). The single column forces an either/or and is why 6 on-topic rows had to be SKIPPED rather than retagged. **Recommend:** a `transcript_matter_tags` join table (many-to-many), OR a `secondary_slugs text[]` column, so `by-matter` can union primary+secondary.
2. **Classifier alias/keyword gap.** `_match_matter_slug` never assigns nvidia-family slugs to AI-Hotel meetings — they resolve to `baker-internal`/`mo-vie-exit`/`personal` first. Add nvidia-family triggers: `NVIDIA`+`hotel`/`Mandarin`, `AI hotel`/`AI-отель`, `Storer`, `Bick`, `Santa Clara`, `Inception` → `nvidia` (+ MOHG-operator terms → `nvidia-mohg`, Corinthia → `nvidia-corinthia`). Cover RU-language variants.
3. **Backfill.** Re-run the fixed classifier over historical `meeting_transcripts` (multi-tag aware) so the active-matter rows in SKIP-list A get their nvidia tag without losing the current one.

## Verification (dispatch method §4-5)

- `by-matter/nvidia` returns the 7-row set (verified via live curl post-write). ✓
- `baker_actions` holds 6 audit rows (17829–17834), all `success=true`, `tier=B`, `committer_agent=b2`. ✓
- All writes wrapped (baker_raw_write, RETURNING-confirmed). No errors. Before/after counts reported above. ✓
