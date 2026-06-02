# CODE_4_PENDING — DASHBOARD_CARD_WORKSTATE_CLARITY_1

status: COMPLETE
completed: 2026-06-02 — PR #55 merged 43dccde; G0 codex no-findings (#1591) + G1 lead + post-deploy AC PASS (b4 #1594: NEW/WORKING/DONE/IDLE on one dot live; stale-open-row gate proven). Known follow-up = WORKING-amber under-fires → FORGE_HEARTBEAT_FRESHNESS_1 (in flight).
dispatched_by: lead
ship-report recipient: lead
repo: brisen-lab (your brisen-lab checkout, e.g. ~/bm-b4/brisen-lab)
task class: production implementation (dashboard UI + small read-only backend field)
gate plan: G0 codex (brief PASS, #1583) → G1 lead static → G2 security-review (likely N/A, confirm) → G3 architect → merge → post-deploy AC
bus topics: ship/dashboard-card-workstate-clarity-1

## Context

Canonical brief (READ IN FULL FIRST): `~/baker-vault/_ops/briefs/BRIEF_DASHBOARD_CARD_WORKSTATE_CLARITY_1.md` (committed 8b7ba20, codex G0 READY-TO-DISPATCH #1583).

Director pain: dashboard card stays "lit" while an agent works — can't tell got-it / working / done. Today the "lit" = unacked inbox (clears only on ack); the work-state is a faint left-edge color. Build ONE legible signal.

## Problem

No single glance-state on a card. Build `computeGlanceState(alias) -> NEW | WORKING | DONE_IDLE` and make the DOT the single visual via `renderStateDot(alias, glanceState)`; RETIRE the competing `data-pending` navy chrome.

## Files Modified

(per brief §Stable Paths) — `static/app.js` (computeGlanceState + renderStateDot refactor, retire data-pending visual), `static/styles.css` (3 distinct dot states + cache-bust), `bus.py`/`app.py` (read-only `is_working` from latest open `forge_sessions.last_seen_at` ≤120s), `tests/`.

## Verification

Per brief §Acceptance. Literal test output. `POST_DEPLOY_AC_VERDICT v1` after live-dashboard check (Director is the acceptance judge — the exact thing he was confused by).

## Quality Checkpoints

Load-bearing (codex #1573/#1578):
1. WORKING signal = latest OPEN `forge_sessions` row with `last_seen_at` ≤120s. NOT daemon_last_seen, NOT forge_events, NOT ended_at-alone. Test AC (c): stale open row (>120s) → is_working FALSE.
2. The DOT is the single signal — REMOVE/stop using `data-pending` card chrome as a visible signal (do not merely gate it).
3. WORKING suppresses NEW (no force-ack).
4. App agents (lead/cowork, no fresh heartbeat) = telemetry-UNKNOWN: keep unread glow; never false IDLE/WORKING; generic rule, no permanent slug hardcode.
5. Existing click-to-wake + cardState green/grey-as-DONE/IDLE-input preserved.

## Constraints

All DB calls in try/except with `conn.rollback()`; read-only query with LIMIT. Cache-bust `?v=N` on changed static assets. No secrets. Ship report answers the done rubric + carries POST_DEPLOY_AC_VERDICT (DONE only at post-deploy AC pass on the live dashboard).
