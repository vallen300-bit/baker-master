---
status: PENDING
brief_id: EMAIL_STORE_CONN_HARDEN_1
to: b3
from: lead
dispatched_by: lead
dispatched_at: 2026-06-10
reply_target: lead (bus)
task_class: production reliability fix — 3 surgical changes, cross-layer (settings + retriever + store_back + trigger_state)
gate_plan: G1 pytest literal -> G3 codex code gate -> lead merge -> POST_DEPLOY_AC: deputy live-verifies Spanyi AC + 24h SSL-event count drop (to lead cc deputy)
---

# EMAIL_STORE_CONN_HARDEN_1 — implement your RCA's 3 fixes (Mode A + Mode B + fail-open hole)

## Context

Your EMAIL_STORE_NEON_SSL_RCA_1 verdict (#2813) accepted in full. This lane implements exactly your AC3 proposals — no scope growth. First: push your RCA report to a branch + PR (docs-only, Brief-SOP-bypass trailer fine) so the evidence is in the audit trail.

## Problem

Mode A: retriever's single cached conn uses pooled dsn WITHOUT keepalives -> Neon idle-kills -> first caller eats SSL-closed (~2/hr, Director-visible). Mode B: store_back ThreadedConnectionPool maxconn=5 exhausts every 5-min tick. Hazard: trigger_state.is_processed fails OPEN on exhaustion (state.py:467) -> duplicate processing + duplicate LLM spend.

## Files Modified

- settings.py (~353-360): mirror SCHEDULER_NEON_IDLE_HARDEN_1 keepalives into dsn_params (pooled path).
- memory/retriever.py (~680): retry-once-on-stale around the cached-conn use in the email-query path (_reset_pg_conn then single retry; second failure surfaces as today).
- store_back.py (~306): maxconn 5 -> 15 (env-overridable BAKER_STOREBACK_MAXCONN, default 15).
- triggers/.../state.py (~467): is_processed fails CLOSED on pool exhaustion — skip item this tick, WARN log with item id; item picked up next tick.
- tests: one per change (keepalive params present; stale-conn retry heals; maxconn env override; fail-closed skip path).

## Verification

pytest literal green on the 4 new tests + existing retriever/store_back suites. No singleton-pattern violations (scripts/check_singletons.sh clean).

## Acceptance criteria

- AC1: pooled dsn_params carries keepalives (assert in test, mirror direct_dsn_params values).
- AC2: simulated stale conn -> one transparent retry -> caller sees success; second consecutive failure still surfaces backend_unavailable.
- AC3: maxconn from env, default 15; pool creation logged once.
- AC4: is_processed pool-exhaustion -> returns True-equivalent SKIP (not "not processed"), WARN with item id, no exception.

## Quality Checkpoints

POST_DEPLOY_AC (after Render deploy): (a) deputy's Spanyi store search passes 3/3 spaced probes; (b) dashboard SSL-closed events in next 24h << 45/23h baseline; (c) zero 'pool exhausted' at two consecutive tick minutes. Verdict to lead cc deputy.

## Context-economy rules (HARD)

Read ONLY the 4 named files at the named regions + their test files. Your RCA context carries the rest. /tmp for outputs. Context >70%: commit, push, bus handoff, STOP.
