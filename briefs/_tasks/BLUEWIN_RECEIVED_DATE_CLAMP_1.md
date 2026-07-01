# BLUEWIN_RECEIVED_DATE_CLAMP_1

**Owner:** lead (AH1) · **Builder:** b-code · **Gate:** codex G3 (MEDIUM) → lead G4 /security-review
**Source:** cowork-ah1 Sacca verdict net-new finding (2026-07-01) — latent watermark-poisoning landmine. Robustness; does NOT block the main signal-journey fix.

## Problem

`email_messages` contains rows with a corrupt **far-future** `received_date`:
~13 bluewin rows dated **2035-07-28 03:59:59Z** (batteryjunction.com "Post_Tracking" spam,
ingested 2026-06-10). Any consumer that advances a watermark by `received_date` over the
contiguous processed prefix is at risk: if a keyword-matching email ever lands with a
corrupt future date, the watermark jumps years into the future and **permanently, silently
starves** the pipeline — the exact failure class we just debugged, but sticky. Every
`received_date`-windowed query is also subtly wrong today.

## Evidence

- `SELECT source, MAX(received_date) ...` → bluewin `latest_received = 2035-07-28 03:59:59Z`
  (vs graph/gmail today's dates). ~13 rows (cowork count).
- The ticketing bridge advances its watermark by `received_date` over the processed prefix
  (airport_ticketing_bridge.py ~1195-1245). Immune TODAY only because those spam rows don't
  match the 3 keywords — a fragile accident, not a guarantee.

## Design (target)

1. **Clamp at ingest (primary):** when writing to `email_messages`, reject/cap a
   `received_date` that is implausibly far in the future — `received_date > ingested_at +
   skew` (skew e.g. 2 days for clock/tz slop) → clamp to `ingested_at` (or the parsed date
   floored) and log. Apply at the ingest layer so ALL sources are covered; at minimum the
   bluewin poller (`triggers/bluewin_poller.py`) where the bad parse originates.
2. **Backfill existing poisoned rows:** a one-time fix (migration or scoped script) that
   caps the ~13 existing far-future rows to a sane value (their `ingested_at`), so current
   watermark/window queries are correct. Confirm the count + scope before writing.
3. **Watermark hardening (defense-in-depth):** the bridge's watermark advance should ignore
   / cap a `received_date` beyond `now + skew` so a single bad row can never jump the cursor
   years forward, even if a future ingest path misses the clamp.

## Constraints

- All DB calls try/except; fault-tolerant. `.claude/rules/python-backend.md`.
- Do NOT drop the offending emails — clamp the date, keep the row (audit).
- Migration (if used) additive/forward-only; never edit an applied migration.
- Surgical: ingest clamp + bluewin poller + watermark guard + tests.

## Acceptance criteria

1. Ingesting a message dated `> ingested_at + skew` stores a clamped, sane `received_date`
   (not the far-future value); event logged.
2. The ~13 existing 2035 rows are capped to a sane date (backfill), verified by re-query.
3. The bridge watermark advance ignores/caps a future-dated row — a single poisoned row
   cannot move the cursor beyond `now + skew`.
4. A legitimate near-future date within skew is NOT clamped (no false positives).
5. Existing ingest + ticketing tests stay green.

## TDD plan

1. Ingest a 2035-dated message → stored date clamped to ingested_at; original preserved in
   raw/log if applicable.
2. Backfill test: a seeded far-future row → capped after the fix runs.
3. Watermark test: a future-dated processed row does not advance the cursor past now+skew.
4. Near-future (within skew) → not clamped.

## Out of scope

- Spam filtering / dropping batteryjunction mail (separate concern; here we only fix dates).
- Broader ingestion-completeness (recipient fields, etc.).
- The drop-observability work — see `BOX5_DROP_OBSERVABILITY_1`.

## Gate

G1 (self-verify + tests) → **codex G3, effort MEDIUM** (data-clamp + backfill; lower blast
radius than the ingest/routing fixes) → **lead G4 /security-review** → lead merge.
