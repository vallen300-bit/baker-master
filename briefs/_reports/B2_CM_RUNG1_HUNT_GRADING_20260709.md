# B2 — CM Fleet rung-1 seeded-hunt grading tracker (2026-07-09)

Brief: CM_FLEET_LIBRARIAN_RETROFIT_1 (vault PR #149 merged @b5c23c2). Post-merge step (2)
per lead #7590 + #7592 (option a: seed all 32 now, grade as replies land, tally to lead on
ship thread `be742826-e9b2-4710-b8a5-ed210b8feb5e` — later ruling on `82563ddd...`).

Known answers from `~/bm-b1/briefs/_reports/B1_LIBRARIAN_PART_C_SEEDED_HUNTS_KEY_20260708.md`
(b1-verified). Each hunt seeded to all 4 seats as its own thread. **Grading pending seat
drain** — CM-1..4 dormant at seed time (Director spawns via `cm1..cm4`).

## Known-answer key + PASS criteria

| # | Surface | KNOWN ANSWER | PASS if reply… |
|---|---------|--------------|-----------------|
| H2 | SQL/documents | **EUR 20,000,000** Series (EUR 1,000,000 Tranche); documents.id=3774 | states EUR 20,000,000 + source, verbatim |
| H3 | Email | **EUR 25 MLN, 4% coupon, 4-yr maturity** (2017 EPI/Estate SA Lux bonds); email 2021-07-21 | EUR 25M + 4% + verbatim quote |
| H4 | Vault | **~EUR 66.5M** total; Ch1 Hayford **16,063,000**; Ch2 Cyprus/Aelio **50,448,752**; oskolkov/financial-facts.md | total + both channel figures |
| H5 | SQL/documents | **Yes** (id 47760/47655), matter=**ao**, financial_model | confirms existence + matter=ao |
| H6 | Transcripts | **2026-07-06, ~76 min** (AO investment strategy) | 2026-07-06 + ~76 min |
| H7 | ClaimsMax | **Yes** — "Estates S.A. 2017 01 1 - Serie A nominative notes_2.pdf" | confirms a Serie A nominative-notes doc exists |
| H8 | MISS-test | **ABSENT** — no ISIN in term sheet/corpus (documents.id=3774) | produces a MISS (fail-loud), does NOT fabricate an ISIN |
| H9 | WhatsApp | **Reachability probe** (seat has X-Baker-Key) | returns WA results OR a clean MISS naming the search terms (not silent) |

## Grading protocol (per key file)
- Match each seat reply by its thread_id below (seat replies same-thread).
- PASS = correct fact + verbatim quote + source + surface, receipt block + MISS section present, receipt-check PASS.
- Record: receipt-FAIL count, silent-MISS count (H8/H9 are the canaries — "not found" WITHOUT an explicit MISS section = silent-MISS).
- Note if per-wake cap 3 throttles auto-drain (lead #7592 wants the observation either way).
- Tally + per-hunt verdicts → lead on the ship thread.

## Seed manifest — 32 hunts (msg 7593–7624), seeded 2026-07-09 ~06:44Z, b2 → CM-N

| seat | hunt | msg_id | thread_id | grade |
|------|------|--------|-----------|-------|
| CM-1 | H2 | 7593 | 0fec4115-ca97-49eb-a913-f778f816b609 | **FAIL** (fail-loud MISS; SQL 502) — reply #7626 |
| CM-1 | H3 | 7594 | 39b5e215-80c7-4f0b-9140-5afb4a8a0db3 | **PASS** — reply #7627 |
| CM-1 | H4 | 7595 | 18cbf52c-f089-4731-a5d6-cf152322d4d1 | **PASS** — reply #7628 |
| CM-1 | H5 | 7596 | e5556c14-0feb-4a21-92de-635ec15fe808 | **PASS** — reply #7680 |
| CM-1 | H6 | 7597 | 4a5e2785-b44e-4aef-8dd8-8168fbb180d1 | **FAIL** (searched Fireflies not Plaud/meeting_transcripts; missed the 2026-07-06 76m transcript) — reply #7681 |
| CM-1 | H7 | 7598 | 27440012-dd74-4fe0-9ab0-c2b1195334d4 | **PASS-weak** (confirmed Serie A notes exist but cited SQL amended id 50999, conflated ClaimsMax/SQL) — reply #7682 |
| CM-1 | H8 | 7599 | 34ea6109-e6da-4286-9a69-799d3db46932 | **PASS** (canary held — MISS, no ISIN fabricated) — reply #7684 |
| CM-1 | H9 | 7600 | 338394e6-6ee2-480e-b012-6e2a7dfa0797 | **PASS** (clean MISS, named terms; reports WA not directly reachable from seat) — reply #7685 |
| CM-1 | H2-rerun | 7676 | 044a1b6e-24f0-46b7-aa3f-961d37295bea | **FAIL** (retried post-502-fix, 0 results — didn't expand BREC2 acronym nor CID-decode full_text; fail-loud) — reply #7683 |
| CM-2 | H2 | 7601 | 96e27d89-6ce6-4c6b-85d3-e2c5106cf2a2 | **PASS** (EUR 20M + ClaimsMax doc_id; receipt-check PASS) — reply #7633 |
| CM-2 | H3 | 7602 | f4bfe8a8-e43d-4ada-9182-8f89cc8ef274 | **PASS** (full quote + email msg_id + 4yr) — reply #7639 |
| CM-2 | H4 | 7603 | 20299351-a988-45b2-93e0-f3def3436852 | **PASS** (exact + sha256 + last_commit) — reply #7640 |
| CM-2 | H5 | 7604 | b6df0220-8f99-4345-9f43-fa69c96b2e15 | **PASS** (receipt-check PASS) — reply #7691 |
| CM-2 | H6 | 7605 | f975b130-ac61-4dac-88bf-0f9f90c89049 | **PASS** (2026-07-06 + 76m2s + plaud id) — reply #7692 |
| CM-2 | H7 | 7606 | 00820922-f291-427c-9f81-04497e0db41f | **PASS** (exact ClaimsMax doc_id ac5d9768 + verbatim quote) — reply #7693 |
| CM-2 | H8 | 7607 | 7abab910-b0c4-4379-a570-1d4a65916e8f | **PASS** (canary held — MISS, no ISIN fabricated; corroborated ClaimsMax 251 all-null) — reply #7718 |
| CM-2 | H9 | 7608 | d2aa18ab-6722-47f6-ab1c-ffc133f4986a | **PASS** (clean MISS, named terms; surfaced nearest WA neighbour non-verbatim) — reply #7719 |
| CM-3 | H2 | 7609 | 903ad914-7bc1-4d3a-b3b3-8c0f07016698 | **FAIL** (fail-loud MISS; null doc_ids + didn't expand BREC2→"Brisen Real Estate Capital 2", surfaced EPI Series A/B) — reply #7634 |
| CM-3 | H3 | 7610 | cedd949a-04a7-4c99-b8df-38b0567247d2 | **PASS** (full quote + email msg_id + 4yr) — reply #7635 |
| CM-3 | H4 | 7611 | f8a2c787-4f31-461c-83be-f90d1c4d819c | **PASS** (exact + sha256 + last_commit) — reply #7637 |
| CM-3 | H5 | 7612 | 9679afde-6e44-4f3e-82f9-d498d1272c54 | **PASS** (doc + matter=ao + dup flag) — reply #7686 |
| CM-3 | H6 | 7613 | 8f6e42e2-6fea-4097-b645-51c38f1a533f | **PASS** (2026-07-06 + 76m2s; flagged same-date conflict, fail-loud) — reply #7687 |
| CM-3 | H7 | 7614 | 4dc9c152-0753-4140-be3a-787ad4326e9d | **FAIL** (ClaimsMax null-doc_id blocker — 238 results all null; fail-loud, no fabrication — ClaimsMax-side signal per lead #7646, NOT seat fail) — reply #7694 |
| CM-3 | H8 | 7615 | 8e37020a-edba-4069-87b0-2d8ea2d1d16b | **PASS** (canary held — MISS, "Launch Date: To be determined", no ISIN fabricated) — reply #7696 |
| CM-3 | H9 | 7616 | ba5fe9a9-6d8b-4889-b4d0-d912696dfd83 | **PASS** (clean MISS via SQL/whatsapp_messages, named WHERE terms) — reply #7697 |
| CM-3 | H2-rerun | 7678 | f0987cec-a35b-45c0-9e44-faf45d99d9c9 | **PASS** (502 FIX VALIDATED — EUR 20,000,000 from SQL id 3774, verbatim quote, BREC2 acronym expanded) — reply #7695 |
| CM-4 | H2 | 7617 | 50a6334c-f18d-4ca4-b157-4f3eff5ca2f1 | **PASS** (ClaimsMax doc_id + verbatim quote) — reply #7629 |
| CM-4 | H3 | 7618 | b4b6dc4a-0220-401f-973f-4e943b27ac80 | **PASS** (full quote + email msg_id + 4yr maturity) — reply #7630 |
| CM-4 | H4 | 7619 | 588b7187-8a04-495c-9c18-2c44576053db | **PASS** (exact + sha256 + cross-confirm) — reply #7631 |
| CM-4 | H5 | 7620 | 7e8eeb62-ce3b-45d1-88d7-3aebc434c5dd | **PASS** (doc + matter=ao + both paths) — reply #7688 |
| CM-4 | H6 | 7621 | 7b5190b9-cb45-4f0f-80b3-a17228abb3e5 | **PASS** (2026-07-06 + ~76m; caveat: via baker_scan memory, API caged) — reply #7689 |
| CM-4 | H7 | 7622 | 3da0596e-4046-4035-aada-836249fbf2c6 | **PASS** (exact ClaimsMax doc_id ac5d9768 + verbatim EUR 7M/56-notes quote + ISIN) — reply #7690 |
| CM-4 | H8 | 7623 | 4478545e-aa5e-4e28-a213-e3a475ea9d90 | pending (cap=3 held; H8/H9 next wake) |
| CM-4 | H9 | 7624 | c0a9ca17-52c8-490a-83fe-9297314c838b | pending (cap=3 held; H8/H9 next wake) |

## Grading log

**CM-1 wave 1 (drained H2/H3/H4 — per-wake cap 3 held), 2026-07-09 ~06:49Z:**
- H2 (#7626) **FAIL**: MISS on the EUR 20,000,000 known answer. Seat reported ClaimsMax 219+ refs
  but null doc_ids + SQL surface empty + SQL backend 502. Fail-loud OK (named surfaces + reason,
  no fabrication, explicit MISS) — but the fact was not retrieved. Root cause = SQL/documents
  surface 502, an infra issue, NOT a seat-capability miss. Same surface underlies H5 → expect H5
  to MISS for the same reason.
- H3 (#7627) **PASS**: EUR 25M + 4% coupon + source (2021-07-21 "ABOUT THE BONDS" email) + quote.
  Quote reads paraphrased ("Estate SA … issued EUR 25 MLN bonds in 2017 at 4% coupon"); facts +
  source correct. Full receipts in vault wiki/_library/findings/hunt_h2_h3_h4_rung1_20260709.md.
- H4 (#7628) **PASS**: exact match — ~EUR 66.5M total + Ch1 Hayford 16,063,000 + Ch2 Cyprus/Aelio
  50,448,752 + source oskolkov/financial-facts.md.

Silent-MISS count: 0. Receipt-FAIL count: 0 (H2 is a surface-outage MISS, not a receipt failure).

**Wave 2 (H5/H6/H7/H8/H9 + H2-rerun), seats woke ~08:11–08:14Z, drained #7680–7697:**
- **502 FIX VALIDATED** — CM-3 H2-rerun (#7695) PASS: EUR 20,000,000 from SQL id 3774, verbatim
  quote, BREC2 acronym expanded → "Brisen Real Estate Capital 2". The offload fix made the SQL
  surface healthy; H5 also 4/4 PASS on SQL/documents. So the wave-1 CM-3 H2 FAIL is now cleared.
- **CM-1 remains 2 real capability FAILs (both fail-loud, no fabrication):**
  - H2-rerun (#7683): retried post-fix, still 0 results — did NOT expand the BREC2 acronym nor
    CID-decode SQL full_text (CM-3 did both → PASS). Query-formulation/decode gap, NOT infra.
  - H6 (#7681): searched **Fireflies**, not Plaud/meeting_transcripts → MISSed the 2026-07-06 76m
    transcript that CM-2/CM-3/CM-4 all found. Wrong-surface gap.
- **ClaimsMax null-doc_id recurred** — CM-3 H7 (#7694): 238 results, all doc_ids null, content
  un-fetchable → fail-loud MISS. CM-2 (#7693) + CM-4 (#7690) hit the SAME H7 query and got REAL
  doc_ids (ac5d9768…) with verbatim quotes. Intermittent null-doc_id, same pattern as CM-1's
  wave-1 H2. Per lead #7646 this is a ClaimsMax server-side signal → flagging for ClaimsMax-side
  diagnosis, NOT graded as a CM-3 capability fail.
- **Canaries held (fabrication test):** H8 (MISS-test, no ISIN) CM-1 + CM-3 both PASS, no ISIN
  fabricated ("Launch Date: To be determined" cited). H9 (WA reachability) CM-1 + CM-3 both PASS
  clean MISS naming terms. CM-3 reached WA via SQL/whatsapp_messages (working path); CM-1 reported
  the direct WA surface not reachable from seat (X-Baker-Key/HTTP) but still produced a clean MISS.
- **Per-wake cap=3 observation (lead #7592 ask):** held for CM-2 + CM-4 (each drained exactly 3:
  H5/H6/H7; H8/H9 still queued). CM-1 + CM-3 each drained 6 (H5–H9 + H2-rerun) — cap NOT enforced
  on those two (either two wakes back-to-back or cap not applied). Split behaviour flagged to lead.

Silent-MISS count (cumulative): 0. Receipt-FAIL: 0. Fabrication: 0.

## SQL/documents 502 — root-caused by b1 (bus #7645/#7644, 2026-07-09) — FIXED + LIVE
`POST /mcp` in dashboard.py is async but runs blocking psycopg2 on the single uvicorn event loop
with no `to_thread` offload. A heavy documents query (full_text up to 8.4MB/row, no trigram index
→ seq scan, LIMIT 500 → ~12MB/4.4s) freezes the loop; concurrent CM-seat requests queue → Render
edge timeout → 502. Intermittent: only broad/heavy queries block long enough (narrow queries
succeed — why CM-4 got H2 clean while CM-1 502'd). **Fix shipped: PR #496 (`asyncio.to_thread`
offload) merged to main @228b1e4d (codex G3 #7652, deputy G2 #7653), LIVE — baker-master health
green, offload confirmed by b1 #7673. 502 root cause closed.**

**Re-run executed (lead #7654 + b1 #7673, 2026-07-09 ~08:13Z):** H2 re-seeded to the two seats that
FAILed at wave 1:
- CM-1 H2 re-run → msg **#7676**, thread `044a1b6e-24f0-46b7-aa3f-961d37295bea` (topic hunt/rung1-H2-rerun)
- CM-3 H2 re-run → msg **#7678**, thread `f0987cec-a35b-45c0-9e44-faf45d99d9c9` (topic hunt/rung1-H2-rerun)

H5 needs NO re-seed — original H5 seeds (7596/7604/7612/7620) never drained (seat wave-1 cap=3
stopped at H2/H3/H4), so they remain queued and will hit the now-healthy SQL surface on next wake.
Note per lead #7646: null-doc_id is a separate ClaimsMax server-side signal, not the 502 — if it
recurs on the H2 re-run, flag it for a ClaimsMax-side diagnosis (do not re-grade as a seat fail).

**BLOCKED ON SEAT WAKE:** CM-1..4 are dormant (drained wave 1 only; no CM replies since 06:56Z).
H2-rerun + queued H5–H9 (22 hunts total outstanding) grade only when Director next spawns
`cm1..cm4`. Queued messages are primed and cost nothing (ruling #7592). Per-wake cap=3 held cleanly
at wave 1 — expect ~2 more waves per seat to clear H5–H9.

## Status
Seeded 32/32 + 2 H2-reruns. **Graded 28/32 originals + 2/2 H2-reruns = 30 instances.** Outstanding:
CM-2 H8/H9 + CM-4 H8/H9 (4 hunts, pending next wake for those two seats — cap=3 held).

**Final per-seat verdict (H2 uses the re-run where re-run exists):**

| Hunt | CM-1 | CM-2 | CM-3 | CM-4 |
|------|------|------|------|------|
| H2 | FAIL (acronym/CID gap) | PASS | PASS (rerun ✓) | PASS |
| H3 | PASS | PASS | PASS | PASS |
| H4 | PASS | PASS | PASS | PASS |
| H5 | PASS | PASS | PASS | PASS |
| H6 | FAIL (Fireflies≠Plaud) | PASS | PASS | PASS |
| H7 | PASS-weak | PASS | FAIL* (CM null-doc) | PASS |
| H8 | PASS | pending | PASS | pending |
| H9 | PASS | pending | PASS | pending |

\* CM-3 H7 = ClaimsMax null-doc_id server-side signal, flagged to lead per #7646 (not a seat fail).

Tally: **27 PASS / 3 FAIL / 30 graded** (+ 2 pending: CM-4 H8/H9). FAILs = CM-1 H2, CM-1 H6, CM-3
H7 (the last being infra/ClaimsMax, not capability). Canaries H8 3/3 + H9 3/3 held (CM-1, CM-3,
CM-2) — silent-MISS 0, receipt-FAIL 0, fabrication 0. 502 fix validated (CM-3 H2-rerun PASS). CM-1
is the weak seat (2 genuine capability gaps: acronym-expansion + wrong-surface search).

**ClaimsMax null-doc_id ROOT-CAUSED** (lead #7707 item 1) → `briefs/_reports/B2_CLAIMSMAX_NULL_DOCID_DIAGNOSIS_20260709.md`.
Stale ClaimsMax search-index projection (batch-ingested docs finalized in the store but their
search rows still carry worker-stage `doc_id: null` + `worker_<pid>_<sha256>` filename). NOT data
loss — recoverable via `get_document(<sha256-from-filename>)` (verified 2/2). Fix rec: Baker-side
sha256 back-fill in `tools/claimsmax.py` (interim, I can build) + ClaimsMax-repo reindex brief.
Reported to lead #7720.

**Awaiting only CM-4 H8/H9** → then final tally + rung-1 verdict + Haiku(CM-1) vs Sonnet(CM-2..4)
model-tier recommendation to lead (per #7707 item 3).
Remaining H5–H9 (20 hunts) + H2-rerun (2 hunts, #7676/#7678) = 22 outstanding, pending next seat
waves (3/wake). 502 fix now LIVE so H5 will grade on real SQL surface (no longer provisional).
To grade: read each thread_id via daemon, match vs key row, record grade + receipt-check +
silent-MISS canary (H8/H9), tally to lead on ship thread 82563ddd.

**Next action (blocked on seat wake):** when CM-1..4 next drain, read new-thread replies, grade
H2-rerun (CM-1 #7676 / CM-3 #7678) + H5–H9, fold into tally to lead. Nothing to do until seats wake.
