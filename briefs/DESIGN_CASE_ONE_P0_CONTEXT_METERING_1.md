# DESIGN / APPROACH — CASE_ONE_P0_CONTEXT_METERING_1 (b3, pre-diff, for lead review)

Brief: `briefs/BRIEF_CASE_ONE_P0_CONTEXT_METERING_1.md` @c042fb81. Dispatched to b3 (bus #9722/#9727).
Gate: lead reviews this design → lead reviews diff → lead merges (Claude-side, codex suspended #9711).
Repos touched: baker-master (`~/bm-b3`) + brisen-lab (`~/bm-b3/brisen-lab`). No new service.

## What already exists (do NOT rebuild — confirmed by code read)

1. **Measured context meter** — `.claude/hooks/context-threshold-check.sh:92-183`. Parses real usage
   fields (input + cache_read + cache_creation), dict-guards non-dict JSONL, falls back to bytes/4 only
   when no usage present. Produces `percent`. SHIPPED #537.
2. **70/85 threshold hook** — same file, config-driven (env → settings.local.json → settings.json →
   default), block-at-most-once over hard. Registered as a Stop hook in per-seat settings.
3. **Per-seat hook installer** — `scripts/install-rollover-stop-hook.py` (idempotent, per-seat).
4. **Seat enumeration (source of truth)** — `orchestrator/agent_identity_data.py:16` `APP_TERMINALS`
   (25 seats incl. lead/deputy/b1-b4/researcher/desks/CM-1..4/hag-filer) + `SNAPSHOT_TERMINALS:19`
   (slug→MacBook path map). Generated from `~/baker-vault/_ops/registries/agent_registry.yml`.
5. **Existing token-pressure state machine** — `brisen-lab/lifecycle.py:417-481` `TokenPressureMachine`
   (green/yellow/orange/red, in-memory only) + ingest `POST /lifecycle/token_pressure/{slug}`
   (`app.py:1159-1187`) + read `GET /lifecycle/status`. Heartbeat: `scripts/forge-agent/heartbeat-ticker.sh`
   → `POST /api/heartbeat`.

## KEY DESIGN FORK (needs a lead ruling before I diff)

The existing `TokenPressureMachine` looks like the natural home for P0.3, but it is a **different meter**
and reusing it collides with the brief. Surfacing both, not averaging.

**Option A — feed measured context% into the existing `/lifecycle/token_pressure` + 4-band machine.**
- Rejected. Three collisions: (1) that endpoint **auto-triggers Hermes (session kill/restart) on red** —
  brief P0.3 explicitly says context-band is *advisory, does NOT auto-kill* (auto-kill is P2). Feeding
  it would arm the P2 loop early. (2) It is `X-Forge-Key` admin-only, posted by the forge-agent, not the
  Stop hook. (3) Its `pct` is the H3-wrapper forge-side token counter for H3 enforcement — a distinct
  quantity from context-window occupancy; overloading it conflates two meters.

**Option B — add a parallel, advisory context-band state, separate from token-pressure. CHOSEN.**
- New per-seat context-band record fed by the measured meter, non-auto-killing, 3-band {ok, soft, hard}
  matching the hook's soft/hard thresholds exactly, with a dispatcher query endpoint. Leaves
  `TokenPressureMachine` and its auto-Hermes untouched. Matches brief P0.3 word-for-word ("advisory
  input… does NOT auto-kill… surfaces the data; the dispatcher/lead still triggers").
- Chosen because it is the only reading consistent with the brief's explicit P0/P2 boundary and the
  "surface conflicts, don't average" rule. The relationship to the existing 4-band machine is documented
  (not a blind second meter): enforcement token-pressure band stays separate from advisory context band
  on purpose.

If lead prefers A (accepting the auto-kill/auth/semantic collisions), I re-plan P0.3 around token_pressure.

## Proposed implementation (Option B)

### P0.1 — one shared band computation + machine field in status posts
- **Extract** the percent+band logic from the Stop hook into a shared callable
  `.claude/hooks/context_meter.py` exposing `compute(transcript_path, window, soft, hard) ->
  {context_percent, band ∈ {ok,soft,hard}, window_tokens, measured: bool}`. The Stop hook imports it for
  its warning; the emitter imports the **same** function → done-rubric #1 "one computation, no drift".
  Refactor is behaviour-preserving; existing hook tests must stay green.
- **Emit channel (sub-decision, I recommend B2 for fault-isolation):**
  - B1: Stop hook does a best-effort fire-and-forget POST of the band field (curl `--max-time 2`,
    backgrounded, all errors swallowed — hook contract is exit 0 on every path).
  - **B2 (chosen):** Stop hook only *writes a local band file* (cannot fail the session); the existing
    `heartbeat-ticker.sh` reads it and includes `context_percent`/`band`/`measured`/`window_tokens` in its
    next `/api/heartbeat` body (≤45s staleness, fine for advisory data). Keeps all network I/O out of the
    Stop hook. If lead prefers immediacy over fault-isolation, switch to B1.
- **Ingest:** extend `/api/heartbeat` (`app.py`) to accept + store the optional band fields.

### P0.2 — universal seat wiring + fail-loud coverage audit
- New `scripts/install-rollover-fleet.sh`: iterate `APP_TERMINALS` × `SNAPSHOT_TERMINALS` paths, call the
  existing `install-rollover-stop-hook.py` per seat (idempotent), feed the measured-meter window.
- New coverage audit (`scripts/audit-rollover-coverage.py` or a `--audit` mode): assert every enumerated
  seat's `settings(.local).json` registers the Stop hook; **REPORT** unreachable/unwireable seats
  (App-resident, Mini-offline) — never silently skip (brief verification #3, fail-loud).

### P0.3 — advisory per-seat context band-state in lifecycle
- New in `lifecycle.py`: a `ContextBandState` store (per-seat `{band, context_percent, measured,
  updated_at}`), persisted to a small brisen-lab Postgres table `brisen_lab_seat_context_band` (bootstrap
  DDL in `db.py` `SCHEMA_*`, CREATE TABLE IF NOT EXISTS — matches the repo's bootstrap-not-migration
  pattern) so it survives daemon restart (the existing machine is in-memory only).
- Ingest from P0.1's heartbeat band field. New query `GET /lifecycle/seats-over-band?band=hard` returns
  seats at/over the band. Advisory only — no Hermes trigger.

## Verification (maps to brief §Verification / done rubric)
1. Unit: hook and emitter call the one shared `context_meter.compute` → identical band for same
   transcript; measured path + bytes/4 fallback both covered.
2. Unit: heartbeat carries `context_percent`/`band`/`measured`; `measured=false` only when usage absent.
3. Wiring audit asserts every enumerated seat has the hook; missing seats REPORTED (fail-loud).
4. Lifecycle: post band=hard → `/lifecycle/seats-over-band` lists that seat; clears on fresh ok status.
5. Live AC: fresh <30-min seat reads `band=ok` low percent (retires E16 false alarm); full seat reads
   `band=hard`. Emit `POST_DEPLOY_AC_VERDICT v1`.

## Migration/DDL check (Lesson #50)
- baker-master: no DB columns added (hook + scripts + heartbeat body only).
- brisen-lab: new table only via bootstrap `CREATE TABLE IF NOT EXISTS`; no ALTER on an applied table.
  Will grep `db.py` bootstrap for any name collision before adding.

## Open items for lead
1. **Design fork A vs B** — I chose B (advisory, separate from token_pressure). Confirm or pick A.
2. **Emit channel B1 (hook POSTs) vs B2 (hook writes file, heartbeat carries)** — I chose B2 for
   fault-isolation. Confirm or pick B1.
3. Everything else follows the brief as written; no other ambiguity found.
