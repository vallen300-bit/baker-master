---
status: PARKED
brief_id: INGESTION_COMPLETENESS_P1_CLEANUP_1
from: lead
created: 2026-06-29
priority: P1
parent: INGESTION_COMPLETENESS_P0_MEASURE_1 (PR #436, MERGED + Director-ratified-closed 2026-06-29)
effort: low
task_class: read-only measurement follow-ups (no fix-to-prod-ingest / no migration / no deploy)
Harness-V2: applies — Context Contract + done rubric + gate plan below
---

# BRIEF (PARKED): INGESTION_COMPLETENESS_P1_CLEANUP_1 — close the three minor measure follow-ups

## Context
P0 measure (`INGESTION_COMPLETENESS_P0_MEASURE_1`, PR #436) shipped + Director-ratified
**closed** 2026-06-29: store healthy on Plaud + WhatsApp, no new P0 ingestion gap,
attachments already ~99.8%. The baseline RUN (b3, bus #4653) surfaced three minor
follow-ups that do NOT gate any P0 work but should be closed to make the harness
fully load-bearing across all four surfaces. This brief folds all three. **PARKED** —
dispatch when worker capacity frees; not urgent.

### Surface contract: N/A — read-only harness follow-ups + one box RUN; no UI/route/card.

## Problem
The P0 baseline left three measurement loose ends: (1) the email surface (bluewin +
graph M365) was never run this pass because it is not runnable from a b-code clone;
(2) Plaud shows a 5-recording count gap with no reconcile of which ids are missing;
(3) the random-sample present-check returned 0/10-absent, contradicting the 95% count
— a suspected id-join artifact that makes the sampler non-load-bearing. None gate P0
work, but each leaves a measurement surface not fully trustworthy.

## Context Contract
- **Owner:** Code Brisen (any free worker; **box run needs Render shell**, see item 1).
- **Task class:** read-only measurement follow-ups.
- **Authority:** read-only. No writes, no backfill, no migration (item 2 is measure-only).
- **Activation state:** harness/CLI only; nothing prod-facing activates.

## The three items

### Item 1 — Email 4th-surface completeness (Render box run)
`scripts/verify_backfill.py --baseline` for the email surfaces (bluewin IMAP + graph
M365) is NOT runnable from a b-code clone: bluewin IMAP EXAMINE hit `BAD "Invalid
characters in atom"` on the auto-picked folder allowlist, the spot-check sampler
imports `mcp` (absent in clone venvs), and GraphClient needs the password-protected
`.pfx` from `pfx_source_url` (not a plain PEM in 1Password). All creds + cert + `mcp`
ARE present on the Render box. **Action:** run the email baseline on the Render box
(one-off), post per-surface completeness%/lag/gap to lead bus. Also fix the bluewin
folder-allowlist atom error if it reproduces on the box.

### Item 2 — Plaud 5-recording gap reconcile (read-only)
Baseline showed Plaud store=95 / truth=100 (95% by count, 5 absent vs 0.98 target).
**Action:** read-only — list the 5 `data_file` ids present in the Plaud full-history
API truth but absent from `meeting_transcripts(source='plaud')`; classify (genuinely
un-ingested vs id-mismatch). NO backfill in this brief — reconcile + report only; a
backfill, if warranted, is a separate authorized brief.

### Item 3 — Sample present-check id-join fix
The random sample present-check returned 0/10 ABSENT, contradicting the 95% count —
almost certainly a harness id-join artifact (sampled `data_file` hash id != stored
key), not a real 0% gap. **Action:** fix the sampler's id-join so the present-check
agrees with the count-based completeness, making the sample load-bearing. Add a
regression test that the sampler and the count metric agree on a known fixture.

## Key Constraints
- **No writes / no backfill / no migration / no deploy.** Items are measure-only.
- Item 1 box run is read-only (`SET default_transaction_read_only=on`, all external GET).
- WhatsApp `source` column (waha-vs-iphone parity) is a SEPARATE P1+ decision — NOT in
  this brief (needs a schema migration ratification first).

## Acceptance criteria
- Email per-surface baseline numbers posted to lead bus (item 1).
- The 5 Plaud-gap ids enumerated + classified (item 2).
- Sampler id-join fixed + regression test green; sample agrees with count metric (item 3).
- `py_compile` clean, `pytest tests/test_verify_backfill.py` green, no-write grep = 0.

## Verification
- Item 1: `python3 scripts/verify_backfill.py --baseline` on the Render box returns
  email completeness%/lag/gap with no IMAP atom error; numbers land on lead bus.
- Item 2: query lists exactly the 5 `data_file` ids in API-truth but absent from
  `meeting_transcripts(source='plaud')`, each labelled un-ingested vs id-mismatch.
- Item 3: on a fixture where count-completeness = N%, the sampler reports the matching
  present/absent split (regression test asserts agreement). No-write grep = 0 throughout.

## Files Modified
- `scripts/verify_backfill.py` — sampler id-join fix (item 3); bluewin folder-atom fix (item 1, if reproes).
- `tests/test_verify_backfill.py` — sampler-vs-count agreement regression test.

## Quality Checkpoints
1. Confirm read-only posture held on the box run (`default_transaction_read_only=on`, all external GET).
2. No `baker_actions` write rows created by any item.
3. Plaud reconcile (item 2) performs NO backfill — report only.
4. WhatsApp `source` column stays out of scope (separate P1+ migration decision).

## Gate Plan
G1 builder self-check → codex G3 (effort low) → cowork-ah1 or lead /security-review →
lead merge → box run (item 1) read-only → numbers to lead bus. No deploy.
