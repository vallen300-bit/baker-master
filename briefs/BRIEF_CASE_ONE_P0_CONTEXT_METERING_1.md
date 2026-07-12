# BRIEF: CASE_ONE_P0_CONTEXT_METERING_1 — machine band field + per-seat threshold hook + lifecycle band-state

> Case One bus-hardening **P0** (fleet-blocking: context metering, E14/E16). Authored by deputy
> (AH2, standing bus-health owner) from ARM's plan `wiki/matters/flight-academy/05_outputs/2026-07-12-case-one-bus-hardening-plan.md` (vault #178).
> **TO LEAD FOR REVIEW BEFORE WORKER DISPATCH.** Codex gate this phase. Standing rule #9255.

dispatched_by: lead (pending review)
assigned_to: <builder — lead assigns after review>
task_class: cross-layer-reliability (context metering: hook + status-post payload + lifecycle band-state)
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: medium

## Context

**Context Contract.** Two repos: baker-master (`.claude/hooks/context-threshold-check.sh`, status-post emitters) + brisen-lab (`lifecycle.py`, status-post ingest / seat state). No new service. Builds ON already-shipped pieces — do NOT redo them.

Director greenlit the full reliability layer, incremental, with a standing owner (2026-07-12). P0 is the fleet-blocking slice: metering. E16 addendum: a 20-minute-old fresh seat reported "past hard band" (#9424) and had to re-queue — rollover cannot converge if a fresh seat starts at the hard band. Lead's line-review close-out: today's 3 rolls were **false alarms** (86% "read" = 18% real).

### SCOPE DEDUPE (MANDATORY — lead #9563). Already shipped; this brief must NOT re-cover:
- **Measured token meter** — SHIPPED as baker-master #537 (`context-threshold-check.sh` now parses real usage fields: last-usage sum incl. cache tokens, dict-guard for non-dict JSONL, bytes/4 fallback). The honest gauge exists.
- **The 70/85 threshold hook itself** — EXISTS and is config-driven (soft 70 / hard 85 defaults, per-key precedence via `settings.local.json`, block-at-most-once over hard band). Deputy swept it to all reachable git clones + hag-desk on 2026-07-12.
- **E14 threshold-hook proposal** already sits with deputy — folded here, not duplicated.

## Problem

Three metering gaps remain after #537, all preventing *mechanical* (dispatcher-ordered, not human-noticed) rollover:

1. **No machine-readable band field in status posts.** The hook warns a human in the transcript, but the dispatcher/lifecycle layer has no structured `context_percent` / `band` field to read, so it cannot order a roll mechanically — a human still has to notice.
2. **The hook is not universally wired.** It is config-driven and deployed to lead + build workers + (now) hag-desk, but "every seat" (all desk pickers, researcher, App-resident seats) is not guaranteed to carry it with a consistent, measured-meter-fed config. Generalize it structurally so no seat is unmetered.
3. **Lifecycle holds no per-seat band state.** brisen-lab's lifecycle layer cannot answer "which seats are over soft / over hard right now?" so the dispatcher cannot sweep-and-roll.

## Fix (three additive pieces)

### P0.1 — Machine band field in status posts
Every seat's status post (and/or a lightweight periodic heartbeat) carries a machine field: `context_percent` (from the measured meter, not bytes/4 estimate where usage fields exist), `band` ∈ {ok, soft, hard}, `window_tokens`, `measured` (bool: true if from usage fields, false if bytes/4 fallback). Source of truth = the same computation `context-threshold-check.sh` already does — factor it so the hook and the status-post emitter share ONE band computation (no drift, per surface-conflicts rule).

### P0.2 — Per-seat generalized threshold hook
Make the 70/85 hook a structural part of EVERY picker, not an opt-in. Deliverable: a wiring step (idempotent installer / settings template) that guarantees `context-threshold-check.sh` is registered as the Stop/threshold hook in every seat's `settings.local.json` (workers, desks, researcher, AH1/AH2, App seats), with the measured meter as input. Enumerate the seat list (reuse the bus-identity 12-seat map + desk pickers). Report any seat that cannot be wired (e.g. Mini-resident + Mini offline) — do NOT silently skip (fail-loud).

### P0.3 — Rollover band-state in lifecycle
brisen-lab lifecycle records the latest `band`/`context_percent` per seat (from P0.1's status field) so the dispatcher can query "seats over hard band" and order rolls mechanically. Band-state is advisory input to the existing rollover flow — it does NOT auto-kill seats (interactive seats can't self-terminate; that closed loop is P2). Surfaces the data; the dispatcher/lead still triggers.

## Files Modified

- baker-master: `.claude/hooks/context-threshold-check.sh` (factor the band computation into a shared, callable form), the status-post emitter (add machine band field), a seat-wiring installer/template + its enumeration.
- brisen-lab: `lifecycle.py` (+ status-post ingest) to persist + expose per-seat band-state; likely a small migration or a column/JSON field on the seat/lifecycle row.
- Tests in both repos.

## Verification

1. **Unit — one band computation:** hook and status-post emitter produce identical band for the same transcript (prove no drift); measured path vs bytes/4 fallback both covered.
2. **Unit — machine field shape:** status post carries `context_percent`/`band`/`measured`; `measured=false` only when usage fields absent.
3. **Wiring audit:** a script asserts every enumerated seat has the hook registered; missing seats are REPORTED (fail-loud), not skipped.
4. **Lifecycle:** post a status with band=hard → lifecycle exposes that seat as over-hard in its query; band clears when a fresh status arrives.
5. **Live AC:** a fresh seat (< 30 min) reports `band=ok` with a low measured percent (retire the E16 false-alarm). A genuinely-full seat reports `band=hard`. Emit `POST_DEPLOY_AC_VERDICT v1`.

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) single shared band computation, no drift; (2) machine band field live in status posts; (3) universal seat wiring with a fail-loud coverage audit; (4) lifecycle exposes per-seat band-state queryable by the dispatcher; (5) live AC: fresh seat reads ok, full seat reads hard, `POST_DEPLOY_AC_VERDICT v1` posted.
- **done-state class:** fleet-blocking production reliability → live AC required, not unit-green alone.
- **gate plan:** deputy authors → **lead reviews (this brief) BEFORE worker dispatch** → builder (b1) implements → **independent Claude-side review by lead BEFORE merge** (was "independent codex verify"; changed 2026-07-12 per Director codex-suspension order #9711 — codex seats unavailable until Director lifts; #9255 independent-verdict-before-merge rule still holds, Claude-side) → lead merges → deploy → deputy verifies live band reporting as bus-health owner.
- **Harness-V2:** covered inline.

## Dedupe / cross-links

- Builds on #537 (measured meter) — do NOT re-parse usage fields.
- Does NOT auto-kill seats (P2 lifecycle closed-loop). Does NOT touch delivery correctness (P1). Sequenced first per ARM's evidence weight (fleet-blocking).
- Evidence: training-file crosswalk E14/E16 (`05_outputs/2026-07-12-case-one-bus-hardening-training-file.md`); live-defect log E16 addendum.
