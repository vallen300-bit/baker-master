# B2 Ship Report — CASE_ONE_P5_DELIVERY_CONFIRMATION_1

- **Date:** 2026-07-13
- **Dispatched by:** lead (#10172), re-fired by deputy (#10195); nudges #10186/#10199
- **Brief:** `briefs/BRIEF_CASE_ONE_P5_DELIVERY_CONFIRMATION_1.md` @a53f6306
- **PRs:** brisen-lab **#127** (core) · baker-master **#550** (`delivery_status.sh` fleet client)
- **Branches:** `b2/case-one-p5-delivery-confirmation` (brisen-lab) · `b2/case-one-p5-delivery-status-client` (baker-master)

## Done rubric — point by point

1. **Per-message delivery state machine wake→ack→started with config SLA, delivered≙started-within-SLA, machine-readable** — DONE. `brisen_lab_delivery_receipt` extended in place: `delivery_state` (posted→wake_fired→acked→started, monotonic), `posted_at`/`wake_fired_at`/`started_at`, `sla_state`, `escalated_at`. Record minted at dispatch (R1 predicate). SLAs config (`BRISEN_LAB_DELIVERY_ACK_SLA_S`=300, `…_STARTED_SLA_S`=900). Machine field — read, never inferred.
2. **Active auto-retry wake on ack-SLA miss (thrash-bounded) → auto-escalate to deputy+lead + dead-letter on started-SLA miss, exactly-once, no human** — DONE. `bus.run_delivery_control_tick` + `_delivery_control_loop`. Rewake bounded by `wake_events` count (reused P2 guard, no 2nd counter). Escalation exactly-once via `mark_delivery_escalated_sync` rowcount guard + `kind=alert` (R3 no-recursion). DARK by default (`BRISEN_LAB_DELIVERY_CONTROL_ENABLED`).
3. **Cross-seat metadata-only `/delivery/status` + `delivery_status.sh`, bodies auth-scoped, orchestration-role authz, standing dispatcher authority** — DONE. `GET /delivery/status` returns metadata only (no body field). `authz.is_orchestration_role` (deputy/deputy-codex/lead) + Director → any seat; other seats self-only. Script never routes a Director permission ask.
4. **Built on merged P1/P2/P3/P4 with NO re-fork of ack/lease/heartbeat/receipt/dashboard** — DONE. Extended the P4 receipt (not forked); consumed P1 ack, P2 heartbeat/thrash/`wake_events`, P3 identity/envelope, P4 dead-letter + dashboard. Dashboard binds the state summary folded into the already-consumed `/api/bus_health`.
5. **Live fleet drill AC + `POST_DEPLOY_AC_VERDICT v1`** — PENDING deploy. Loop is dark; deputy (bus-health owner) flips `BRISEN_LAB_DELIVERY_CONTROL_ENABLED=true` and runs the drill post-merge, then emits the verdict.

## Riders (all binding, all implemented)
- **R1** — trigger predicate `kind=dispatch AND execute_obligation=true` (`_is_delivery_tracked`); `VALID_KINDS` unchanged, no new kind.
- **R2** — job_ref-less start = recipient's first non-ack reply on the dispatch thread (`detect_delivery_started_sync`); linked P2 job progress used when a job exists; **ack alone never counts (E22)** — tested.
- **R3** — escalation posted as `kind=alert` (not delivery-tracked) → no recursion; exactly-once tagged via `escalated_at`.
- **E22** (ack-then-idle) — covered by the started-SLA escalation path; tested (`test_reply_on_thread_counts_as_started_but_ack_alone_does_not`).

## Tests (literal pytest, local Postgres)
- `tests/test_case_one_p5_delivery_confirmation.py` — **10 passed** (state machine incl. out-of-order; rewake thrash-bound; escalate exactly-once + dead-letter; R3 non-recursion; R2 reply/job start + ack-not-start; `/delivery/status` cross-seat no-body + self-scope 403; P4-undelivered-still-holds).
- Regression: `test_case_one_p2/p3/p4` — **47 passed**.
- Full suite — **591 passed, 1 skipped, 4 pre-existing failures** (`test_agent_identity_generated` ×3 + `test_bus_autowake::test_cowork_bb_desk_never_fires_wake`) — confirmed pre-existing via `git stash` (fail on clean main; local vault registry not synced). **Not caused by this change.**

## Decisions surfaced (fail-loud)
- **delivered_at made NULLABLE** + P4 `bus_health` undelivered query re-keyed on `delivered_at IS NOT NULL` (was row-existence). Behaviour-identical; the brief pre-decided "the record is a machine field" which requires a row at dispatch time. Regression-tested.
- **Dashboard binds `/api/bus_health` (not `/delivery/status`)** — an unauthenticated browser must not carry a terminal key; the authed cross-seat endpoint stays the CLI/orchestration surface, and the aggregate state summary is folded into the endpoint the page already consumes. Divergence from the brief's literal wording, flagged in PR #127 for reviewer confirmation.
- **Control loop DARK by default** — a mis-firing auto-actuator is worse than none (done-state class); ships OFF, flipped for the live AC. Matches `_refresh_cadence_loop` / `_desk_backlog_wake_loop` convention.

## Meta defect
My ack of #10172 at claim did not surface to lead/deputy (drove the #10186/#10195/#10199 nudge-storm + a stale wake-lock clear) — the exact silent-delivery class P5 addresses. Flagged to lead on the bus for its own look.

## Gate
codex verify (effort=high, production control loop) → lead merge → deploy → deputy live-verify + `POST_DEPLOY_AC_VERDICT v1`.
