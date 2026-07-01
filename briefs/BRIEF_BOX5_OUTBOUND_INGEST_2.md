# BRIEF — BOX5_OUTBOUND_INGEST_2 (Baker OS V2 · Signal Journey · outbound ratification → ClickUp timetable + flight-state)

**Author:** lead (AH1). **dispatched_by:** lead. **Ship report + gate verdicts → lead.**
**Task class:** production feature, additive + **DARK** behind the EXISTING flag `AIRPORT_OUTBOUND_INGEST_ENABLED` (default false). **Harness-V2:** full (Context Contract + AC + done rubric + gate plan below).
**Builder:** b4 (built Increment 1 = `BOX5_OUTBOUND_INGEST_1` #445, plus D + E lanes; deepest context on the outbound capture path + savepoint/terminal-orthogonality patterns).
**Design source (READ FIRST, AUTHORITATIVE):** `~/baker-vault/_ops/build/baker-os-v2/05_outputs/baker-os-v2-box5-routing-reversal-e-outbound-increment2-spec-codex-arch-20260701.md` §"Deliverable 2 — Outbound Ingestion Increment 2". The spec carries the FULL state machine, ClickUp write contract, flight-state contract, correlation order, and the 12 acceptance tests. This brief is the build envelope + constraints; **build to the spec, do not re-derive it.**

## Context
Director ruling (2026-07-01): Brisen OUTBOUND email is a first-class ratification signal — it advances the ClickUp timetable and the flight process because outbound is often the ratification of what humans proposed to the Director. Increment 1 (merged dark, PR #445 1fb2306) already: classifies direction, adds `airport_tickets.direction`, and — when the flag is on — captures each outbound row as `direction='outbound'`, `status='candidate'`, `proposed_desk_slug='outbound'`, and logs one `airport_ticket.outbound_signal` action, **never boarding a desk**. Increment 2 wires that captured signal to (a) ClickUp timetable create/update and (b) flight-state progression — for **ratifying** outbound only; routine outbound stays evidence-only. Activation stays Director-gated: the same flag flips skip + capture + connector **together**.

### Surface contract: N/A — backend connector (event state machine + ClickUp/flight writes); no clickable UI surface.

## Estimated time: ~5-6h · Complexity: High · Prerequisites: Increment 1 (#445, merged) — the outbound capture path already exists.

## Diagnose gate (facts to build on — re-pin all line refs by grep; file is volatile, ~1684 lines)
- Flag + Brisen sender allowlists + `_OUTBOUND_DESK`: `orchestrator/airport_ticketing_bridge.py` — `_classify_direction` L273, `_outbound_ingest_enabled` L293.
- Outbound capture (Increment 1): the `direction=='outbound'` branch that writes the candidate row + `airport_ticket.outbound_signal` action and short-circuits BEFORE D/E lanes (grep `outbound_signal` and `outbound` short-circuit in `run_tick`). **Increment 2 extends this branch — it does not touch inbound D/E/(f).**
- ClickUp: use the existing MCP/tool path (`grep -rn "clickup" tools/ orchestrator/`); respect the repo hard rules — **BAKER Space (901510186446) ONLY**, kill switch `BAKER_CLICKUP_READONLY=true`, ≤10 writes/cycle. `project_registry.clickup_list_id` gives the target list per project.
- Audit: every write inserts a `baker_actions` row (see spec §audit blocks for exact `action_type`/payload).
- Correlation reuses `resolve_project_number` / `extract_project_codes` (`kbl/project_registry_store.py`) + existing `airport_tickets` thread ids; participant manifest is a HINT only, never sole correlation for a state mutation.

## Engineering Craft Gates
- **Diagnose:** applies — feedback loop = the 12 AC pytest (spec §"Increment 2 Tests"); symptom = outbound captured but inert; probe = AC3 (ratifying → ClickUp) + AC4 (idempotent re-tick).
- **Prototype:** N/A — codex-arch spec settles the state model, contracts, and transitions. No design uncertainty to prototype.
- **TDD/verification:** applies — write AC1 (flag-off byte-identical) + AC4 (idempotency, no duplicate writes) FIRST as the two load-bearing seams, then the rest. Real temp-conn / existing bridge harness; no implementation-coupled ClickUp mocks beyond a thin fake that records calls.

## Implementation (build to spec §"Deliverable 2"; shape summary)
1. **Durable event state** — new table `airport_outbound_events` keyed to the outbound `airport_tickets.ticket_id` (new migration `migrations/<next_seq>_airport_outbound_events.sql`; mirror `ADD ... IF NOT EXISTS` bootstrap; **never edit an applied migration**). States + transitions exactly per spec §"Event State Machine".
2. **Ratifying vs routine gate** — all four conditions (direction proven, sender authority, correlation, ratification content class) per spec §"Ratifying Vs Routine Outbound". Routine → `EVIDENCE_ONLY`, stop.
3. **Correlation** — strict order per spec §"Correlation Order"; >1 correlated project/flight → `NEEDS_CONTROLLER`, no write.
4. **ClickUp write connector** — only for `RATIFICATION_READY`; `CLICKUP_TIMETABLE_WRITE v1` payload + status mapping per spec; idempotency key `outbound-clickup:v1:<message_id>:<target_ref>:<transition>`; every write → `baker_actions action_type='airport_outbound.clickup_write'`.
5. **Flight-state progression** — only AFTER ClickUp write succeeds (or Controller-allowed evidence-only); `OUTBOUND_FLIGHT_TRANSITION v1` + allowed-transition table per spec; audit `action_type='airport_outbound.flight_progressed'`.
6. **Closure guard** — outbound can advance state but CANNOT land/close without a returned package or accepted final proof (spec §"Do Not Close From Outbound Alone").
7. **Single activation gate** — reuse `AIRPORT_OUTBOUND_INGEST_ENABLED`. An internal connector kill switch is allowed, but Director-facing activation stays ONE flag; skip + capture + connector activate together. No production path where outbound is skipped-but-not-captured or captured-but-not-connector-eligible.

## Key Constraints
- Flag OFF → outbound sender path byte-identical to pre-Increment-2 (regression guard AC1). No capture, no skip, no connector.
- Routine outbound = evidence-only; NO ClickUp write, NO flight transition.
- Ratifying outbound writes ClickUp BEFORE any flight progression.
- Idempotent: re-ticking the same outbound writes NO duplicate ClickUp task and NO duplicate flight transition (AC4).
- Never close/land from outbound alone (closure guard).
- **No external email/WA send** (repo hard rule — this connector is internal state + ClickUp only). **ClickUp writes: BAKER Space only, ≤10/cycle, honor `BAKER_CLICKUP_READONLY`.**
- All DB/API calls in try/except with `conn.rollback()` before re-query; a ClickUp API failure → `ERROR_RETRY`/`CLICKUP_BLOCKED`, email cursor does NOT silently drop the event (AC10).
- System/task-notification emails NEVER become outbound ratification (AC11).

## Verification (pytest, literal — all 12 spec ACs, no "by inspection")
Implement spec §"Increment 2 Tests" 1-12 verbatim as the AC set. Load-bearing: AC1 (flag-off byte-identical), AC3 (ratifying+complete → one ClickUp task w/ idempotency key), AC4 (re-tick no dup), AC5 (missing owner/date/action → `CLICKUP_BLOCKED`, no flight), AC7 (external-send → `Waiting Reply`/`waiting_counterparty`, not Closed), AC9 (final-acceptance + returned package → `landed`), AC10 (ClickUp failure → retry, no cursor drop), AC12 (>1 correlated → `NEEDS_CONTROLLER`).

## Files Modified
- `orchestrator/airport_ticketing_bridge.py` — extend the outbound capture branch into the event state machine + connector calls.
- new connector module (e.g. `orchestrator/airport_outbound_connector.py`) — ClickUp write + flight-state contracts + idempotency (keeps the bridge lean).
- `migrations/<next_seq>_airport_outbound_events.sql` — new event table (additive).
- `tests/test_box5_*` — the 12 ACs.

## Do NOT Touch
- Inbound D (e.5) / E (e.7) / (f) lanes — this is the outbound branch only. (E is being changed in parallel by `BOX5_ROUTING_REVERSAL_E_1`; stay out of it.)
- Any applied migration — create new only. `orchestrator/airport_checkin_reader.py`. `triggers/`.
- The activation flag DEFAULT — it stays `false`. Flipping it is a Director-gated Tier-B step lead owns AFTER this ships + Director approves.

## Coordination note (parallel build)
`BOX5_ROUTING_REVERSAL_E_1` (b3) edits the E lane of the same file — non-overlapping region. Branch off current `main`; if b3 merges first, rebase (outbound branch vs E lane do not collide). Flag any real conflict to lead (do not average).

## Gate plan
G1 self-check (`py_compile` + full 12-AC pytest + `bash scripts/check_singletons.sh`) → codex **G3 on the BUS** (topic `gate/box5-outbound-ingest-2-g3`, effort HIGH; focus: flag-off byte-identical, idempotency across re-ticks, ClickUp-before-flight ordering, closure guard, no external send, correlation conflict → NEEDS_CONTROLLER, audit row on every write, migration-safe) → lead **G4 `/security-review`** → lead squash-merge. FAIL → findings to b4, rework, re-gate codex.

## Done rubric
Done = flag OFF is a provable no-op on the outbound path; flag ON captures every outbound with durable event state + idempotency key; routine outbound is evidence-only; ratifying outbound writes ClickUp (BAKER Space) then progresses flight, never closing without returned package/receipt; every ClickUp write + flight transition has a `baker_actions` audit row; all 12 ACs green; codex G3 PASS (HIGH); G4 clean. Ship report answers THIS rubric (not "tests pass"). Activation remains Director-gated.

## Branch / hygiene
Branch `box5-outbound-ingest-2`. Path-scoped commits. Co-author trailer: Claude Opus 4.7 (1M context).
