# BRIEF — AO_LABEL_MAP_CANONICAL_FIX_1

> Authored by lead 2026-07-07 (source: ao-desk flag #6506 after b1's AO_FLIGHT_IDENTITY_RECONCILE_1).
> Small, surgical. Target: deputy-codex. Effort recommendation: **medium**.

| Field | Value |
|---|---|
| dispatched_by | lead |
| task class | bug-class code fix (classifier label map) + tests; 1-sitting scale |
| repo | baker-master |
| harness-v2 | REQUIRED (production classifier path) |

## Context

**Context Contract (Harness V2):**
- b1 executed the one-time 511-doc split of the legacy combined label (`Oskolkov-RG7` → ao=301, hagenauer-rg7=71, mo-vie-am=46, mrci=22, steininger=10, lilienmatt=4; 57 manual). Reports: PRs #477/#478, `briefs/_reports/B1_AO_FLIGHT_IDENTITY_RECONCILE_1_20260707.md`.
- Director-ratified slug ruling 2026-07-07 (ao-desk #6359): canonical matter slug = `ao` in ALL stores; `oskolkov` / `Oskolkov-RG7` are aliases only.
- AO flight (B6, Baker OS V2 Wave 2) reads `ao`; launch flip is lead-owned and separate.

## Problem

`tools/document_pipeline.py:118` still maps `'Oskolkov': 'Oskolkov-RG7'` — every NEW ingested doc re-mints the retired combined label. b1's one-time split rots over time; the classifier cannot do the source_path split b1 did manually, so fragmentation re-opens on every ingest.

## Files to touch

- `tools/document_pipeline.py` — label map fix (line ~118) + any other code path that can mint `Oskolkov-RG7` (audit scoped to AO only; do NOT overhaul the full legacy map).
- `tests/` — the document_pipeline test module (add AC1/AC2 cases alongside existing pattern).
- NOTHING else. Diff must be surgical.

**Mixed-doc ruling (lead, binding):** combined labels are RETIRED as mint-able. Genuinely mixed docs → single dominant matter (same rule b1 applied manually). Truly undecidable → existing manual-routing lane (57-doc pattern), never a combined label. Label string for `ao`: verify against matter_registry id=15 — do not hardcode a guess.

## Acceptance criteria

- **AC1** — new doc containing Oskolkov entities classifies to `ao` (unit test, real classifier call path).
- **AC2** — `Oskolkov-RG7` is not mintable by any code path (grep + test assert).
- **AC3** — existing document_pipeline tests pass; no other label mapping changed (diff surgical).
- **AC4** — post-deploy: first live-ingested Oskolkov doc after merge carries `ao` (POST_DEPLOY_AC_VERDICT v1 per convention).

## Verification

- `pytest tests/test_document_pipeline*.py -v` (or the module's actual test file — locate, don't assume) — all pass incl. new AC1/AC2 cases.
- `grep -rn "Oskolkov-RG7" tools/ orchestrator/ kbl/` — remaining hits are read-only/alias handling only; none mint.
- Post-merge: watch first live Oskolkov-entity ingest → label = `ao` → post the AC4 verdict to lead.

**Done rubric:** all 4 ACs evidenced (AC1/AC2 = real test output, not prose); diff touches only the 2 file surfaces above; post-deploy verdict posted.
**Gate plan:** G1 self-verify → G2 deputy quick cross-lane → G3 codex bus (effort=medium, additive fix) → merge → AC4 post-deploy verdict.

## Out of scope

- Full legacy label-map modernization (separate cleanup brief if wanted).
- The 57-doc manual routing (ao-desk owns).
- Any cortex-config change (lead owns the `ao` flip separately).
