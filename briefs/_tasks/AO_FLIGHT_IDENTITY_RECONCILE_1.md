# AO_FLIGHT_IDENTITY_RECONCILE_1

dispatched_by: lead
assignee: b1 (warm continuation of B4 preflight; if context >50%, checkpoint+respawn first per refresh rule)
task_class: data-ops + config reconcile (launch-blocking H1/H2 from B4 preflight)
priority: P1 — blocks B6 AO flight launch
Harness-V2: compact — done rubric = Acceptance criteria; gate plan = self-verify SQL + codex bus gate reasoning_effort=medium on any code diff; report to lead

## Context

B4 preflight (briefs/_reports/B1_BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1_20260707.md, merged) found the AO
launch risk is matter-identity fragmentation, not coverage. This brief executes proposals 1, 2, 4 and
the bluewin half of 5. Ratified participant manifest:
`wiki/matters/oskolkov/02_inventory/2026-07-07-ao-flight-participant-manifest-ratified.md`.

**LEAD RULING (slug, H1):** flight `matter_slug` = **`ao`** — the slugs.yml canonical wins; `oskolkov`
stays an alias, never a data key. Vault folder `wiki/matters/oskolkov/` keeps its path (folder ≠ slug);
flight config + manifest + registry + retrieval filters all declare `ao`.
**LEAD ANSWER (Fireflies, proposal 5b):** intentional — Fireflies ingest disabled by design (PR #341,
Plaud-only policy). No investigation; just note in flight config that meetings lane = Plaud.

## Problem

1. H1: flight/brief/manifest key on alias `oskolkov`; queries return 0 — real data lives under `ao`.
2. H2: matter_registry id=15 "Oskolkov-RG7" has 3/12 ratified participants, includes EXCLUDED
   Edita+Siegfried, and its keywords (RG7/LCG/Lilienmatt/Annaberg/Balgerstrasse/mandarin-oriental)
   pull exactly the MOVIE↔Baden-Baden crossroad content the Director ordered OUT of AO.
3. airport_tickets: 133 rows all suspect lilienmatt/hagenauer, zero ao; matter_slug + registry_version
   NULL on all 133 — classifier never stamps versions.
4. 14 future-dated bluewin rows (max 2035) — sibling of the Aukera window bug.

## Tasks

1. Apply the slug ruling: annotate the ratified manifest + flight-config artifacts with `matter_slug: ao`;
   fix any `oskolkov`-keyed filter/config in flight scope. Do NOT touch baker-vault/slugs.yml (separate-repo rule).
2. Reshape the AO registry entry to the ratified manifest: 12 INCLUDE participants; drop Edita+Siegfried;
   move crossroad keywords to their own matters' entries (or drop if already present there). Name-trigger
   tier only for Oskolkov/Lana/Ania per manifest; rest coverage-keys.
3. Wire/verify classifier stamps `registry_version` + `classification_version` on new tickets once the
   AO registry entry loads (code fix if small; else report exact insertion point for a follow-up brief).
4. Bluewin: clamp/quarantine the 14 future-dated rows (received_date > now → quarantine flag or clamp
   to header date; preserve originals, log ids).
5. Verify lilienmatt↔AO ticketing boundary after task 2 (proposal 4) — sample re-classification, report.

## Files Modified

matter_registry rows (prod DB), flight/manifest config artifacts, possibly classifier stamp code
(small diff → PR + codex gate medium). NOT: baker-vault/slugs.yml, LOOKBACK_HOURS (b1 C5 deferred item),
meeting_transcripts slug backfill (b2 owns, in flight).

## Verification

```sql
-- registry: AO entry has 12 participants, no Edita/Siegfried, no crossroad keywords
-- transcripts: by-matter/ao returns rows (after b2 backfill lands; coordinate, don't duplicate)
-- bluewin: 0 rows with received_date > now()
-- tickets: new AO-classified tickets carry registry_version NOT NULL
```

## Acceptance criteria

- AC1: all flight-scope artifacts key on `ao`; zero `oskolkov`-keyed data filters remain.
- AC2: registry entry matches ratified manifest exactly (12/12, exclusions honored, keywords rehomed).
- AC3: version-stamping verified or precise gap report delivered.
- AC4: 14 bluewin rows repaired/quarantined with ids logged.
- AC5: boundary sample report (lilienmatt vs ao) posted.
- Report: bus to lead + ao-desk with per-AC verdicts + BEFORE/AFTER counts.
