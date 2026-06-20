# HANDOFF → lead: AI_HOTEL_RESEARCH_FINDINGS_1

**From:** cowork-ah1 · **To:** AH1-lead (run autonomously overnight) · **Date:** 2026-06-20
**Director ask (verbatim intent):** "Fill in the cards which say *unknown to research* with the research results received from the researcher." + "Check with the researcher for ALL the research that he has done."

You own this end-to-end. Director is asleep. I (cowork) cannot run autonomously, so I built the frontend + drafted the data; you finish: verify data with researcher → backfill DB → merge → deploy → live-verify. Branch is pushed: **`cowork-ah1/ai-hotel-research-findings`** (off origin/main f8fff72).

---

## 1. WHAT THIS IS

The AI-Hotel "Field notes" cards (the Director's phone captures) include **site_visit** cards whose `unknowns_to_research` field lists open questions (owner, zoning, lot size, price, permits, comps). The researcher has now answered those for the scouted Silicon Valley sites. The Director wants those answers written back onto each card so they render in the dashboard card-detail modal.

## 2. WHAT I ALREADY DID (frontend — DONE, committed on the branch)

Commit `209a9bd` — `outputs/static/ai-hotel.html`, frontend-only, `node --check` PASS:
- New `renderResearchFindings(b, rf)` helper + a **"🔎 Research findings"** block in `openNoteDetail`, rendered right after "Card fields".
- It renders a structured `form_record.values.research_findings` object: `headline` (amber callout) + per-unknown `answers:[{q,a}]` as kv rows + `flags:[...]` + `needs`/`needs_paid_pull` + `sources`.
- The generic Card-fields loop now **skips** the `research_findings` key (so it never renders as `[object Object]`) and **suppresses** the raw `unknowns_to_research` row once findings exist (answers supersede it).
- Compact card shows **"✓ researched"** instead of "N to research" once findings exist.
- New CSS: `.rf-head/.rf-meta/.rf-flag/.rf-need/.rf-src` (amber accent, reuses existing tokens).

**No backend change needed.** `_ai_hotel_form_record_view` (dashboard.py ~10338) returns the *whole* `corrected_json`/`extracted_json` as `values`, so a new `research_findings` key flows through automatically.

## 3. HOW THE DATA WRITE WORKS (the part you run)

Target table: `ai_hotel_form_records`. Per capture, the latest non-discarded row. All 3 target rows are **`status='confirmed'`** → the view reads **`corrected_json`** (falls back to `extracted_json` only if not confirmed). **Write `research_findings` into BOTH `corrected_json` and `extracted_json`** (belt-and-suspenders; survives any status flip).

Cards in scope (visible `unknowns_to_research`):

| capture_id | fr_id | site | data quality |
|---|---|---|---|
| 24 | 8 | 2900 Lakeside | FULL — confident answers |
| 19 | 7 | Santa Clara "spectacular view" | PARTIAL — address-gated; photos suggest Sunnyvale Baylands Park |
| 17 | 5 | Palo Alto / Four Seasons | PARTIAL — competitor confirmed, our parcel address-gated |

SQL pattern (use `mcp__baker__baker_raw_write`; payloads in `_handoff/research_findings_backfill.json`):
```sql
UPDATE ai_hotel_form_records
   SET corrected_json = jsonb_set(COALESCE(corrected_json,'{}'::jsonb), '{research_findings}', %s::jsonb, true),
       extracted_json = jsonb_set(COALESCE(extracted_json,'{}'::jsonb), '{research_findings}', %s::jsonb, true),
       updated_at = now()
 WHERE id = %s;   -- fr_id 8, then 7, then 5
```
Pass the per-card `research_findings` object (JSON string) as both `%s` params + the fr_id.

## 4. ⚠️ DIRECTOR INSTRUCTION — CHECK WITH RESEARCHER FOR ALL RESEARCH FIRST

Before/while you backfill, **bus the researcher and confirm you have his COMPLETE corpus** — do not rely only on my drafted JSON. Known research outputs so far:
- `wiki/matters/nvidia/curated/2026-06-19-ai-hotel-field-notes-site-research.md` (vault 4dd8d09) — 4 sites (24, 19, 17, **13**).
- `wiki/matters/nvidia/curated/2026-06-20-ai-hotel-lakeside-sites-1851-1856.md` (vault 80859dc) — site **1851** (cap 22, NEW 14.5-acre standout, APN 216-30-049) + **1856** (cap 23 = DUPLICATE of 2900 Lakeside).
- Researcher bus thread `dd21dfb1-...` (#3436 Moffett Park — DROPPED per Director; #3483 the 1851/1856 result).

Ask researcher: *"Is this the full set of AI-Hotel site research, or is anything else done/in-flight? Any corrections to the cap 24 / 19 / 17 answers?"* Fold any corrections into the payloads before writing.

## 5. SITES I SCOPED OUT — your call with researcher

- **cap 13** (fr_id 1, "vacant office ~2 blocks from NVIDIA") — researched (Site 13 in the 4-site note) BUT its `corrected_json` dropped the `unknowns_to_research` key, so it shows **no** "to research" badge → not literally a card "that says unknown to research." Research is mostly BLOCKED/address-gated + NVIDIA-encirclement risk. **Optionally** backfill it too (payload not pre-drafted — pull from the note's Site 13 section).
- **cap 22 = site 1851** (the NEW 14.5-acre standout) — has **no form_record** (it's a geo/free note), so no card fields + no `research_findings` slot. To surface 1851's findings on a card you'd need to create a site_visit form_record for it (bigger move — confirm with Director, not overnight-autonomous).
- **cap 23 = site 1856** — DUPLICATE of 2900 Lakeside; no separate fill (noted as a flag inside cap 24's findings).

## 6. SHIP SEQUENCE (suggested)

1. Bus researcher for the full corpus + corrections (§4). Wait for reply.
2. Reconcile payloads in `_handoff/research_findings_backfill.json` with his answer.
3. `baker_raw_write` the 3 (or 4) UPDATEs (§3).
4. Merge **only `outputs/static/ai-hotel.html`** from this branch to `main` (drop the `_handoff/` scratch dir — or keep, harmless). Push → Render auto-deploys `baker-master`.
5. Poll the Render deploy; then **live-verify**: load `/static/ai-hotel.html` (PIN 6470 or X-Baker-Key `bakerbhavanga`), open cards 24/19/17, confirm the "🔎 Research findings" block renders with answers, the compact card shows "✓ researched", and NO `[object Object]` row appears. `GET /api/ai-hotel/captures?limit=100` should show `form_record.values.research_findings` on the 3.
6. Bus the Director a one-line done + post-deploy AC verdict.

## 7. COORDINATION NOTES

- This supersedes my clearance ping **#3484** — you now own the ai-hotel.html push (no cross-AH1 contention; I'm done touching it).
- `ai-hotel.html` is the file you also edit directly — single-threaded is moot now, it's all yours.
- Frontend is fail-soft: if a `research_findings` object is malformed, `renderResearchFindings` just skips fields (never throws); cards without findings are untouched.
- My drafted answers are faithful to the 4-site note + #3483, but the Director explicitly wants the **researcher** to own data accuracy — treat my JSON as a verified-by-cowork draft, not gospel.
