# SHIP REPORT — AO_FLIGHT_PROD_TICKET_ROUTING_1

**Author:** b1 · **Date:** 2026-07-07 · **Branch:** `b1/ao-flight-ticket-routing`
**Dispatched by:** lead · **Reply topic:** `baker-os-v2/ao-flight-ticket-routing`
**Gate state:** self-verify PASS → handing to deputy G2.

## What shipped

Per-matter airport-ticket desk routing, **sourced from `project_registry.desk_owner`**
(lead ruling #6850 SUPERSEDED the brief's original env-JSON design — registry is the
single source of truth, already consumed fleet-wide, no drift, no migration).

- `kbl/project_registry_store.py` — new `desk_owner_for_matter(conn, matter_slug)`:
  SELECT-only, returns the matter's ACTIVE-row `desk_owner` iff unambiguous (exactly one
  distinct non-empty owner); None on unknown / no-owner / **ambiguous (>1 owner)** →
  caller falls back to the global desk (mirrors #5035 multi-matter-safety). Fault-tolerant
  (rollback + None on any error).
- `orchestrator/airport_ticketing_bridge.py` — new `_desk_for_matter(matter_slug, conn=None)`:
  registry desk_owner when matter known + conn in hand, else global `_desk_slug()`; keeps
  the `resolve_owner_slug` + `RESERVED_RECIPIENTS` guard. `conn=None` ⇒ zero DB hit (pure
  builders stay DB-free). Wired into `build_plaud_ticket` (routes by `arrival.matter_slug`);
  `_run_nonmail_lane` threads the tick's `conn`.
- WA + email lanes **unchanged** this brief (no matter attribution at mint — diagnose §1);
  WA accepts+ignores `conn` for the shared build_fn signature.

## Diagnose gate (posted #6849, ruled #6850)

Full findings: `B1_AO_FLIGHT_PROD_TICKET_ROUTING_1_DIAGNOSE_20260707.md`. Key: **only Plaud**
carries matter attribution at mint (`PlaudArrival.matter_slug`). WA has no `matter_slug`
field (brief's "route plaud/WA via arrival.matter_slug" was not buildable for WA). Email/WA
identity is Director-barred from auto-routing (#5035). Existing e.7/e.8 code/thread lanes
already registry-route via `desk_owner` downstream. Lead confirmed Plaud slice + supervised
mode (#6826) satisfies launch; keyword→matter map is a follow-up brief.

## Acceptance criteria

- **AC1 (adjusted per #6850)** — Plaud arrival whose registry `desk_owner=ao-desk` mints
  `proposed_desk_slug='ao-desk'`. **PASS** — `test_build_plaud_ticket_routes_ao_by_registry` (live PG).
- **AC2** — BB-matter arrival still mints `baden-baden-desk`; unmapped matter falls back to
  global. **PASS** — same test + `test_desk_for_matter_registry_routes_by_matter` (live PG).
- **AC3** — live-PG tests RAN, not skipped. **PASS** — ran against a throwaway local PG16
  (isolated DB `baker_test_ao_routing`; prod DATABASE_URL deliberately NOT used — the
  fixtures DELETE/INSERT). Literal output below.
- **AC4** — POST_DEPLOY_AC_VERDICT v1 after merge + Render deploy + a real AO ticket observed
  on ao-desk's flight. **PENDING** (post-merge). NOTE: no env var to set — routing is
  registry-sourced, so AC4 verification is: confirm AO's `project_registry` row has
  `desk_owner='ao-desk'` in prod (id=15, slug `ao`) + observe a real AO Plaud ticket board
  ao-desk. No `AIRPORT_TICKETING_DESK_MAP` env is introduced.

## Literal pytest output

New tests (live PG):
```
tests/test_airport_nonmail_signals.py::test_desk_for_matter_no_conn_global_fallback PASSED
tests/test_airport_nonmail_signals.py::test_desk_for_matter_registry_routes_by_matter PASSED
tests/test_airport_nonmail_signals.py::test_build_plaud_ticket_routes_ao_by_registry PASSED
3 passed, 21 deselected in 0.12s
```
Full nonmail file (live PG): `24 passed in 0.20s`.
Regression — airport + registry suites (live PG):
```
tests/test_airport_nonmail_signals.py tests/test_airport_ticketing_bridge.py
tests/test_project_registry.py tests/test_airport_boarding_flow.py
tests/test_airport_terminal_columns.py
106 passed in 0.74s
```
(5 unrelated files — substack / brisen_lab_consumer_mcp / email_attachment_read /
mcp_baker_extension / gate4_fixes — have pre-existing local import-collection errors in this
picker, untouched by this change; not run here.)

## Quality checkpoints

1. Bad `AIRPORT_TICKETING_DESK_MAP` JSON → **N/A** — no env JSON introduced (#6850 registry-sourced).
2. desk_owner pointing at reserved/unknown recipient → `_desk_for_matter` guard rejects +
   falls back to global (mirrors :598-599). Also structurally prevented: `register_project`
   enforces `desk_owner == DESK_CODES[prefix]`, so a reserved recipient cannot be stored.
3. Render restart mid-deploy → `_desk_slug()` reads `os.environ` at call time; registry read
   is per-tick on the live conn. No in-memory-only state.
4. Lanes covered + matter attribution: Plaud=registry-routed (matter known); WA+email=global
   this brief (no mint-time matter) — see diagnose report.

## Constraints honored

Config/registry-driven, NO schema migration. Nothing deleted (store-everything). PR #482 WA
suppression (`_wa_identity_only`/`_wa_identity_suppressed`) untouched. BB flight unaffected
(fallback default unchanged). `dispatcher.py` / classifier label map untouched. `project_registry`
rows untouched (the Joseph coverage-key request #6825 was flagged to lead, NOT actioned here).

## Files
- `orchestrator/airport_ticketing_bridge.py`
- `kbl/project_registry_store.py`
- `tests/test_airport_nonmail_signals.py`
