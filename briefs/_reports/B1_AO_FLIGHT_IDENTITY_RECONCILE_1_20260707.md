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
