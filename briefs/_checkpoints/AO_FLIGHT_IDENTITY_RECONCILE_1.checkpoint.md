---
brief_id: AO_FLIGHT_IDENTITY_RECONCILE_1
attempt: 2
status: CLAIMED — successor resumed; executing Task 2 (registry reshape) first per §5
dispatched_by: lead
reply_to: lead + ao-desk (bus topic baker-os-v2/b4-ao-data-preflight)
priority: P1 — blocks B6 AO flight launch
created: 2026-07-07
---

# Checkpoint — AO_FLIGHT_IDENTITY_RECONCILE_1 (attempt 1)

Successor: claim by bumping `attempt:` to 2 in this file + commit (NOT by bus ack). If attempt already ≥2, stand down.

## 1. What's done
- **Nothing on THIS brief yet** — checkpointed at dispatch because predecessor session (the B4 preflight
  that produced the findings) was ~60% context, over lead's 50% refresh threshold (lead #6264).
- Predecessor B4 preflight is MERGED: PR #476, report `briefs/_reports/B1_BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1_20260707.md`.
- Lead rulings received and folded into the brief (see below).

## 2. What's left — all 5 tasks / AC1–AC5 (source of truth: briefs/_tasks/AO_FLIGHT_IDENTITY_RECONCILE_1.md)
- **Task 1 (AC1):** apply slug ruling `matter_slug: ao` to ratified manifest + flight-config artifacts; fix any `oskolkov`-keyed filter/config in flight scope. Do NOT touch baker-vault/slugs.yml.
- **Task 2 (AC2):** reshape matter_registry AO entry to ratified 12 participants; drop Edita + Siegfried; rehome crossroad keywords (RG7/LCG/Lilienmatt/Annaberg/Balgerstrasse/mandarin-oriental) to their own matters; name-trigger tier = Oskolkov/Lana/Ania only, rest coverage-keys.
- **Task 3 (AC3):** wire/verify classifier stamps `registry_version` + `classification_version` on new tickets once AO registry entry loads (small code fix → PR + codex gate medium; else report exact insertion point).
- **Task 4 (AC4):** quarantine/clamp the 14 future-dated bluewin rows (received_date > now); preserve originals, log ids.
- **Task 5 (AC5):** sample lilienmatt↔ao ticketing boundary after Task 2; report re-classification.
- Final: bus report to lead + ao-desk with per-AC verdicts + BEFORE/AFTER counts.

## 3. Lead rulings (do not re-litigate)
- **H1 slug:** flight `matter_slug` = **`ao`** (slugs.yml canonical wins). `oskolkov` stays an alias, never a data key. Vault folder `wiki/matters/oskolkov/` path UNCHANGED (folder ≠ slug).
- **Fireflies (5b):** intentionally disabled by design (PR #341, Plaud-only). No investigation — just note meetings lane = Plaud in flight config.
- **Irina Sudomoyeva identity:** goes to ao-desk, NOT b1. Out of scope here.
- **meeting_transcripts slug backfill:** b2 owns it, in flight — COORDINATE via bus, do NOT duplicate. transcripts by-matter/ao verification waits on b2's backfill landing.

## 4. Key paths / facts / commits (warm data from preflight — saves re-querying)
- Brief: `briefs/_tasks/AO_FLIGHT_IDENTITY_RECONCILE_1.md` (main @f5b89975).
- Manifest (ratified 12): `wiki/matters/oskolkov/02_inventory/2026-07-07-ao-flight-participant-manifest-ratified.md`.
- **matter_registry AO entry = id=15 "Oskolkov-RG7"**, current state:
  - people: ['Andrey Oskolkov','Constantinos Pohanis','Siegfried','Edita Vallen','Vitaly']  ← drop Siegfried+Edita; add missing 9
  - keywords: ['Oskolkov','AO','Andrey','Aelio','RG7','LCG','capital call','shareholder loan','Baden','Lilienmatt','Annaberg','Balgerstrasse','Constantinos','Siegfried','participation agreement']  ← rehome RG7/LCG/Baden/Lilienmatt/Annaberg/Balgerstrasse
  - projects: ['rg7','mandarin-oriental','baden-baden','lilienmatt']  ← crossroad; rehome
  - Ratified 12 to install: Andrey Oskolkov, Lana Oskolkov, Anna(Ania) [name-triggers]; Pohanis, George Demosthenous, Masha, Irina Sudomoyeva, Katya, Sardarov, Vitaly, Merz, Aelio Holding [coverage-keys].
- **Bluewin 14 future-dated rows:** `SELECT message_id, received_date FROM email_messages WHERE source='bluewin' AND received_date > now();` (max seen 2035-07-28). Repair = quarantine flag or clamp to header date; log ids.
- **airport_tickets version-stamp gap:** all 133 rows have registry_version + classification_version + final matter_slug NULL. Classifier insertion point NOT yet located — grep orchestrator/triggers for airport_tickets INSERT/classification writer. Read-only DB writes go via prod (no migration expected for registry/bluewin data rows).
- Schema notes: email_messages + whatsapp_messages have NO matter_slug column (derived tagging); meeting_transcripts + airport_tickets DO. matter_registry cols: matter_name, people[], keywords[], projects[], status, category.

## 5. Next concrete step
1. Confirm context is fresh (respawned session), read the brief + this checkpoint.
2. Bump `attempt: 2` here, commit (this is the claim).
3. Bus-ping b2 on topic `baker-os-v2/b4-ao-data-preflight` to sync on meeting_transcripts backfill boundary (avoid dup).
4. Start Task 2 (registry reshape) — highest-value, unblocks Task 5 boundary sample; then Task 1 (slug config), Task 4 (bluewin), Task 3 (version-stamp), Task 5 (boundary sample).
5. Branch `b1/ao-flight-identity-reconcile` for any code diff; prod DB data writes (registry/bluewin) are read-only-tool-exempt ops — use raw_write path per project rules, log every write.
