# B1 REPORT — BAKER_OS_V2_MOVIE_DATA_PREFLIGHT_1

- **Brief:** `briefs/_tasks/BAKER_OS_V2_MOVIE_DATA_PREFLIGHT_1.md` (dispatched_by: lead; main @78c69a4e)
- **Reply-to:** lead + movie-desk (bus topic `movie-flight/data-preflight`)
- **Matter:** `movie` (⚠ **NOT a canonical slug** — it is an *alias* of `mo-vie-am`; see H1)
- **Precedent mirrored:** `B1_BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1_20260707.md` (same checks, matter `ao`)
- **Date:** 2026-07-09 · **Class:** diagnostic/verification, READ-ONLY · **POST_DEPLOY_AC:** N/A (no deploy)
- **Manifest used:** DRAFT participant families from the brief (MOHG op team incl. `mhabicher@mohg.com`, RG7 GmbH, LCG SA, `rolf.huebner@brisengroup.com`/Vienna office, Moravcik). movie-desk's `manifest/MOVIE` is the confirmed list — **delta re-run owed when it posts** (see §Delta).
- **Data as-of:** prod read via `baker_raw_query` (live pooled `/mcp`), 2026-07-09 ~11:50–12:00 UTC.

## Bottom line
Raw ingestion for the MOVIE participant families is **deep and fresh** — the Aukera seed-window truncation class does **NOT** reproduce (post-2026-07-04 reseed corroborated). The AO precedent's 14 future-dated `bluewin` rows are also **gone** (data-quality PASS). The launch risk is the *same as AO*: **matter-identity fragmentation.** MOVIE has no `movie` tag — its data is split across `mo-vie-am` / `mo-vie-exit`, spills into `hagenauer-rg7` (RG7 GmbH is the MOVIE property company), and sits partly untagged. Any launch that filters on a single `matter_slug='movie'` returns **zero**. Three HIGH items (H1 slug, H2 registry, H3 tagging) should be reconciled before the MOVIE flight go-live (which stays behind the C3/T2 gate anyway).

## Findings table

| # | Check | Method | Result | Gap? | Severity |
|---|-------|--------|--------|------|----------|
| H1 | Canonical slug identity | `slugs.yml` grep + `matter_slug` distribution on `meeting_transcripts` | **No canonical `movie` slug.** `movie` is an *alias* of `mo-vie-am` (`slugs.yml:38`). Canonical family: `mo-vie-am` (asset mgmt), `mo-vie-exit` (sale/exit), `mo-prague` (**separate** — Prague, not Vienna). Brief/flight key on `movie`; transcripts tagged `mo-vie-am`(12)/`mo-vie-exit`(14), **zero as `movie`**. | **YES** — `WHERE matter_slug='movie'` → 0 rows. | **HIGH** |
| H2 | `matter_registry` ↔ participant parity | rows id=7 + id=6 vs draft participant families | Registry id=7 "Mandarin Oriental Asset Management" + id=6 "Mandarin Oriental Sales" carry **only Rolf Hübner + Edita Vallen** as `people`. **MOHG op team (mhabicher), RG7 GmbH, LCG SA, Moravcik all ABSENT.** Both rows share identical `keywords` (`mandarin oriental / MO`) + `projects` (`mandarin-oriental`). | **YES** — registry-driven routing under-captures ≥4 participant families; keyword-routing **cannot separate AM from Exit** (identical keys). | **HIGH** |
| H3 | Matter tagging (transcripts/email/WA) | schema + `matter_slug` group-by + cross-tag counts | `email_messages` + `whatsapp_messages` have **no `matter_slug` column** (tagging is derived). `meeting_transcripts`: **26 MOVIE tagged** (`mo-vie-am` 12 + `mo-vie-exit` 14, none `movie`); **71 untagged**, of which **8 are MOVIE-relevant** (mention mandarin/mohg); **35 `hagenauer-rg7`**, of which **11 mention mandarin/mohg** (RG7 = MOVIE property co, legit cross-lane). | **YES** — any single-slug filter under-captures; RG7 (a MOVIE participant) is an alias of `hagenauer-rg7`, so RG7 traffic routes to the Hagenauer lane. | **HIGH** |
| 1 | Seed-window email coverage | per-family count + min/max `received_date` | MOHG-domain **911** (2014-06→2026-07-06); Rolf Hübner **388** (2018→2026-07-09); Vienna office **568** (2017→2026-07-07); mhabicher **33** (2024-09→2026-07-03); Moravcik **1109** (2020→2026-07-09); "mandarin oriental" body **7851** (2012→2026-07-08). Deep history, no truncation. Corroborated by `graph_mail_poll:seed_lookback_reseed_v1` @2026-07-04. | **NO** (PASS) | — |
| 1b | LCG SA coverage window | body `%lcg sa%`/`@lcg%` + WA | Email **108**, but max `received_date` **2026-05-14** (~8-week drop-off). LCG WhatsApp presence strong (**381**). | **WATCH** — verify no post-May email drop-off (may be legit low-traffic holding co). | **LOW** |
| 1c | RG7-subject coverage window | subject/sender `%rg7%` | **4674** hits, max `received_date` **2026-06-22** (~2.5 wk). Broad substring (RG7 GmbH is the property co). | **WATCH** — confirm no recent-window gap (likely just no RG7-subject email since 06-22). | **LOW** |
| 2 | Subject-family completeness | subject-level FILTER counts | All retrieve: "mandarin oriental" **4079**, mo vie/movie **1927**, residences **3158**, LCG **1846**, RG7 **4674**, forecast/budget **509**, MOHG **350**, hotel-ops (occupancy/revpar/f&b/adr) **186**. | **WATCH** — hotel-ops subjects thin (186); ops metrics likely live in attachments/MOHG reports, not subjects. No deal-codes supplied → NOT CHECKED. | **LOW** |
| 3 | Ticketing classification | `airport_tickets` group-by | 252 tickets: suspected `lilienmatt` **237** / null 9 / `ao` 5 / `hagenauer-rg7` 1. **Zero `movie`/`mo-vie-*`. `final matter_slug` NULL on all.** No MOVIE tickets classified. | **YES** — MOVIE has no ticketing footprint yet; lane dominated by `lilienmatt`. | **MEDIUM** |
| 4 | Non-mail presence (Plaud/WA) | transcript + WA scans | WA presence strong + fresh: mandarin/mohg **246**, LCG **381**, Moravcik **45**, habicher 2, huebner 1 (Rolf is email-heavy); latest WA **2026-07-09 11:16**. Plaud transcripts: 26 tagged MOVIE + 8 untagged candidates. WA has **no `matter_slug`** (presence-only). | **WATCH** — presence OK; matter-tagging gap rolled into H3. | **LOW/MED** |
| 5 | Watermark freshness | `trigger_watermarks` + per-source max-ts | Email (`email_poll`, `graph_mail_poll`, `bluewin_poll`), Plaud, Dropbox all **fresh today ~11:57**. `airport_ticketing:{whatsapp,plaud}` = 07-08/07-06 are lane-consumer cursors (not ingestion staleness). `exchange_poll` frozen **2026-06-02** (expected — M365 cutover). `todoist` 2026-06-24. | **WATCH** — `exchange_poll` frozen (expected); `todoist` ~2 wk (not MOVIE-critical). | **LOW** |
| 6 | Data quality — future dates | `count FILTER (received_date > now())` per source | **Zero future-dated rows** across `bluewin`/`email`/`gmail`/`graph`. The AO precedent's 14 future-dated `bluewin` rows are **no longer present** (fixed since 2026-07-07). | **NO** (PASS — regression cleared) | — |

## Reproducible pointers (per gap)

- **H1 slug:** `grep -nE "slug: (movie|mo-vie|mo-prague)" ~/baker-vault/slugs.yml` → `mo-vie-am` (`:35`, aliases incl. `movie`), `mo-vie-exit` (`:107`), `mo-prague` (`:112`). Cross-check: `SELECT matter_slug, count(*) FROM meeting_transcripts GROUP BY 1` → `mo-vie-exit`=14, `mo-vie-am`=12, `movie`=0.
- **H2 registry:** `SELECT id, matter_name, people, keywords, projects FROM matter_registry WHERE matter_name ILIKE '%mandarin%';` → id=7 + id=6, `people` = {Rolf Hübner, Edita Vallen} only; identical `keywords`/`projects`.
- **H3 tagging:** `SELECT matter_slug, count(*) FROM meeting_transcripts GROUP BY 1;` (movie=0, split across mo-vie-am/mo-vie-exit/null/hagenauer-rg7). Cross-tag: `SELECT count(*) FILTER (WHERE matter_slug='hagenauer-rg7' AND (lower(full_transcript) LIKE '%mandarin%' OR lower(full_transcript) LIKE '%mohg%')) FROM meeting_transcripts;` → 11; untagged MOVIE-cand → 8. Schema: `information_schema.columns WHERE table_name IN ('email_messages','whatsapp_messages')` → no `matter_slug`.
- **1 seed-window:** `SELECT count(*), min(received_date), max(received_date) FROM email_messages WHERE lower(sender_email) LIKE '%@mohg.com%';` → 911 / 2014-06-22 / 2026-07-06. (repeat per family: `%rolf.hu%bner%`, `%office.vienna%`, `%mhabicher%`, body `%moravcik%`.)
- **1b LCG:** `SELECT count(*), max(received_date) FROM email_messages WHERE lower(full_body) LIKE '%lcg sa%' OR lower(sender_email) LIKE '%@lcg%';` → 108 / 2026-05-14.
- **3 tickets:** `SELECT suspected_matter_slug, matter_slug, count(*) FROM airport_tickets GROUP BY 1,2;` → no movie/mo-vie; all `final` NULL.
- **5 watermarks:** `SELECT source, last_seen FROM trigger_watermarks ORDER BY last_seen DESC;` → email/graph/bluewin/plaud fresh today; `exchange_poll`=2026-06-02.
- **6 future dates:** `SELECT source, count(*) FILTER (WHERE received_date > now()) FROM email_messages GROUP BY 1;` → all 0.

## Proposals (read-only; for lead to slice as follow-up briefs — NOT executed)
1. **Decide the MOVIE flight's canonical `matter_slug` before go-live.** `mo-vie-am` (asset mgmt) is the natural key, but the flight scope may span `mo-vie-exit` too. Pick one (or an explicit `IN (...)` set), then align transcripts / retrieval filters / registry to it. `movie` as a bare filter returns 0. (H1 — blocks clean launch.)
2. **Scope a MOVIE-flight `matter_registry` entry** that names the real participant set (MOHG op team incl. mhabicher, RG7 GmbH, LCG SA, Moravcik, Rolf Hübner) and disambiguates AM vs Exit (current id=6/id=7 share identical keywords). (H2)
3. **Define the RG7 boundary.** RG7 GmbH is both the MOVIE property company and an alias of `hagenauer-rg7`. Decide whether RG7 traffic belongs to the MOVIE lane, the Hagenauer lane, or both (tag-with-context), so the 11 cross-mentioned transcripts + RG7 email don't silently land in only one. (H3)
4. **Re-tag / sweep the 8 untagged MOVIE-relevant transcripts** (mention mandarin/mohg, `matter_slug` NULL) once the canonical slug is chosen. (H3)
5. **Confirm LCG SA email drop-off after 2026-05-14** — verify it is genuine low traffic, not a source/window gap (WA stays active at 381). (1b)

## Delta re-run (owed)
Draft participant families were used. **Re-run the per-family deltas when movie-desk posts `manifest/MOVIE`** — specifically the *confirmed email domains* for RG7 GmbH, LCG SA, and Moravcik (searched here by body/name substring, not confirmed addresses) and any deal-codes for a Check-2 completeness pass. Coordinated with movie-desk (project-room build running in parallel — did not block on it).

## NOT CHECKED (and why)
- **Confirmed email domains** for RG7 GmbH / LCG SA / Moravcik — matched by body/sender-name substring only; exact addresses pending `manifest/MOVIE`.
- **Deal-code variants (Check 2)** — none supplied in the draft; needs movie-desk to enumerate.
- **Qdrant / vector-index freshness** — verified Postgres stores only, not the RAG embedding index for MOVIE retrieval parity.
- **`email_attachments` + `sent_emails` (outbound)** — inbound `email_messages` + WA checked; outbound + attachment-level presence not scanned (no `matter_slug` there either).
- **`fireflies` watermark** — not surfaced (buried below calendar-prep noise under the 60-row cap). Plaud is the live MOVIE transcript source and is fresh today, so Fireflies deprecation (flagged in AO precedent @2026-05-20) is not MOVIE-blocking.
- **Live M365 `graph` inbox vs store parity** — used stored rows; did not diff against the live Graph inbox.
- **`mo-prague` disambiguation depth** — confirmed a *separate* slug (Mandarin Oriental Prague, evaluation-stage); not scanned (out of MOVIE-Vienna scope).
- **Which registry row (id=6 vs id=7) the flight will key on** — flight config not yet built (movie-desk owns).

## Verification note
All numbers are from live `baker_raw_query` runs this session (read-only; no writes, no backfills, no re-tags — per brief Key Constraints). Queries ran through the **pooled** `/mcp` endpoint (same path just hotfixed by PR #502). No code changed; no PR. Report is the sole deliverable.
