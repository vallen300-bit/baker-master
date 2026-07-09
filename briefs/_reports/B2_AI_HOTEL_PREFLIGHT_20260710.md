# B2 — AI Hotel Flight Data Preflight (AI-HTL-001)

- **Brief:** `AI_HOTEL_FLIGHT_DATA_PREFLIGHT_1` @ `cff884a2` (main)
- **Dispatched by:** lead (bus #8265, topic `flight/ai-htl-001`)
- **Task class:** diagnostic / read-only sweep. Harness-V2: N/A (report-only, no production code).
- **Date:** 2026-07-10
- **Scope:** AI Hotel family only (NVIDIA + MOHG, Silicon Valley). MO Prague out of scope (noted where encountered, not swept).
- **Method:** read-only. Email via `baker_email_search` + read-only SQL over `email_messages`. WhatsApp via `GET /api/whatsapp/messages`. Transcripts via `GET /api/transcripts/by-matter/{slug}` + read-only SQL over `meeting_transcripts`. Vault via room `_people.md` + `02_inventory/` reads. No writes to any store, vault, or ClickUp.

---

## Headline (for the manifest/registry fold)

1. **Do NOT read transcripts through the `by-matter/{nvidia-*}` endpoint.** All four nvidia-family slugs return ~0 transcripts (`nvidia`=3, of which 2 real + 1 mis-tagged; the three siblings = 0). The ~31–37 genuinely on-topic AI-Hotel transcripts are tagged to `baker-internal` / `mo-vie-exit` / `personal` / `hagenauer-rg7` / `austrian-tax` / etc. The classifier never assigned a nvidia-family slug to any of them. **HIGH.**
2. **Pin ONE canonical spelling of Sergey.** Three spellings live across systems: brief "Krainii" / email "Krayniy" / WhatsApp + vault "Kraynii". Same person (US mobile +1 860 309 9075, gmail). **HIGH.**
3. Email keyword sweep must use the **tight 2026 NVIDIA-intersection predicate**, not raw "Mandarin Oriental" (8,068 hits) / "MOHG" (3,457 hits) — those are dominated by MO Vienna hotel history back to 2010. **LOW (method note).**
4. Two raw-store participants are **absent from all four rooms**: Alex Bena (`info@lps-china.com`) and Blaschka Arndt (`A.Blaschka@eh.at`, E+H). **MED / LOW.**

The rooms are otherwise mature: 18-person cast Director-ratified via Triaga 2026-06-01; the room's own `02_inventory/2026-06-13-supplementary-sweep-*` already found the transcript scatter — but the underlying `matter_slug` tags were never corrected, so the live data layer still misses them.

---

## AC1 — Per-channel counts + date ranges, per participant

### Email — `email_messages` store (Gmail + Bluewin + M365/graph merged)

Raw keyword totals (all-time, whole store) — showing the over-match trap:

| Keyword | Hits | Date span |
|---|---|---|
| mandarin oriental | 8,068 | 2012-04-13 → 2026-07-08 |
| mohg | 3,457 | 2010-12-08 → 2026-07-09 |
| nvidia | 663 | 2022-01-26 → 2026-07-09 |
| silicon valley | 356 | 2020-12-21 → 2026-07-08 |
| santa clara | 98 | 2021-08-17 → 2026-07-09 |
| ai hotel | 29 | 2016-11-02 → 2026-07-09 |
| ellie technologies | 9 | 2026-02-19 → 2026-06-01 |
| krainii (name) | 2 | 2026-05-31 |

**Tight AI-Hotel set** (2026-only, `nvidia AND (hotel|mandarin|mohg|corinthia)` OR `ai hotel` OR `krayniy` OR `ellie technolog`): **91 emails, 2026-01-07 → 2026-07-09, 19 distinct senders** (~9 are newsletter noise → ~82 deal-relevant). Per-sender (sender-side only; see AC3 blind spot):

| Sender | Email | Org | n | Sources | Span |
|---|---|---|---|---|---|
| Raphael Bick | rbick@mohg.com | MOHG | 8 | email, graph | 2026-05-28 → 07-06 |
| Peter Storer | pestorer@nvidia.com | NVIDIA | 8 | email, graph | 2026-03-16 → 05-28 |
| Sergey Krayniy | sergey.krayniy@gmail.com | (verify) | 6 | email, graph | 2026-04-07 → 06-14 |
| Jasmyn Jarnigan | Jasmyn@higgsfield.ai | Higgsfield AI | 3 | graph | 2026-03-16 → 03-18 |
| Alex Bena | info@lps-china.com | LPS China | 3 | email, graph | 2026-05-26 → 07-09 |
| Blaschka Arndt | A.Blaschka@eh.at | E+H (counsel) | 2 | email, graph | 2026-03-16 |
| Philip Vallen | philipvallen@ellietechnologies.co.uk / pvallen@protonmail.com / philip.vallen@brisengroup.com | Ellie Technologies / Brisen | 8 | email, graph | 2026-02-19 → 06-01 |
| Dimitry Vallen (outbound) | dvallen@brisengroup.com / vallen300@gmail.com | Brisen | ~44 | email, graph | 2026-03-11 → 06-14 |
| **Noise** (not participants) | news@nvidia.com (GTC×2), GTC_Registration@nvidia.com, reuters_ai@ / dailybriefing@thomsonreuters.com, thetimes.com, altrata.com, hotelsmag.net, evok.com | newsletters / security | 9 | graph, bluewin | 2026-01-07 → 03-19 |

### WhatsApp — `GET /api/whatsapp/messages` (contact-scoped, 2026-01-01 → 07-10, per named participant)

| Contact | sender_name | chat_id | n | Span |
|---|---|---|---|---|
| Philip Vallen | Philip Vallen | 447578191477 (+44 UK) | 125 | 2026-01-28 → 07-09 |
| Sergey | Sergey Kraynii | 18603099075 (+1 860 US) | 113 | 2026-01-13 → 04-08 |
| Bick | Raphael Bick | 85296606625 (+852 HK) | 5 | 2026-05-12 → 05-29 |
| Storer | Peter Storer | 14404760488 (+1 US) | 1 | 2026-05-13 |
| Krayniy / Jasmyn / Bena / Higgsfield / "nvidia" / "mandarin" / "mohg" | — | — | 0 | — |

WA content is **not** matter-filtered — the endpoint returns whole participant threads, so Sergey's 113 and Philip's 125 span mixed topics, only a fraction AI-Hotel (see AC3).

### Transcripts — `meeting_transcripts` (`by-matter` endpoint + full-table keyword fallback)

Live `by-matter/{slug}` (what the manifest fold will read):

| Slug | count | Reality |
|---|---|---|
| nvidia | 3 | 2 real Fireflies (Mar 17 + Mar 18, GTC window) + 1 mis-tagged YouTube ("Google's New Quantization") |
| nvidia-ai-hotel | 0 | — |
| nvidia-mohg | 0 | — |
| nvidia-corinthia | 0 | — |

Full-table keyword fallback (title+summary, on-topic) — **31 matches, none tagged nvidia-family**, scattered by current slug: `baker-internal` 11 · `mo-vie-exit` 4 · `personal` 3 · `claimsmax` 3 · `hagenauer-rg7` 3 · `mo-vie-am` 3 · `kitzbuhel-six-senses` 2 (false) · `ao` 2. The room's own 2026-06-13 full-body sweep found 37 (33 new-to-room). Marquee meeting **2026-06-17 "AI Hotel Project with Nvidia and Mandarin"** (`plaud_a167dc25…`) is tagged `baker-internal` and post-dates the 06-13 sweep — the scatter continues for new ingests.

---

## AC2 — Distinct-participant list (feeds the researcher census)

| # | Name (canonical) | Org / Role | Email(s) | WhatsApp ID | In rooms? |
|---|---|---|---|---|---|
| 1 | Peter Storer | NVIDIA — Head of Hospitality | pestorer@nvidia.com | 14404760488@c.us | ✅ `nvidia-peter-storer` (ratified) |
| 2 | Raphael Bick | MOHG — Head of Information & AI | rbick@mohg.com | 85296606625@c.us | ✅ `mohg-raphael-bick` (ratified) |
| 3 | Sergey Kraynii ⚠ | technical lead / GTC facilitator — **role + affiliation to verify** | sergey.krayniy@gmail.com | 18603099075@s.whatsapp.net | ✅ `kraynii-sergey` (ratified, ⚠ flag) |
| 4 | Philip Vallen | Brisen / Ellie Technologies | philipvallen@ellietechnologies.co.uk; pvallen@protonmail.com; philip.vallen@brisengroup.com | 447578191477@s.whatsapp.net | ✅ `vallen-philip` (ratified) |
| 5 | Jasmyn Jarnigan (aka Jasmine) | Higgsfield AI — warm-intro channel to NVIDIA Inception | Jasmyn@higgsfield.ai | — | ✅ `brisen-jasmyn-jarnigan` (ratified) |
| 6 | Dimitry Vallen | Brisen — Director | dvallen@brisengroup.com; vallen300@gmail.com | (Director) | ✅ `vallen-dimitry` |
| 7 | **Alex Bena** | **LPS China (info@lps-china.com) — role unresolved** | info@lps-china.com | — | ❌ absent from all 4 rooms |
| 8 | **Blaschka Arndt** | **E+H (eh.at) — likely counsel cc** | A.Blaschka@eh.at | — | ❌ absent from all 4 rooms |

Rostered-but-no-raw-correspondence (research targets, correctly no raw traffic): Jensen Huang, Colette Kress (NVIDIA C-suite), Laurent Kleitman (MOHG CEO), AiOla (Haramaty/Fine), Bellboy (Hefftz), Jacob Hobson (deferred), Corinthia Pisanis/Naudi (sibling lane).

---

## AC3 — Gaps + risks (rated)

- **HIGH — Transcript tagging scatter.** Zero transcripts carry a nvidia-family `matter_slug`; ~31–37 on-topic transcripts live under `baker-internal` / `mo-vie-exit` / `personal` / `hagenauer-rg7` / `austrian-tax` / `mo-vie-am` / `claimsmax`. The `by-matter/{nvidia-*}` endpoint returns ~0. The room's 2026-06-13 inventory sweep documented this in markdown but the tags were never fixed, and new ingests (e.g. 06-17 marquee meeting) keep landing on `baker-internal`. **Action:** the manifest/registry fold must source transcripts via keyword sweep over `meeting_transcripts` (title+summary+body), OR the transcripts must be re-tagged to the nvidia-family slugs before the fold. Do not trust `by-matter` for this matter.
- **HIGH — Participant identity ambiguity (Sergey).** brief "Krainii" / email "Krayniy" / WA+vault "Kraynii"; vault filenames use both "krainii" and "kraynii". One person (mobile +1 860 309 9075, sergey.krayniy@gmail.com). `_people.md` already carries a ⚠ "role + affiliation to verify" flag. Census must pin one canonical spelling and resolve role/affiliation. **NB:** transcript keyword hits on "Krainii" are FALSE POSITIVES — the Russian adjective "крайний" (last/extreme). Sergey has no confirmed transcript presence; he is an email + WhatsApp participant only.
- **MED — Reverse gap: Alex Bena / LPS China.** `info@lps-china.com`, 3 emails 2026-05-26 → 07-09, absent from all rooms and from the 06-13 sweep (transcript-only). Identity/role unresolved (possible AI-Hotel supplier vs unrelated). Census should resolve or explicitly exclude.
- **MED — WhatsApp counts are whole-thread, not matter-filtered.** Sergey (113) + Philip (125) span mixed topics; AI-Hotel share is a subset. Also Sergey's WA ends 2026-04-08 while his email runs to 06-14 — a channel handoff (WA→email), not a data gap, but the census should not read the 04-08 WA cutoff as disengagement.
- **MED — Email store is sender-only (no recipient column).** Counterparties Dimitry emailed who never replied (or whose replies weren't ingested) are invisible. Bick/Storer/Sergey are captured via their inbound replies, so the core is covered — but any silent-recipient counterparty is a blind spot the census can't see from email alone.
- **LOW — Blaschka Arndt / E+H (eh.at).** 2 emails, 2026-03-16, not in rooms. Almost certainly Austrian counsel cc'd; confirm relevance before adding to the census.
- **LOW — Fireflies native MCP keyword search is broken on this account** (documented in the 06-13 sweep: control terms that appear in summaries return zero). The `meeting_transcripts` DB / `by-matter` endpoint is the reliable transcript surface; do not use Fireflies `keyword:` search for coverage claims.
- **LOW — Keyword over-match + MO Prague bleed.** "Mandarin Oriental" (8,068) and "MOHG" (3,457) are dominated by MO Vienna hotel operations history (2010→) and some MO Prague (out of scope). Use the tight 2026 NVIDIA-intersection predicate; a raw-keyword census would drown in MO Vienna noise.

---

## AC4 — Per-store sweep status

| Store | Status | Detail |
|---|---|---|
| Email (`email_messages`) | **Swept fully** | Read-only SQL over the full table, all sources (Gmail/Bluewin/graph), all-time + tight-2026 set. No errors. |
| WhatsApp (`/api/whatsapp/messages`) | **Swept fully for the named participant set** | 11 contact queries (Storer, Bick, Sergey, Krayniy, Jasmyn, Bena, Philip, nvidia, Mandarin, MOHG, Higgsfield). 2 responses (Sergey, Philip) needed lenient JSON re-parse due to control chars in bodies — re-fetched cleanly. This is contact-scoped, NOT a whole-store scan (endpoint requires a contact filter). No errors after re-parse. |
| Transcripts (`meeting_transcripts`) | **Swept fully** | `by-matter` for all 4 slugs + full-table keyword fallback (title/summary/body). `by-matter/nvidia` needed lenient parse (control char); re-fetched cleanly. No errors. |
| Vault (rooms) | **Swept fully for rosters + inventory** | Read `_people.md` for all 4 rooms + `nvidia/02_inventory/` sweep files + file listings. Did not read every output/draft doc (out of scope for a participant/coverage preflight). |

No store reported "clean" on a skipped scan — every count above traces to an executed query.
