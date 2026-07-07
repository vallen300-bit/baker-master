# B1 REPORT — AO_FLIGHT_IDENTITY_RECONCILE_1

- **Brief:** `briefs/_tasks/AO_FLIGHT_IDENTITY_RECONCILE_1.md` (dispatched_by: lead; main @f5b89975)
- **Reply-to:** lead + ao-desk (bus topic `baker-os-v2/b4-ao-data-preflight`)
- **Predecessor:** B4 preflight `B1_BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1_20260707.md` (PR #476, merged). Warm continuation; checkpoint attempt 2.
- **Class:** data-ops + config reconcile. **Prod writes:** 2 (matter_registry id=15; email_messages bluewin ×14). **Code PR:** none (per brief gate plan — findings report; fix PRs = separate briefs).
- **Data as-of:** prod `baker_raw_query`/`baker_raw_write`, 2026-07-07 ~12:25–12:35 UTC.

## Bottom line
Two ratified data repairs executed and verified (AC2 registry reshape, AC4 bluewin future-date clamp). AC3 + AC5 delivered as reports (both are correctly out of "small code fix" territory). **AC1 is a partial + escalation:** the H1 slug fragmentation is deeper than a config annotation — the AO data is scattered across **three** slugs (`documents`=511 `Oskolkov-RG7`, `baker_insights`=3 `oskolkov`, `meeting_transcripts`=1 `ao`), so aligning config to canonical `ao` **without** a coordinated data re-tag would break the 511-doc retrieval. That re-tag is unowned, exceeds this brief's Files-Modified, and touches a Tier-B artifact (`cortex-config.md`). Escalated rather than guess-edited.

## Per-AC verdicts

| AC | Verdict | Evidence |
|----|---------|----------|
| **AC1** — flight artifacts key on `ao`, zero oskolkov data-filters | **PARTIAL / ESCALATED** | Repo-side: no `matter_slug='oskolkov'` data-filter in flight code (filters are name-based `sender_name ILIKE '%oskolkov%'` in `calendar_trigger.py:390/403`, correct; folder alias `oskolkov`→`ao` already resolved in `curated_wiki_reader.py:13`). Real oskolkov-keyed **config** lives in `baker-vault/.../oskolkov/cortex-config.md` (L4 `matter_slug: oskolkov`; L55 loads on `matter_slug='oskolkov'`; L139-140 filter `'oskolkov-rg7'`). Data reality (below) means config-only edit to `ao` breaks doc retrieval → escalated. |
| **AC2** — registry matches ratified 12, exclusions honored, keywords rehomed | **PASS** | `matter_registry` id=15 reshaped + verified: `people_has_excluded=False`, `kw_has_crossroad=False`, 12/12 people, `projects=['ao']`. |
| **AC3** — version-stamp verified or precise gap | **PASS (gap report)** | Insertion point = `orchestrator/airport_ticketing_bridge.py:1546-1572` (INSERT INTO airport_tickets); cols exist via DDL L1027-1028 but are absent from the INSERT → NULL on all rows. No version constant/source exists in the lane (grep negative). Needs version-semantics decision → follow-up brief. |
| **AC4** — 14 bluewin future rows repaired, ids logged | **PASS** | 14 rows (all `received_date=2035-07-28 03:59:59+00`) clamped → `ingested_at` (2026-06-10). Verified: 0 bluewin future rows, 0 future rows any source. Ids logged below. |
| **AC5** — lilienmatt↔ao boundary sample | **PASS (report)** | 24 of 143 `lilienmatt`-suspected tickets reference AO principals; sampled set is dominated by **Constantinos Pohanis** (dual-role). Boundary leak is at the **ticketing desk-config layer** (`suspected_matter_slug`=`_MATTER_ENV`), not `matter_registry`. |

## AC2 — matter_registry id=15 reshape (BEFORE → AFTER)

| Field | BEFORE (updated_at 2026-03-08) | AFTER (updated_at 2026-07-07 12:28Z) |
|-------|-------|-------|
| people (n) | 5 — `Andrey Oskolkov, Constantinos Pohanis, Siegfried, Edita Vallen, Vitaly` | 12 — `Andrey Oskolkov, Lana Oskolkov, Anna, Constantinos Pohanis, George Demosthenous, Masha, Irina Sudomoyeva, Katya, Sardarov, Vitaly, Merz, Aelio Holding Ltd` |
| keywords (n) | 15 (incl. crossroad RG7/LCG/Baden/Lilienmatt/Annaberg/Balgerstrasse + excluded `Siegfried`) | 42 — manifest RU/EN match-keys for all 12 + AO subjects (`capital call`, `shareholder loan`, `participation agreement`, `Villa Gabbiano`); **crossroad + Siegfried removed** |
| projects | `rg7, mandarin-oriental, baden-baden, lilienmatt` | `ao` |

**Exclusions honored:** Edita Vallen + Siegfried dropped from people; no `edita`/`siegfried` in keywords.
**Crossroad rehoming:** RG7/LCG/Baden/Lilienmatt/Annaberg/Balgerstrasse dropped from AO. `lilienmatt` already lives in id=4 (FX Mayr); `baden-baden`/`BB` in id=8; `mandarin-oriental` in id=6/7. **`RG7`/`LCG`/`Annaberg`/`Balgerstrasse` lack a clean sibling keyword home** — NOT re-inserted into another desk's matter row (cross-desk edit + would need each owner's nod). Flagged for lead: decide whether to add these to Baden-Baden (id=8) / a Hagenauer-RG7 entry.
**matter_name kept** as `Oskolkov-RG7` (renaming risks breaking name-keyed lookups in `get_matter_context`); flagged as a cosmetic inconsistency now that RG7 is rehomed out.

### Tier note (name-trigger vs coverage-key)
The manifest's tier split (3 name-triggers = standalone; 9 coverage-keys = completeness-only) is **NOT representable in `matter_registry`**: `people[]` and `keywords[]` are consumed **symmetrically** as retrieval-expansion / matter-detection terms (`memory/retriever.py:1409-1459`, `orchestrator/scan_prompt.py:244-279`). `matter_registry` is a retrieval/context surface, not a ticket-trigger surface. The tier lives in the **box5/airport lane**: env-var keywords (`active_keywords()`) = triggers; `project_registry` participant lane (dark-flag OFF, `airport_ticketing_bridge.py:356`) = identity/coverage ("participant match alone → desk review, never fast", L819). Enforcing the tier for the AO flight = a box5/project_registry config task (B6 launch), out of `matter_registry` scope.

### Substring-noise WATCH (for lead/ao-desk)
The manifest match-keys include short/ambiguous tokens now in AO keywords: `AO`, `Eli`, `Ania`, `George`, `Anna`, `Masha`. As ILIKE-substring retrieval-expansion terms these will over-match (preflight already flagged `ania`→"Romania"/"Lithuania"). Kept verbatim (manifest is Director-ratified authority on the keys); recommend a noise-tuning pass if AO retrieval precision drops.

## AC4 — 14 bluewin rows clamped (ids logged, originals preserved here)
All had `received_date = 2035-07-28 03:59:59+00:00` (spam: `Post_Tracking`/`batteryjunction.com` via amazonses). Clamped to each row's `ingested_at` (2026-06-10). message_ids:
```
ah9u9h5j2c7zjr2c-alcw909i-lzqs-j8uq-zsob-om8hv0pnez5t-000000@email.amazonses.com
ekps0jk8zqcv4lm6-pfl28rez-pphb-7vsd-e5kf-cea25gs0syut-000000@email.amazonses.com
zkvv9imtign238md-4esuf90j-iyss-pe85-zg90-xdg4g1xyzzk0-000000@email.amazonses.com
03bbmmnpqcpi4len-wgnfsnv2-uhvy-pf2c-7eod-n754kyookez0-000000@email.amazonses.com
nma0l06md4oc0dl6-h3rllc8t-zkwr-jevj-380i-uevn9ub20ib6-000000@email.amazonses.com
dw517u6makq9squm-v16y85sm-mrnk-5k7z-mxhn-ckfztj59q0jb-000000@email.amazonses.com
3d4v0pry7emh1k59-y5k5o1jd-uxpt-ubhg-k98d-1yxb31d7957s-000000@email.amazonses.com
7cm0997ywwydesxk-cxbuztpc-yctm-c5m6-0vnt-a3pspf7v7j9g-000000@email.amazonses.com
7960g7qv6uggb15e-npx0fihy-gvxs-0pgp-d9gb-n1g2mxk5h25u-000000@email.amazonses.com
fdfws67as346i37g-tmowj170-ovdu-zp8f-p9tc-xut16qq3ifvc-000000@email.amazonses.com
ma4zhbafvcbop2bf-8kfxklsq-aamd-k2yo-1o01-3ujbut3a76ta-000000@email.amazonses.com
34yix6lvw84imuhq-fx0d4jdq-mcwg-s8yf-9q8x-57sm1af3i8g5-000000@email.amazonses.com
bny5lj14iaocwn4m-2bw2dsoo-paoi-ly26-wz3b-cl14tsqnese6-000000@email.amazonses.com
4rmufpuuusig0a54-hgcg4x6m-jmyb-9lrx-cj5x-6xej3kky40rk-000000@email.amazonses.com
```
> Repair mechanism note: `email_messages` has no quarantine/status/header-date column and `raw_write` blocks DDL, so the ratified "quarantine flag" path wasn't available — clamp-to-`ingested_at` was used; originals preserved in this log. Root-cause (the bluewin date parser that produced 2035) is a **separate follow-up** — this repairs the 14 rows, not the parser.

## AC1 / H1 — the real data-slug fragmentation (ESCALATION)
`documents` = **511** rows `Oskolkov-RG7` · `baker_insights` = 3 `oskolkov` · `meeting_transcripts` = 1 `ao`. Canonical (slugs.yml) = `ao`. So the bulk data is NOT under canonical `ao`, and `cortex-config.md`'s three different filter values each match a different store (`oskolkov`→insights, `oskolkov-rg7`→docs, and note the config's lowercase `oskolkov-rg7` vs data's capitalised `Oskolkov-RG7` is itself a case-mismatch bug).

**Why not just edit the config to `ao`:** it would make Cortex Phase-2 load on `matter_slug='ao'` and filter docs on `ao` → returns ~0 documents (511 are `Oskolkov-RG7`). The fix is a **coordinated slug-unification**: re-tag `documents` (511) + `baker_insights` (3) → `ao`, align `cortex-config.md` (Tier-B, AH1-owned) + the classifier label map (`tools/document_pipeline.py:118` `'Oskolkov'→'Oskolkov-RG7'`), converged with b2's `meeting_transcripts` backfill. That spans ownership (Tier-B config + b2 transcripts) and exceeds this brief's Files-Modified.

**Decision needed from lead:** (a) target slug = `ao` for all stores? (b) who owns the `documents`/`baker_insights` re-tag + the `cortex-config.md` edit (Tier-B)? (c) sequence vs b2's transcript backfill. Coordinated with b2 on bus #6319.

## What I did NOT touch (and why)
- `baker-vault/slugs.yml` — forbidden (separate-repo PR).
- `cortex-config.md` — Tier-B (AH1-owned) + config-only edit would break 511-doc retrieval; escalated.
- Manifest frontmatter (`matter: oskolkov`) — ao-desk's room copy; folded into the AC1 escalation rather than a lone cross-desk edit.
- `documents`/`baker_insights` re-tag — unowned, out of Files-Modified.
- `meeting_transcripts` — b2 owns (coordinating, not duplicating).
- Sibling matter rows (id=4/8) — no unilateral cross-desk keyword adds.

## Verification (all live `baker_raw_query`, read-only)
- AC2: `people_has_excluded=False, kw_has_crossroad=False, n_people=12, projects={ao}`.
- AC4: `bluewin_future=0, any_source_future=0, clamped=14`.
- AC5: `lilienmatt suspected=143, AO-principal-referencing=24 (Pohanis-dominated)`.
- AC1: `documents Oskolkov-RG7=511, baker_insights oskolkov=3, meeting_transcripts ao=1`.

## AC1 — EXECUTION (post lead rulings #6325 + #6333)
Lead extended Files-Modified to me: re-tag `documents`+`baker_insights` to canonical slugs; `cortex-config` = lead (Tier-B, fires last); guard = sample-first. Guard fired → 511 `Oskolkov-RG7` is a legacy combined label (~59% AO), so split by deterministic source_path markers to slugs.yml-canonical targets (all 7 verified canonical). One atomic priority-ordered UPDATE.

**documents BEFORE → AFTER (511 total):**

| Target slug | n | note |
|-------------|---|------|
| `ao` | 301 | AO-investor (oskolkov/AO GF/AO_MASTER/AO RG7/AO CBH/AO-LCG/aelio/SPA AO markers) |
| `hagenauer-rg7` | 71 | bucket1 hagenauer/mebloform/cupial/S&K (17) + bucket7 rg7/riemergasse/BAU (54) — rg7+oskolkov-rg7 are its slugs.yml aliases |
| `mo-vie-am` | 46 | mandarin/movie/granit |
| `mrci` | 22 | mrci/balgerstrasse/mercedes (Baden-Baden) |
| `steininger` | 10 | Steininger (Kitzbühel) |
| `lilienmatt` | 4 | lilienmatt-marked |
| `annaberg` | 0 | none matched |
| `Oskolkov-RG7` (held) | 57 | **manual-pass** — see below |

Re-tagged **454**, held **57**. Verified: 7 canonical slugs sum to exactly 511 → zero pre-existing docs under these slugs (no collision), `ao`=301 (was 0).

**Deviation from lead's ratified bucket-3=39:** on inspection the 13 bare-`baden` docs were genuinely mixed (AO-RG7 meeting notes, Sosnin/MRC&I loans, Riemergasse LOI, Lilienmatt call options) and lead's sub-split only named lilienmatt/annaberg/mrci. So bucket-3 re-tagged the 26 clean matches (lilienmatt 4 + mrci 22) and the 13 baden-only went to manual-pass rather than mis-tag AO docs as Baden-Baden. Flagged.

**Manual-pass (57 held as `Oskolkov-RG7`)** = 37 unclassified + 13 baden-only + 7 EPI. Per lead: no re-tag, listing for later desk routing (not launch-blocking). Sample flags for routers: EPI/bondholders → financing; S&K/Hagenauer/RG7-defects → hagenauer-rg7; MOHG notes → mo-vie-am; Steininger/Hayford/French-Monaco corporate → their matters. NOTE a few AO-adjacent items are in here because path markers missed them (`pm/OKOLKOV_MEETING_PREP` typo, `MESSAGE_TO_CODE300_AO_BRIEF`, Ilana Oskolkova ETL letter id=64834) — so the 57 are NOT purely non-AO. Full 57-row listing (id, source_path, first line) in Appendix A below.

**baker_insights x3** — verified Lilienmatt-centric (270 Lilienmatt/MRCI 2024 FS Russian-tax EUR3M penalty; 271 AO's msg re the fine; 272 Lilienmatt shareholder meeting EUR19.65M loss). Re-tagged `oskolkov`→`lilienmatt` (270 co-references MRCI; Russian-filing entity = Lilienmatt). Verified: 0 `oskolkov` insights remain.

**Still open (flagged to lead, NOT mine to execute):**
- `cortex-config.md` slug flip (L4/L55/L139-140) → `ao` — Tier-B, lead-owned, fires last (now safe since docs are `ao`).
- Classifier label map `tools/document_pipeline.py:118` (`'Oskolkov'→'Oskolkov-RG7'`) will keep minting the combined label on NEW docs — needs a decision (map to `ao`? it can't do the path-split the bulk needed). Follow-up.
- Manual-pass 57 → desk routing.

## Appendix A — manual-pass listing (57 docs held as `Oskolkov-RG7`, id · path · first line)
```
15    email:.../Brief an Brisen _Sicherstellung.PDF               EINSCHREIBEN Brisen Development GmbH zH Edita/Dimitry Vallen (Hagenauer Sicherstellung)
42    email:.../Brief an HAG_Aufrechnungserklärung_03.03.2026     Brisen Development GmbH — Aufrechnungserklärung (Hagenauer)
92    email:.../220706-LM-TRANSPARENZREGISTER                     Transparenzregister Eingangsmitteilung (LM)
487   EPI ESTATE FUND/Summary Torbex debt restructuring/sale RG7  RESTRUCTURING OF TORBEX LOANS & SALE OF RG7 TO LCG
1610  Official Docs/СОГЛАСИЯ Осколковы.docx                       СОГЛАСИЕ (Oskolkov/Ilana consent, Izhevsk) — AO-family
2072  INTERNAL DRAFTS/History of Transactions AO and Baden        AO + Baden accounts transaction history — AO-investor
2308  Loan Brisen Capital GSM to VS & IO/Amendment                Amendment to Loan Agreement (Ilana Oskolkova/Sosnin/GSM) -> mrci?
3272  1. HISTORY/PHOTO-2020...jpg                                 Clemens Krause WP transcription — AO
3975  Loan .../Shareholder Loan Assignment (Oskolkova) exec       Shareholder Loan Receivables Assignment (MRC&I) -> mrci?
4105  2020/Confirmation Oskolkov 2020-10-13                       Confirmation Oskolkov + Lilienmatt/Opus -> lilienmatt?
4116  Loan .../2020.09.28 Loan Agreement Amended                  Loan Agreement A&R (Ilana/Sosnin/GSM) -> mrci?
5080  Loan .../Shareholder Loan Assignment EXECUTED               Shareholder Loan Assignment (MRC&I) -> mrci?
6060  AO RG7/PREPARING NOTES 30 AUG 18 MEETING BADEN              Contract for sales AO RG7 — AO/rg7
6087  AO_RG7_pre-2025/PREPARING NOTES ... MEETING BADEN           (dup of 6060) — AO/rg7
7769  AO RG7/Talking Points 2018 Aug 30 Baden meeting            AO RG7 talking points — AO/rg7
8009  Development Agreement/Riemergasse LOI Brisen exec           Riemergasse LOI (LCG/UBM) -> hagenauer-rg7
8449  2020/Charterd Investment Germany Call Option               Options-Vereinbarung (Ilana/Sosnin/Lilienmatt) -> lilienmatt
8618  email:.../260217_Projection Completion.xlsx                1029 RG7 Project Completion/Defects -> hagenauer-rg7
8621  email:.../invoice-brisen-ellie(2).pdf                      Ellie Technologies invoice (Baker/ops)
8633  email:.../Baker_vs_Ava_Reconciliation.pdf                  Baker vs Ava reconciliation (ops)
14770 email:.../DRAFT_action(1249821.2).docx                     Court draft action (Hagenauer/Mebloform litigation) -> hagenauer-rg7
23344 email:.../ET-2026-003.pdf                                  LCG Services Immobiliers (Ellie Tech invoice)
44620 Hayford Old/MW comments re Hayford to KPMG 11 Feb 2020     Hayford/KPMG — financing
44715 Meeting Minutes/Note 11 Oct 2019                           AGENDA RG7 BAU -> hagenauer-rg7
44743 Hayford/MW comments re Hayford to KPMG                     (dup of 44620) Hayford/KPMG
46167 to MOHG/BALAZS LTR TO FRANCESCO                            Balazs to MOHG KYC -> mo-vie-am
46169 to MOHG/Balazs to MOHG                                     (dup) -> mo-vie-am
46212 LCG expenses/2018-11-20 Facture 10312                      Gantey/LCG expense
46340 EPI - Letter to bondholders/EPISCA                         EPI bondholders letter — financing
46352 LCG expenses/Gantey 2017.12.28                             Gantey/LCG expense
46374 Hayford Old/HAYFORD BS DRAFT 2016                          Hayford balance sheet
46436 EPI - Letter to bondholders/EPI_Letter                     EPI bondholders — financing
46469 Legal Docs/PROPOSED LETTER TO ALRIC                        Letter to Alric (Ofenheimer/litigation)
46538 WURZINGER/Note 22 Nov 2017                                 BAU Financing mandate terms -> hagenauer-rg7
46544 to MOHG/Note 23 May 2019                                   MOHG note -> mo-vie-am
46745 INCOME DRAFT 2020/RECEIVABLE 2020                          GSM SA receivables 2020
46849 to MOHG/Note 28 May 2019                                   MOHG note -> mo-vie-am
47264 to MOHG/Note 2 Jun 2019                                    MOHG note -> mo-vie-am
47341 Estate Notes/EPISCA bondholders                            EPI bondholders — financing
47381 03. Corporate Information/Reunion parts une seule main     Monaco/French corporate (Helico?)
47440 22_07_22 MW/Pièce 70.pdf                                   Performance Fee Agreement (Hayford/Torbex)
47655 EPI 2024/Estates Notes RG7 Interest 31.12.2020            Estates Notes RG7 interest — financing/rg7
47713 03. Corporate Information/PV CHANGEMENT DE GERANCE         French/Monaco corporate PV
47715 03. Corporate Information/PV TRANSFERT PARTS               French/Monaco corporate PV (Helico)
47760 ESTATE NOTES & EPI/Estates Notes RG7 Interest             (dup 47655) — financing/rg7
49867 Agreements/Loan Agreement DV:KO 25.02.2022                 Loan Agreement DV / Konstantin Oshepkov
50005 ESTATE NOTES & EPI/EPISCA bondholders                     EPI bondholders — financing
50200 1989-2013/DV SoW 2019 11 05                                DV Source of Wealth — Vallen wealth
50540 Organization/2018.11.05 MoU LCG Mr R                       MoU LCG/Riemergasse -> hagenauer-rg7
50709 03. Corporate Information/PV registered_Helico             Helico (Monaco) corporate PV
64834 email:.../RE_2025251600.pdf                                Ilana Oskolkova / ETL Weippert (German tax) — AO-family
78249 _archive/SK_Bankruptcy_Cost_Analysis                      S&K insolvency cost analysis -> hagenauer-rg7
78250 _archive/SK_Bankruptcy_Cost_Analysis.md                   (dup) S&K insolvency -> hagenauer-rg7
78285 gmail/gmail_threads.json                                   FW 1029 RG7 Access to Excel -> hagenauer-rg7
78953 pm/OKOLKOV_MEETING_PREP_PROTOCOL.md                        AO meeting prep protocol — AO (marker missed: 'OKOLKOV' typo)
79899 pm/PM_HANDOVER_SESSION_E.md                                AO PM handover — AO
79919 pm/MESSAGE_TO_CODE300_AO_BRIEF.md                          AO profiling brief — AO (marker missed: 'AO_' underscore)
```
