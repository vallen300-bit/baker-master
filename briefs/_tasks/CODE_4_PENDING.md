# CODE_4_PENDING — FORGE_HEARTBEAT_FRESHNESS_1

status: PENDING
dispatched_by: lead
ship-report recipient: lead
repo: brisen-lab (new /api/heartbeat) + ~/forge-agent/ (per-session ticker, NOT git-tracked — edit in place on this Mac)
task class: production implementation (agent telemetry)
gate plan: G0 codex (brief PASS #1603) → G1 lead static → G2 security-review REQUIRED (codex #1603 ruling) → G3 architect → merge → post-deploy AC
bus topics: ship/forge-heartbeat-freshness-1

## Context

Canonical brief (READ IN FULL FIRST): `~/baker-vault/_ops/briefs/BRIEF_FORGE_HEARTBEAT_FRESHNESS_1.md` (v2, commit a98d279; codex G0 PASS #1603 — all 3 prior REVISE findings folded).

You shipped DASHBOARD_CARD_WORKSTATE_CLARITY_1 (the consumer). This closes its known gap: WORKING-amber under-fires because `last_seen_at` only refreshes on JSONL-activity forge_events; a reasoning/long-op agent looks idle. Add a periodic session heartbeat so WORKING reflects "session alive."

## Problem

`is_working` (latest open `forge_sessions.last_seen_at` ≤120s) goes stale during reasoning. Add a dedicated heartbeat that keeps `last_seen_at` honest, stops cleanly on session end.

## Files Modified

(per brief §Stable Paths) — `~/forge-agent/session-start-hook.sh` (spawn ticker), NEW `~/forge-agent/heartbeat-ticker.sh` (45s loop + parent-PID exit watch + fire-and-forget POST), brisen-lab `app.py` (NEW `POST /api/heartbeat` UPDATE-only) + `bus.py`/`db.py` as needed + `tests/`.

Do NOT touch: `/api/event` handler, brisen-lab `is_working` logic (just merged + verified), `forge_snapshot_push.sh`.

## Quality Checkpoints (load-bearing — codex #1598/#1603)

1. Heartbeat hits a NEW dedicated `POST /api/heartbeat` (UPDATE-only `forge_sessions.last_seen_at`) — NOT `/api/event`; zero forge_events rows, zero `_broadcast`, zero dashboard timeline noise. AC3 asserts UPDATE-only.
2. Single stop mechanism = SessionStart-spawned per-session backgrounded ticker with parent-PID / process-exit watch; ticker exits when parent dies. AC2 PROVES exit-on-parent-death. BANNED: launchd-per-session, sessions.json-only global loop (no SessionEnd hook in installed SDK).
3. Canonical emitter home = `~/forge-agent/` (agent.py is the real `/api/event` producer); settings.json is only the SessionStart launcher.
4. Cadence 45s vs 120s freshness window (one missed beat → ~90s margin, per codex).
5. Fire-and-forget: ≤5s HTTP timeout, catch + log class/status only, never block SessionStart beyond spawn, never log `FORGE_KEY`.
6. Keyed by `session_uuid` (UNIQUE column, verified by codex); multi-session safe.

## Verification

Per brief §Acceptance. Literal test output (AC1 cadence; AC2 ticker-exits-on-parent-death; AC3 heartbeat-is-UPDATE-only; AC4 failure swallowed). Post-deploy: live dashboard working b-code = amber, idle/ended → grey ≤2 min, timeline shows NO heartbeat noise. Emit `POST_DEPLOY_AC_VERDICT v1` (Director is visual judge).

## G2 note (REQUIRED, do not skip)

codex #1603 ruled `/security-review` REQUIRED — new production POST endpoint gated by `X-Forge-Key` writing the DB. G2 must check: auth/header handling, freeze behavior, terminal/session validation, no secret logging, NO broadcast/timeline side effect, bounded DB write.

## Constraints

All DB calls in try/except with `conn.rollback()`; bounded UPDATE. No secrets in logs. No `--no-verify`. Ship report answers the done rubric + carries the POST_DEPLOY_AC_VERDICT (DONE only at post-deploy AC pass on the live dashboard + writeback to `_ops/processes/autonomous-delegated-loop-spec.md`).
