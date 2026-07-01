# BOX5_DROP_OBSERVABILITY_1

**Owner:** lead (AH1) · **Builder:** b-code · **Gate:** codex G3 (HIGH) → lead G4 /security-review
**Source:** Sacca Gate-4 + cowork-ah1 verdict (2026-07-01) — instrument BEFORE broadening. Run this WITH the merged ingestion widen so we can measure which gate now binds.

## Problem

The signal journey drops signals at every gate **silently**. There is no queryable
"considered-and-dropped + reason" trail, so we cannot measure whether widening ingestion
(#450, merged) actually delivers mail, or which gate is now binding. cowork's rule:
instrument first, then size the Gate-2 keyword-broadening off real drop data — not a guess.

## Evidence

- Gate 2 (keyword prefilter): `fetch_email_arrivals` (airport_ticketing_bridge.py ~521-530)
  hard-filters `ILIKE` on 3 keywords in SQL — keyword-miss mail is never even fetched, so
  it can't be logged. Silent by construction.
- Gate 3 (routing): drops to `airport-noise:*` rows (status=candidate, proposed_desk=UNROUTED)
  — present but carry no structured drop-reason, and mix with true noise.
- No single place answers "what did we see, what did we drop, and why" per tick.

## Design (target)

Add a queryable drop-log that records every considered-and-dropped inbound signal + reason,
WITHOUT changing what gets ticketed (same emails ticket; we only now LOG the drops).

1. **New table `box5_dropped_signals`** (migration): message_id, thread_id, sender_email,
   subject (truncated), matched_keywords, gate (`keyword_prefilter` / `routing_unrouted` /
   `routing_conflict` / `other`), reason (text), received_date, tick_at. Indexed on tick_at
   + gate. Additive; no change to airport_tickets.
2. **Gate-2 instrumentation (KEY):** convert the silent SQL keyword prefilter into
   fetch-a-superset-then-classify-and-log. Fetch the recent window WITHOUT the 3-keyword
   `ILIKE` (bounded by lookback + a hard row cap), then in Python: keyword-match → proceed
   as today; keyword-miss → write a `keyword_prefilter` drop row and skip. Net behavior on
   what tickets is UNCHANGED; the miss set is now visible. (Guard the row cap + log if capped.)
3. **Gate-3 instrumentation:** when routing yields UNROUTED/CONFLICT, also write a
   `routing_unrouted` / `routing_conflict` drop row with the reason. May annotate the
   existing noise row rather than duplicate — builder's call, keep it queryable.
4. **Read-only surface:** a simple query path (raw SQL is fine) so lead can run
   "last 24h drops by gate". No dashboard work required this brief.

## Constraints

- Do NOT change what gets ticketed — this is observability only. Prove parity.
- All DB calls try/except; fault-tolerant — a drop-log write failure must NEVER block or
  abort the tick (log + continue). `.claude/rules/python-backend.md`.
- Bounded fetch: the un-prefiltered superset fetch MUST have a hard cap + lookback bound
  (no unbounded scan); log when the cap truncates.
- Migration additive + forward-only; mirror the ensure_ pattern (Lesson #50) if a bootstrap
  path exists.
- Surgical: airport_ticketing_bridge.py + migration + tests.

## Acceptance criteria

1. A keyword-miss email in the lookback window produces a `keyword_prefilter` drop row;
   the SAME email set still tickets as before (parity proven).
2. An UNROUTED/CONFLICT routing outcome produces a drop row with a reason.
3. Drop-log write failure does not abort the tick (fault-tolerant).
4. Superset fetch is capped + bounded; truncation is logged, never silent.
5. Existing ticketing tests stay green.

## TDD plan

1. Parity: with drop-logging on, the set of emails that ticket is identical to pre-change.
2. Keyword-miss → one `keyword_prefilter` drop row with matched_keywords empty.
3. UNROUTED + CONFLICT → drop rows with correct gate + reason.
4. Drop-log insert raises → tick still completes (fault-tolerant).

## Out of scope

- Broadening the keyword gate itself (that's the NEXT brief, sized off this drop-log).
- Dashboard/UI. Alerting.
- Watermark future-date clamp — see `BLUEWIN_RECEIVED_DATE_CLAMP_1`.

## Gate

G1 (self-verify + tests, parity proof) → **codex G3, effort HIGH** (touches the live
ticketing fetch path + a migration) → **lead G4 /security-review** → lead merge.
