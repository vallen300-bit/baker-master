# BRIEF — AO_FLIGHT_PROD_TICKET_ROUTING_1

> Authored by lead 2026-07-07 via /write-brief SOP (source: Director goal "AO Desk flight onboarding … in production" + bb-desk relay #6778).
> Lead pre-explored the code — current-state anchors below are VERIFIED, design is pre-picked. Target: b1 (fresh seat). Effort recommendation: **medium**.

| Field | Value |
|---|---|
| dispatched_by | lead |
| task class | feature-gap fix (per-matter ticket routing) + tests; 1-sitting scale |
| repo | baker-master |
| reply_target | lead (bus topic `baker-os-v2/ao-flight-ticket-routing`) |
| harness-v2 | REQUIRED (production airport-ticketing path) |
| complexity | Medium |
| estimated time | ~2-3h incl. gates |

## Context

**Context Contract (Harness V2):**
- Director goal 2026-07-07: AO Desk onboarded to the airport-ticketing flight system IN PRODUCTION — it must receive its own tickets. Today AO-matter arrivals ticket onto baden-baden-desk's flight (bb-desk #6778; Eli/Joseph cluster handoff #6704; ao-desk took ownership #6715).
- Already landed, do NOT redo: project_registry id=15 reshaped to the ratified 12-participant manifest, slug `ao` (report `briefs/_reports/B1_AO_FLIGHT_IDENTITY_RECONCILE_1_20260707.md`, PRs #477/#478); cortex-config matter_slug flip → `ao` (vault @a5b1e65); WA identity-only suppression live (PR #482 @4a0d7ae8, b2 post-deploy watch #6718).
- Adjacent in-flight, coordinate don't collide: `AO_LABEL_MAP_CANONICAL_FIX_1` (deputy-codex) — classifier label map, NOT ticket destination.
- Ratified manifest: `wiki/matters/oskolkov/02_inventory/2026-07-07-ao-flight-participant-manifest-ratified.md` (12 include / 11 exclude; name-triggers Andrey Oskolkov, Lana, Ania; MOVIE↔BB crossroad EXCLUDED).

## Problem

The bridge is architected single-flight. VERIFIED current state (`orchestrator/airport_ticketing_bridge.py`):
- `_DESK_ENV = "AIRPORT_TICKETING_DESK"` (:49), `_DEFAULT_DESK = "baden-baden-desk"` (:58) — ONE global destination desk for every ticket.
- `_desk_slug()` (:482) consumed at email mint (:597) and plaud mint (:712); WA mint sits in the :688-710 identity branch (b2 #6632).
- `_matter_slug()` (:486) — a second GLOBAL env; email tickets stamp `suspected_matter_slug=_matter_slug()` (:636) regardless of which matter's keywords matched.
- Nonmail lanes DO know the real matter at mint time (`arrival.matter_slug` from `project_registry`, :725-743; active-set query :677-685).

Consequence: AO-manifest arrivals mint tickets owned by baden-baden-desk. AO flight cannot run its loop.

## Solution (pre-picked by lead — Option A, config-driven)

Add a per-matter desk map consulted whenever a matter is known at mint time; global env stays as fallback:
- New env `AIRPORT_TICKETING_DESK_MAP` — JSON object `{"ao": "ao-desk"}`. Parsed defensively (bad JSON → log + empty map → fallback behavior, fail-open to today's routing, NEVER a crash).
- New helper `_desk_for_matter(matter_slug: str | None) -> str`: map hit → mapped desk; else `_desk_slug()` fallback. Resolve through `resolve_owner_slug` + `RESERVED_RECIPIENTS` guard exactly as :597-599 does today.
- Nonmail lanes (plaud/WA): route via `_desk_for_matter(arrival.matter_slug)`.
- Email lane: diagnosis decides (see gate below) whether keyword→matter attribution exists at mint time; if the matched registry row's matter is available, route via it; if genuinely not available without a bigger refactor, email keeps global desk THIS brief and the gap is reported as a follow-up finding — do not silently widen scope.
- Registry-column design (durable Option B) is explicitly OUT of scope — noted for a follow-up brief.

## Engineering craft gates

- **Diagnose (applies):** trace one real Eli/Joseph cluster ticket end-to-end (arrival → match → `_desk_slug()` → mint). Confirm which lanes carry real matter attribution at mint time, especially the email lane's keyword→matter linkage. Post findings on the reply topic; lead confirms scope BEFORE fix commits.
- **Prototype: N/A** — design pre-picked (env map), no UI/state-model uncertainty.
- **TDD (applies):** first vertical test BEFORE implementation: throwaway-PG test where an AO-manifest arrival mints a ticket with `proposed_desk_slug='ao-desk'` while a BB-keyword arrival still mints to `baden-baden-desk`. Extend `tests/test_airport_nonmail_signals.py` patterns; no implementation-coupled mocks.

## Key constraints

- Config-driven only; NO schema migration in this brief.
- NOTHING deleted; store-everything stands (#6209 lineage). Misroutes re-route, never dropped.
- Watermark-safe: no cursor rewinds; do not disturb PR #482 suppression semantics (`_wa_identity_only` / `_wa_identity_suppressed` untouched).
- BB flight unaffected: aukera/annaberg/lilienmatt keyword lanes keep ticketing to baden-baden-desk (fallback default unchanged).
- MOVIE↔BB crossroad stays EXCLUDED from AO per ratified manifest.
- All DB/env reads wrapped try/except; fault-tolerant or it doesn't ship.
- After setting the Render env var, VERIFY it exists via Render API (env-var-persistence anti-pattern).

## Acceptance criteria

1. AC1 — throwaway-PG proof: AO-manifest arrival mints `proposed_desk_slug='ao-desk'`; ticket boards ao-desk.
2. AC2 — regression: BB-keyword arrival still mints to `baden-baden-desk`; unmapped matters fall back to global desk.
3. AC3 — live-PG tests RUN, not skip (gate rule @df5b253); ship report states RAN vs SKIPPED with literal output.
4. AC4 — POST_DEPLOY_AC_VERDICT v1 on the reply topic after merge + Render deploy + env map set `{"ao":"ao-desk"}` + a real AO ticket observed on ao-desk's flight.

## Gate plan

Diagnose-confirm (lead) → TDD test first → fix → self-verify (AC1-AC3 literal evidence) → deputy G2 → codex G3 on bus (`gate/ao-ticket-routing-g3`, reasoning_effort=medium) → lead merge → AC4 post-deploy verdict.

## Files modified
- `orchestrator/airport_ticketing_bridge.py` — `_desk_for_matter` helper + lane call sites.
- `tests/test_airport_nonmail_signals.py` (or sibling) — routing tests.

## Do NOT touch
- PR #482 suppression logic (`_wa_identity_only`, `_wa_identity_suppressed`, watermark advance).
- `project_registry` schema/rows (registry already ratified-shaped).
- `orchestrator/dispatcher.py` (`resolve_owner_slug` / `RESERVED_RECIPIENTS` are consumed, not changed).
- Classifier label map (deputy-codex's `AO_LABEL_MAP_CANONICAL_FIX_1` lane).

## Quality checkpoints
1. Bad `AIRPORT_TICKETING_DESK_MAP` JSON → warning logged, fallback routing, no crash, cursor holds.
2. Desk map entry pointing at a reserved/unknown recipient → guard rejects, falls back, warning logged (mirrors :598-599).
3. Render restart mid-deploy → env read at call time or module reload safe; no in-memory-only state.
4. Ship report includes literal pytest output + lanes covered (email/WA/plaud) + which lanes carry matter attribution.
