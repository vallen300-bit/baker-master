# Cortex Service Retirement — Decision Memo

**Date:** 2026-07-23 · **Decided by:** Director (verbal "go", evening session, AH1 lane)
**Charter basis:** ai-head-autonomy-charter §4 — Cortex Design prerogative, Director-ratified.

## Decision

Retire the Cortex 3T per-matter cycle service (6-phase sense→load→reason→propose→act→archive,
`orchestrator/cortex_runner.py` + Phase 1-6 modules). The matter-desk fleet + airport process
(Sentinel arrivals → Ticketing Desk → flights → Director dashboards) now carries every matter
end-to-end and has fully superseded Cortex's design intent.

## Evidence (live DB, 2026-07-23)

| Metric | Value |
|---|---|
| Cycles ever run | 38 |
| Last cycle | 2026-05-20 (64 days silent) |
| Outcomes | 21 approved · 9 failed · 6 rejected · 2 stuck tier_b_pending |
| Last phase output | 2026-06-08 |
| Cycles since desks went live fleet-wide | 0 |

Nothing — auto-trigger or Director manual — has invoked Cortex in over two months. Zero demand.

## What is kept (already migrated, no action needed)

- Curated per-matter knowledge: `baker-vault/wiki/matters/<slug>/curated/` — desks write it now.
- Specialist reasoning: desk skills + invoked subagents.
- Audit trail: `baker_actions` unchanged; `cortex_cycles` / `cortex_phase_outputs` tables kept
  READ-ONLY as historical record (never dropped).
- Read/observability endpoints (`GET /api/cortex/events|stats`) kept for the historical data.

## Retirement phases

- **Phase 1 (now, brief CORTEX_RETIRE_PHASE1_1 → b1):** cycle-starting surfaces return 410
  RETIRED (`POST /api/cortex/trigger`, `POST /api/cortex/run`, gate-decide fire path); stuck-cycle
  sentinel disabled; the 2 stuck `tier_b_pending` rows closed `rejected` with retirement note;
  docs flagged RETIRED. Reversible (guard flag), codex-gated.
- **Phase 2 (later, separate brief):** code excision of `orchestrator/cortex_*` + dashboard.py
  route removal once Phase 1 has soaked. Not urgent; dead code behind a 410 guard is safe.

## Anchor

Director, 2026-07-23: "I don't feel that Cortex idea and design bring anything useful… do we
need it at all?" → evidence pull → "go" on retirement. Supersedes the Cortex roadmap
(`_ops/processes/cortex3t-roadmap.md`) and Stage-2 tracker as forward plans; they remain as
historical design records.
