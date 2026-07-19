# BRIEF: COCKPIT_REVAMP_CTX_BARS_LOCAL_SOURCE_1 — context bars from local band files + codex pane-parse

## Context
Spec item **1** of the Director-ratified cockpit revamp
(`briefs/_plans/COCKPIT_REVAMP_SPEC_20260719.md` @d5e25efa). Context bars must stop
depending on the Lab round-trip: read local band files directly, never null a
last-known value, and give Codex-family seats (no Claude hooks) a pane-parsed
context % + real is_working. Meter hook install on the 15 missing pickers was done
2026-07-19 — bands appear after each seat's next completed turn.

## Estimated time: ~3-4h
## Complexity: Medium
## Prerequisites: none hard. Frontend meter region overlaps the colors brief only
trivially; rebase on main before PR.

## Baker Agent Vault Rails
Relevant: build-command-center, verification-surfaces.
Ignore: bus-and-lanes (no bus schema changes), memory-and-lessons, loop-runner.

## Harness V2
- **Context Contract:** inputs = this brief + spec item 1 + `cockpit_controller.py`
  (band/glance/poll regions) + meter region of cockpit.js + one sample band file from
  `~/forge-agent/context-band/`; no vault reads; do NOT touch the meter-hook writer.
- **Task class:** production implementation — controller data-path change + minor
  frontend render change; local filesystem + tmux read-only IO; no DB, no external API.
- **Done rubric / done-state class:** done = branch pushed + unit tests for reader/
  precedence/parser green + full cockpit suite green + live Quality Checkpoints 3-5
  exercised with /api/agents curl evidence in the report. Done-state class:
  gate-verified merge; compile-clean is NOT done (Lesson #8).
- **Gate plan:** independent codex gate on `gates/cockpit-revamp-ctx-bars-local-source-1`
  (cross-vendor rule holds: deputy-codex authorship → codex seat gates, lead reviews
  diff before merge); lead merges on PASS + App Support re-sync + controller
  kickstart + live bar check on lead/codex seats as post-deploy AC.

## UI-surface prebrief (6 checks)
Surface = existing per-card context meter (cockpit.js ~373-391) on the local cockpit.
No new clickable elements — a render-state change (dimmed + age) on an existing bar.
Data path verified on disk: `~/forge-agent/context-band/` holds per-session JSONs +
`<alias>.current` symlinks (schema: `session_id`, `context_percent` 0-100, `band`,
`measured`, `window_tokens`).

---

## Feature 1: Controller reads local band files directly

### Problem
`context_pct` comes from the Lab glance feed (`context_used_percent`) and
`derive_context_pct()` (cockpit_controller.py ~114-130) NULLS it on stale heartbeat
(>900s) — bars vanish exactly when the Director most wants the last-known value.
Lab round-trip also lags the local truth.

### Current State
- `derive_context_pct()` cockpit_controller.py ~114-130: explicit `context_pct` →
  `context_used_percent` fallback → null on stale/missing.
- `get_agents()` ~1218-1255 assembles rows; `is_working` = Lab `row.is_working` OR
  local tmux activity within `LOCAL_WORKING_WINDOW_S` (~1238-1243, D8 pattern).
- Frontend meter cockpit.js ~373-391: renders only when `pct` numeric; null → em-dash.
- Disk: `~/forge-agent/context-band/<alias>.current` → symlink to latest session JSON.

### Engineering Craft Gates
- Diagnose: N/A — behavior change, not a bug hunt.
- Prototype: N/A — data source verified on disk; schema known.
- TDD/verification: applies — add unit tests for the new
  `read_local_context_band(slug)` helper (tmp dir with fake band files + symlink:
  fresh value, stale value, missing file, broken symlink, malformed JSON) and for
  the merged precedence (local fresh > local stale > Lab fallback). Extend
  `tests/test_cockpit_controller.py` (56-test suite must stay green).

### Implementation
1. New controller helper `read_local_context_band(slug)`:
   - Resolve `~/forge-agent/context-band/<alias>.current` (alias per seat — use the
     same slug→alias mapping the manifest carries; try slug if alias file absent).
   - Read JSON `context_percent` + file mtime → `(pct, age_sec)`.
   - Fault-tolerant: any OSError/JSONDecodeError → `(None, None)` (never raises into
     the poll loop). No caching needed at poll cadence; stat+read is cheap.
2. Precedence in `get_agents()` per seat:
   - local band value present → use it, `context_src="local"`, `context_age_sec=age`.
   - else Lab value (current path) → `context_src="lab"`.
   - NEVER null a last-known value for staleness — always ship the number + age.
3. New row fields: `context_age_sec` (float|null), `context_stale` (bool —
   age > `CONTEXT_STALE_S = 900`, named const), `context_src`.
4. Frontend meter (~373-391): always render last-known %; when `context_stale`,
   render DIMMED (reduced opacity class `ctx-stale`) + age shown compactly ("44% ·
   2h"). Director verbatim: "show stale bars dimmed rather than hiding them."
   Quiet-when-healthy: dimming, not color, signals staleness.

## Feature 2: Codex-family seats — pane-parse context % + activity is_working

### Problem
codex / codex-arch / deputy-codex have no Claude hooks → no band files, and Lab
under-reports them, so they show falsely "idle" with no context bar (Director flagged
CT & Verification plate).

### Current State
- Pane reader exists: `_read_pane()` cockpit_controller.py ~763-781
  (`tmux capture-pane -t {slug} -p`; C-l repaint + settle used by wake verify — do
  NOT reuse the C-l repaint for passive polling, it disturbs the seat).
- Codex TUI status line shows "Context N% used" in the pane.

### Engineering Craft Gates
- Diagnose: N/A. Prototype: N/A — pane format observable on live seats now.
- TDD/verification: applies — parser is a pure function
  `parse_codex_context(pane_text) -> int|None`; unit-test against captured fixtures
  (status line present, absent, multiple matches → take last, garbled).

### Implementation
1. Passive capture in the poll path for the codex-family seats ONLY (named const
   `CODEX_FAMILY = ("codex", "codex-arch", "deputy-codex")`): plain
   `tmux capture-pane -t <slug> -p` — NO C-l, NO keystrokes, read-only.
2. Parse "Context N% used" (regex, last match wins). Feed result into the same
   context fields as Feature 1 (`context_src="pane"`); fresh capture → age 0.
3. is_working for codex-family: pane-content change between polls OR the existing
   local tmux activity clock (D8) — either marks working. Store last pane hash per
   seat in the controller's in-memory state (restart-safe: falls back to unknown on
   first poll after restart, then converges — acceptable).
4. Throttle: capture at the existing poll cadence; if capture adds latency, limit to
   every other poll for codex seats (measure first, don't pre-optimize).

### Key Constraints
- Read-only pane access — NEVER send keys/C-l from the poll path.
- All new IO in try/except; a broken band dir or dead tmux must not break /api/agents
  (fault-tolerant or it doesn't ship).
- Lab glance code path stays intact as fallback — do not remove `derive_context_pct`,
  extend around it.
- No brisen-lab changes this round.
- Cache-bust `?v=N` on cockpit.js if the colors brief already introduced versioning;
  else introduce it (Lesson #4).

## Files Modified
- `scripts/cockpit_controller.py` — band reader, precedence, codex pane-parse, new row fields
- `scripts/cockpit_static/cockpit.js` — stale-dim + age render on the meter
- `scripts/cockpit_static/cockpit.css` — `.ctx-stale` dim class
- `tests/test_cockpit_controller.py` — band reader + precedence + parser tests

## Do NOT Touch
- Wake/composer paths (`_read_pane` C-l flow) — reuse capture-pane invocation only.
- `~/forge-agent/*` writer side (meter hook) — consumer only.
- `brisen-lab/*`.

## Quality Checkpoints
1. Unit tests: band reader edge cases + precedence + codex parser fixtures — green.
2. Full cockpit suite green (`pytest tests/test_cockpit_controller.py tests/test_cockpit_wake.py -q`).
3. Live: lead seat bar sourced local (`context_src":"local"` in /api/agents curl);
   a stale band (touch an old session file) renders dimmed + age, value visible.
4. Live: all 3 codex-family seats show context % matching their pane status line;
   a codex seat mid-build shows working, not idle.
5. /api/agents latency not visibly degraded (compare before/after poll timing).

## Handoff / gate
Branch `deputy-codex/cockpit-revamp-ctx-bars-local-source-1`. QUEUE ORDER: finish the
msg-panel-body-preview fix round + SWEEP_TIMING_ACTIVE_WORK_GUARD_1 first; this is
third in your queue. Report exact HEAD on bus topic
`cockpit-revamp-ctx-bars-local-source-1`; independent codex gate follows; lead merges
on PASS + re-syncs App Support + kickstarts controller. Do not merge.

## Verification SQL
N/A — no DB surface.
