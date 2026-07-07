# B1 REPORT — BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1

- **Brief:** `briefs/_tasks/BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1.md` (dispatched_by: lead; main @2bc85b47)
- **Reply-to:** lead + ao-desk (bus topic `baker-os-v2/b4-ao-data-preflight`)
- **Matter:** `oskolkov` (⚠ canonical slug is actually `ao` — see H1)
- **Date:** 2026-07-07 · **Class:** diagnostic/verification, READ-ONLY · **POST_DEPLOY_AC:** N/A (no deploy)
- **Manifest used:** `wiki/matters/oskolkov/02_inventory/2026-07-07-ao-flight-participant-manifest-ratified.md` (Director-ratified, 12 INCLUDE / 11 EXCLUDE). No delta re-run needed (list already final).
- **Data as-of:** prod read via `baker_raw_query` / `baker_watermarks` / `baker_health`, 2026-07-07 ~11:40–12:00 UTC.

## Bottom line
Email + WhatsApp + Plaud raw ingestion for AO participants is **fresh and historically deep** — the Aukera seed-window truncation class does **NOT** reproduce here (post-2026-07-04 reseed). The launch risk is not missing raw data; it is **matter-identity fragmentation**: the AO matter is split across four different slugs/keys (`ao`, `oskolkov`, `lilienmatt`, "Oskolkov-RG7"), so any launch that filters on a single `matter_slug` will silently under- or over-capture. Two HIGH items (H1 slug, H2 registry) should be reconciled before B6 go-live. One participant (Sudomoyeva) has zero email/WA presence.

## Findings table

| # | Check | Method | Result | Gap? | Severity |
|---|-------|--------|--------|------|----------|
| H1 | Canonical slug identity | `slugs.yml` grep + `matter_slug` distributions | Canonical slug = **`ao`** (`oskolkov` is an *alias*). Flight/brief/manifest key on `oskolkov`. Transcripts tagged `ao` (1 row); tickets suspect `lilienmatt`; registry = "Oskolkov-RG7". | **YES** — `WHERE matter_slug='oskolkov'` returns 0 transcripts; the 1 real AO transcript is under `ao`. | **HIGH** |
| H2 | matter_registry ↔ manifest parity | `matter_registry` id=15 vs ratified 12 | Registry `people` = only 3/12 manifest participants (AO, Pohanis, Vitaly); **includes manifest-EXCLUDED Edita Vallen + Siegfried**; keywords/projects pull cross-lane (RG7/LCG/Lilienmatt/Annaberg/Balgerstrasse/mandarin-oriental). | **YES** — registry-driven routing under-captures 9 participants, over-captures Baden-Baden/MOVIE. | **HIGH** |
| 1 | Seed-window email coverage | per-participant count + min/max `received_date` | Oskolkov 683 hits, **2011-10-21 → 2026-07-03**; Pohanis 1886, **2016-12 → 2026-07-03**. Deep history, no truncation. | **NO** (PASS) | — |
| 1b | Sudomoyeva coverage | sender/subject + body + WA scan | **0 email, 0 WhatsApp, 0 tagged transcripts.** €440K fund sender per manifest. | **YES** — zero signal for a listed participant. | **MEDIUM** |
| 1c | Aelio coverage window | min/max `received_date` | Email subj/sender hits confined to **2026-01-22 → 2026-04-09** (none since April). Body hits 64. Entity is new (Cyprus vehicle), so start-date plausible. | **WATCH** — verify no post-April drop-off. | **LOW** |
| 2 | Subject-family completeness | subject-level FILTER counts | Villa Gabbiano **3** subj / 4 WA; capital call 24; shareholder loan 34; participation agreement 9; Aelio 23. All retrieve. | **WATCH** — Villa Gabbiano low (body richer). Deal-codes NOT supplied → NOT CHECKED. | **LOW** |
| 3 | matter tagging (email/WA) | schema inspection | `email_messages` and `whatsapp_messages` have **no `matter_slug` column** — tagging is derived (registry keywords/people or ticketing), not stored. So H1/H2 ARE the email/WA tagging surface. | **YES** (structural) — see H1/H2. | **HIGH (rolled into H1/H2)** |
| 3b | ticketing classification | `airport_tickets` group-by | 133 tickets: suspected `lilienmatt` 126 / `hagenauer-rg7` 1 / null 6. **Zero `ao`/`oskolkov`. `final matter_slug` NULL on all 133. `registry_version`/`classification_version` NULL on all.** AO-adjacent (Lana/Lilienmatt) traffic routes to the excluded `lilienmatt` lane. | **YES** — AO↔lilienmatt boundary unverified; no manifest-version stamping. | **MEDIUM** |
| 4 | Non-mail presence (Plaud/WA) | transcript + WA scans | WhatsApp AO presence strong (Oskolkov 218, Pohanis 704, Aelio 69, Lana 52) & fresh (latest 2026-07-07 10:44). Plaud transcripts through 2026-07-06. **AO-dedicated transcripts = 1** (`ao`); 75 untagged; AO co-mentions mostly tagged `hagenauer-rg7` (legit cross-lane). | **WATCH** — WA has no matter_slug (presence-only); AO-dedicated transcript coverage thin. | **LOW/MED** |
| 5 | Watermark freshness | `baker_watermarks` + max-ts per store | Email (`email_poll`, `graph_mail_poll`, `bluewin_poll`) fresh today. Plaud raw fresh (11:39). WA raw fresh (10:44). AO Dropbox folder polled today. **`fireflies` frozen 2026-05-20**; `exchange_poll` frozen 2026-06-02 (expected — M365 cutover). `airport_ticketing:plaud`=06-22, `:whatsapp`=06-12 are lane-consumer cursors, not ingestion staleness. | **WATCH** — Fireflies stopped ~May 20; confirm intended (Plaud superseded). | **MEDIUM (Fireflies)** |
| 6 | Data quality — future dates | count `received_date > now()` | **14 `bluewin` rows future-dated** (max 2035-07-28). Sibling class to the Aukera seed-window bug — poisons max-date/window math. (614 pre-2010 `graph` rows = benign archive.) | **YES** — small but corrupts window logic. | **MEDIUM** |

## Reproducible pointers (per gap)

- **H1 slug:** `grep -nE "slug: (ao|oskolkov)" ~/baker-vault/slugs.yml` → line 40 `slug: ao`, `aliases: [oskolkov, ...]`. Cross-check: `SELECT matter_slug, count(*) FROM meeting_transcripts GROUP BY 1` → `ao`=1, `oskolkov`=0.
- **H2 registry:** `SELECT people, keywords, projects FROM matter_registry WHERE id=15;` → compare to manifest's 12 INCLUDE.
- **1b Sudomoyeva:** `SELECT count(*) FROM email_messages WHERE lower(full_body) LIKE '%sudomoyeva%' OR lower(full_body) LIKE '%судомоева%';` → 0. Same pattern on `whatsapp_messages.full_text` → 0.
- **3b tickets:** `SELECT suspected_matter_slug, matter_slug, registry_version, count(*) FROM airport_tickets GROUP BY 1,2,3;` → no `ao`/`oskolkov`, all `final`/`registry_version` NULL.
- **5 Fireflies:** `SELECT source, last_seen FROM trigger_watermarks WHERE source='fireflies';` → 2026-05-20. `SELECT max(meeting_date) FROM meeting_transcripts WHERE source='fireflies';` → 2026-05-19.
- **6 future dates:** `SELECT source, count(*) FILTER (WHERE received_date > now()) FROM email_messages GROUP BY 1;` → bluewin 14.

## Proposals (read-only; for lead to slice as follow-up briefs — NOT executed)
1. **Reconcile the AO canonical slug before B6.** Decide `ao` (canonical) vs `oskolkov` (alias) as the flight's `matter_slug`, then align transcripts / ticketing / registry / retrieval filters to it. (H1 — blocks clean launch.)
2. **Scope a dedicated AO-flight `matter_registry` entry** matching the ratified 12 (drop Edita/Siegfried; move RG7/LCG/Lilienmatt/Annaberg/Balgerstrasse/mandarin-oriental keywords to their own lanes). (H2)
3. **Confirm Irina Sudomoyeva's email identity** or mark her document-only (bank/transfer records) — currently invisible to any name-keyed retrieval. (1b)
4. **Verify the lilienmatt↔AO ticketing boundary** and wire the classifier to stamp `registry_version`/`classification_version` once the AO manifest loads. (3b)
5. **Repair the 14 future-dated `bluewin` rows** (clamp/quarantine) and **confirm Fireflies deprecation** (else AO meetings via Fireflies are lost after 2026-05-20). (5, 6)

## NOT CHECKED (and why)
- **Deal-code variants (Check 2):** the manifest/brief did not enumerate AO deal codes; only Villa Gabbiano is a known asset. Needs ao-desk to supply codes for a completeness pass.
- **Qdrant / vector-index freshness:** verified Postgres stores only, not the RAG embedding index for AO retrieval parity.
- **email_attachments coverage:** attachment-level presence not scanned.
- **sent_emails (outbound):** inbound `email_messages` + WA checked; outbound-to-participant cross-check not run (no `matter_slug` there either).
- **Live M365 `graph` inbox vs store parity:** used `provider=store`; did not diff against the live Graph inbox.
- **Ambiguous-substring exact identities (Lana/Ania):** counts retrieve but are substring-noisy (e.g. "Romania"/"Lithuania" for `ania`); exact per-person email addresses were triaged only for Merz (→ `merz-recht.de` legit, Commerzbank 43 = noise).

## Verification note
All numbers above are from live `baker_raw_query` runs this session (read-only; no writes, no backfills, no re-tags — per brief Key Constraints). No code changed; no PR. Report is the deliverable.
