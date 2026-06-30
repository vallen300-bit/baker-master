---
status: MERGED
pr: 441
merge_commit: ddb2ea4
head_sha: 873c491
shipped_at: 2026-06-30
merged_at: 2026-06-30
gates: codex G3 PASS (#4735, clean first pass) + lead G4 /security-review clean; additive schema, deployed; seed NOT run (Director annaberg confirm pending)
brief_id: BOX5_SCHEMA_FOUNDATION_1
to: b4
from: lead
dispatched_by: cowork-ah1
dispatched_at: 2026-06-30
branch: box5-schema-foundation-1
reply_target: cowork-ah1 (bus) for ship report; gate verdicts to lead
effort: medium
task_class: additive schema (airport_tickets terminal columns + own CHECK) + gated one-off BB pilot seed script (NOT auto-run)
gate_plan: G1 builder self-check -> codex G3 (bus, effort medium) -> lead G4 /security-review -> lead merge. Migration applies on boot (additive, idempotent); seed is one-off + Director-gated (annaberg confirm) — do NOT run it. No deploy flag (pure additive schema).
full_brief: briefs/BRIEF_BOX5_SCHEMA_FOUNDATION_1.md
---

# BOX5_SCHEMA_FOUNDATION_1 — airport_tickets terminal columns + gated BB pilot seed (Box 5 Build Order 3-4)

## Read this first
Complete copy-pasteable impl in **`briefs/BRIEF_BOX5_SCHEMA_FOUNDATION_1.md`** (433 lines, on main, committed alongside this dispatch). Implement exactly. Brief authored + verifier-checked by cowork-ah1; do not redesign. This envelope = dispatch metadata + gates only.

## Context (one paragraph)
Box 5 Build Order 3-4, the schema foundation (no runner, no fast-lane logic). PR #440 (receipt/TTL) already merged — this builds ON it. Part 1: additive `airport_tickets` terminal columns — a dedicated `terminal_status` column with its OWN CHECK over exactly 6 states (DUPLICATE, REJECT_NOISE, REJECT_LOW_RELEVANCE, FAST_TICKET, TICKET, FILE_UNSORTED — VISIBLE_HOLD deliberately EXCLUDED, its own later brief) + 15 result fields, via new `ensure_airport_ticket_terminal_columns` mirrored in `ensure_airport_ticket_table` + versioned `migrations/20260630_airport_tickets_terminal_columns.sql`. Live `status` + `check_in_outcome` CHECKs are an ORTHOGONAL axis — UNTOUCHED. Part 2: idempotent gated BB pilot seed via new `scripts/seed_bb_pilot_registry.py` calling #439's `register_project`.

## Scope (locked — do NOT exceed)
- Part 1: additive terminal columns + own CHECK, mirrored in `ensure_airport_ticket_table` + versioned migration. Do NOT touch live `status`/`check_in_outcome` CHECKs or indexes.
- Part 2: `scripts/seed_bb_pilot_registry.py` — one-off, gated, NOT auto-run on boot. Calls `register_project` (PR #439). matter_slug=**annaberg** (the Baden-Baden project vehicle; "AUK" is the human mnemonic, NOT the aukera lender — matches #439's seed_bb_pilot).
- Additive only. No new env, no deps, every SELECT LIMIT, rollback in except. No collision with PR #440's columns (last_nudged_at/nudge_count/escalated_at) — those are merged; add only the terminal-status set.

## Acceptance criteria
- AC1: `py_compile` clean (migration-runner-applied migration + the seed script).
- AC2: `pytest` new tests pass (live-PG auto-skip without TEST_DATABASE_URL; CI live).
- AC3: `bash scripts/check_singletons.sh` OK; `bash scripts/check_applied_migrations.sh` OK.
- AC4: terminal_status CHECK rejects an out-of-set value; the 6 valid states accepted; VISIBLE_HOLD rejected (excluded by design).
- AC5: migration + bootstrap mirror both add the same columns (no migration-vs-bootstrap drift); live `status`/`check_in_outcome` axis unchanged.

## Done rubric
Build-done = PR merged + AC1-AC5 green + migration applies clean on boot. Seed is NOT run by this build — seed execution is a separate Director-gated step (annaberg matter confirm). No deploy flag (pure additive schema; columns unused until the runner brief consumes them).

## Context-economy (HARD — no auto-compaction)
- Read ONLY the files in the brief's Context Contract. Output to /tmp; tails only. Context >70%: commit, push, bus handoff, STOP.
